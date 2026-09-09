import json
from pathlib import Path
import subprocess
import threading
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

from sumika_core.browser.runtime import BrowserRuntimeError, BrowserSkillClient
from sumika_core.integrations.modelscope_benefits import (
    COMMAND_TIMEOUT,
    LOAD_TIMEOUT_SECONDS,
    MAX_POLLS,
    ModelScopeBenefitsReader,
    READ_EXPRESSION,
    SELECT_RECORDS_EXPRESSION,
    USAGE_URL,
)


def evidence(**updates):
    result = {
        "state": "verified", "available_balance": 242.25, "unit": "magicube",
        "grants": [{"kind": "daily-login", "amount": 200, "granted_date_display": "2026-09-08",
                    "validity_days_display": 1, "expires_at": None}],
    }
    result.update(updates)
    return result


class ModelScopeBenefitsTests(unittest.TestCase):
    def test_fixed_expressions_keep_native_extraction_contract_without_css_hashes(self):
        from sumika_core.integrations import modelscope_benefits
        source = Path(modelscope_benefits.__file__).read_text(encoding="utf-8")
        guard = source.split('_PAGE_GUARD = r"""', 1)[1].split('"""', 1)[0]
        for name, expression in (("READ_EXPRESSION", READ_EXPRESSION), ("SELECT_RECORDS_EXPRESSION", SELECT_RECORDS_EXPRESSION)):
            marker = name + ' = "JSON.stringify((() => {\\n" + _PAGE_GUARD + r"""'
            body = source.split(marker, 1)[1].split('"""', 1)[0]
            self.assertEqual("JSON.stringify((() => {\n" + guard + body, expression)
            self.assertNotIn(".acss-", expression)
            self.assertNotIn("location.search", expression)
            self.assertNotIn("fetch(", expression)

    def test_semantic_ambiguity_discards_evidence_without_selecting_or_retrying(self):
        self.observations = [{"state": "needs-review", "reason": "ambiguous-records-tab", "available_balance": 999}]
        result = self.read()
        self.assertEqual(result["state"], "needs-review")
        self.assertEqual(result["error"], "ambiguous-records-tab")
        self.assertIsNone(result["available_balance"])
        self.assertEqual(result["grants"], [])
        self.assertEqual(sum(command[0] == "evaluate" for command in self.commands), 1)
        self.assert_closed_own_session()

    def setUp(self):
        self.commands = []
        self.stop_event = threading.Event()
        self.observations = [evidence()]
        self.select_result = {"state": "pending", "reason": "records-selected"}
        self.hook = None
        self.client = BrowserSkillClient(r"D:\Tools\BrowserSkill\0.1.11\bsk.exe", runner=self.runner, timeout=50)
        self.reader = ModelScopeBenefitsReader(self.client)

    def runner(self, args):
        self.commands.append(args)
        if self.hook is not None:
            result = self.hook(args)
            if result is not None:
                return result
        if args == ("status",):
            return {"browsers": [{"instance_id": "browser-edge-1", "browser_name": "Edge", "private": "must-not-project"}],
                    "sessions": [{"id": "user-existing-session"}], "other": "must-not-project"}
        if args == ("session", "start", "--browser", "browser-edge-1", "--no-focus"):
            return {"id": "reader-session", "browser_instance_id": "browser-edge-1"}
        if args == ("tab", "create", "--session", "reader-session", "--url", "about:blank", "--no-active"):
            return {"tab": {"id": 27}}
        if args == ("navigate", "--session", "reader-session", "--tab-id", "27", "--wait-until", "commit", "--timeout", "8s", USAGE_URL):
            return {"ok": True}
        if args[:5] == ("evaluate", "--session", "reader-session", "--tab-id", "27"):
            if args[5] == SELECT_RECORDS_EXPRESSION:
                return {"ok": True, "value": json.dumps(self.select_result)}
            self.assertEqual(args[5], READ_EXPRESSION)
            return {"ok": True, "value": json.dumps(self.observations.pop(0))}
        if args == ("session", "stop", "reader-session"):
            return {"closed": True}
        raise AssertionError("unexpected command")

    def read(self):
        return self.reader.read("browser-edge-1", self.stop_event)

    def assert_closed_own_session(self):
        self.assertEqual(self.commands[-1], ("session", "stop", "reader-session"))
        self.assertEqual(sum(command[:2] == ("session", "stop") for command in self.commands), 1)
        self.assertNotIn(("session", "stop", "user-existing-session"), self.commands)

    def test_browsers_projects_only_safe_metadata_and_connected_instance(self):
        self.assertEqual(self.reader.browsers(), [{"instance_id": "browser-edge-1", "browser_name": "Edge"}])
        self.assertEqual(self.commands, [("status",)])

    def test_unknown_browser_name_never_exposes_profile_or_page_text(self):
        self.hook = lambda args: {"browsers": [{"instanceId": "browser-edge-1", "name": "private-profile@example.invalid"}]} if args == ("status",) else None
        self.assertEqual(self.reader.browsers(), [{"instance_id": "browser-edge-1", "browser_name": "unknown"}])

    def test_verified_projection_does_not_export_text_or_assert_key_account_binding(self):
        self.observations = [evidence(account_binding_verified=True, private_text="private-html-body", error="private-error")]
        self.observations[0]["grants"][0]["title"] = "private-grant-title"
        result = self.read()
        self.assertEqual(result["state"], "verified")
        self.assertEqual(result["available_balance"], 242.25)
        self.assertEqual(result["unit"], "magicube")
        self.assertFalse(result["account_binding_verified"])
        self.assertIsNone(result["error"])
        self.assertIsNotNone(datetime.fromisoformat(result["checked_at"]).utcoffset())
        self.assertEqual(set(result), {"state", "checked_at", "available_balance", "unit", "grants", "error", "account_binding_verified"})
        self.assertEqual(set(result["grants"][0]), {"kind", "amount", "granted_date_display", "validity_days_display", "expires_at"})
        self.assertNotIn("private", json.dumps(result))
        self.assert_closed_own_session()

    def test_zero_balance_and_binding_grant_are_valid_without_daily_or_expiry_inference(self):
        self.observations = [evidence(available_balance=0)]
        self.observations[0]["grants"][0].update(kind="aliyun-binding", validity_days_display=90)
        result = self.read()
        self.assertEqual(result["state"], "verified")
        self.assertEqual(result["available_balance"], 0)
        self.assertIsNone(result["grants"][0]["expires_at"])
        self.assertFalse(result["account_binding_verified"])

    def test_navigation_is_fixed_background_tab_in_exact_no_focus_browser(self):
        self.read()
        self.assertIn(("session", "start", "--browser", "browser-edge-1", "--no-focus"), self.commands)
        created = ("tab", "create", "--session", "reader-session", "--url", "about:blank", "--no-active")
        navigated = ("navigate", "--session", "reader-session", "--tab-id", "27", "--wait-until", "commit", "--timeout", "8s", USAGE_URL)
        self.assertIn(created, self.commands)
        self.assertIn(navigated, self.commands)
        self.assertLess(self.commands.index(created), self.commands.index(navigated))
        self.assertEqual(sum(command[0] == "navigate" for command in self.commands), 1)
        self.assertFalse(any(command[0] in {"fill", "press", "click", "request-help", "network", "get-html"} for command in self.commands))
        self.assert_closed_own_session()

    def test_exact_records_click_runs_once_then_reads_again(self):
        self.observations = [{"state": "select-records"}, {"state": "select-records"}, evidence()]
        with patch.object(self.stop_event, "wait", return_value=False):
            result = self.read()
        self.assertEqual(result["state"], "verified")
        self.assertEqual(sum(command[-1] == SELECT_RECORDS_EXPRESSION for command in self.commands), 1)
        self.assert_closed_own_session()

    def test_polling_is_bounded_without_re_navigation_or_re_submission(self):
        self.observations = [{"state": "pending"}] * MAX_POLLS
        with patch.object(self.stop_event, "wait", return_value=False) as wait:
            result = self.read()
        self.assertEqual(result["state"], "needs-review")
        self.assertEqual(result["error"], "poll-limit")
        self.assertIsNone(result["available_balance"])
        self.assertEqual(sum(command[0] == "evaluate" for command in self.commands), MAX_POLLS)
        self.assertEqual(wait.call_count, MAX_POLLS - 1)
        self.assert_closed_own_session()

    def test_initial_blank_and_loading_eventually_verify_after_eight_seconds(self):
        elapsed = [0.0]
        self.observations = ([{"state": "pending", "reason": "initial-blank"}] * 6
                             + [{"state": "pending", "reason": "page-loading"}] * 6
                             + [{"state": "pending", "reason": "missing-records-tabs"}] * 4
                             + [{"state": "select-records"}, evidence()])
        def wait(seconds):
            elapsed[0] += seconds
            return False
        with patch("sumika_core.integrations.modelscope_benefits.monotonic", side_effect=lambda: elapsed[0]), patch.object(self.stop_event, "wait", side_effect=wait):
            result = self.read()
        self.assertEqual(result["state"], "verified")
        self.assertGreaterEqual(elapsed[0], 8)
        self.assertLessEqual(elapsed[0], LOAD_TIMEOUT_SECONDS)
        self.assertEqual(sum(command[0] == "navigate" for command in self.commands), 1)
        self.assertEqual(sum(command[-1] == SELECT_RECORDS_EXPRESSION for command in self.commands), 1)
        self.assert_closed_own_session()

    def test_loading_deadline_includes_navigation_and_never_reloads(self):
        elapsed = [0.0]
        self.observations = [{"state": "pending", "reason": "initial-blank"}] * MAX_POLLS
        def hook(args):
            if args[0] == "navigate":
                elapsed[0] += 7
        def wait(seconds):
            elapsed[0] += seconds
            return False
        self.hook = hook
        with patch("sumika_core.integrations.modelscope_benefits.monotonic", side_effect=lambda: elapsed[0]), patch.object(self.stop_event, "wait", side_effect=wait):
            result = self.read()
        self.assertEqual(result["state"], "needs-review")
        self.assertEqual(result["error"], "page-load-timeout")
        self.assertEqual(elapsed[0], LOAD_TIMEOUT_SECONDS)
        self.assertIsNone(result["available_balance"])
        self.assertEqual(sum(command[0] == "navigate" for command in self.commands), 1)
        self.assert_closed_own_session()

    def test_late_verified_response_after_loading_deadline_is_discarded(self):
        elapsed = [0.0]
        def hook(args):
            if args[0] == "evaluate":
                elapsed[0] = LOAD_TIMEOUT_SECONDS + 0.01
        self.hook = hook
        with patch("sumika_core.integrations.modelscope_benefits.monotonic", side_effect=lambda: elapsed[0]):
            result = self.read()
        self.assertEqual(result["state"], "needs-review")
        self.assertEqual(result["error"], "page-load-timeout")
        self.assertIsNone(result["available_balance"])
        self.assertEqual(result["grants"], [])
        self.assert_closed_own_session()

    def test_remaining_loading_budget_caps_the_real_client_subprocess_timeout(self):
        client = BrowserSkillClient("bsk", timeout=60)
        reader = ModelScopeBenefitsReader(client)
        completed = SimpleNamespace(returncode=0, stdout='{"ok":true}')
        with patch("sumika_core.integrations.modelscope_benefits.monotonic", return_value=9), patch("sumika_core.browser.runtime.subprocess.run", return_value=completed) as run:
            reader._command(("evaluate",), self.stop_event, deadline=12)
        self.assertEqual(run.call_args.kwargs["timeout"], 3)
        self.assertEqual(client.timeout, 60)

    def test_blank_after_verified_origin_or_foreign_loading_page_is_not_retried(self):
        for final in ({"state": "pending", "reason": "initial-blank"}, {"state": "needs-review", "reason": "wrong-page"}):
            with self.subTest(final=final):
                self.commands.clear()
                self.observations = [{"state": "pending", "reason": "page-loading"}, final]
                with patch.object(self.stop_event, "wait", return_value=False):
                    result = self.read()
                self.assertEqual(result["state"], "needs-review")
                self.assertEqual(result["error"], "wrong-page")
                self.assertEqual(sum(command[0] == "evaluate" for command in self.commands), 2)
                self.assert_closed_own_session()

    def test_tabs_loading_between_read_and_select_do_not_consume_the_click(self):
        self.observations = [{"state": "select-records"}, {"state": "select-records"}, evidence()]
        selections = iter([{"state": "pending", "reason": "missing-records-tabs"}, {"state": "pending", "reason": "records-selected"}])
        self.hook = lambda args: {"ok": True, "value": json.dumps(next(selections))} if args[-1] == SELECT_RECORDS_EXPRESSION else None
        with patch.object(self.stop_event, "wait", return_value=False):
            self.assertEqual(self.read()["state"], "verified")
        self.assertEqual(sum(command[-1] == SELECT_RECORDS_EXPRESSION for command in self.commands), 2)
        self.assert_closed_own_session()

    def test_navigation_abort_stops_before_dom_and_closes_session(self):
        self.hook = lambda args: {"ok": False, "code": "user_aborted"} if args[0] == "navigate" else None
        self.assertEqual(self.read()["state"], "interrupted")
        self.assertFalse(any(command[0] == "evaluate" for command in self.commands))
        self.assert_closed_own_session()

    def test_login_challenge_or_unknown_reason_stop_without_more_dom_work(self):
        for state in ("login-required", "challenge", "needs-review"):
            with self.subTest(state=state):
                self.commands.clear()
                self.observations = [{"state": state, "reason": "private-webpage-body"}]
                result = self.read()
                self.assertEqual(result["state"], state)
                self.assertEqual(result["error"], "page-unverified")
                self.assertIsNone(result["available_balance"])
                self.assertEqual(sum(command[0] == "evaluate" for command in self.commands), 1)
                self.assertNotIn("private", json.dumps(result))
                self.assert_closed_own_session()

    def test_login_or_challenge_during_tab_selection_stops(self):
        self.observations = [{"state": "select-records"}]
        self.select_result = {"state": "challenge", "reason": "challenge"}
        result = self.read()
        self.assertEqual(result["state"], "challenge")
        self.assert_closed_own_session()

    def test_user_aborted_exception_and_command_payload_become_interrupted(self):
        for raises in (False, True):
            with self.subTest(raises=raises):
                self.commands.clear()
                def hook(args):
                    if args[0] == "evaluate":
                        if raises:
                            raise BrowserRuntimeError("private-abort-message", code="user_aborted")
                        return {"ok": False, "error": {"code": "user_aborted", "message": "private-abort-message"}}
                self.hook = hook
                result = self.read()
                self.assertEqual(result["state"], "interrupted")
                self.assertNotIn("private", json.dumps(result))
                self.assertEqual(sum(command[0] == "evaluate" for command in self.commands), 1)
                self.assert_closed_own_session()

    def test_stop_before_start_makes_no_commands(self):
        self.stop_event.set()
        self.assertEqual(self.read()["state"], "interrupted")
        self.assertEqual(self.commands, [])

    def test_stop_during_session_creation_still_closes_that_session(self):
        def hook(args):
            if args[:2] == ("session", "start"):
                self.stop_event.set()
        self.hook = hook
        self.assertEqual(self.read()["state"], "interrupted")
        self.assertEqual(len(self.commands), 3)
        self.assert_closed_own_session()

    def test_stop_after_dom_response_drops_balance_and_closes_session(self):
        def hook(args):
            if args[0] == "evaluate":
                self.stop_event.set()
        self.hook = hook
        result = self.read()
        self.assertEqual(result["state"], "interrupted")
        self.assertIsNone(result["available_balance"])
        self.assertEqual(result["grants"], [])
        self.assert_closed_own_session()

    def test_stop_while_waiting_stops_polling(self):
        self.observations = [{"state": "pending"}]
        with patch.object(self.stop_event, "wait", return_value=True):
            self.assertEqual(self.read()["state"], "interrupted")
        self.assert_closed_own_session()

    def test_invalid_balance_grant_amount_date_or_validity_never_verifies(self):
        invalid = [evidence(available_balance=value) for value in (None, True, -1, float("inf"), float("nan"), "242", 1.001, 1_000_000_000)]
        for key, value in (("amount", True), ("amount", -1), ("amount", "200"), ("amount", 0),
                           ("granted_date_display", "2026-02-30"), ("granted_date_display", "private-date"),
                           ("validity_days_display", True), ("validity_days_display", 0), ("validity_days_display", 1000),
                           ("kind", "unapproved-private-grant"), ("expires_at", "2026-09-09T00:00:00Z")):
            observation = evidence()
            observation["grants"][0][key] = value
            invalid.append(observation)
        invalid.extend([evidence(unit="tokens"), evidence(grants=[]), evidence(grants=evidence()["grants"] * 2)])
        for observation in invalid:
            with self.subTest(observation=observation):
                self.commands.clear()
                self.observations = [observation]
                result = self.read()
                self.assertEqual(result["state"], "needs-review")
                self.assertIsNone(result["available_balance"])
                self.assertEqual(result["grants"], [])
                self.assertNotIn("private", json.dumps(result))
                self.assert_closed_own_session()

    def test_failed_later_read_never_reuses_previous_balance(self):
        self.assertEqual(self.read()["state"], "verified")
        self.observations = [{"state": "login-required", "reason": "login-required"}]
        result = self.read()
        self.assertEqual(result["state"], "login-required")
        self.assertIsNone(result["available_balance"])
        self.assertEqual(result["grants"], [])

    def test_disconnected_or_invalid_browser_has_no_session_or_fallback(self):
        for identifier in ("missing-browser", "--browser=other", "*", "browser name"):
            with self.subTest(identifier=identifier):
                self.commands.clear()
                self.assertNotEqual(self.reader.read(identifier, self.stop_event)["state"], "verified")
                self.assertFalse(any(command[:2] == ("session", "start") for command in self.commands))

    def test_browser_instance_mismatch_closes_new_session(self):
        self.hook = lambda args: {"id": "reader-session", "browser_instance_id": "other-browser"} if args[:2] == ("session", "start") else None
        result = self.read()
        self.assertEqual(result["error"], "browser-instance-mismatch")
        self.assert_closed_own_session()

    def test_malformed_browser_lists_are_not_partially_trusted(self):
        for rows in ([{"id": "browser-edge-1", "instance_id": "other"}], [{"id": "duplicate"}] * 2,
                     [{"id": f"browser-{index}"} for index in range(65)], "private-browser-list"):
            with self.subTest(rows=rows):
                self.hook = lambda args: {"browsers": rows}
                self.assertEqual(self.reader.browsers(), [])

    def test_unknown_browser_error_is_sanitized_and_session_is_closed(self):
        def hook(args):
            if args[0] == "evaluate":
                raise BrowserRuntimeError("private-body-and-key", code="private-error-code")
        self.hook = hook
        result = self.read()
        self.assertEqual(result["state"], "unavailable")
        self.assertEqual(result["error"], "browser-command-failed")
        self.assertNotIn("private", json.dumps(result))
        self.assert_closed_own_session()

    def test_dom_envelope_must_be_successful_bounded_json_object(self):
        for response in ({"ok": True, "value": "not-json"}, {"ok": True, "value": "[]"},
                         {"ok": True, "value": "x" * 32_001}, {"value": json.dumps(evidence())},
                         {"ok": True, "value": '{"state":"challenge","state":"verified"}'},
                         {"ok": True, "value": '{"state":[]}'},
                         {"ok": True, "value": '{"available_balance":NaN}'}):
            with self.subTest(response=str(response)[:60]):
                self.commands.clear()
                self.hook = lambda args: response if args[0] == "evaluate" else None
                self.assertEqual(self.read()["state"], "needs-review")
                self.assert_closed_own_session()

    def test_session_cleanup_failure_does_not_return_verified_balance(self):
        def hook(args):
            if args[:2] == ("session", "stop"):
                raise BrowserRuntimeError("private-close-error")
        self.hook = hook
        result = self.read()
        self.assertEqual(result["state"], "needs-review")
        self.assertEqual(result["error"], "session-close-failed")
        self.assertIsNone(result["available_balance"])

    def test_user_abort_while_closing_or_in_dom_result_stays_interrupted(self):
        self.observations = [evidence()]
        self.hook = lambda args: {"ok": False, "error": "user_aborted"} if args[:2] == ("session", "stop") else None
        result = self.read()
        self.assertEqual(result["state"], "interrupted")
        self.assertIsNone(result["available_balance"])
        self.assertEqual(result["grants"], [])
        self.hook = None
        self.observations = [{"state": "user_aborted"}]
        self.assertEqual(self.read()["state"], "interrupted")

    def test_real_client_command_timeout_is_capped_without_mutating_shared_client(self):
        client = BrowserSkillClient(r"D:\Tools\BrowserSkill\0.1.11\bsk.exe", timeout=60)
        reader = ModelScopeBenefitsReader(client)
        completed = SimpleNamespace(returncode=0, stdout='{"browsers": []}')
        with patch("sumika_core.browser.runtime.subprocess.run", return_value=completed) as run:
            self.assertEqual(reader.browsers(), [])
        self.assertEqual(run.call_args.kwargs["timeout"], COMMAND_TIMEOUT)
        self.assertEqual(client.timeout, 60)
        self.assertEqual(run.call_args.args[0], [client.executable, "status", "--json"])

    def test_timeout_returns_unavailable_without_retry_or_real_execution(self):
        client = BrowserSkillClient("bsk", timeout=90)
        with patch("sumika_core.browser.runtime.subprocess.run", side_effect=subprocess.TimeoutExpired("bsk", 10)) as run:
            result = ModelScopeBenefitsReader(client).read("browser-edge-1", self.stop_event)
        self.assertEqual(result["state"], "unavailable")
        self.assertEqual(run.call_count, 1)


if __name__ == "__main__":
    unittest.main()
