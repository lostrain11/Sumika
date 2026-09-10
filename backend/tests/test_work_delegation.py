import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from quality_routing import RoutingError, Scope
from sumika_core.providers.guard import RequestNotSent
from sumika_core.quality.legacy_admission import LegacyWorkAdmission
from sumika_core.quality.work import WorkService
from sumika_core.storage import Storage


class WorkDelegationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "work.sqlite"
        self.storage = Storage(self.path)
        self.addCleanup(self.storage.close)
        self.quality = SimpleNamespace(_scope=lambda params: Scope(params["assistant_id"], params["session_id"]))
        self.work = WorkService(self.storage, self.quality)
        self.addCleanup(self.work.close)
        self.prices = {"parent-session": "1", "child-one": "2", "child-two": "3"}
        self.admission = LegacyWorkAdmission(self.work, profiles=lambda: [], routes=lambda: [], agent_offer=self.offer)
        self.params = {"client_request_id": "parent", "sessionId": "parent-session", "text": "整理报告",
                       "external_steps": [
                           {"id": "one", "purpose": "提取资料", "method": "agent.session.prompt", "params": {"sessionId": "child-one", "text": "提取事实"}},
                           {"id": "two", "purpose": "验证资料", "method": "agent.session.prompt", "params": {"sessionId": "child-two", "text": "验证事实"}},
                       ]}

    def offer(self, params):
        session = params.get("sessionId")
        high = self.prices.get(session)
        return {"candidate_id": "fixture:" + str(session), "identity": ["fixture", session, "v1"],
                "high_cny": high, "limit_enforced": high is not None, "free": high == "0", "funding": "cash"}

    def parent(self):
        return self.work.get("parent", "sumika")

    def start(self):
        execute = Mock(return_value={"status": "completed", "text": "原始正文"})
        pending = self.admission.dispatch("agent.session.prompt", self.params, execute)
        execute.assert_not_called()
        self.assertEqual(pending["work_request"]["quote"]["high_cny"], "6")
        self.work.confirm({"request_id": "parent", "assistant_id": "sumika", "revision": 1, "max_cny": "6"})
        result = self.admission.dispatch("agent.session.prompt", self.params, execute)
        self.assertEqual(result["work_request"]["status"], "executing")
        self.assertEqual(result["work_request"]["authorization"]["spent_cny"], "1")
        return result

    def child_params(self, index=0):
        step = self.parent()["external_steps"][index]
        return {**step["params"], "parent_work_request_id": "parent", "parent_revision": 1, "parent_step_id": step["id"]}

    def child(self, execute, index=0, params=None):
        return self.admission.dispatch("agent.session.prompt", params or self.child_params(index), execute)

    def test_confirmed_plan_shares_one_total_and_completion_is_idempotent(self):
        self.start()
        execute = Mock(return_value={"status": "completed", "text": "child answer"})
        first = self.child(execute)
        self.child(execute)
        self.work.external_observe(first["work_request_id"], "sumika", {"status": "completed"})
        self.assertEqual(execute.call_count, 1)
        self.assertEqual(self.parent()["authorization"]["spent_cny"], "3")
        self.assertEqual(first["work_request"]["authorization"]["budget_owner_request_id"], "parent")
        self.child(execute, 1)
        parent = self.parent()
        self.assertEqual(parent["status"], "completed")
        self.assertEqual(parent["authorization"]["spent_cny"], "6")
        self.assertEqual(parent["authorization"]["reserved_cny"], "0")
        self.assertEqual(parent["artifacts"][0]["content"], "原始正文")
        self.assertEqual(len(parent["attempts"]), 3)

    def test_free_web_plan_confirms_scope_once_then_uses_original_child_entry(self):
        admission = LegacyWorkAdmission(self.work, profiles=lambda: [
            {"id": "parent-profile", "budget_policy": "free-only"},
            {"id": "child-profile", "budget_policy": "free-only"},
        ], routes=lambda: [], agent_offer=self.offer)
        params = {"client_request_id": "web-parent", "profile_id": "parent-profile", "text": "整理材料", "external_steps": [
            {"id": "web-verify", "purpose": "核验已有材料", "method": "browser.web_chat.message.start",
             "params": {"profile_id": "child-profile", "text": "核验事实"}},
        ]}
        execute = Mock(return_value={"status": "completed", "text": "web result"})
        pending = admission.dispatch("browser.web_chat.message.start", params, execute)
        self.assertEqual(pending["status"], "awaiting-confirmation")
        execute.assert_not_called()
        self.work.confirm({"request_id": "web-parent", "assistant_id": "sumika", "revision": 1, "max_cny": "0"})
        parent = admission.dispatch("browser.web_chat.message.start", params, execute)["work_request"]
        step = parent["external_steps"][0]
        result = admission.dispatch(step["method"], {**step["params"], "parent_work_request_id": "web-parent",
                                     "parent_revision": 1, "parent_step_id": "web-verify"}, execute)
        self.assertEqual(result["work_request"]["status"], "completed")
        self.assertEqual(execute.call_count, 2)
        self.assertEqual(self.work.get("web-parent", "sumika")["status"], "completed")

    def test_unconfirmed_parent_does_not_authorize_child(self):
        self.admission.dispatch("agent.session.prompt", self.params, Mock())
        execute = Mock()
        with self.assertRaises(RoutingError):
            self.child(execute)
        execute.assert_not_called()

    def test_ready_parent_must_start_before_children_can_reserve(self):
        self.admission.dispatch("agent.session.prompt", self.params, Mock())
        self.work.confirm({"request_id": "parent", "assistant_id": "sumika", "revision": 1, "max_cny": "6"})
        execute = Mock()
        with self.assertRaises(RoutingError):
            self.child(execute)
        execute.assert_not_called()
        self.assertEqual(self.parent()["attempts"], {})

    def test_late_completed_text_enriches_artifact_without_charging_again(self):
        self.start()
        child = self.child(Mock(return_value={"status": "completed", "turn_id": "turn"}))
        result = self.work.external_observe(child["work_request_id"], "sumika", {"status": "completed", "text": "late clean text"})
        self.assertEqual(result["work_request"]["artifacts"][0]["content"], "late clean text")
        self.assertEqual(self.parent()["authorization"]["spent_cny"], "3")
        self.assertEqual(result["work_request"]["authorization"]["spent_cny"], "2")

    def test_scope_goal_version_and_undeclared_steps_are_rejected(self):
        self.start()
        for changes in ({"assistant_id": "other"}, {"core_session_id": "other"}, {"project_id": "other"},
                        {"text": "删除其他目录"}, {"parent_revision": 2}, {"parent_step_id": "new-step"}):
            with self.subTest(changes=changes):
                execute = Mock()
                with self.assertRaises(RoutingError):
                    self.child(execute, params={**self.child_params(), **changes})
                execute.assert_not_called()

    def test_changed_channel_price_and_manifest_require_new_confirmation(self):
        self.start()
        self.prices["child-one"] = "1"
        execute = Mock()
        with self.assertRaises(RoutingError):
            self.child(execute)
        changed = deepcopy(self.params)
        changed["external_steps"][0]["purpose"] = "新的范围"
        with self.assertRaises(RoutingError):
            self.admission.dispatch("agent.session.prompt", changed, execute)
        execute.assert_not_called()

    def test_unknown_child_price_blocks_entire_plan_before_parent_call(self):
        self.prices["child-one"] = None
        execute = Mock()
        result = self.admission.dispatch("agent.session.prompt", self.params, execute)
        self.assertIsNone(result["work_request"]["quote"]["high_cny"])
        with self.assertRaises(RoutingError):
            self.work.confirm({"request_id": "parent", "assistant_id": "sumika", "revision": 1, "max_cny": "100"})
        execute.assert_not_called()

    def test_plan_rejects_credentials_before_persistence_or_dispatch(self):
        for supplied in ({"headers": {"Authorization": "fixture-value"}}, {"config": {"api_key": "fixture-value"}},
                         {"text": "password=fixture-only"}):
            with self.subTest(supplied=supplied):
                params = deepcopy(self.params)
                params["external_steps"][0]["params"].update(supplied)
                execute = Mock()
                with self.assertRaises(RoutingError):
                    self.admission.dispatch("agent.session.prompt", params, execute)
                execute.assert_not_called()
                self.assertEqual(self.work.list("sumika"), [])

    def test_concurrent_children_reserve_under_same_ceiling(self):
        self.start()
        barrier = threading.Barrier(3)
        release = threading.Event()
        def execute():
            barrier.wait(timeout=5)
            self.assertTrue(release.wait(5))
            return {"status": "completed"}
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(self.child, execute, 0)
            second = pool.submit(self.child, execute, 1)
            barrier.wait(timeout=5)
            self.assertEqual(self.parent()["authorization"]["reserved_cny"], "5")
            self.assertEqual(self.parent()["authorization"]["spent_cny"], "1")
            release.set()
            first.result()
            second.result()
        self.assertEqual(self.parent()["authorization"]["spent_cny"], "6")

    def test_shared_budget_exhaustion_blocks_before_execute(self):
        self.start()
        parent = self.parent()
        parent["authorization"]["spent_cny"] = "5"
        self.work._save(parent)
        execute = Mock()
        with self.assertRaises(RoutingError):
            self.child(execute)
        execute.assert_not_called()

    def test_unknown_child_holds_parent_budget_and_blocks_siblings(self):
        self.start()
        execute = Mock(return_value={"status": "unknown", "possibly_sent": True, "attempt_id": "turn"})
        child = self.child(execute)
        self.child(execute)
        self.assertEqual(execute.call_count, 1)
        self.assertEqual(self.parent()["status"], "submission-unknown")
        self.assertEqual(self.parent()["authorization"]["reserved_cny"], "2")
        with self.assertRaises(RoutingError):
            self.child(Mock(), 1)
        self.work.external_observe(child["work_request_id"], "sumika", {"status": "completed"})
        self.assertEqual(self.parent()["status"], "executing")
        self.assertEqual(self.parent()["authorization"]["reserved_cny"], "0")

    def test_unsent_child_releases_only_its_reservation(self):
        self.start()
        with self.assertRaises(RequestNotSent):
            self.child(Mock(side_effect=RequestNotSent("not sent")))
        self.assertEqual(self.parent()["authorization"]["reserved_cny"], "0")
        self.assertEqual(self.parent()["authorization"]["spent_cny"], "1")
        self.assertEqual(self.parent()["status"], "failed")

    def test_cancel_parent_blocks_new_children_and_keeps_pending_cost(self):
        self.start()
        child = self.child(Mock(return_value={"status": "running", "accepted": True, "turn_id": "turn"}))
        self.work.cancel({"request_id": "parent", "assistant_id": "sumika"})
        self.assertEqual(self.parent()["status"], "cancel-requested")
        self.assertEqual(self.parent()["authorization"]["reserved_cny"], "2")
        self.assertEqual(self.work.get(child["work_request_id"], "sumika")["status"], "cancel-requested")
        with self.assertRaises(RoutingError):
            self.child(Mock(), 1)
        self.work.external_observe(child["work_request_id"], "sumika", {"status": "completed"})
        self.assertEqual(self.parent()["status"], "cancelled")
        self.assertEqual(self.parent()["authorization"]["spent_cny"], "3")

    def test_restart_does_not_lose_or_double_book_reservations(self):
        self.start()
        params = self.child_params()
        self.child(Mock(return_value={"status": "running", "accepted": True, "turn_id": "turn"}))
        self.work.close()
        self.storage.close()
        reopened = Storage(self.path)
        self.addCleanup(reopened.close)
        restored = WorkService(reopened, self.quality, owner_ids=["sumika"])
        self.addCleanup(restored.close)
        admission = LegacyWorkAdmission(restored, profiles=lambda: [], routes=lambda: [], agent_offer=self.offer)
        execute = Mock()
        result = admission.dispatch("agent.session.prompt", params, execute)
        self.assertEqual(result["status"], "submission-unknown")
        self.assertEqual(restored.get("parent", "sumika")["authorization"]["reserved_cny"], "2")
        execute.assert_not_called()

    def test_group_write_failure_rolls_back_parent_and_prevents_execution(self):
        self.start()
        original = self.storage.save_record_group
        def fail_second(namespace, owner, updates):
            broken = deepcopy(updates)
            broken[1][0]["revision"] = 900
            return original(namespace, owner, broken)
        execute = Mock()
        with patch.object(self.storage, "save_record_group", side_effect=fail_second), self.assertRaises(ValueError):
            self.child(execute)
        self.assertEqual(self.parent()["authorization"]["reserved_cny"], "0")
        self.assertEqual(len(self.parent()["attempts"]), 1)
        child = next(row for row in self.work.list("sumika") if row.get("parent_authorization"))
        self.assertEqual(child["attempts"], {})
        execute.assert_not_called()


if __name__ == "__main__":
    unittest.main()
