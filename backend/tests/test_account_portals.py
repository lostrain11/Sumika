from __future__ import annotations

import json
from pathlib import Path
import subprocess
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

from sumika_core.integrations.account_portals import (
    AccountPortalReader,
    OLLAMA_STARTER_MODELS,
    project_modelscope_portal,
    project_ollama_starter_portal,
)


NOW = datetime(2026, 9, 8, 16, 0, tzinfo=timezone.utc)


def modelscope_observation(**updates):
    value = {
        "state": "verified", "available_balance": 242, "unit": "magicube",
        "grants": [
            {"kind": "daily-login", "amount": 200, "granted_date_display": "2026-09-08", "validity_days_display": 1},
            {"kind": "aliyun-binding", "amount": 50, "granted_date_display": "2026-09-08", "validity_days_display": 1},
        ],
    }
    value.update(updates)
    return value


def ollama_observation(**updates):
    value = {"state": "verified", "free_usage_percent": 0, "extra_usage_balance": 0,
             "allowed_models": list(OLLAMA_STARTER_MODELS)}
    value.update(updates)
    return value


class ProjectionTests(unittest.TestCase):
    def test_receipt_reader_projects_exact_logs_and_cleans_its_own_session(self):
        from sumika_core.integrations.account_sources import MOARK_RECEIPTS_URL
        commands = []
        evidence = {"schema": "moark-receipts/v1", "source_url": MOARK_RECEIPTS_URL, "state": "verified", "receipts": [
            {"evidence_id": "a" * 64, "trace_fingerprint": "b" * 64, "package_fingerprint": "c" * 64,
             "model_id": "fixture", "amount": "0.0009136", "unit": "CNY", "charge_source": "resource-package", "finalized": True}]}
        def runner(args):
            commands.append(args)
            if args == ("status",):
                return {"browsers": [{"instance_id": "selected"}]}
            if args[:2] == ("session", "start"):
                return {"session_id": "owned", "browser_instance_id": "selected"}
            if args[:2] == ("tab", "create"):
                return {"tab_id": 123}
            if args[0] == "evaluate":
                return {"value": json.dumps(evidence)}
            return {"ok": True}
        client = SimpleNamespace(runner=runner, _run=lambda args, timeout=None: runner(args))
        result = AccountPortalReader(client).read_receipts("moark", "selected")
        self.assertEqual(result["receipts"][0]["amount"], "0.0009136")
        self.assertIn(("session", "start", "--browser", "selected", "--no-focus"), commands)
        self.assertIn(("tab", "close", "--session", "owned", "123"), commands)
        self.assertIn(("session", "stop", "owned"), commands)
        self.assertFalse(any(command[:2] == ("tab", "list") for command in commands))
        evidence["receipts"][0]["amount"] = 0.0009136
        commands.clear()
        self.assertEqual(AccountPortalReader(client).read_receipts("moark", "selected")["state"], "needs-review")
        self.assertIn(("session", "stop", "owned"), commands)

    def test_modelscope_projects_amount_unit_and_conservative_date_boundary(self):
        result = project_modelscope_portal(modelscope_observation(), observed_at=NOW)
        self.assertEqual(result["available_balance"], 242)
        self.assertEqual(result["unit"], "magicube")
        self.assertEqual(result["grants"][0]["safe_valid_until"], "2026-09-09T00:00:00+08:00")
        self.assertIsNone(result["grants"][0]["exact_expires_at"])
        self.assertEqual(result["quality"]["blocking_reason"], "account-binding-unverified")
        self.assertEqual(result["routing_blockers"], ["account-binding-unverified", "model-cost-category-unverified"])
        self.assertLessEqual(datetime.fromisoformat(result["fresh_until"]) - NOW, __import__("datetime").timedelta(minutes=15))

    def test_modelscope_rejects_login_page_nan_bad_amount_and_dates(self):
        for observation in (
            {"state": "login-required", "reason": "login-required"},
            modelscope_observation(available_balance=float("nan")),
            modelscope_observation(grants=[{**modelscope_observation()["grants"][0], "amount": 0}]),
            modelscope_observation(grants=[{**modelscope_observation()["grants"][0], "granted_date_display": "2026-02-30"}]),
        ):
            with self.subTest(observation=repr(observation)[:80]):
                self.assertNotEqual(project_modelscope_portal(observation, observed_at=NOW)["quality"]["state"], "verified")

    def test_ollama_keeps_unknown_absolute_quota_and_only_expected_models(self):
        result = project_ollama_starter_portal(ollama_observation(), observed_at=NOW)
        self.assertIsNone(result["available_balance"])
        self.assertIsNone(result["unit"])
        self.assertEqual(result["allowed_models"], list(OLLAMA_STARTER_MODELS))
        self.assertEqual(result["displayed_extra_usage_balance"], {"amount": 0, "unit": "USD"})
        self.assertEqual(result["quality"]["blocking_reason"], "absolute-free-usage-quota-not-displayed")
        self.assertFalse(result["routing_eligible"])
        self.assertEqual(result["displayed_reset"], None)

    def test_ollama_preserves_a_displayed_reset_without_interpreting_its_time(self):
        result = project_ollama_starter_portal(ollama_observation(displayed_reset="重置时间：明天凌晨"), observed_at=NOW)
        self.assertEqual(result["displayed_reset"], "重置时间：明天凌晨")

    def test_ollama_rejects_unknown_or_reordered_models_and_nan(self):
        for observation in (
            ollama_observation(allowed_models=list(OLLAMA_STARTER_MODELS[:-1])),
            ollama_observation(allowed_models=list(reversed(OLLAMA_STARTER_MODELS))),
            ollama_observation(allowed_models=[*OLLAMA_STARTER_MODELS[:-1], "unknown:1b"]),
            ollama_observation(extra_usage_balance=float("nan")),
        ):
            with self.subTest(observation=repr(observation)[:80]):
                self.assertEqual(project_ollama_starter_portal(observation, observed_at=NOW)["quality"]["state"], "needs-review")


class ReaderTests(unittest.TestCase):
    def test_fixed_receipt_expression_offline(self):
        result = subprocess.run(["node", "--test", str(Path(__file__).with_name("test_account_portals_dom.mjs"))],
                                capture_output=True, text=True, encoding="utf-8", timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_receipt_failure_codes_are_preserved_without_arbitrary_page_text(self):
        for reason in ("invalid-receipt-identity", "official-log-forbidden", "private-account-message"):
            commands = []
            def runner(args):
                commands.append(args)
                if args == ("status",):
                    return {"browsers": [{"instance_id": "browser"}]}
                if args[:2] == ("session", "start"):
                    return {"id": "temporary"}
                if args[:2] == ("tab", "create"):
                    return {"id": 123}
                if args[0] == "evaluate":
                    return {"value": json.dumps({"state": "needs-review", "reason": reason})}
                return {"ok": True}
            client = SimpleNamespace(runner=runner, _run=lambda args, timeout=None: runner(args))
            result = AccountPortalReader(client).read_receipts("moark", "browser")
            self.assertEqual(result["reason"], "official-log-read-failed" if reason.startswith("private") else reason)
            self.assertNotIn("private", json.dumps(result))
            self.assertIn(("tab", "close", "--session", "temporary", "123"), commands)

    def test_ollama_waits_for_usage_to_render_but_bounds_permanent_failure(self):
        loading = {"state": "needs-review", "reason": "missing-usage-section"}
        for observations, times, expected in (([loading, ollama_observation()], [0, 0, 0, 1], "observed-with-limitations"),
                                              ([loading], [0, 0, 0, 13], "needs-review")):
            commands = []
            responses = iter(observations)
            def runner(args):
                commands.append(args)
                if args == ("status",):
                    return {"browsers": [{"instance_id": "browser"}]}
                if args[:2] == ("session", "start"):
                    return {"id": "temporary"}
                if args[:2] == ("tab", "create"):
                    return {"id": 123}
                if args[0] == "evaluate":
                    return {"value": json.dumps(next(responses))}
                return {"ok": True}
            client = SimpleNamespace(runner=runner, _run=lambda args, timeout=None: runner(args))
            stop = SimpleNamespace(is_set=lambda: False, wait=lambda seconds: None)
            with self.subTest(expected=expected), patch("sumika_core.integrations.account_portals.monotonic", side_effect=times):
                result = AccountPortalReader(client).read("ollama", "browser", stop, observed_at=NOW)
            self.assertEqual(result["quality"]["state"], expected)
            self.assertEqual(sum(command[0] == "navigate" for command in commands), 1)
            self.assertIn(("tab", "close", "--session", "temporary", "123"), commands)
            self.assertIn(("session", "stop", "temporary"), commands)

    def test_ollama_reader_owns_only_a_temporary_no_focus_session_and_tab(self):
        commands = []

        def runner(args):
            commands.append(args)
            if args == ("status",):
                return {"ok": True, "browsers": [{"instance_id": "7c8b150e"}]}
            if args[:2] == ("session", "start"):
                return {"ok": True, "id": "temporary-session", "browser_instance_id": "7c8b150e"}
            if args[:2] == ("tab", "create"):
                return {"ok": True, "tab": {"id": 123}}
            if args[0] == "evaluate":
                return {"ok": True, "value": json.dumps(ollama_observation())}
            return {"ok": True}

        client = SimpleNamespace(runner=runner, _run=lambda args, timeout=None: runner(args))
        result = AccountPortalReader(client).read("ollama", "7c8b150e", observed_at=NOW)
        self.assertEqual(result["source"], "ollama-starter")
        self.assertIn(("session", "start", "--browser", "7c8b150e", "--no-focus"), commands)
        self.assertTrue(any(command[:2] == ("tab", "create") and "--no-active" in command for command in commands))
        self.assertTrue(any(command[:2] == ("tab", "close") for command in commands))
        self.assertTrue(any(command[:2] == ("session", "stop") for command in commands))
        self.assertFalse(any(command[:2] == ("tab", "list") for command in commands))

    def test_modelscope_reader_uses_existing_safe_reader_without_a_binding_claim(self):
        client = SimpleNamespace()
        with patch("sumika_core.integrations.account_portals.ModelScopeBenefitsReader.read", return_value=modelscope_observation()) as read:
            result = AccountPortalReader(client).read("modelscope", "7c8b150e", observed_at=NOW)
        read.assert_called_once()
        self.assertFalse(result["account_binding_verified"])

    def test_disconnected_browser_is_a_sanitized_failure(self):
        client = SimpleNamespace(runner=lambda _args: {"ok": True, "browsers": []},
                                 _run=lambda _args, timeout=None: {"ok": True, "browsers": []})
        result = AccountPortalReader(client).read("ollama", "7c8b150e", observed_at=NOW)
        self.assertEqual(result["quality"]["blocking_reason"], "browser-not-connected")


if __name__ == "__main__":
    unittest.main()
