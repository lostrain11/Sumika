"""Evaluate Moark text candidates with public prices and a reserved cash ceiling."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from decimal import Decimal
import json
from pathlib import Path
import sys
import time
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "backend/src"), str(ROOT / "packages/quality-routing/src")]

from sumika_core.credentials import WindowsCredentialStore, credential_namespace_for_data_dir
from sumika_core.free_model_routing import FreeModelRouting
from sumika_core.integrations.moark_catalog import API_URL, amount, fetch_catalog, request_cost_upper
from sumika_core.provider_profiles import ProviderProfileManager, provider_account_revision
from sumika_core.protocol.models import ChatRequest, Message
from sumika_core.providers.guard import RequestNotSent
from sumika_core.storage import Storage
from tools.activate_free_models import CHECKS, matches


PROFILE_ID = "moark-free-candidates"


class CashBudget:
    def __init__(self, limit):
        self.limit = amount(limit)
        if self.limit > Decimal("0.50"):
            raise ValueError("this evaluator is limited to CNY 0.50 per run")
        self.reserved = Decimal(0)

    def reserve(self, estimate):
        estimate = amount(estimate)
        if self.reserved + estimate > self.limit:
            raise RequestNotSent("evaluation budget exhausted")
        self.reserved += estimate


def diagnostics(answer):
    value = answer.strip()
    try:
        json.loads(value)
        valid_json = True
    except ValueError:
        valid_json = False
    return {"nonempty": bool(value), "valid_json": valid_json,
            "markdown_fence": value.startswith("```"), "inline_reasoning": "<think>" in value or "</think>" in value}


def semantic_diagnostics(answer, expected):
    value = answer.strip()
    if value.startswith("<think>") and "</think>" in value:
        value = value.split("</think>", 1)[1].strip()
    if value.startswith("```json\n") and value.endswith("```"):
        value = value[8:-3].strip()
    return {"after_protocol_cleanup_matches": matches(value, expected)}


def run(data_dir, credential_dir, model_ids, *, all_free=False, cash_budget="0", report_path):
    budget = CashBudget(cash_budget)
    catalog = fetch_catalog()
    indexed = {row["model_id"]: row for row in catalog["models"]}
    selected = list(model_ids)
    if all_free:
        selected = list(dict.fromkeys([row["model_id"] for row in catalog["models"]
                                     if row["text_generation"] and row["zero_price"]] + selected))
    if not 1 <= len(selected) <= 16 or len(set(selected)) != len(selected):
        raise ValueError("select one to sixteen unique models")
    for model_id in selected:
        request_cost_upper(indexed[model_id], CHECKS[0][1], 2048)
    storage = Storage(data_dir / "sumika.sqlite3")
    profiles = ProviderProfileManager(storage, WindowsCredentialStore(credential_namespace_for_data_dir(credential_dir)))
    manager = FreeModelRouting(profiles, data_dir)
    report = {"schema": "moark-bounded-evaluation/v2", "checked_at": datetime.now(timezone.utc).isoformat(),
              "suite": "bounded-text-v1", "public_catalog": catalog, "cash_budget_cny": str(budget.limit),
              "cash_reserved_upper_cny": "0", "cash_billed": None, "model_calls": 0, "models": [],
              "failover_enabled": False, "paid_routes_activated": False}
    try:
        profile = profiles.get(PROFILE_ID)
        config = profile["config"]
        if config["active_base_url"] != API_URL or config.get("headers") != {"X-Failover-Enabled": "false"}:
            raise ValueError("fixed Moark endpoint with failover disabled required")
        configured = {row["id"] for row in config["models"] if row.get("enabled", True)}
        if set(selected) - configured:
            raise ValueError("selected models must already be registered")
        manager.enroll(PROFILE_ID, "moark")
        manager.refresh(PROFILE_ID, force=True)
        revision = provider_account_revision(profile)
        abort_batch = False
        for model_id in selected:
            price = indexed[model_id]
            row = {"model_id": model_id, "zero_price": price["zero_price"], "checks": [], "qualified": False}
            report["models"].append(row)
            for check_id, prompt, expected in CHECKS:
                estimate = request_cost_upper(price, prompt, 2048)
                check = {"id": check_id, "passed": False, "cash_reserved_upper_cny": str(estimate)}
                row["checks"].append(check)
                try:
                    budget.reserve(estimate)
                except RequestNotSent:
                    check.update(failure_class="budget-exhausted", sent=False)
                    abort_batch = True
                    break
                time.sleep(4.1)
                provider = profiles.runtime(PROFILE_ID, model_id=model_id)
                provider.disallow_redirects = True
                provider.timeout = 45
                if price["zero_price"]:
                    provider = manager.wrap(provider, PROFILE_ID, model_id, evaluation=True)
                chunks = []
                started = time.monotonic()
                report["model_calls"] += 1
                try:
                    request = ChatRequest("moark-evaluation", [Message("user", prompt)], max_tokens=2048, temperature=0)
                    for chunk in provider.stream(request):
                        chunks.append(chunk)
                    answer = "".join(chunks)
                    check["passed"] = (matches(answer, expected) and provider.last_finish_reason == "stop"
                                       and provider.response_model_matches(provider.last_response_model)
                                       and not provider.last_response_model_mismatch)
                    del answer
                except Exception as error:
                    if isinstance(error, RequestNotSent):
                        report["model_calls"] -= 1
                    cause = error if isinstance(error, HTTPError) else error.__cause__
                    status = cause.code if isinstance(cause, HTTPError) else None
                    if isinstance(cause, HTTPError):
                        cause.close()
                    check.update(failure_class=type(error).__name__, http_status=status, sent=not isinstance(error, RequestNotSent))
                    if price["zero_price"]:
                        check["route_state"] = manager.projection(PROFILE_ID, model_id, evaluation=True)["reason"]
                    abort_batch = (status in {401, 402, 403, 429} or check.get("route_state") == "rate-limited"
                                   or (check.get("route_state") == "submission-uncertain"
                                       and getattr(provider, "last_finish_reason", None) is None))
                finally:
                    check.update(diagnostics("".join(chunks)))
                    check.update(semantic_diagnostics("".join(chunks), expected))
                    chunks.clear()
                    check.update(usage=getattr(provider, "last_usage", {}), finish_reason=getattr(provider, "last_finish_reason", None),
                                 model_echo_matches=provider.response_model_matches(getattr(provider, "last_response_model", None)),
                                 latency_ms=round((time.monotonic() - started) * 1000))
                if not check["passed"]:
                    break
            passed = len(row["checks"]) == len(CHECKS) and all(check["passed"] for check in row["checks"])
            row["qualified"] = passed
            if price["zero_price"]:
                manager.record_evaluation(PROFILE_ID, model_id, passed=passed, revision=revision)
            report["cash_reserved_upper_cny"] = str(budget.reserved)
            if abort_batch:
                break
        return report
    finally:
        report["cash_reserved_upper_cny"] = str(budget.reserved)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        manager.close()
        storage.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--credential-data-dir", type=Path)
    parser.add_argument("--model", action="append", default=[])
    parser.add_argument("--all-free", action="store_true")
    parser.add_argument("--cash-budget-cny", default="0")
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    if args.report.exists():
        raise ValueError("report exists")
    args.report.parent.mkdir(parents=True, exist_ok=True)
    report = run(args.data_dir.resolve(), (args.credential_data_dir or args.data_dir).resolve(), args.model,
                 all_free=args.all_free, cash_budget=args.cash_budget_cny, report_path=args.report)
    print(json.dumps({key: value for key, value in report.items() if key != "public_catalog"}, ensure_ascii=True))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(json.dumps({"ok": False, "failure_class": type(error).__name__}))
        raise SystemExit(1) from None
