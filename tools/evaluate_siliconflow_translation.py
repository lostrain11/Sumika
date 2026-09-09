"""Bounded translation-only probe; no routing promotion or response text logs."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from decimal import Decimal
import json
from pathlib import Path
import sys
import time
from urllib.request import ProxyHandler, build_opener

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.evaluate_siliconflow_candidates import (
    BASE_URL, PROFILE_ID, NoRedirect, Storage, WindowsCredentialStore,
    credential_namespace_for_data_dir, failure_metadata, reported_cost, request_json, _usage,
)
from tools.read_siliconflow_public_pricing import fetch_prices

MODEL = "tencent/Hunyuan-MT-7B"
CHECKS = (
    ("en-zh-action", "Please save the file before closing the window.",
     (("\u4fdd\u5b58",), ("\u6587\u4ef6",), ("\u5173\u95ed",), ("\u7a97\u53e3",))),
    ("ja-zh-status", "\u66f4\u65b0\u304c\u5b8c\u4e86\u3057\u307e\u3057\u305f\u3002\u30a2\u30d7\u30ea\u3092\u518d\u8d77\u52d5\u3057\u3066\u304f\u3060\u3055\u3044\u3002",
     (("\u66f4\u65b0",), ("\u5b8c\u6210", "\u7ed3\u675f"), ("\u5e94\u7528", "\u7a0b\u5e8f", "\u8f6f\u4ef6"), ("\u91cd\u542f", "\u91cd\u65b0\u542f\u52a8"))),
    ("en-zh-identifiers", "The meeting starts at 14:30 in Room B-204.",
     (("\u4f1a\u8bae",), ("14:30",), ("B-204",))),
)


def run_suite(key, *, allow_confirmed_free_tests=False):
    if allow_confirmed_free_tests is not True:
        raise ValueError("explicit free-test authorization required")
    if not isinstance(key, str) or not 1 <= len(key) <= 512 or any(not 33 <= ord(character) <= 126 for character in key):
        raise ValueError("invalid credential")
    report = {"schema": "siliconflow-translation-sanity/v1", "checked_at": datetime.now(timezone.utc).isoformat(),
              "model_id": MODEL, "capability": "text-translation", "model_calls": 0,
              "authenticated": False, "health_passed": False, "basic_checks_passed": False,
              "scope": "keyword-and-identifier-sanity-only; not semantic, OCR, chat, or routing qualification",
              "routing_qualified": False, "actual_billed_cash_cny": None,
              "applied_reasoning_effort": None, "checks": []}
    try:
        prices = fetch_prices()
        matches = [row for row in prices["models"] if row.get("model_id") == MODEL]
        if len(matches) != 1 or any(matches[0].get(field) != "free" for field in ("input_price_label", "output_price_label")):
            raise ValueError("fresh explicit free translation prices required")
        report["price_evidence"] = {"source_url": prices["source_url"], "observed_at": prices["observed_at"], **matches[0]}
        opener = build_opener(ProxyHandler({}), NoRedirect())
        rows = request_json(opener, key).get("data")
        if not isinstance(rows, list) or not 1 <= len(rows) <= 10000:
            raise ValueError("bounded account catalog required")
        report["authenticated"] = True
        if sum(isinstance(row, dict) and row.get("id") == MODEL for row in rows) != 1:
            raise ValueError("unique exact translation model required")
    except Exception as error:
        report.update(failure_metadata(error))
        return report
    for check_id, source, groups in CHECKS:
        record = {"check_id": check_id, "passed": False, "usage": {}, "reported_cost_value": None}
        report["checks"].append(record)
        started = time.monotonic()
        report["model_calls"] += 1
        try:
            response = request_json(opener, key, {"model": MODEL, "stream": False, "max_tokens": 256,
                "messages": [{"role": "user", "content": "Translate the following segment into Chinese, without additional explanation.\n\n" + source}]})
            record["usage"] = _usage(response)
            record["reported_cost_value"] = reported_cost(response)
            if record["reported_cost_value"] is not None and Decimal(record["reported_cost_value"]) > 0:
                record["failure_class"] = "unexpected-reported-charge"
                break
            if response.get("model") != MODEL:
                record["failure_class"] = "unexpected-model-identity"
                break
            choices = response.get("choices")
            if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
                raise ValueError("single choice required")
            message = choices[0].get("message")
            if not isinstance(message, dict):
                raise ValueError("assistant response required")
            content = message.get("content")
            valid = (message.get("role") == "assistant" and isinstance(content, str) and bool(content.strip())
                     and not message.get("tool_calls") and not message.get("function_call") and not message.get("refusal"))
            report["health_passed"] = report["health_passed"] or bool(valid)
            record["complete"] = choices[0].get("finish_reason") == "stop"
            record["keywords_preserved"] = bool(valid and all(any(term in content for term in group) for group in groups))
            record["passed"] = bool(valid and record["complete"] and record["keywords_preserved"]
                                    and {"input_tokens", "output_tokens"} <= record["usage"].keys())
            if not record["passed"]:
                break
        except Exception as error:
            record.update(failure_metadata(error))
            break
        finally:
            record["latency_ms"] = round((time.monotonic() - started) * 1000, 3)
    report["basic_checks_passed"] = len(report["checks"]) == len(CHECKS) and all(record["passed"] for record in report["checks"])
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--allow-confirmed-free-tests", action="store_true", required=True)
    args = parser.parse_args()
    database = args.data_dir.resolve() / "sumika.sqlite3"
    if not database.is_file() or args.report.exists():
        raise ValueError("existing data directory and new report required")
    args.report.parent.mkdir(parents=True, exist_ok=True)
    with args.report.open("x", encoding="utf-8") as output:
        key = None
        storage = None
        report = {"model_calls": 0, "routing_qualified": False, "basic_checks_passed": False}
        try:
            storage = Storage(database)
            profile = storage.get_provider_profile(PROFILE_ID)
            if not profile or profile.get("archived_at") or profile["config"].get("active_base_url", "").rstrip("/") != BASE_URL:
                raise ValueError("matching official profile required")
            vault = WindowsCredentialStore(credential_namespace_for_data_dir(args.data_dir))
            key = vault.read(profile.get("credential_ref") or "").get("api_key")
            report = run_suite(key, allow_confirmed_free_tests=args.allow_confirmed_free_tests)
        except Exception as error:
            report.update(failure_metadata(error))
        finally:
            key = None
            if storage is not None:
                storage.close()
            json.dump(report, output, indent=2, allow_nan=False)
    print(json.dumps(report, allow_nan=False))
    return 0 if report["basic_checks_passed"] else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(json.dumps({"ok": False, "failure_class": type(error).__name__}))
        raise SystemExit(1) from None
