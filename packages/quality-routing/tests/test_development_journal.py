import unittest
from unittest.mock import Mock

from quality_routing import RoutingError
from quality_routing.development import DevelopmentNotSent, DevelopmentReply, run_development
from quality_routing.development_journal import SCHEMA, append_event, evidence_digest, recovery_state


class DevelopmentJournalTests(unittest.TestCase):
    def setUp(self):
        self.records = []

    def journal(self, event):
        self.records = append_event(self.records, event)

    def run_loop(self, invoke, execute=None, **kwargs):
        return run_development("fixture", invoke=invoke, execute=execute or Mock(return_value={}),
                               cancelled=lambda: False, context="", journal=self.journal, **kwargs)

    def test_missing_test_is_not_passed_when_digest_provider_returns_none(self):
        with self.assertRaises(RoutingError):
            self.run_loop(lambda messages, tools: DevelopmentReply("done"), required_tests=1,
                          workspace_digest=lambda: None)

    def test_failed_intent_persistence_prevents_model_call(self):
        invoke = Mock()
        with self.assertRaises(OSError):
            run_development("fixture", invoke=invoke, execute=Mock(), cancelled=lambda: False, context="",
                            journal=Mock(side_effect=OSError("disk full")))
        invoke.assert_not_called()

    def test_model_unknown_is_left_pending(self):
        with self.assertRaises(TimeoutError):
            self.run_loop(Mock(side_effect=TimeoutError("response missing")))
        self.assertEqual(recovery_state(self.records)["state"], "submission-unknown")
        self.assertEqual(recovery_state(self.records)["pending_operations"][0]["operation_id"], "model-1")

    def test_invalid_reply_fields_never_dispatch_tools(self):
        for reply in (DevelopmentReply(None), DevelopmentReply("", None),
                      DevelopmentReply("", [{"name": ["write_file"], "arguments": "{}"}]),
                      DevelopmentReply("", [{"name": "write_file", "arguments": "{}", "id": []}]),
                      DevelopmentReply("", [{"name": "write_file", "arguments": "{}", "id": " "}]),
                      DevelopmentReply("", reasoning_content={})):
            with self.subTest(reply=reply):
                self.records = []
                execute = Mock()
                with self.assertRaises(RoutingError):
                    self.run_loop(Mock(return_value=reply), execute)
                execute.assert_not_called()
                self.assertEqual(recovery_state(self.records)["pending_operations"], [])

    def test_host_proven_not_sent_does_not_become_unknown(self):
        with self.assertRaises(DevelopmentNotSent):
            self.run_loop(Mock(side_effect=DevelopmentNotSent("not sent")))
        self.assertEqual(self.records[-1]["outcome"], "rejected")
        self.assertEqual(recovery_state(self.records)["pending_operations"], [])

    def test_restart_cannot_replay_the_same_operation(self):
        with self.assertRaises(TimeoutError):
            self.run_loop(Mock(side_effect=TimeoutError()))
        invoke = Mock()
        with self.assertRaises(RoutingError):
            self.run_loop(invoke)
        invoke.assert_not_called()

    def test_intents_precede_side_effects_and_receipts_precede_events(self):
        replies = iter([DevelopmentReply("", [{"name": "write_file", "arguments": '{}'}]), DevelopmentReply("done")])
        def execute(name, arguments):
            self.assertEqual(self.records[-1]["operation_id"], "tool-1-0")
            self.assertEqual(self.records[-1]["phase"], "started")
            return {"sha256": "a" * 64}
        def event(item):
            self.assertEqual(self.records[-1]["phase"], "finished")
        self.run_loop(lambda messages, tools: next(replies), execute, event=event)
        self.assertEqual(recovery_state(self.records)["state"], "interrupted")
        self.assertFalse(recovery_state(self.records)["automatic_replay"])

    def test_tool_exception_after_side_effect_stops_dispatch(self):
        invoke = Mock(return_value=DevelopmentReply("", [{"name": "write_file", "arguments": '{}'},
                                                        {"name": "run_test", "arguments": '{"index":0}'}]))
        execute = Mock(side_effect=OSError("write result unknown"))
        result = self.run_loop(invoke, execute)
        self.assertEqual(result["status"], "submission-unknown")
        execute.assert_called_once()
        invoke.assert_called_once()
        self.assertEqual(recovery_state(self.records)["pending_operations"][0]["operation_id"], "tool-1-0")

    def test_malformed_json_is_a_rejected_request_without_tool_execution(self):
        replies = iter([DevelopmentReply("", [{"name": "write_file", "arguments": '{'}]), DevelopmentReply("done")])
        execute = Mock()
        self.run_loop(lambda messages, tools: next(replies), execute)
        execute.assert_not_called()
        self.assertEqual(self.records[3]["outcome"], "rejected")
        self.assertEqual(recovery_state(self.records)["pending_operations"], [])

    def test_journal_rejects_content_invalid_order_and_duplicate_receipts(self):
        intent = {"schema_version": SCHEMA, "kind": "model", "operation_id": "model-1", "turn": 1,
                  "phase": "started", "input_digest": evidence_digest("input")}
        receipt = {key: value for key, value in intent.items() if key != "input_digest"}
        receipt.update(phase="finished", outcome="returned", output_digest=evidence_digest("output"))
        for invalid in ({**intent, "content": "secret"}, receipt):
            with self.assertRaises(RoutingError):
                append_event([], invalid)
        records = append_event(append_event([], intent), receipt)
        with self.assertRaises(RoutingError):
            append_event(records, receipt)

    def test_failed_receipt_storage_prevents_following_tool(self):
        execute = Mock(return_value={})
        def broken_journal(event):
            if event["kind"] == "tool" and event["phase"] == "finished":
                raise OSError("disk full")
            self.journal(event)
        reply = DevelopmentReply("", [{"name": "write_file", "arguments": '{}'},
                                       {"name": "run_test", "arguments": '{"index":0}'}])
        with self.assertRaises(OSError):
            run_development("fixture", invoke=Mock(return_value=reply), execute=execute,
                            cancelled=lambda: False, context="", journal=broken_journal)
        execute.assert_called_once()
        self.assertEqual(recovery_state(self.records)["state"], "submission-unknown")


if __name__ == "__main__":
    unittest.main()
