"""Opt-in free-route sanity tests; no retries, fallback, or quality promotion."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import sys
import time
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "backend/src"), str(ROOT / "packages/quality-routing/src")]

from sumika_core.credentials import WindowsCredentialStore, credential_namespace_for_data_dir
from sumika_core.integrations.zhipu_pricing import read_bounded
from sumika_core.storage import Storage
from tools.evaluate_zhipu_candidates import CHECKS, FINISH_REASONS, _json_loads, _matches, _usage
from tools.register_openrouter_free_candidates import NoRedirect, PROFILE_ID, fetch_catalog

BASE_URL = "https://openrouter.ai/api/v1"
CANDIDATES = (
    "google/gemma-4-31b-it:free",
    "google/gemma-4-26b-a4b-it:free",
    "nvidia/nemotron-3-super-120b-a12b:free",
)
TIMEOUT_SECONDS = 30
MAX_TOKENS = 1024


class ApiFailure(ValueError):
    def __init__(self, status, category):
        super().__init__("OpenRouter request failed")
        self.status = status
        self.category = category


def request_json(opener, key, path, payload=None):
    if path not in {"/key", "/chat/completions"}:
        raise ValueError("unsupported endpoint")
    headers = {"Authorization": "Bearer " + key, "Accept": "application/json", "Accept-Encoding": "identity"}
    if payload is not None:
        headers["Content-Type"] = "application/json"
    request = Request(BASE_URL + path, headers=headers,
                      data=None if payload is None else json.dumps(payload).encode("utf-8"),
                      method="GET" if payload is None else "POST")
    started = time.monotonic()
    try:
        with opener.open(request, timeout=TIMEOUT_SECONDS) as response:
            if response.status != 200 or response.geturl() != request.full_url:
                raise ValueError("unexpected response")
            if response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
                raise ValueError("JSON response required")
            if response.headers.get("Content-Encoding", "identity").lower() != "identity":
                raise ValueError("encoded response rejected")
            remaining = TIMEOUT_SECONDS - (time.monotonic() - started)
            if remaining <= 0:
                raise TimeoutError
            connection = getattr(getattr(response, "fp", None), "raw", None)
            connection_socket = getattr(connection, "_sock", None)
            if connection_socket is not None:
                connection_socket.settimeout(remaining)
            result = _json_loads(read_bounded(response, 128000, remaining))
            if time.monotonic() - started >= TIMEOUT_SECONDS:
                raise TimeoutError
            if not isinstance(result, dict) or "error" in result:
                raise ValueError("invalid API response")
            return result
    except HTTPError as error:
        category = {401: "authentication", 402: "credit-limit", 403: "access-denied",
                    404: "no-endpoint", 429: "rate-limit"}.get(error.code, "http-error")
        try:
            body = _json_loads(read_bounded(error, 8192, 2))
            detail = body.get("error") if isinstance(body, dict) else None
            message = detail.get("message") if isinstance(detail, dict) else None
            if isinstance(message, str) and any(token in message.lower() for token in ("data policy", "privacy", "data collection")):
                category = "privacy-policy-no-endpoint"
        except Exception:
            pass
        finally:
            error.close()
        raise ApiFailure(error.code, category) from None


def reported_cost(payload):
    usage = payload.get("usage")
    value = usage.get("cost") if isinstance(usage, dict) else None
    if type(value) not in (str, int, float):
        return None
    try:
        cost = Decimal(str(value))
        return str(cost) if cost.is_finite() and 0 <= cost <= 1000000 else None
    except InvalidOperation:
        return None


def failure_metadata(error):
    if isinstance(error, ApiFailure):
        return {"http_status": error.status, "failure_class": error.category}
    return {"failure_class": type(error).__name__}


def run_suite(key, models, *, allow_free_tests=False):
    if (allow_free_tests is not True or not models or len(models) > 3
            or len(set(models)) != len(models) or any(model not in CANDIDATES for model in models)):
        raise ValueError("explicit authorization and bounded model allowlist required")
    if not isinstance(key, str) or not 1 <= len(key) <= 512 or any(not 33 <= ord(character) <= 126 for character in key):
        raise ValueError("invalid credential")
    report = {"schema": "openrouter-candidate-sanity/v1", "checked_at": datetime.now(timezone.utc).isoformat(),
              "scope": "short-text-sanity-only; not leader, role, or routing qualification",
              "authenticated": False, "is_free_tier": None, "free_requests_remaining": None,
              "model_calls": 0, "routing_qualified": False, "candidates": []}
    opener = build_opener(ProxyHandler({}), NoRedirect())
    try:
        account = request_json(opener, key, "/key").get("data")
        if not isinstance(account, dict) or account.get("is_management_key") is not False:
            raise ValueError("ordinary API key required")
        report["authenticated"] = True
        if type(account.get("is_free_tier")) is bool:
            report["is_free_tier"] = account["is_free_tier"]
        catalog = fetch_catalog()
        free_ids = {row["model_id"] for row in catalog["models"]}
        report["pricing_observed_at"] = catalog["observed_at"]
    except Exception as error:
        report.update(failure_metadata(error))
        return report
    for model in models:
        candidate = {"model_id": model, "health_passed": False, "passed": False, "checks": [],
                     "model_version": None, "applied_reasoning_effort": None}
        report["candidates"].append(candidate)
        if model not in free_ids:
            candidate["failure_class"] = "not-in-current-free-catalog"
            continue
        for check_id, prompt in CHECKS:
            record = {"check_id": check_id, "passed": False, "usage": {}, "reported_cost_usd": None}
            candidate["checks"].append(record)
            payload = {"model": model, "messages": [{"role": "user", "content": prompt}],
                       "max_tokens": MAX_TOKENS, "stream": False,
                       "provider": {"allow_fallbacks": False, "require_parameters": True,
                                    "max_price": {"prompt": 0, "completion": 0}}}
            started = time.monotonic()
            report["model_calls"] += 1
            try:
                response = request_json(opener, key, "/chat/completions", payload)
                record["usage"] = _usage(response)
                record["reported_cost_usd"] = reported_cost(response)
                choices = response.get("choices")
                if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
                    raise ValueError("invalid choice")
                choice = choices[0]
                message = choice.get("message")
                finish = choice.get("finish_reason")
                record["finish_reason"] = finish if isinstance(finish, str) and finish in FINISH_REASONS else None
                identity_matches = response.get("model") in {model, model.removesuffix(":free")}
                valid = (identity_matches and isinstance(message, dict) and message.get("role") == "assistant"
                         and isinstance(message.get("content"), str) and not message.get("tool_calls")
                         and not message.get("function_call") and not message.get("refusal"))
                candidate["health_passed"] = candidate["health_passed"] or valid
                record["passed"] = bool(valid and finish == "stop" and _matches(check_id, message.get("content")))
                if (not identity_matches or not {"input_tokens", "output_tokens"} <= record["usage"].keys()
                        or record["reported_cost_usd"] is None or Decimal(record["reported_cost_usd"]) != 0):
                    record["failure_class"] = "identity-usage-or-free-cost-unconfirmed"
                    return report
            except ApiFailure as error:
                record.update(failure_metadata(error))
                if error.status in {401, 402, 403, 429} or error.category == "privacy-policy-no-endpoint":
                    return report
                break
            except Exception as error:
                record.update(failure_metadata(error))
                return report
            finally:
                record["latency_ms"] = round((time.monotonic() - started) * 1000, 3)
            if not record["passed"]:
                break
        candidate["passed"] = len(candidate["checks"]) == len(CHECKS) and all(record["passed"] for record in candidate["checks"])
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--model", action="append", choices=CANDIDATES)
    parser.add_argument("--allow-free-tests", action="store_true", required=True)
    args = parser.parse_args()
    database = args.data_dir.resolve() / "sumika.sqlite3"
    if not database.is_file() or args.report.exists():
        raise ValueError("existing data and new report path required")
    args.report.parent.mkdir(parents=True, exist_ok=True)
    with args.report.open("x", encoding="utf-8") as output:
        key = None
        storage = Storage(database)
        try:
            profile = storage.get_provider_profile(PROFILE_ID)
            if not profile or profile.get("archived_at") or profile["config"].get("active_base_url", "").rstrip("/") != BASE_URL:
                raise ValueError("matching active official profile required")
            models = args.model or list(CANDIDATES)
            configured = {row["id"] for row in profile["config"].get("models", []) if row.get("enabled") is True}
            if not set(models) <= configured:
                raise ValueError("registered models required")
            vault = WindowsCredentialStore(credential_namespace_for_data_dir(args.data_dir))
            key = vault.read(profile.get("credential_ref") or "").get("api_key")
            report = run_suite(key, models, allow_free_tests=args.allow_free_tests)
        finally:
            key = None
            storage.close()
        json.dump(report, output, indent=2, allow_nan=False)
    print(json.dumps(report, allow_nan=False))
    return 0 if report["candidates"] and all(candidate["passed"] for candidate in report["candidates"]) and "failure_class" not in report else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(json.dumps({"ok": False, "failure_class": type(error).__name__}))
        raise SystemExit(1) from None
