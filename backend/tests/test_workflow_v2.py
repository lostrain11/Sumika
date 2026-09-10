import hashlib
import tempfile
import threading
import sqlite3
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

from quality_routing import Candidate, Outcome, QualityEvidence, Quote, RoutingError, Scope
from quality_routing.workflow import WorkRequest, admission_state, authorize, check_authorization, classify_request, work_artifact
from sumika_core.quality.work import WorkService
from sumika_core.storage import Storage


class WorkflowContractsTests(unittest.TestCase):
    def test_admission_does_not_confuse_zero_cash_with_free(self):
        zero = Quote(0, 0, 0, 4, 4000)
        self.assertEqual(admission_state("simple", zero, funding="free", executable=True), "ready")
        for complexity, funding in (("complex", "free"), ("simple", "purchased"), ("simple", "unknown")):
            self.assertEqual(admission_state(complexity, zero, funding=funding, executable=True), "awaiting-confirmation")
        self.assertEqual(classify_request("翻译为英文：你好")["complexity"], "simple")
        self.assertEqual(classify_request("删除项目文件")["complexity"], "complex")

    def test_authorization_is_versioned_and_budget_limited(self):
        request = WorkRequest("request", "one", "session", "goal")
        authorization = authorize(request, Quote(1, 2, 3, 4, 5000), candidate_ids=("candidate",), max_cny=3)
        check_authorization(request, authorization, "candidate", 3)
        for candidate, cost in (("different", 0), ("candidate", 4)):
            with self.assertRaises(RoutingError):
                check_authorization(request, authorization, candidate, cost)
        with self.assertRaises(RoutingError):
            check_authorization(WorkRequest("request", "one", "session", "changed", 2), authorization, "candidate", 0)

    def test_artifact_is_verbatim(self):
        text = '{\n  "answer": 42\n}\n'
        artifact = work_artifact("task", "one", text, format="json")
        self.assertEqual(artifact["content"], text)
        self.assertEqual(artifact["sha256"], hashlib.sha256(text.encode()).hexdigest())


class WorkflowStoreTests(unittest.TestCase):
    def test_version_18_upgrade_preserves_messages_and_creates_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.sqlite"
            storage = Storage(path)
            storage.create_character("one", "One", {})
            storage.create_session("session", character_id="one")
            storage.close()
            connection = sqlite3.connect(path)
            connection.execute("UPDATE schema_meta SET value='18' WHERE key='version'")
            connection.execute("DROP TABLE workflow_records")
            connection.commit()
            connection.close()
            migrated = Storage(path)
            self.assertEqual(migrated.list_sessions()[0]["id"], "session")
            self.assertTrue(Path(str(path) + ".before-v19.sqlite").exists())
            migrated.close()

    def test_scope_and_reopen(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.sqlite"
            storage = Storage(path)
            storage.save_record("projects/v1", "project", "one", {"id": "project", "assistant_id": "one"})
            self.assertIsNone(storage.get_record("projects/v1", "project", "two"))
            self.assertFalse(storage.delete_record("projects/v1", "project", "two"))
            with self.assertRaises(ValueError):
                storage.save_record("projects/v1", "project", "two", {})
            storage.close()
            reopened = Storage(path)
            self.assertEqual(len(reopened.list_records("projects/v1", "one")), 1)
            reopened.close()


class WorkAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.storage = Storage()
        self.candidate = Candidate("candidate", "account", "model", "api", authorized=True, available=True,
                                   fixed_cash=0, quality=(QualityEvidence("bounded-text", "bounded-text-v1", time.time() + 1000, "fixture"),))
        self.quality = SimpleNamespace(
            _scope=lambda params: Scope(params.get("assistant_id", "one"), params.get("session_id", "session")),
            settings=lambda owner: {"candidate_pool": ["candidate"]},
            select_bindings=lambda owner: {"leader_candidate_id": "candidate", "role_candidate_id": "candidate"},
            engine=SimpleNamespace(candidates=lambda: (self.candidate,)),
        )
        self.work = WorkService(self.storage, self.quality)

    def tearDown(self):
        self.work.close()
        self.storage.close()

    def test_complex_free_waits_without_invoking_planner(self):
        value = self.work.preflight({"request_id": "request", "goal": "设计系统"})
        self.assertEqual(value["status"], "awaiting-confirmation")
        self.assertEqual(self.work.submit({"request_id": "request", "assistant_id": "one"})["status"], "awaiting-confirmation")
        self.assertEqual(value["quote"]["high_cny"], "0")

    def test_free_simple_ready_paid_simple_waits_and_unknown_retains_reservation(self):
        value = self.work.preflight({"request_id": "free", "goal": "翻译：你好"})
        self.assertEqual(value["status"], "ready")
        self.candidate = Candidate("candidate", "account", "model", "api", authorized=True, available=True,
                                   fixed_cash="1", quality=self.candidate.quality)
        value = self.work.preflight({"request_id": "paid", "goal": "翻译：你好"})
        self.assertEqual(value["status"], "awaiting-confirmation")
        scope = Scope("one", "session")
        with self.assertRaises(RoutingError):
            self.work.reserve("paid", scope, self.candidate, 100, 100)
        self.work.confirm({"request_id": "paid", "assistant_id": "one", "revision": 1, "max_cny": "4"})
        attempt = self.work.reserve("paid", scope, self.candidate, 100, 100)
        self.work.settle("paid", scope, attempt, Outcome("unknown", possibly_sent=True), self.candidate)
        with self.assertRaises(RoutingError):
            self.work.reserve("paid", scope, self.candidate, 100, 100)
        self.assertEqual(self.work.get("paid", "one")["authorization"]["reserved_cny"], "1")
        self.assertEqual(self.work.get("paid", "one")["status"], "submission-unknown")
        with self.assertRaises(RoutingError):
            self.work.reserve("free", scope, self.candidate, 100, 100)

    def test_duplicate_preflight_and_changed_goal(self):
        params = {"request_id": "request", "goal": "设计系统"}
        self.assertEqual(self.work.preflight(params), self.work.preflight(params))
        with self.assertRaises(RoutingError):
            self.work.preflight({**params, "goal": "不同目标"})
