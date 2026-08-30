"""Fixed-fixture tests for runtime-neutral web route consultation."""

from __future__ import annotations

import json
import threading
import time
import unittest

from sumika_core.agent.routes import (
    AGENT_CONSULTATION_SCHEMA,
    AGENT_ROUTE_SCHEMA,
    ConsultationRequest,
    RouteCoordinator,
    RouteValidationError,
    sanitize_context,
)
from sumika_core.storage import Storage


class WebChatFixture:
    def __init__(self, profiles, responses=None):
        self.profiles = [dict(item) for item in profiles]
        self.responses = {key: list(value) for key, value in (responses or {}).items()}
        self.calls = []
        self.blockers = {}
        self.started = {}

    def list_profiles(self, *, include_archived=False):
        return [dict(item) for item in self.profiles if include_archived or not item.get("archived_at")]

    def list_adapters(self):
        return [
            {"id": "deepseek-web", "name": "DeepSeek", "domains": ["chat.deepseek.com"]},
            {"id": "chatgpt-web", "name": "ChatGPT", "domains": ["chatgpt.com"]},
            {"id": "zhipu-web", "name": "智谱", "domains": ["chat.z.ai"]},
        ]

    def send_message(self, profile_id, text):
        self.calls.append({"profile_id": profile_id, "text": text})
        self.started.setdefault(profile_id, threading.Event()).set()
        blocker = self.blockers.get(profile_id)
        if blocker is not None:
            blocker.wait(timeout=2)
        values = self.responses.get(profile_id) or [{"ok": False, "reason": "fixture failure"}]
        return dict(values.pop(0))


def profile(profile_id, adapter_id, *, ready=True):
    return {
        "id": profile_id,
        "name": profile_id,
        "adapter_id": adapter_id,
        "site_key": adapter_id,
        "status": "ready" if ready else "needs-auth",
        "auth_state": "authorized" if ready else "needs-auth",
        "auto_chat_enabled": bool(ready),
        "allowed_actions": ["chat.read", "chat.send"],
        "config": {"domains": [f"{adapter_id}.example.test"]},
        "archived_at": None,
    }


class AgentRouteContractTests(unittest.TestCase):
    def setUp(self):
        self.storage = Storage(":memory:")
        self.coordinators = []

    def tearDown(self):
        for coordinator in self.coordinators:
            coordinator.close()
        self.storage.close()

    def coordinator(self, fixture):
        value = RouteCoordinator(fixture, self.storage)
        self.coordinators.append(value)
        return value

    def test_catalog_includes_templates_but_routes_only_consent_ready_profiles(self):
        fixture = WebChatFixture(
            [
                profile("web-chat-ready0001", "deepseek-web"),
                profile("web-chat-login0001", "chatgpt-web", ready=False),
            ]
        )
        catalog = self.coordinator(fixture).catalog()
        self.assertEqual(catalog["schema"], AGENT_ROUTE_SCHEMA)
        ready = next(item for item in catalog["routes"] if item["provider_profile_id"] == "web-chat-ready0001")
        login = next(item for item in catalog["routes"] if item["provider_profile_id"] == "web-chat-login0001")
        self.assertTrue(ready["routable"])
        self.assertFalse(login["routable"])
        self.assertEqual(ready["quota_state"], "unknown")
        self.assertNotIn("免费", json.dumps(catalog, ensure_ascii=False))

    def test_context_is_redacted_and_sensitive_files_are_blocked(self):
        safe = sanitize_context(
            {
                "goal": "Review C:\\Users\\Example\\repo and token=secret-value-123456",
                "authorization": "Bearer should-never-leave",
            }
        )
        serialized = json.dumps(safe, ensure_ascii=False)
        self.assertNotIn("secret-value", serialized)
        self.assertNotIn("should-never-leave", serialized)
        self.assertNotIn("C:\\Users", serialized)
        with self.assertRaisesRegex(RouteValidationError, "sensitive-context"):
            sanitize_context({"path": "C:\\repo\\.env"})
        with self.assertRaisesRegex(RouteValidationError, "context-too-large"):
            sanitize_context({"diff": "x" * 30_000})

    def test_consultation_uses_distinct_providers_and_does_not_leak_answers_between_members(self):
        fixture = WebChatFixture(
            [
                profile("web-chat-deepseek1", "deepseek-web"),
                # Same provider is intentionally skipped for a panel.
                profile("web-chat-deepseek2", "deepseek-web"),
                profile("web-chat-chatgpt01", "chatgpt-web"),
                profile("web-chat-zhipu0001", "zhipu-web"),
            ],
            {
                "web-chat-deepseek1": [{"ok": True, "text": "独立答案 A"}],
                "web-chat-chatgpt01": [{"ok": True, "text": "独立答案 B"}],
                "web-chat-zhipu0001": [{"ok": True, "text": "独立答案 C"}],
            },
        )
        coordinator = self.coordinator(fixture)
        result = coordinator.start_consultation(
            {
                "parent_session_id": "session-parent",
                "parent_turn_id": "turn-2",
                "question": "给出独立建议",
                "decision_kind": "plan-review",
                "context_refs": {"diff": "+ safe change"},
                "max_members": 3,
            },
            wait=True,
        )
        self.assertEqual(result["schema"], AGENT_CONSULTATION_SCHEMA)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["successful_count"], 3)
        self.assertEqual(
            {item["profile_id"] for item in fixture.calls},
            {"web-chat-deepseek1", "web-chat-chatgpt01", "web-chat-zhipu0001"},
        )
        # Every call received the original sanitized input only; no later
        # member sees an earlier member's answer.
        for call in fixture.calls:
            self.assertIn("给出独立建议", call["text"])
            self.assertNotIn("独立答案 A", call["text"])
            self.assertNotIn("独立答案 B", call["text"])
            self.assertNotIn("独立答案 C", call["text"])

    def test_partial_and_total_failure_are_explicit_without_fake_text(self):
        fixture = WebChatFixture(
            [
                profile("web-chat-success01", "deepseek-web"),
                profile("web-chat-failure01", "chatgpt-web"),
            ],
            {
                "web-chat-success01": [{"ok": True, "text": "唯一真实回复"}],
                "web-chat-failure01": [{"ok": False, "reason": "site unavailable"}],
            },
        )
        coordinator = self.coordinator(fixture)
        result = coordinator.start_consultation(
            {
                "parent_session_id": "session-partial",
                "question": "检查失败边界",
                "decision_kind": "fact-check",
                "max_members": 2,
            },
            wait=True,
        )
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["successful_count"], 1)
        self.assertEqual(result["failed_count"], 1)
        failed = next(item for item in result["members"] if item["status"] == "failed")
        self.assertIsNone(failed["answer"])
        self.assertTrue(failed["untrusted_external"])

        total = self.coordinator(
            WebChatFixture(
                [profile("web-chat-totalfail1", "deepseek-web")],
                {"web-chat-totalfail1": [{"ok": False, "reason": "offline"}]},
            )
        ).start_consultation(
            {
                "parent_session_id": "session-total",
                "question": "不要伪造",
                "decision_kind": "small-answer",
                "max_members": 1,
            },
            wait=True,
        )
        self.assertEqual(total["status"], "failed")
        self.assertIsNone(total["members"][0]["answer"])

    def test_manual_occupancy_blocks_agent_and_takeover_cancels_running_work(self):
        fixture = WebChatFixture(
            [profile("web-chat-occupied1", "deepseek-web")],
            {"web-chat-occupied1": [{"ok": True, "text": "late answer"}]},
        )
        coordinator = self.coordinator(fixture)
        coordinator.set_occupancy("web-chat-occupied1", "manual")
        catalog = coordinator.catalog(include_templates=False)
        self.assertFalse(catalog["routes"][0]["routable"])
        coordinator.set_occupancy("web-chat-occupied1", "idle")
        blocker = threading.Event()
        fixture.blockers["web-chat-occupied1"] = blocker
        fixture.started["web-chat-occupied1"] = threading.Event()
        dispatched = coordinator.dispatch(
            {
                "parent_session_id": "session-takeover",
                "route_id": "web-chat:web-chat-occupied1",
                "question": "will be cancelled",
            }
        )
        dispatch_id = dispatched["dispatch"]["dispatch_id"]
        fixture.started["web-chat-occupied1"].wait(timeout=1)
        takeover = coordinator.request_takeover("web-chat-occupied1")
        blocker.set()
        final = coordinator.wait(dispatch_id, timeout=2)
        self.assertTrue(takeover["requested"])
        self.assertIn(dispatch_id, takeover["cancelled_dispatches"])
        self.assertEqual(final["status"], "cancelled")

    def test_storage_projection_contains_metadata_but_not_prompt_or_answer(self):
        fixture = WebChatFixture(
            [profile("web-chat-storage01", "deepseek-web")],
            {"web-chat-storage01": [{"ok": True, "text": "reply-body-must-not-persist"}]},
        )
        coordinator = self.coordinator(fixture)
        result = coordinator.start_consultation(
            ConsultationRequest(
                consultation_id="consultation-storage",
                parent_session_id="session-storage",
                question="prompt-body-must-not-persist",
                decision_kind="brainstorm",
                max_members=1,
            ),
            wait=True,
        )
        self.assertEqual(result["status"], "completed")
        rows = self.storage.list_agent_route_runs(consultation_id="consultation-storage")
        consultation = self.storage.get_agent_consultation("consultation-storage")
        serialized = json.dumps({"runs": rows, "consultation": consultation}, ensure_ascii=False)
        self.assertNotIn("prompt-body-must-not-persist", serialized)
        self.assertNotIn("reply-body-must-not-persist", serialized)
        self.assertEqual(rows[0]["result_length"], len("reply-body-must-not-persist"))
        self.assertTrue(rows[0]["summary_hash"])


if __name__ == "__main__":
    unittest.main()
