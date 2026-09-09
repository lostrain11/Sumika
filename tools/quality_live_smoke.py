"""Bounded, opt-in Zhipu smoke through the real Sumika text workflow."""

from __future__ import annotations

import argparse
from contextlib import ExitStack
from datetime import datetime, timezone
from decimal import Decimal
import getpass
import io
import json
import logging
import os
from pathlib import Path
import sys
import threading
import time
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, Request, build_opener


ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "backend/src"), str(ROOT / "packages/quality-routing/src")]

from sumika_core.credentials import MemoryCredentialStore, WindowsCredentialStore
from sumika_core.protocol.models import ChatRequest, Message
from sumika_core.providers.openai_compatible import OpenAICompatibleProvider
from sumika_core.server import CoreApplication


BASE_URL = "https://open.bigmodel.cn/api/paas/v4"
PRICE_SOURCE = "https://open.bigmodel.cn/pricing"
MODEL = "glm-4.5-flash"
PAID_MODEL = "glm-5.3-flash"
PAID_INPUT_RATE = Decimal("0.8")
PAID_OUTPUT_RATE = Decimal("2.8")
VAULT_NAMESPACE = "approved-provider-tests"
VAULT_REFERENCE = "zhipu-official"


class SmokeStopped(RuntimeError):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        raise SmokeStopped("redirect-rejected")


class RequestGuard:
    def __init__(self, *, max_calls=8, max_output=4096, max_input_bytes=16000, allow_paid=False, cash_limit="0.50"):
        self.max_calls = max_calls
        self.max_output = max_output
        self.max_input_bytes = max_input_bytes
        self.allow_paid = allow_paid
        self.cash_limit = Decimal(cash_limit)
        if not self.cash_limit.is_finite() or self.cash_limit <= 0:
            raise ValueError("invalid cash limit")
        self.reserved_cash = Decimal(0)
        self.calls = []
        self.stopped = False
        self.lock = threading.Lock()
        self.opener = build_opener(NoRedirect())

    def admit(self, request):
        with self.lock:
            if self.stopped:
                raise SmokeStopped("previous-failure")
            if request.full_url == BASE_URL + "/models" and request.method == "GET":
                return None
            if request.full_url != BASE_URL + "/chat/completions" or request.method != "POST":
                raise SmokeStopped("destination-rejected")
            payload = json.loads(request.data)
            if payload.get("model") not in ({MODEL, PAID_MODEL} if self.allow_paid else {MODEL}):
                raise SmokeStopped("model-rejected")
            output = payload.get("max_tokens")
            if type(output) is not int or not 1 <= output <= self.max_output:
                raise SmokeStopped("output-limit")
            context = {key: payload[key] for key in ("messages", "tools") if key in payload}
            input_bytes = len(json.dumps(context, ensure_ascii=False).encode("utf-8"))
            if input_bytes > self.max_input_bytes or len(self.calls) >= self.max_calls:
                raise SmokeStopped("request-limit")
            reserved = ((Decimal(input_bytes + 512) * PAID_INPUT_RATE + Decimal(output) * PAID_OUTPUT_RATE) / 1000000
                        if payload["model"] == PAID_MODEL else Decimal(0))
            if self.reserved_cash + reserved > self.cash_limit:
                raise SmokeStopped("cash-limit")
            self.reserved_cash += reserved
            record = {"call": len(self.calls) + 1, "model": payload["model"],
                      "input_bytes": input_bytes, "max_output_tokens": output,
                      "reserved_cash_cny": str(reserved), "thinking_request": payload.get("thinking"),
                      "requested_reasoning_effort": payload.get("reasoning_effort"),
                      "applied_reasoning_effort": None, "usage": {}, "status": "submitted"}
            self.calls.append(record)
            return record

    def open(self, provider, request, *, timeout=None):
        record = self.admit(request)
        provider._smoke_record = record
        try:
            response = self.opener.open(request, timeout=min(timeout or provider.timeout, 90))
            if record is not None:
                record["http_status"] = response.status
                if not json.loads(request.data).get("stream"):
                    with response:
                        body = response.read(128001)
                        if len(body) > 128000:
                            raise SmokeStopped("response-limit")
                        provider._capture_usage(json.loads(body))
                        self.finish(provider, False)
                        buffered = io.BytesIO(body)
                        buffered.status = response.status
                        buffered.headers = response.headers
                    return buffered
            return response
        except HTTPError as error:
            if record is not None or error.code not in {404, 405}:
                self.stopped = True
            if record is not None:
                record.update(status="http-error", http_status=error.code)
            raise
        except Exception as error:
            self.stopped = True
            if record is not None:
                record["status"] = "submission-unknown"
                record["failure_class"] = type(error).__name__
            raise

    def finish(self, provider, failed):
        record = getattr(provider, "_smoke_record", None)
        if record is None:
            return
        if failed:
            self.stopped = True
            record["status"] = "failed"
        else:
            record["status"] = "completed"
        usage = getattr(provider, "last_usage", {})
        record["usage"] = {key: value for key, value in usage.items()
                           if type(value) is int and value >= 0}
        record["applied_reasoning_effort"] = getattr(provider, "last_applied_reasoning_effort", None)
        record["finish_reason"] = getattr(provider, "last_finish_reason", None)
        record["reasoning_content_seen"] = getattr(provider, "last_reasoning_content_seen", False)

    def summary(self):
        complete = bool(self.calls) and all("input_tokens" in item["usage"] and "output_tokens" in item["usage"] for item in self.calls)
        estimated = sum((Decimal(item["usage"].get("input_tokens", 0)) * PAID_INPUT_RATE
                         + Decimal(item["usage"].get("output_tokens", 0)) * PAID_OUTPUT_RATE) / 1000000
                        for item in self.calls if item["model"] == PAID_MODEL)
        return {"calls": self.calls, "usage_complete": complete,
                "reported_input_tokens": sum(item["usage"].get("input_tokens", 0) for item in self.calls),
                "reported_output_tokens": sum(item["usage"].get("output_tokens", 0) for item in self.calls),
                "estimated_cash_cny": str(estimated) if complete else None, "actual_billed_cash_cny": None,
                "reserved_cash_cny": str(self.reserved_cash), "cash_limit_cny": str(self.cash_limit),
                "pricing_basis": "GLM-5.3-Flash undiscounted input 0.8/output 2.8 CNY per million; no promotional, resource-pack or cache discounts",
                "remaining_balance_cny": None, "price_source": PRICE_SOURCE,
                "limits": {"max_calls": self.max_calls, "max_output_tokens_per_call": self.max_output,
                           "max_input_bytes_per_call": self.max_input_bytes}}


def run_smoke(key, guard, *, paid_only=False):
    if paid_only and not guard.allow_paid:
        raise ValueError("paid-only requires explicit paid authorization")
    role_model = PAID_MODEL if paid_only else MODEL
    role_rates = {"currency": "CNY", "input_price_per_million": float(PAID_INPUT_RATE) if paid_only else 0,
                  "output_price_per_million": float(PAID_OUTPUT_RATE) if paid_only else 0}
    checks = {}
    report = {"checked_at": datetime.now(timezone.utc).isoformat(), "checks": checks,
              "scope": "isolated-api-text-workflow; no cross-channel quality equivalence claim"}
    original_stream = OpenAICompatibleProvider.stream

    def stream(provider, request):
        failed = True
        pieces = []
        try:
            for piece in original_stream(provider, request):
                pieces.append(piece)
                yield piece
            failed = False
        finally:
            guard.finish(provider, failed)
            record = getattr(provider, "_smoke_record", None)
            if record is not None:
                prompt = request.messages[-1].content
                record["workflow_stage"] = ("role-introduction" if "short in-character introduction" in prompt
                                            else "role-fidelity-review" if "role-introduction fidelity" in prompt else "other")
                answer = "".join(pieces).strip()
                record["response_nonempty"] = bool(answer)
                record["response_fenced"] = answer.startswith("```")
                try:
                    parsed = json.loads(answer)
                except ValueError:
                    parsed = None
                record["response_json_object"] = isinstance(parsed, dict)

    environment = {name: value for name, value in os.environ.items() if not name.startswith("SUMIKA_")}
    environment.update(SUMIKA_AGENT_RUNTIME="none", SUMIKA_AGENT_AUTOSTART="0", SUMIKA_ZCODE_AUTODISCOVER="0")
    app = None
    task_scope = None
    with ExitStack() as stack:
        stack.enter_context(patch.dict(os.environ, environment, clear=True))
        stack.enter_context(patch.object(OpenAICompatibleProvider, "_open", lambda provider, request, **kwargs: guard.open(provider, request, **kwargs)))
        stack.enter_context(patch.object(OpenAICompatibleProvider, "stream", stream))
        try:
            app = CoreApplication(":memory:", credential_store=MemoryCredentialStore())
            profile = app.provider_profiles.save({
                "name": "Isolated Zhipu smoke", "base_url": BASE_URL, "model": role_model,
                "models": [{"id": role_model, "reasoning_efforts": [] if paid_only else ["off"]}],
                "api_key": key, "processing_location": "cloud", "timeout": 90,
                "pricing": {"source_type": "manual", "billing_group": "official-smoke",
                            "rates": role_rates,
                            "cash_conversion": {"paid_amount": 1, "credited_amount": 1, "currency": "CNY"}},
            })
            health = app.provider_profiles.health(profile["id"], allow_chat_probe=True)
            checks["health"] = health.get("ok") is True
            report["health"] = {name: health.get(name) for name in ("ok", "status", "model_catalog", "health_probe", "error")}
            if not checks["health"]:
                raise SmokeStopped("health-failed")
            app.modules.update("llm", enabled=True, implementation_id="openai-compatible", config={"profile_id": profile["id"]})
            candidate = next(item for item in app.quality.catalog()["candidates"] if item["model_id"] == role_model and item["reasoning_effort"] is None)
            candidate_id = candidate["candidate_id"]
            role_id = candidate_id if paid_only else candidate_id + ":effort:off"
            checks["authorized_candidate"] = candidate["authorized"] and candidate["available"]
            app.quality.update_settings({"assistant_id": "sumika", "role_candidate_id": role_id})
            ordinary = app.rpc("chat.send", {"character_id": "sumika", "session_id": "smoke-chat", "max_tokens": 1024,
                                             "messages": [{"role": "user", "content": "Calculate 6 times 7. Reply only with the number."}]})
            checks["ordinary_answer"] = ordinary["message"]["content"].strip() == "42"
            if not checks["ordinary_answer"]:
                raise SmokeStopped("ordinary-answer-failed")
            if guard.allow_paid and not paid_only:
                paid = app.provider_profiles.save({"name": "Isolated paid leader", "base_url": BASE_URL,
                    "model": PAID_MODEL, "api_key": key, "processing_location": "cloud", "timeout": 90,
                    "pricing": {"source_type": "manual", "billing_group": "official-smoke",
                        "rates": {"currency": "CNY", "input_price_per_million": float(PAID_INPUT_RATE), "output_price_per_million": float(PAID_OUTPUT_RATE)},
                        "cash_conversion": {"paid_amount": 1, "credited_amount": 1, "currency": "CNY"}}})
                checks["paid_health"] = app.provider_profiles.health(paid["id"], allow_chat_probe=True).get("ok") is True
                if not checks["paid_health"]:
                    raise SmokeStopped("paid-health-failed")
                candidate_id = next(item["candidate_id"] for item in app.quality.catalog()["candidates"] if item["model_id"] == PAID_MODEL)
            app.quality.update_settings({"assistant_id": "sumika", "role_candidate_id": role_id, "leader_candidate_id": candidate_id})
            plan = app.rpc("quality.task.plan", {"assistant_id": "sumika", "session_id": "smoke-task", "external_allowed": True,
                "allowed_candidate_ids": list(dict.fromkeys([candidate_id, role_id])),
                "goal": "Calculate 6 times 7. The answer deliverable must be the exact string \"42\": two ASCII digits only, no words, math expressions, punctuation or Markdown. Planning constraint: use one synthesis node with no dependencies and output_tokens=1024. Do not use tools."})
            task_scope = {"assistant_id": "sumika", "session_id": "smoke-task", "task_id": plan["task_id"]}
            checks["awaits_confirmation"] = plan["status"] == "awaiting-confirmation"
            checks["bounded_plan"] = len(plan["plan"]["nodes"]) == 1
            report["quote"] = plan["budget"]["quote"]
            count_before = len(guard.calls)
            time.sleep(0.1)
            checks["no_execution_before_confirmation"] = len(guard.calls) == count_before
            if not all(checks.values()):
                raise SmokeStopped("plan-check-failed")
            app.rpc("quality.task.confirm", {**task_scope, "revision": plan["revision"]})
            deadline = time.monotonic() + 180
            while time.monotonic() < deadline:
                result = app.rpc("quality.task.get", task_scope)
                if result.get("final_message") or result.get("workflow_error") or guard.stopped:
                    break
                if result["status"] in {"needs-attention", "cancelled"}:
                    break
                time.sleep(0.1)
            checks["workflow_completed"] = result["status"] == "completed" and bool(result.get("final_message"))
            checks["verified_answer"] = bool(result["results"]) and all(item["text"].strip() == "42" for item in result["results"].values())
            checks["delivery_preserves_answer"] = (result.get("final_message") or {}).get("content", "").strip().endswith("42")
            introductions = [call for call in guard.calls if call.get("workflow_stage") == "role-introduction"]
            checks["role_introduction_nonempty"] = (bool(introductions) and bool(introductions[-1].get("response_nonempty"))
                and introductions[-1]["model"] == role_model
                and introductions[-1].get("thinking_request") == (None if paid_only else {"type": "disabled"})
                and introductions[-1].get("finish_reason") not in {"length", "content_filter"})
            if guard.allow_paid:
                paid_calls = [item for item in guard.calls if item["model"] == PAID_MODEL and item.get("response_nonempty")]
                checks["paid_leader_workflow"] = len(paid_calls) >= 3
                checks["paid_thinking_not_disabled"] = all(item.get("thinking_request") != {"type": "disabled"} for item in paid_calls)
            checks["authorized_models_only"] = all(item["model"] in ({MODEL, PAID_MODEL} if guard.allow_paid else {MODEL}) for item in guard.calls)
            report["workflow"] = {"status": result["status"], "revision": result["revision"],
                                  "states": list(result["states"].values()), "calls": result["budget"]["calls"]}
            report["passed"] = all(checks.values())
        except Exception as error:
            report["passed"] = False
            report["failure_class"] = type(error).__name__
            if isinstance(error, SmokeStopped):
                report["failure_code"] = str(error)
            else:
                safe_codes = ("leader response must be a JSON object", "leader response must be an object",
                              "leader plan contains unsupported fields", "invalid identifier", "invalid risk",
                              "invalid task list", "invalid non-negative count", "no qualified candidate")
                report["failure_code"] = next((code for code in safe_codes if code in str(error)), "unclassified")
        finally:
            guard.stopped = True
            if app is not None:
                if task_scope is not None:
                    app.rpc("quality.task.cancel", task_scope)
                app.close()
    report.update(guard.summary())
    return report


def run_paid_probe(key, guard):
    provider = OpenAICompatibleProvider(base_url=BASE_URL, model=PAID_MODEL, api_key=key, timeout=90)
    report = {"checked_at": datetime.now(timezone.utc).isoformat(), "scope": "isolated-paid-model-probe", "passed": False}
    failed = True
    try:
        with patch.object(provider, "_open", lambda request: guard.open(provider, request)):
            answer = "".join(provider.stream(ChatRequest("paid-probe", [Message("user", "Compute 17 plus 25. Return only the integer.")], max_tokens=4096)))
        failed = False
        report["checks"] = {"exact_answer": answer.strip() == "42", "complete": provider.last_finish_reason == "stop"}
        report["passed"] = all(report["checks"].values())
    except Exception as error:
        report["failure_class"] = type(error).__name__
    finally:
        guard.finish(provider, failed)
        guard.stopped = True
    report.update(guard.summary())
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--key-stdin", action="store_true", help="Read key from a private pipe, never argv or environment")
    parser.add_argument("--save-key", action="store_true", help="Store input in Windows Credential Manager; no model calls")
    parser.add_argument("--saved-key", action="store_true", help="Use the explicitly user-approved stored Zhipu credential")
    parser.add_argument("--allow-paid", action="store_true", help="Use GLM-5.3-Flash leader with a 0.50 CNY conservative ceiling")
    parser.add_argument("--probe-paid", action="store_true", help="One direct GLM-5.3-Flash probe without free-model prerequisites; requires allow-paid")
    parser.add_argument("--paid-only", action="store_true", help="Run the full workflow with GLM-5.3-Flash only; requires allow-paid")
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    logging.disable(logging.CRITICAL)
    if args.saved_key and (args.save_key or args.key_stdin):
        parser.error("saved-key cannot be combined with key input")
    if args.probe_paid and (not args.allow_paid or args.save_key):
        parser.error("probe-paid requires allow-paid and cannot save credentials")
    if args.paid_only and (not args.allow_paid or args.save_key or args.probe_paid):
        parser.error("paid-only requires allow-paid and cannot combine with save-key or probe-paid")
    vault = WindowsCredentialStore(VAULT_NAMESPACE) if args.saved_key or args.save_key else None
    key = vault.read(VAULT_REFERENCE).get("api_key", "") if args.saved_key else sys.stdin.readline().strip() if args.key_stdin else getpass.getpass("Zhipu API key: ")
    if not key or len(key) > 512 or any(character.isspace() for character in key):
        raise SystemExit("Invalid key input")
    if args.save_key:
        vault.write(VAULT_REFERENCE, {"api_key": key})
        result = {"passed": vault.read(VAULT_REFERENCE).get("api_key") == key,
                  "credential_store": "Windows Credential Manager", "namespace": VAULT_NAMESPACE,
                  "reference": VAULT_REFERENCE, "model_calls": 0}
    elif args.probe_paid:
        result = run_paid_probe(key, RequestGuard(allow_paid=True, max_calls=1))
    else:
        result = run_smoke(key, RequestGuard(allow_paid=args.allow_paid), paid_only=args.paid_only)
    key = None
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
