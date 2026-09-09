"""Explicit bounded tests of user-confirmed free candidates, without promotion."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from decimal import Decimal
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
from tools.evaluate_openrouter_candidates import reported_cost
from tools.evaluate_zhipu_candidates import CHECKS, FINISH_REASONS, _json_loads, _matches, _safe_error_metadata, _usage
from tools.register_openrouter_free_candidates import NoRedirect
from tools.read_xfyun_public_catalog import fetch_catalog as fetch_xfyun_catalog

BASE_URL = "https://api.siliconflow.cn/v1"
PROFILE_ID = "siliconflow-free-candidates"
MODELS = ("Qwen/Qwen3-8B", "THUDM/GLM-4-9B-0414", "deepseek-ai/DeepSeek-R1-0528-Qwen3-8B")
TIMEOUT = 30
MAX_TOKENS = 1024
PROVIDERS = {
    "siliconflow": {
        "base_url": BASE_URL, "profile_id": PROFILE_ID, "models": MODELS,
        "price_evidence": "user-confirmed-free; bounded-test-authorization-only",
        "interval_seconds": 0,
    },
    "agnes": {
        "base_url": "https://apihub.agnes-ai.com/v1", "profile_id": "agnes-free-candidates",
        "models": ("agnes-2.0-flash", "agnes-2.5-flash"),
        "price_evidence": "official-free-default-key-documentation; user-supplied-free-key; billing-unverified",
        "interval_seconds": 3.1,
    },
    "xfyun": {
        "base_url": "https://maas-api.cn-huabei-1.xf-yun.com/v2", "profile_id": "xfyun-free-candidates",
        "models": ("spark-x2.5-1.7b", "spark-x2.5-4b"),
        "price_evidence": "fresh-official-inference-catalog; account-quota-unverified",
        "interval_seconds": 3.1,
    },
    "ollama-cloud": {
        "base_url": "https://ollama.com/v1", "profile_id": "ollama-cloud-candidates",
        "models": ("gpt-oss:20b", "glm-5.3-flash", "gemma4:31b"),
        "price_evidence": "official-free-starter-credits; not-zero-unit-price; account-balance-unverified",
        "catalog_is_public": True, "interval_seconds": 1,
    },
    "modelscope": {
        "base_url": "https://api-inference.modelscope.cn/v1", "profile_id": "modelscope-free-candidates",
        "models": ("Qwen/Qwen3-Coder-30B-A3B-Instruct", "Qwen/Qwen3.5-35B-A3B", "deepseek-ai/DeepSeek-V4-Flash-0731"),
        "price_evidence": "official-community-api-inference; magicube-credits-required; account-balance-unverified",
        "catalog_is_public": True, "interval_seconds": 1,
    },
}


class ApiFailure(ValueError):
    def __init__(self, status, code, category):
        super().__init__("provider request failed")
        self.status, self.code, self.category = status, code, category


def request_json(opener, key, payload=None, *, provider="siliconflow"):
    path = "/models" if payload is None else "/chat/completions"
    headers = {"Authorization": "Bearer " + key, "Accept": "application/json", "Accept-Encoding": "identity"}
    if payload is not None:
        headers["Content-Type"] = "application/json"
    request = Request(PROVIDERS[provider]["base_url"] + path, headers=headers, method="GET" if payload is None else "POST",
                      data=None if payload is None else json.dumps(payload).encode("utf-8"))
    started = time.monotonic()
    try:
        with opener.open(request, timeout=TIMEOUT) as response:
            if response.status != 200 or response.geturl() != request.full_url:
                raise ValueError("unexpected response")
            if response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
                raise ValueError("JSON required")
            if response.headers.get("Content-Encoding", "identity").lower() != "identity":
                raise ValueError("encoded response rejected")
            remaining = TIMEOUT - (time.monotonic() - started)
            if remaining <= 0:
                raise TimeoutError
            connection = getattr(getattr(response, "fp", None), "raw", None)
            connection_socket = getattr(connection, "_sock", None)
            if connection_socket is not None:
                connection_socket.settimeout(remaining)
            result = _json_loads(read_bounded(response, 128000, remaining))
            if time.monotonic() - started >= TIMEOUT:
                raise TimeoutError
            if not isinstance(result, dict) or "error" in result:
                raise ValueError("invalid provider response")
            return result
    except HTTPError as error:
        code, category = _safe_error_metadata(error)
        error.close()
        raise ApiFailure(error.code, code, category) from None


def failure_metadata(error):
    if isinstance(error, ApiFailure):
        return {"failure_class": "provider-http-error", "http_status": error.status,
                "provider_code": error.code, "provider_error_category": error.category}
    return {"failure_class": type(error).__name__}


def run_suite(key, models, *, allow_confirmed_free_tests=False, check_ids=None, provider="siliconflow",
              allow_public_catalog_probe=False):
    settings = PROVIDERS[provider]
    selected_ids = tuple(check_ids) if check_ids is not None else tuple(check_id for check_id, _prompt in CHECKS)
    allowed_ids = {check_id for check_id, _prompt in CHECKS}
    if (allow_confirmed_free_tests is not True or not models or len(models) > 3
            or len(set(models)) != len(models) or any(model not in settings["models"] for model in models)
            or not selected_ids or len(set(selected_ids)) != len(selected_ids) or not set(selected_ids) <= allowed_ids):
        raise ValueError("bounded user-confirmed free models and explicit authorization required")
    if not isinstance(key, str) or not 1 <= len(key) <= 512 or any(not 33 <= ord(character) <= 126 for character in key):
        raise ValueError("invalid credential")
    report = {"schema": provider + "-candidate-sanity/v1", "checked_at": datetime.now(timezone.utc).isoformat(),
              "price_evidence": settings["price_evidence"],
              "scope": "short-text-sanity-only; not leader, role, or routing qualification",
              "authenticated": False, "model_calls": 0, "actual_billed_cash_cny": None,
              "routing_qualified": False, "selected_checks": list(selected_ids), "candidates": []}
    opener = build_opener(ProxyHandler({}), NoRedirect())
    try:
        if provider == "xfyun":
            report["public_pricing"] = fetch_xfyun_catalog()
        rows = request_json(opener, key, provider=provider).get("data")
        if not isinstance(rows, list) or len(rows) > 10000:
            raise ValueError("invalid catalog")
        if provider == "xfyun" and not rows and allow_public_catalog_probe is True:
            rows = [{"id": row["model_id"]} for row in report["public_pricing"]["models"]]
            report["catalog_basis"] = "public-catalog; account-catalog-empty; explicit-chat-health-probe"
        elif not rows:
            raise ValueError("empty account catalog; explicit public-catalog probe required")
        else:
            report["authenticated"] = not settings.get("catalog_is_public", False)
    except Exception as error:
        report.update(failure_metadata(error))
        return report
    previous_started = None
    for model in models:
        candidate = {"model_id": model, "health_passed": False, "passed": False, "selected_checks_passed": False, "checks": [],
                     "model_version": None, "applied_reasoning_effort": None}
        report["candidates"].append(candidate)
        if sum(isinstance(row, dict) and row.get("id") == model for row in rows) != 1:
            candidate["failure_class"] = "missing-or-duplicate-catalog-model"
            continue
        for check_id, prompt in CHECKS:
            if check_id not in selected_ids:
                continue
            record = {"check_id": check_id, "passed": False, "usage": {}, "reported_cost_value": None}
            candidate["checks"].append(record)
            if previous_started is not None:
                time.sleep(max(0, settings["interval_seconds"] - (time.monotonic() - previous_started)))
            started = time.monotonic()
            previous_started = started
            report["model_calls"] += 1
            try:
                response = request_json(opener, key, {"model": model, "messages": [{"role": "user", "content": prompt}],
                                        "max_tokens": MAX_TOKENS, "stream": False}, provider=provider)
                record["usage"] = _usage(response)
                record["reported_cost_value"] = reported_cost(response)
                if record["reported_cost_value"] is not None and Decimal(record["reported_cost_value"]) > 0:
                    record["failure_class"] = "unexpected-reported-charge"
                    return report
                choices = response.get("choices")
                if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
                    raise ValueError("invalid choice")
                choice = choices[0]
                message = choice.get("message")
                finish = choice.get("finish_reason")
                record["finish_reason"] = finish if isinstance(finish, str) and finish in FINISH_REASONS else None
                valid = (isinstance(message, dict)
                         and message.get("role") == "assistant" and isinstance(message.get("content"), str)
                         and bool(message["content"].strip())
                         and not message.get("tool_calls") and not message.get("function_call") and not message.get("refusal"))
                identity_matches = response.get("model") == model
                candidate["health_passed"] = candidate["health_passed"] or (valid and identity_matches)
                report["authenticated"] = report["authenticated"] or valid
                record["answer_contract_passed"] = bool(valid and finish == "stop" and _matches(check_id, message.get("content")))
                record["model_echo_present"] = "model" in response
                if not identity_matches:
                    record["failure_class"] = "unexpected-model-identity"
                    return report
                record["passed"] = bool(valid and finish == "stop" and _matches(check_id, message.get("content")))
                if not valid or not {"input_tokens", "output_tokens"} <= record["usage"].keys():
                    break
            except Exception as error:
                record.update(failure_metadata(error))
                if isinstance(error, ApiFailure) and error.status in {401, 402, 403, 429}:
                    return report
                break
            finally:
                record["latency_ms"] = round((time.monotonic() - started) * 1000, 3)
        candidate["selected_checks_passed"] = (len(candidate["checks"]) == len(selected_ids)
            and all(record["passed"] and {"input_tokens", "output_tokens"} <= record["usage"].keys()
                    for record in candidate["checks"]))
        candidate["passed"] = len(selected_ids) == len(CHECKS) and candidate["selected_checks_passed"]
    return report


def main(*, provider="siliconflow"):
    settings = PROVIDERS[provider]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--model", action="append", choices=settings["models"])
    parser.add_argument("--check", action="append", choices=[check_id for check_id, _prompt in CHECKS])
    parser.add_argument("--allow-confirmed-free-tests", action="store_true", required=True)
    parser.add_argument("--allow-public-catalog-probe", action="store_true")
    args = parser.parse_args()
    database = args.data_dir.resolve() / "sumika.sqlite3"
    if not database.is_file() or args.report.exists():
        raise ValueError("existing data directory and new report required")
    report = {"schema": provider + "-candidate-sanity/v1", "model_calls": 0, "candidates": [], "routing_qualified": False}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    with args.report.open("x", encoding="utf-8") as output:
        key = None
        storage = Storage(database)
        try:
            profile = storage.get_provider_profile(settings["profile_id"])
            if not profile or profile.get("archived_at") or profile["config"].get("active_base_url", "").rstrip("/") != settings["base_url"]:
                raise ValueError("matching official profile required")
            models = args.model or list(settings["models"])
            configured = {row["id"] for row in profile["config"].get("models", []) if row.get("enabled") is True}
            if not set(models) <= configured:
                raise ValueError("registered enabled models required")
            vault = WindowsCredentialStore(credential_namespace_for_data_dir(args.data_dir))
            key = vault.read(profile.get("credential_ref") or "").get("api_key")
            report = run_suite(key, models, allow_confirmed_free_tests=args.allow_confirmed_free_tests,
                               check_ids=args.check, provider=provider,
                               allow_public_catalog_probe=args.allow_public_catalog_probe)
        except Exception as error:
            report.update(failure_metadata(error))
        finally:
            key = None
            storage.close()
            json.dump(report, output, indent=2, allow_nan=False)
    print(json.dumps(report, allow_nan=False))
    return 0 if report["candidates"] and all(candidate["selected_checks_passed"] for candidate in report["candidates"]) else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(json.dumps({"ok": False, "failure_class": type(error).__name__}))
        raise SystemExit(1) from None
