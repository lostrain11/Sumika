"""Contract tests for the controlled, runtime-neutral desktop automation boundary."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from sumika_core.desktop_automation import (
    DesktopAdapter,
    DesktopApplication,
    DesktopAutomationError,
    DesktopLeaseError,
    ElectronCdpClient,
    TransportDesktopAdapter,
    WindowsUiAutomationClient,
    DesktopAutomationRuntime,
)
from sumika_core.protocol.models import utc_now
from sumika_core.server import CoreApplication
from sumika_core.storage import Storage


class RecordingAdapter(DesktopAdapter):
    """A deterministic adapter that never touches a real window."""

    adapter_id = "recording"
    transport = "app-protocol"
    capabilities = frozenset({"observe", "read", "control", "send"})

    def __init__(self, responses=None):
        self.responses = list(responses or [])
        self.opened = []
        self.actions = []
        self.closed = []

    def health(self, application: DesktopApplication):
        return {"ok": True, "state": "ready", "app_id": application.app_id}

    def open(self, application: DesktopApplication, profile_id: str, options):
        del options
        native = f"native-{len(self.opened) + 1}"
        self.opened.append((application.app_id, profile_id, native))
        return {"native_session_id": native, "transport": self.transport, "state": "ready"}

    def observe(self, session, options):
        return {"native": session.native_session_id, "options": dict(options), "state": "ready"}

    def act(self, session, request):
        self.actions.append(request)
        if self.responses:
            value = self.responses.pop(0)
            return dict(value) if isinstance(value, dict) else value
        return {"completed": True, "action": request.action}

    def close(self, session):
        self.closed.append(session.native_session_id)
        return {"closed": True}


class DesktopAutomationRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.storage = Storage(":memory:")
        self.adapter = RecordingAdapter()
        self.runtime = DesktopAutomationRuntime(
            storage=self.storage,
            adapters={"recording": self.adapter},
            register_zcode=False,
        )
        self.runtime.register_application(
            {
                "app_id": "sample-app",
                "name": "Sample App",
                "adapter_id": "recording",
                "profile_id": "profile-a",
                "config": {"executable": r"C:\\Apps\\sample.exe", "fixed": ["--safe"]},
            },
            approved=True,
            confirm_app_id="sample-app",
        )

    def tearDown(self):
        self.runtime.close()
        self.storage.close()

    def open(self, *, profile_id="profile-a"):
        return self.runtime.open_session("sample-app", profile_id=profile_id, owner="agent")

    def test_application_projection_persists_profile_without_config_or_secrets(self):
        row = self.storage.get_desktop_application("sample-app")
        self.assertEqual(row["profile_id"], "profile-a")
        self.assertNotIn("executable", row.get("metadata", {}))

        self.runtime.close()
        restored = DesktopAutomationRuntime(
            storage=self.storage,
            adapters={"recording": RecordingAdapter()},
            register_zcode=False,
        )
        self.addCleanup(restored.close)
        app = next(item for item in restored.catalog()["apps"] if item["app_id"] == "sample-app")
        self.assertTrue(app["profile_configured"])
        self.assertTrue(app["approved"])
        self.assertNotIn("config", app)

    def test_lease_is_exclusive_and_released_on_close(self):
        first = self.open()
        with self.assertRaises(DesktopLeaseError):
            self.open()
        closed = self.runtime.close_session(first["session"]["session_id"])
        self.assertTrue(closed["closed"])
        second = self.open()
        self.assertEqual(second["session"]["profile_id"], "profile-a")

    def test_expired_persisted_lease_can_be_reclaimed(self):
        past = (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat().replace("+00:00", "Z")
        self.storage.acquire_desktop_automation_lease(
            profile_key="profile-expired",
            session_id="old-session",
            app_id="sample-app",
            owner="agent",
            lease_id="old-lease",
            expires_at=past,
        )
        reclaimed = self.storage.acquire_desktop_automation_lease(
            profile_key="profile-expired",
            session_id="new-session",
            app_id="sample-app",
            owner="manual",
            lease_id="new-lease",
            expires_at=utc_now(),
        )
        self.assertEqual(reclaimed["lease_id"], "new-lease")

    def test_control_approval_is_bound_to_the_original_action_input(self):
        opened = self.open()
        session_id = opened["session"]["session_id"]
        pending = self.runtime.act({"session_id": session_id, "action": "click", "target": "send"})
        self.assertEqual(pending["status"], "waiting-approval")
        approval_id = pending["approval_id"]
        self.runtime.approval({"operation": "approve", "approval_id": approval_id, "approved": True})

        mismatched = self.runtime.act(
            {
                "session_id": session_id,
                "action": "click",
                "target": "different-target",
                "approval_id": approval_id,
            }
        )
        self.assertEqual(mismatched["status"], "waiting-approval")
        self.assertEqual(len(self.adapter.actions), 0)

        completed = self.runtime.act(
            {
                "session_id": session_id,
                "action": "click",
                "target": "send",
                "approval_id": approval_id,
            }
        )
        self.assertEqual(completed["status"], "completed")
        self.assertEqual(len(self.adapter.actions), 1)

    def test_nested_credentials_are_denied_before_adapter_and_sensitive_actions_need_approval(self):
        opened = self.open()
        session_id = opened["session"]["session_id"]
        denied = self.runtime.act(
            {
                "session_id": session_id,
                "action": "click",
                "args": {"nested": {"authorization": "Bearer hidden-value"}},
                "approved": True,
            }
        )
        self.assertEqual(denied["status"], "denied")
        self.assertEqual(denied["error_code"], "credential-input-requires-human")
        self.assertEqual(len(self.adapter.actions), 0)

        sensitive = self.runtime.act(
            {"session_id": session_id, "action": "delete", "target": "record", "approved": False}
        )
        self.assertEqual(sensitive["status"], "waiting-approval")
        self.assertEqual(sensitive["risk"], "sensitive")

    def test_idempotency_replays_completed_results_but_unknown_send_is_not_retried(self):
        opened = self.open()
        session_id = opened["session"]["session_id"]
        self.runtime.approval(
            {
                "operation": "grant",
                "app_id": "sample-app",
                "scope": "control",
                "approved": True,
                "confirm_app_id": "sample-app",
            }
        )
        first = self.runtime.act(
            {"session_id": session_id, "action": "click", "target": "ok", "idempotency_key": "click-1"}
        )
        replay = self.runtime.act(
            {"session_id": session_id, "action": "click", "target": "ok", "idempotency_key": "click-1"}
        )
        self.assertEqual(first["status"], "completed")
        self.assertTrue(replay["idempotent_replay"])
        self.assertEqual(len(self.adapter.actions), 1)

        self.adapter.responses.append({"possibly_sent": True})
        unknown = self.runtime.act(
            {"session_id": session_id, "action": "send", "value": "hello", "idempotency_key": "send-1"}
        )
        self.assertEqual(unknown["status"], "unknown")
        self.assertEqual(unknown["error_code"], "possibly-sent")
        self.assertFalse(unknown["retryable"])

    def test_closed_runtime_rejects_new_sessions(self):
        self.runtime.close()
        with self.assertRaisesRegex(DesktopAutomationError, "closed"):
            self.runtime.open_session("sample-app")

    def test_nested_registration_credentials_are_rejected(self):
        with self.assertRaisesRegex(DesktopAutomationError, "credentials"):
            self.runtime.register_application(
                {
                    "app_id": "unsafe-app",
                    "name": "Unsafe",
                    "adapter_id": "recording",
                    "config": {"nested": {"token": "secret"}},
                },
                approved=True,
            )


class TransportDesktopAdapterTests(unittest.TestCase):
    def test_cdp_client_can_be_registered_through_generic_adapter(self):
        calls = []

        def runner(operation, payload):
            calls.append((operation, dict(payload)))
            if operation == "health":
                return {"ok": True, "state": "ready"}
            if operation == "open":
                return {"window_id": "window-1"}
            if operation == "observe":
                return {"title": "ZCode"}
            if operation == "act":
                return {"completed": True}
            if operation == "close":
                return {"closed": True}
            raise AssertionError(operation)

        client = ElectronCdpClient(runner=runner)
        adapter = TransportDesktopAdapter("zcode-cdp", client, transport="electron-cdp")
        storage = Storage(":memory:")
        runtime = DesktopAutomationRuntime(storage=storage, adapters={"zcode-cdp": adapter}, register_zcode=False)
        try:
            runtime.register_application(
                {"app_id": "zcode-window", "name": "ZCode window", "adapter_id": "zcode-cdp"},
                approved=True,
            )
            opened = runtime.open_session("zcode-window", options={"tab": "main"})
            session_id = opened["session"]["session_id"]
            self.assertEqual(runtime.observe(session_id)["status"], "completed")
            self.assertEqual(
                runtime.act({"session_id": session_id, "action": "click", "target": "send", "approved": True})[
                    "status"
                ],
                "completed",
            )
            self.assertTrue(runtime.close_session(session_id)["closed"])
            self.assertEqual([item[0] for item in calls], ["open", "observe", "act", "close"])
        finally:
            runtime.close()
            storage.close()

    def test_uia_client_wrapper_rejects_takeover_without_explicit_enablement(self):
        client = WindowsUiAutomationClient(runner=lambda operation, payload: {"ok": True, "operation": operation})
        adapter = TransportDesktopAdapter("uia", client, transport="windows-uia")
        with self.assertRaisesRegex(DesktopAutomationError, "disabled"):
            adapter.takeover(
                type("Session", (), {"native_session_id": "window-1"})(),
                enabled=True,
            )


class DesktopAutomationRpcTests(unittest.TestCase):
    def test_core_rpc_exposes_full_registration_session_and_capability_projection(self):
        application = CoreApplication(":memory:")
        adapter = RecordingAdapter()
        application.desktop_automation.register_adapter("recording", adapter)
        try:
            registered = application.rpc(
                "desktop.automation.register",
                {
                    "application": {
                        "app_id": "rpc-app",
                        "name": "RPC App",
                        "adapter_id": "recording",
                    },
                    "approved": True,
                    "confirm_app_id": "rpc-app",
                },
            )
            self.assertEqual(registered["app_id"], "rpc-app")
            opened = application.rpc(
                "desktop.automation.open",
                {"app_id": "rpc-app", "approved": True, "owner": "agent"},
            )
            session_id = opened["session"]["session_id"]
            self.assertEqual(
                application.rpc("desktop.automation.observe", {"session_id": session_id})["status"],
                "completed",
            )
            catalog = application.rpc("capability.catalog", {"includeRuntime": False})
            entries = [entry for group in catalog["groups"] for entry in group["entries"]]
            self.assertIn("desktop:rpc-app", {entry["id"] for entry in entries})
            closed = application.rpc(
                "desktop.automation.close",
                {"session_id": session_id, "approved": True},
            )
            self.assertTrue(closed["closed"])
        finally:
            application.close()


if __name__ == "__main__":
    unittest.main()
