"""Opt-in short-text sanity suite, NOT leader/role or complex-task evaluation.

Uses the same approved-provider-tests/zhipu-official Windows vault entry as
quality_live_smoke.py. One GET /models must succeed before at most three chat
requests. No retries, implicit probes, tools, candidate promotion, or Core writes.
Unknown usage stops the remaining questions; unknown effort/version stays unknown.
Prices are not established by this suite, even for models whose name says Flash.
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
import time
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.quality_live_smoke import BASE_URL, NoRedirect, VAULT_NAMESPACE, VAULT_REFERENCE, WindowsCredentialStore
from sumika_core.integrations.zhipu_pricing import read_bounded


ALLOWED_MODELS = ("glm-4.7-flash", "glm-4.6v-flash")
MAX_TOKENS = 1024
TIMEOUT_SECONDS = 30
MAX_RESPONSE_BYTES = 128_000
CHECKS = (
    ("arithmetic", "Compute 6 * 7. Reply with only the decimal result."),
    ("json", "Return a JSON object with exactly two properties: ok is boolean true and count is integer 3. No Markdown or explanation."),
    ("transform", "Change only status=pending to status=done in the following line. Preserve the identifier and all other characters. Reply with only the transformed line.\nid=Case_A7-x9;status=pending"),
)
FINISH_REASONS = {"stop", "length", "tool_calls", "function_call", "content_filter"}
APPLIED_EFFORTS = {"off", "none", "minimal", "low", "medium", "high", "xhigh", "max"}


class ProviderHttpError(ValueError):
    def __init__(self, status, provider_code=None, reason=None):
        super().__init__("provider HTTP failure")
        self.status = status
        self.provider_code = provider_code
        self.reason = reason


def _safe_error_metadata(error):
    try:
        payload = _json_loads(read_bounded(error, 8192, 2))
        detail = payload.get("error") if isinstance(payload, dict) else None
        if not isinstance(detail, dict):
            return None, None
        code = str(detail.get("code", ""))
        code = code if code.isascii() and code.isdigit() and 1 <= len(code) <= 8 else None
        message = detail.get("message")
        reason = None
        if isinstance(message, str):
            for token, label in (("\u4f59\u989d\u4e0d\u8db3", "insufficient-balance"),
                                 ("\u5e76\u53d1", "concurrency-limit"),
                                 ("\u9891\u7387", "request-rate-limit"),
                                 ("\u989d\u5ea6", "quota-limit")):
                if token in message:
                    reason = label
                    break
        return code, reason
    except Exception:
        return None, None


def _unique_object(pairs):
    result = {}
    for name, value in pairs:
        if name in result:
            raise ValueError("duplicate JSON property")
        result[name] = value
    return result


def _reject_constant(value):
    raise ValueError("nonfinite JSON constant")


def _json_loads(value):
    return json.loads(value, object_pairs_hook=_unique_object, parse_constant=_reject_constant)


def _matches(check_id, content):
    if not isinstance(content, str):
        return False
    answer = content.strip()
    if check_id == "arithmetic":
        return answer == "42"
    if check_id == "transform":
        return answer == "id=Case_A7-x9;status=done"
    if check_id == "json":
        try:
            value = _json_loads(answer)
        except (ValueError, RecursionError):
            return False
        return (isinstance(value, dict) and set(value) == {"ok", "count"}
                and value["ok"] is True and type(value["count"]) is int and value["count"] == 3)
    return False


def _usage(payload):
    raw = payload.get("usage")
    if not isinstance(raw, dict):
        return {}
    result = {}
    for target, names in {
        "input_tokens": ("input_tokens", "prompt_tokens"),
        "output_tokens": ("output_tokens", "completion_tokens"),
        "total_tokens": ("total_tokens",),
    }.items():
        values = [raw[name] for name in names if name in raw]
        if values and all(type(value) is int and 0 <= value <= 10_000_000_000 for value in values) and len(set(values)) == 1:
            result[target] = values[0]
    for field, token_name, target in (
        ("prompt_tokens_details", "cached_tokens", "cache_read_tokens"),
        ("completion_tokens_details", "reasoning_tokens", "reasoning_tokens"),
    ):
        details = raw.get(field)
        value = details.get(token_name) if isinstance(details, dict) else None
        if type(value) is int and 0 <= value <= 10_000_000_000:
            result[target] = value
    return result


def _request_json(opener, key, model, *, prompt=None):
    path = "/models" if prompt is None else "/chat/completions"
    payload = None if prompt is None else {
        "model": model, "messages": [{"role": "user", "content": prompt}],
        "max_tokens": MAX_TOKENS, "stream": False,
    }
    headers = {"Authorization": "Bearer " + key, "Accept": "application/json", "Accept-Encoding": "identity"}
    if payload is not None:
        headers["Content-Type"] = "application/json"
    request = Request(BASE_URL + path, data=None if payload is None else json.dumps(payload).encode("utf-8"),
                      headers=headers, method="GET" if payload is None else "POST")
    started = time.monotonic()
    try:
        with opener.open(request, timeout=TIMEOUT_SECONDS) as response:
            if response.status != 200 or response.geturl() != request.full_url:
                raise ValueError("unexpected response")
            if response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
                raise ValueError("unexpected content type")
            if response.headers.get("Content-Encoding", "identity").lower() != "identity":
                raise ValueError("encoded response rejected")
            remaining = TIMEOUT_SECONDS - (time.monotonic() - started)
            if remaining <= 0:
                raise TimeoutError
            connection = getattr(getattr(response, "fp", None), "raw", None)
            connection_socket = getattr(connection, "_sock", None)
            if connection_socket is not None:
                connection_socket.settimeout(remaining)
            body = read_bounded(response, MAX_RESPONSE_BYTES, remaining)
            if time.monotonic() - started >= TIMEOUT_SECONDS:
                raise TimeoutError
            result = _json_loads(body)
            if not isinstance(result, dict) or "error" in result:
                raise ValueError("invalid provider response")
            return result
    except HTTPError as error:
        status = error.code
        provider_code, reason = _safe_error_metadata(error)
        error.close()
        raise ProviderHttpError(status, provider_code, reason) from None


def _empty_report(model):
    return {
        "schema": "zhipu-candidate-sanity/v1",
        "model_id": model,
        "model_version": None,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "scope": "short-text-sanity-only; not complex-task, leader, role, or routing qualification",
        "passed": False,
        "health": {"passed": False, "latency_ms": None},
        "checks": [],
        "usage_complete": False,
        "estimated_cash_cny": None,
        "actual_billed_cash_cny": None,
    }


def run_sanity_suite(key, model, *, allow_paid=False, allow_chat_health=False):
    if allow_paid is not True or model not in ALLOWED_MODELS:
        raise ValueError("explicit paid authorization and an allowlisted model are required")
    if not isinstance(key, str) or not 1 <= len(key) <= 512 or any(not 33 <= ord(character) <= 126 for character in key):
        raise ValueError("invalid saved credential")
    report = _empty_report(model)
    health_start = time.monotonic()
    chat_health = False
    try:
        opener = build_opener(ProxyHandler({}), NoRedirect())
        catalog = _request_json(opener, key, model)
        rows = catalog.get("data")
        report["health"]["passed"] = (isinstance(rows, list) and 1 <= len(rows) <= 1024
                                      and sum(isinstance(row, dict) and row.get("id") == model for row in rows) == 1)
        if not report["health"]["passed"]:
            report["health"]["failure_class"] = "model-not-in-catalog"
            chat_health = allow_chat_health is True and isinstance(rows, list)
    except ProviderHttpError as error:
        report["health"]["http_status"] = error.status
        report["health"]["failure_class"] = "catalog-http-error"
        chat_health = allow_chat_health is True and error.status in {404, 405}
    except Exception as error:
        report["health"]["failure_class"] = type(error).__name__
        return report
    finally:
        report["health"]["latency_ms"] = round((time.monotonic() - health_start) * 1000, 3)
    if not report["health"]["passed"] and not chat_health:
        return report
    report["health"]["source"] = "explicit-chat-probe" if chat_health else "models-endpoint"
    for check_id, prompt in CHECKS:
        record = {"check_id": check_id, "passed": False, "usage": {}, "latency_ms": None,
                  "finish_reason": None, "applied_reasoning_effort": None}
        report["checks"].append(record)
        started = time.monotonic()
        try:
            payload = _request_json(opener, key, model, prompt=prompt)
            record["usage"] = _usage(payload)
            applied = payload.get("applied_reasoning_effort")
            record["applied_reasoning_effort"] = applied if isinstance(applied, str) and applied in APPLIED_EFFORTS else None
            choices = payload.get("choices")
            if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
                return report
            choice = choices[0]
            finish = choice.get("finish_reason")
            record["finish_reason"] = finish if isinstance(finish, str) and finish in FINISH_REASONS else None
            message = choice.get("message")
            record["passed"] = (
                record["finish_reason"] == "stop" and isinstance(message, dict)
                and message.get("role") == "assistant" and not message.get("tool_calls")
                and not message.get("function_call") and not message.get("refusal")
                and payload.get("model", model) == model and _matches(check_id, message.get("content"))
            )
            if chat_health and check_id == "arithmetic":
                report["health"]["passed"] = record["passed"]
                report["health"]["latency_ms"] = round((time.monotonic() - started) * 1000, 3)
        except Exception as error:
            record["failure_class"] = type(error).__name__
            if isinstance(error, ProviderHttpError):
                record["http_status"] = error.status
                record["provider_code"] = error.provider_code
                record["provider_error_category"] = error.reason
            return report
        finally:
            record["latency_ms"] = round((time.monotonic() - started) * 1000, 3)
            report["usage_complete"] = all(
                {"input_tokens", "output_tokens"}.issubset(item["usage"]) for item in report["checks"]
            )
        if not record["passed"] or not {"input_tokens", "output_tokens"}.issubset(record["usage"]):
            return report
    report["passed"] = True
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--saved-key", action="store_true", required=True, help="Read the previously approved Windows vault credential")
    parser.add_argument("--allow-paid", action="store_true", required=True, help="Authorize at most three bounded calls; monetary pricing is unknown")
    parser.add_argument("--allow-chat-health", action="store_true", help="Explicitly allow the first fixed task as health probe when GET /models is missing")
    parser.add_argument("--model", choices=ALLOWED_MODELS, required=True)
    parser.add_argument("--report", type=Path, required=True, help="New report path; existing files are never overwritten")
    args = parser.parse_args(argv)
    report = _empty_report(args.model)
    try:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        with args.report.open("x", encoding="utf-8") as output:
            key = None
            try:
                vault = WindowsCredentialStore(VAULT_NAMESPACE)
                key = vault.read(VAULT_REFERENCE).get("api_key", "")
                report = run_sanity_suite(key, args.model, allow_paid=args.allow_paid, allow_chat_health=args.allow_chat_health)
            except Exception:
                pass
            finally:
                key = None
                output.write(json.dumps(report, ensure_ascii=True, indent=2, allow_nan=False) + "\n")
    except OSError:
        print("Sanity report could not be created; no existing report was overwritten.", file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=True, allow_nan=False))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
