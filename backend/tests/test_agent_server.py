import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from sumika_core.agent import AgentCapability, AgentRuntimeError
from sumika_core.agent.supervisor import ProviderWorker, RuntimeRouteDescriptor
from sumika_core.protocol.jsonrpc import JsonRpcError
from sumika_core.server import CoreApplication
from sumika_core.workspace import WorkspaceError


class AgentServerTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict("os.environ", {"SUMIKA_DSH_ENABLED": "0"})
        self.environment.start()
        self.application = CoreApplication(":memory:")

    def tearDown(self):
        self.application.close()
        self.environment.stop()

    def test_status_endpoints_are_explicit_when_dsh_is_not_running(self):
        agent = self.application.rpc("agent.status", {})
        self.assertIn(agent["state"], {"unavailable", "disabled"})
        browser = self.application.rpc("browser.status", {})
        self.assertFalse(browser["ready"])

    def test_agent_diagnostics_returns_a_safe_runtime_report(self):
        with patch.object(
            self.application.agent,
            "diagnostics",
            return_value={
                "checked_at": "2026-08-26T00:00:00Z",
                "runtime": {"state": "ready", "ready": True},
                "capabilities": [{"id": "host", "status": "available"}],
                "mcp": {"available": False, "status": "not-exposed"},
                "summary": {"available": 1, "not-exposed": 1},
            },
        ):
            result = self.application.rpc("agent.diagnostics", {})
        self.assertTrue(result["runtime"]["ready"])
        self.assertEqual(result["mcp"]["status"], "not-exposed")
        self.assertNotIn("secret", str(result))

    def test_agent_mcp_inventory_uses_observed_session_tools_without_raw_payloads(self):
        inventory = {
            "available": True,
            "status": "observed",
            "catalog_available": False,
            "observation_source": "session-history",
            "client_installed": True,
            "client_version": "0.1.1-rc.2",
            "entries": [{"name": "github", "tools": [{"name": "mcp__github__search"}]}],
            "server_count": 1,
            "tool_count": 1,
        }
        with patch.object(self.application.agent, "mcp_inventory", return_value=inventory) as observe:
            result = self.application.rpc("agent.mcp.inventory", {"sessionId": "s1"})
        observe.assert_called_once_with({"sessionId": "s1"})
        self.assertEqual(result["entries"][0]["name"], "github")
        self.assertFalse(result["catalog_available"])
        self.assertNotIn("arguments", str(result))
        self.assertNotIn("result", str(result))

    def test_skill_catalog_rpc_is_metadata_only_and_requires_exact_approval(self):
        with TemporaryDirectory() as directory:
            skill_dir = Path(directory) / "private-skill"
            skill_dir.mkdir()
            skill_path = skill_dir / "SKILL.md"
            skill_path.write_text(
                "---\nname: Private Skill\npermissions: read\n---\n"
                "private instruction body\n",
                encoding="utf-8",
            )
            discovered = self.application.rpc("agent.skills.discover", {"paths": [str(skill_dir)]})
            candidate = discovered["skills"][0]
            self.assertEqual(candidate["state"], "discovered")
            self.assertNotIn(str(directory), str(candidate))
            self.assertNotIn("private instruction body", str(candidate))

            with self.assertRaises(JsonRpcError) as error:
                self.application.rpc(
                    "agent.skills.approve",
                    {"candidate_id": candidate["candidate_id"], "approved": True},
                )
            self.assertEqual(error.exception.code, -32031)

            approved = self.application.rpc(
                "agent.skills.approve",
                {
                    "candidate_id": candidate["candidate_id"],
                    "approved": True,
                    "confirm_skill_id": candidate["candidate_id"],
                },
            )
            self.assertEqual(approved["state"], "approved")
            revoked = self.application.rpc(
                "agent.skills.revoke",
                {
                    "candidate_id": candidate["candidate_id"],
                    "approved": True,
                    "confirm_skill_id": candidate["candidate_id"],
                },
            )
            self.assertEqual(revoked["state"], "revoked")
            self.assertTrue(skill_path.exists())
            audit = str(self.application.storage.list_events(20))
            self.assertNotIn(str(directory), audit)
            self.assertNotIn("private instruction body", audit)

    def test_agent_mcp_configuration_requires_preview_and_explicit_apply_approval(self):
        configurations = {
            "agent_preset": "sumika-work",
            "configurations": [
                {
                    "server_name": "filesystem",
                    "transport": "stdio",
                    "enabled": False,
                    "command": "npx",
                    "args": ["-y", "server-filesystem"],
                    "tool_call_timeout_ms": 60000,
                }
            ],
            "credential_fields_supported": False,
        }
        with patch.object(
            self.application.agent,
            "list_mcp_configurations",
            return_value=configurations,
        ) as list_configurations:
            listed = self.application.rpc(
                "agent.mcp.configurations",
                {"agentPreset": "sumika-work"},
            )
        list_configurations.assert_called_once_with({"agentPreset": "sumika-work"})
        self.assertEqual(listed["configurations"][0]["server_name"], "filesystem")

        preview_result = {
            "agent_preset": "sumika-work",
            "server_name": "filesystem",
            "action": "upsert",
            "change": "create",
            "preview_token": "private-preview-token",
            "requires_approval": True,
            "configuration": configurations["configurations"][0],
        }
        request = {
            "agentPreset": "sumika-work",
            "action": "upsert",
            "configuration": configurations["configurations"][0],
        }
        with patch.object(
            self.application.agent,
            "preview_mcp_configuration",
            return_value=preview_result,
        ) as preview:
            result = self.application.rpc("agent.mcp.configuration.preview", request)
        preview.assert_called_once_with(request)
        self.assertEqual(result["preview_token"], "private-preview-token")

        for params in (
            {"agentPreset": "sumika-work", "previewToken": "private-preview-token"},
            {
                "agentPreset": "sumika-work",
                "previewToken": "private-preview-token",
                "approved": True,
                "confirm_agent_preset": "other",
            },
        ):
            with self.subTest(params=params), self.assertRaises(JsonRpcError):
                self.application.rpc("agent.mcp.configuration.apply", params)

        apply_result = {
            "agent_preset": "sumika-work",
            "server_name": "filesystem",
            "change": "create",
            "applied": True,
            "mountable": True,
            "validation_session_archived": True,
            "backup_retained": True,
            "credential_changed": True,
            "credential_removed": False,
            "restart_required": True,
        }
        with patch.object(
            self.application.agent,
            "apply_mcp_configuration",
            return_value=apply_result,
        ) as apply:
            applied = self.application.rpc(
                "agent.mcp.configuration.apply",
                {
                    "agentPreset": "sumika-work",
                    "previewToken": "private-preview-token",
                    "approved": True,
                    "confirm_agent_preset": "sumika-work",
                    "credentialValue": "private-mcp-secret",
                },
            )
        apply.assert_called_once_with(
            {
                "agentPreset": "sumika-work",
                "previewToken": "private-preview-token",
                "credentialValue": "private-mcp-secret",
            }
        )
        self.assertTrue(applied["backup_retained"])
        audit = str(self.application.storage.list_events(20))
        self.assertIn("agent.mcp.configuration.previewed", audit)
        self.assertIn("agent.mcp.configuration.applied", audit)
        self.assertNotIn("private-preview-token", audit)
        self.assertNotIn("server-filesystem", audit)
        self.assertNotIn("private-mcp-secret", audit)

    def test_browser_policy_and_agent_event_audit_are_fail_closed(self):
        session = self.application.rpc("browser.session.create", {"profile": "temporary", "character_id": "sumika"})
        listed = self.application.rpc("browser.sessions", {})
        self.assertEqual(listed["sessions"][0]["id"], session["id"])
        self.assertNotIn("backend_session_id", listed["sessions"][0])
        decision = self.application.rpc("browser.action.check", {"session_id": session["id"], "action": "login", "domain": "example.com"})
        self.assertTrue(decision["requires_approval"])
        event = self.application.rpc("agent.event.ingest", {"event": {"type": "approval/requested", "sessionId": "dsh-session", "apiKey": "sk-secret"}})
        self.assertEqual(event["event_type"], "approval/requested")
        audit = self.application.storage.list_events(5)
        serialized = str(audit)
        self.assertNotIn("sk-secret", serialized)

    def test_named_browser_profile_rpc_is_persistent_and_approval_gated(self):
        with self.assertRaises(JsonRpcError) as error:
            self.application.rpc(
                "browser.profile.create",
                {"name": "未经确认", "character_id": "sumika"},
            )
        self.assertEqual(error.exception.code, -32031)

        created = self.application.rpc(
            "browser.profile.create",
            {"name": "工作登录", "character_id": "sumika", "approved": True},
        )
        profile = created
        self.assertEqual(profile["status"], "active")
        listed = self.application.rpc("browser.profiles", {"include_archived": True})
        self.assertEqual(listed["profiles"][0]["name"], "工作登录")
        with self.assertRaises(JsonRpcError) as error:
            self.application.rpc(
                "browser.session.create",
                {
                    "profile": "named",
                    "profile_id": profile["id"],
                    "character_id": "other",
                    "approved": True,
                },
            )
        self.assertEqual(error.exception.code, -32031)
        archived = self.application.rpc(
            "browser.profile.archive",
            {"profile_id": profile["id"], "approved": True},
        )
        self.assertEqual(archived["status"], "archived")
        restored = self.application.rpc(
            "browser.profile.restore",
            {"profile_id": profile["id"], "approved": True},
        )
        self.assertEqual(restored["status"], "active")

    def test_browser_observe_and_navigation_endpoints_keep_policy_and_content_boundaries(self):
        with patch.object(
            self.application.browser,
            "observe_session",
            return_value={"session_id": "browser-1", "ready": True, "observation": {"tree": [{"text": "safe"}]}},
        ):
            observed = self.application.rpc("browser.observe", {"session_id": "browser-1"})
        self.assertTrue(observed["ready"])
        self.assertEqual(observed["observation"]["tree"][0]["text"], "safe")
        with patch.object(
            self.application.browser,
            "navigate_session",
            return_value={"session_id": "browser-1", "executed": False, "policy": {"allowed": False, "requires_approval": True, "domain": "example.test"}},
        ):
            pending = self.application.rpc("browser.navigate", {"session_id": "browser-1", "url": "https://example.test"})
        self.assertFalse(pending["executed"])
        events = self.application.storage.list_events(5)
        self.assertIn("browser.observed", str(events))
        self.assertIn("browser.navigation.waiting_approval", str(events))
        self.assertNotIn("safe", str(events))

    def test_browser_dom_action_endpoint_does_not_log_input_values(self):
        with patch.object(
            self.application.browser,
            "execute_action",
            return_value={"session_id": "browser-1", "executed": False, "action": "fill", "requires_human": True},
        ):
            result = self.application.rpc(
                "browser.action.execute",
                {"session_id": "browser-1", "action": "fill", "target": "#password", "value": "private-password"},
            )
        self.assertTrue(result["requires_human"])
        events = self.application.storage.list_events(5)
        self.assertIn("browser.action.waiting_approval", str(events))
        self.assertNotIn("private-password", str(events))

    def test_agent_prompt_does_not_fallback_when_dsh_is_unavailable(self):
        with self.assertRaises(JsonRpcError) as error:
            self.application.rpc("agent.session.prompt", {"session_id": "missing", "text": "hello"})
        self.assertEqual(error.exception.code, -32030)

    def test_agent_prompt_rejection_is_audited_without_prompt_content(self):
        with patch.object(self.application.agent, "prompt", side_effect=AgentRuntimeError("commands/execute unavailable")):
            with self.assertRaises(JsonRpcError):
                self.application.rpc("agent.session.prompt", {"session_id": "s1", "text": "private target"})
        events = self.application.storage.list_events(5)
        serialized = str(events)
        self.assertIn("agent.turn.rejected", serialized)
        self.assertNotIn("private target", serialized)

    def test_agent_session_snapshot_is_exposed_without_raw_history(self):
        snapshot = {
            "session_id": "s1",
            "state": "completed",
            "messages": [{"role": "assistant", "content": "done"}],
            "tools": [],
            "plan": {"active": False, "pending": False, "steps": []},
        }
        with patch.object(self.application.agent, "snapshot", return_value=snapshot):
            result = self.application.rpc("agent.session.snapshot", {"session_id": "s1"})
        self.assertEqual(result["session_id"], "s1")
        self.assertNotIn("events", result)

    def test_agent_retry_requires_explicit_approval_and_exact_session_confirmation(self):
        with patch.object(
            self.application.agent,
            "supports",
            side_effect=lambda capability: capability == AgentCapability.RETRY,
        ), patch.object(self.application.agent, "retry_prompt", return_value={
            "accepted": True,
            "session_id": "s1",
            "source_turn": 3,
            "mode": "execute",
            "text_length": 11,
            "prompt": "must never cross the boundary",
        }) as retry:
            for params in (
                {"sessionId": "s1", "confirmSessionId": "s1"},
                {"sessionId": "s1", "approved": True, "confirmSessionId": "other"},
            ):
                with self.subTest(params=params), self.assertRaises(JsonRpcError) as error:
                    self.application.rpc("agent.session.retry", params)
                self.assertEqual(error.exception.code, -32031)
            with self.assertRaises(JsonRpcError) as error:
                self.application.rpc("agent.session.retry", {"sessionId": "bad\nid", "approved": True, "confirmSessionId": "bad\nid"})
            self.assertEqual(error.exception.code, -32602)

            result = self.application.rpc(
                "agent.session.retry",
                {"sessionId": "s1", "approved": True, "confirmSessionId": "s1", "mode": "execute"},
            )

        retry.assert_called_once_with({"sessionId": "s1", "mode": "execute"})
        self.assertEqual(result["session_id"], "s1")
        self.assertNotIn("prompt", result)
        audit = str(self.application.storage.list_events(20))
        self.assertIn("agent.turn.retry_requested", audit)
        self.assertIn("agent.turn.retry_rejected", audit)
        self.assertIn("agent.turn.retry_accepted", audit)
        self.assertNotIn("must never cross the boundary", audit)

    def test_agent_retry_creates_workspace_checkpoint_and_filters_adapter_receipt(self):
        checkpoint = {
            "id": "wschk-0123456789abcdef0123",
            "name": "Agent retry · s1",
            "workspace_id": "ws-1",
            "path": "D:\\private\\workspace",
            "file_count": 2,
        }
        with patch.object(
            self.application.agent,
            "supports",
            side_effect=lambda capability: capability in {AgentCapability.RETRY, AgentCapability.WORKSPACES},
        ), patch.object(self.application, "_agent_workspace_safety_active", return_value=True), patch.object(
            self.application,
            "_agent_workspace_binding",
            return_value=({"id": "ws-1", "path": "D:\\private\\workspace"}, "D:\\private\\workspace"),
        ) as workspace_binding, patch.object(self.application.workspace, "create_checkpoint", return_value={"checkpoint": checkpoint}) as create_checkpoint, patch.object(
            self.application.agent,
            "retry_prompt",
            return_value={
                "accepted": True,
                "session_id": "s1",
                "source_turn": 4,
                "mode": "execute",
                "text_length": 9,
                "prompt": "private target",
                "raw_history": [{"content": "private target"}],
            },
        ) as retry:
            result = self.application.rpc(
                "agent.session.retry",
                {
                    "sessionId": "s1",
                    "workspaceId": "ws-1",
                    "approved": True,
                    "confirmSessionId": "s1",
                },
            )

        create_checkpoint.assert_called_once_with("D:\\private\\workspace", name="Agent retry · s1")
        workspace_binding.assert_called_once_with(
            {"sessionId": "s1", "workspaceId": "ws-1"},
            session_id="s1",
        )
        retry.assert_called_once_with({"sessionId": "s1"})
        self.assertEqual(result["workspace_checkpoint"], checkpoint)
        self.assertNotIn("prompt", result)
        self.assertNotIn("raw_history", result)
        self.assertNotIn("private target", str(self.application.storage.list_events(20)))

    def test_agent_queue_endpoints_are_runtime_owned_and_audited_without_text(self):
        queue = {
            "session_id": "s1",
            "known": True,
            "items": [{"id": "item-1", "placement": "queued", "text": "safe summary", "editable": True}],
            "hidden_context_count": 0,
        }
        with patch.object(self.application.agent, "queue", return_value=queue):
            result = self.application.rpc("agent.session.queue", {"session_id": "s1"})
        self.assertEqual(result["items"][0]["id"], "item-1")
        with patch.object(
            self.application.agent,
            "update_queue",
            return_value={"accepted": True, "session_id": "s1", "item_id": "item-1", "action": "edit"},
        ):
            updated = self.application.rpc(
                "agent.session.update_queue",
                {"session_id": "s1", "item_id": "item-1", "kind": "edit", "text": "private queue text"},
            )
        self.assertTrue(updated["accepted"])
        events = self.application.storage.list_events(5)
        serialized = str(events)
        self.assertIn("agent.session.queue.updated", serialized)
        self.assertIn("item-1", serialized)
        self.assertNotIn("private queue text", serialized)

    def test_agent_sessions_endpoint_returns_runtime_owned_list(self):
        with patch.object(self.application.agent, "list_sessions", return_value={"sessions": [{"id": "s1", "title": "工作会话"}]}):
            result = self.application.rpc("agent.sessions", {})
        self.assertEqual(result["sessions"][0]["id"], "s1")

    def test_agent_session_search_and_rename_are_bounded_and_audited(self):
        with patch.object(
            self.application.agent,
            "search_sessions",
            return_value={"items": [{"session_id": "s1", "snippet": "匹配摘要"}], "has_more": False},
        ) as search:
            result = self.application.rpc("agent.sessions.search", {"query": "摘要"})
        self.assertEqual(result["items"][0]["session_id"], "s1")
        search.assert_called_once_with({"query": "摘要"})

        with patch.object(
            self.application.agent,
            "rename_session",
            return_value={"session_id": "s1", "title": "新标题", "seq": 9},
        ):
            renamed = self.application.rpc(
                "agent.session.rename",
                {"sessionId": "s1", "title": "新标题"},
            )
        self.assertEqual(renamed["seq"], 9)
        events = self.application.storage.list_events(5)
        self.assertIn("agent.session.renamed", str(events))
        self.assertIn("新标题", str(events))

        for method, params in (
            ("agent.sessions.search", {"query": "\n"}),
            ("agent.session.rename", {"sessionId": "s1", "title": "bad\ntitle"}),
        ):
            with self.assertRaises(JsonRpcError) as error:
                self.application.rpc(method, params)
            self.assertEqual(error.exception.code, -32602)

    def test_agent_attachment_endpoint_returns_data_without_audit_payload(self):
        response = {
            "session_id": "s1",
            "attachment": {"attachment_id": "att-1", "media_type": "image/png", "bytes": 4},
            "data": "aW1n",
        }
        with patch.object(self.application.agent, "attachment", return_value=response) as attachment:
            result = self.application.rpc(
                "agent.session.attachment",
                {"sessionId": "s1", "attachmentId": "att-1"},
            )
        self.assertEqual(result["data"], "aW1n")
        attachment.assert_called_once_with({"sessionId": "s1", "attachmentId": "att-1"})
        self.assertNotIn("aW1n", str(self.application.storage.list_events(10)))

        with self.assertRaises(JsonRpcError) as error:
            self.application.rpc(
                "agent.session.attachment",
                {"sessionId": "s1", "attachmentId": "bad\nid"},
            )
        self.assertEqual(error.exception.code, -32602)

    def test_agent_model_catalog_and_fork_are_runtime_owned(self):
        catalog = {
            "current": {"provider": "local", "model": "qwen3:4b"},
            "routable": True,
            "groups": [],
            "failures": [],
        }
        with patch.object(self.application.agent, "session_models", return_value=catalog):
            result = self.application.rpc("agent.session.models", {"session_id": "parent-1"})
        self.assertEqual(result["current"]["model"], "qwen3:4b")
        with patch.object(self.application.agent, "fork_session", return_value={"sessionId": "child-1"}):
            child = self.application.rpc("agent.session.fork", {"session_id": "parent-1"})
        self.assertEqual(child["sessionId"], "child-1")
        events = self.application.storage.list_events(5)
        self.assertIn("agent.session.forked", str(events))
        self.assertIn("child-1", str(events))

    def test_model_policy_preflight_without_a_candidate_does_not_create_a_session(self):
        decision = {
            "status": "no-compatible-route",
            "selected_route": None,
            "selected_entry": None,
            "requires_confirmation": True,
            "reason_codes": ["no_compatible_route"],
        }
        with patch.object(
            self.application.model_policy,
            "preflight",
            return_value={"decision": decision},
        ) as preflight, patch.object(self.application.agent, "create_session") as create_session:
            result = self.application.rpc(
                "agent.session.create",
                {"routing": {"taskKind": "code"}},
            )

        self.assertFalse(result["accepted"])
        self.assertFalse(result["session_created"])
        preflight.assert_called_once()
        create_session.assert_not_called()

    def test_route_bridge_handshake_requires_ready_runtime_and_exact_tool_set(self):
        tools = [
            "sumika_route_catalog",
            "sumika_route_replan",
            "sumika_route_dispatch",
            "sumika_route_status",
            "sumika_consultation_start",
            "sumika_consultation_status",
            "sumika_route_cancel",
            "sumika_route_retry",
        ]
        pending = self.application.rpc(
            "sumika.route.bridge_tools",
            {
                "register": True,
                "plugin_id": "sumika.dsh-route-bridge",
                "plugin_version": "0.1.0",
                "tools": tools,
            },
        )
        self.assertFalse(pending["registered"])
        self.assertEqual(pending["status"], "runtime-unavailable")

        with patch.object(self.application.agent, "status", return_value={"state": "ready", "ready": True}):
            registered = self.application.rpc(
                "sumika.route.bridge_tools",
                {
                    "register": True,
                    "plugin_id": "sumika.dsh-route-bridge",
                    "plugin_version": "0.1.0",
                    "tools": tools,
                },
            )
        self.assertTrue(registered["registered"])
        self.assertEqual(registered["status"], "registered")
        self.assertEqual(registered["plugin"]["id"], "sumika.dsh-route-bridge")
        self.assertEqual(len(registered["tools"]), 8)

        with patch.object(self.application.agent, "status", return_value={"state": "ready", "ready": True}):
            mismatch = self.application.rpc(
                "sumika.route.bridge_tools",
                {
                    "register": True,
                    "plugin_id": "sumika.dsh-route-bridge",
                    "plugin_version": "0.1.0",
                    "tools": tools[:-1],
                },
            )
        self.assertFalse(mismatch["registered"])
        self.assertEqual(mismatch["status"], "tool-set-mismatch")

    def test_route_bridge_handshake_rejects_malformed_registration_and_clears(self):
        with self.assertRaises(JsonRpcError) as error:
            self.application.rpc(
                "sumika.route.bridge_tools",
                {"register": "yes"},
            )
        self.assertEqual(error.exception.code, -32602)
        with self.assertRaises(JsonRpcError) as error:
            self.application.rpc(
                "sumika.route.bridge_tools",
                {
                    "register": True,
                    "plugin_id": "sumika.dsh-route-bridge",
                    "plugin_version": "0.1.0",
                    "tools": ["sumika_route_catalog", "sumika_route_catalog"],
                },
            )
        self.assertEqual(error.exception.code, -32602)

        self.application._route_bridge_registrations["sumika.dsh-route-bridge"] = {
            "plugin_id": "sumika.dsh-route-bridge",
            "plugin_version": "0.1.0",
            "tools": (),
            "registered_at": "2026-08-31T00:00:00+00:00",
        }
        cleared = self.application.rpc(
            "sumika.route.bridge_tools",
            {"plugin_id": "sumika.dsh-route-bridge", "unregister": True},
        )
        self.assertFalse(cleared["registered"])
        self.assertEqual(cleared["status"], "unregistered")

    def test_consultation_rpc_prefers_modern_supervisor_for_routable_web_route(self):
        self.application.route_supervisor.set_route_catalog(
            [
                RuntimeRouteDescriptor(
                    route_id="web:modern-profile",
                    kind="web-worker",
                    label="Modern web profile",
                    runtime_id="browserskill",
                    executor="web-coordinator",
                    transport="browser-dom",
                    provider_profile_id="modern-profile",
                    provider_key="modern-provider",
                    capabilities=("text", "chat", "browser"),
                    status="ready",
                    routable=True,
                    source_kind="web-chat",
                    auth_state="authorized",
                    health_state="healthy",
                    quota_consent="granted",
                    quota_state="unknown",
                    cost_class="unknown",
                )
            ]
        )
        modern_result = {
            "schema": "agent-consultation/v1",
            "consultation_id": "consultation-modern",
            "status": "running",
            "members": [],
        }
        with (
            patch.object(self.application.route_supervisor, "start_consultation", return_value=modern_result) as modern,
            patch.object(self.application.routes, "start_consultation") as legacy,
        ):
            result = self.application.rpc(
                "sumika.consultation.start",
                {
                    "consultation_id": "consultation-modern",
                    "parent_session_id": "session-modern",
                    "question": "use the modern route",
                    "decision_kind": "brainstorm",
                    "max_members": 1,
                },
            )
        self.assertEqual(result["consultation_id"], "consultation-modern")
        modern.assert_called_once()
        legacy.assert_not_called()

    def test_consultation_rpc_keeps_legacy_route_id_on_legacy_coordinator(self):
        legacy_result = {
            "schema": "agent-consultation/v1",
            "consultation_id": "consultation-legacy",
            "status": "failed",
            "members": [],
        }
        self.application.route_supervisor.set_route_catalog(
            [
                RuntimeRouteDescriptor(
                    route_id="web:modern-profile",
                    kind="web-worker",
                    label="Modern web profile",
                    runtime_id="browserskill",
                    executor="web-coordinator",
                    transport="browser-dom",
                    provider_profile_id="modern-profile",
                    provider_key="modern-provider",
                    capabilities=("text",),
                    status="ready",
                    routable=True,
                    source_kind="web-chat",
                    auth_state="authorized",
                    health_state="healthy",
                    quota_consent="granted",
                    quota_state="unknown",
                    cost_class="unknown",
                )
            ]
        )
        with (
            patch.object(self.application.route_supervisor, "start_consultation") as modern,
            patch.object(self.application.routes, "start_consultation", return_value=legacy_result) as legacy,
        ):
            result = self.application.rpc(
                "sumika.consultation.start",
                {
                    "consultation_id": "consultation-legacy",
                    "parent_session_id": "session-legacy",
                    "question": "old route spelling",
                    "decision_kind": "small-answer",
                    "route_constraints": {"route_ids": ["web-chat:legacy-profile"]},
                    "max_members": 1,
                },
            )
        self.assertEqual(result["consultation_id"], "consultation-legacy")
        legacy.assert_called_once()
        modern.assert_not_called()

    @staticmethod
    def _modern_web_route(route_id, *, provider_key, profile_id=None, occupancy="idle", quota_consent="granted"):
        return RuntimeRouteDescriptor(
            route_id=route_id,
            kind="web-worker",
            label=route_id,
            runtime_id="browserskill",
            executor="fixture-web",
            transport="browser-dom",
            provider_profile_id=profile_id or route_id,
            provider_key=provider_key,
            capabilities=("text", "chat", "browser"),
            status="ready",
            routable=True,
            occupancy=occupancy,
            source_kind="web-chat",
            auth_state="authorized",
            health_state="healthy",
            quota_consent=quota_consent,
            quota_state="unknown",
            cost_class="unknown",
            processing_location="cloud",
        )

    def _install_modern_web_routes(self, routes, executor):
        for route in routes:
            self.application.route_supervisor.register_route(
                route,
                worker=ProviderWorker(executor, worker_id=f"worker-{route.route_id}", runtime_id="browserskill"),
            )

    def test_modern_consultation_rpc_runs_distinct_web_providers(self):
        calls = []

        def execute(dispatch, route, cancel_event):
            calls.append(route.route_id)
            return {"status": "completed", "answer": f"opinion-{route.route_id}"}

        routes = [
            self._modern_web_route("web:provider-a-1", provider_key="provider-a", profile_id="profile-a-1"),
            self._modern_web_route("web:provider-a-2", provider_key="provider-a", profile_id="profile-a-2"),
            self._modern_web_route("web:provider-b", provider_key="provider-b", profile_id="profile-b"),
        ]
        self._install_modern_web_routes(routes, execute)

        result = self.application.rpc(
            "sumika.consultation.start",
            {
                "consultation_id": "consultation-rpc-panel",
                "parent_session_id": "session-rpc-panel",
                "parent_turn_id": "turn-rpc-panel",
                "question": "compare independent approaches",
                "decision_kind": "brainstorm",
                "max_members": 3,
                "wait": True,
                "timeout": 2,
            },
        )

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["successful_count"], 2)
        self.assertEqual({item["route_id"] for item in result["members"]}, {"web:provider-a-1", "web:provider-b"})
        self.assertEqual(len(calls), 2)
        self.assertTrue(result["disagreement_detected"])
        self.assertTrue(result["untrusted_external"])

    def test_modern_consultation_rpc_exposes_partial_and_total_failures(self):
        def execute(dispatch, route, cancel_event):
            if route.route_id.endswith("fail"):
                return {"status": "failed", "error_code": "site-unavailable"}
            return {"status": "completed", "answer": "one opinion"}

        partial_routes = [
            self._modern_web_route("web:rpc-ok", provider_key="rpc-ok", profile_id="rpc-ok"),
            self._modern_web_route("web:rpc-fail", provider_key="rpc-fail", profile_id="rpc-fail"),
        ]
        self._install_modern_web_routes(partial_routes, execute)
        partial = self.application.rpc(
            "sumika.consultation.start",
            {
                "consultation_id": "consultation-rpc-partial",
                "parent_session_id": "session-rpc-failures",
                "question": "check partial failure",
                "decision_kind": "fact-check",
                "max_members": 2,
                "wait": True,
                "timeout": 2,
            },
        )
        self.assertEqual(partial["status"], "partial")
        self.assertEqual(partial["successful_count"], 1)
        self.assertEqual(partial["failed_count"], 1)
        failed_member = next(item for item in partial["members"] if item["status"] == "failed")
        self.assertIsNone(failed_member["answer"])
        self.assertEqual(failed_member["error_code"], "site-unavailable")

        total_routes = [
            self._modern_web_route("web:rpc-total-fail-a", provider_key="rpc-total-a", profile_id="rpc-total-a"),
            self._modern_web_route("web:rpc-total-fail-b", provider_key="rpc-total-b", profile_id="rpc-total-b"),
        ]
        self._install_modern_web_routes(total_routes, lambda dispatch, route, cancel_event: {"status": "failed", "error_code": "all-sites-down"})
        total = self.application.rpc(
            "sumika.consultation.start",
            {
                "consultation_id": "consultation-rpc-total",
                "parent_session_id": "session-rpc-failures",
                "question": "check total failure",
                "decision_kind": "fact-check",
                "route_constraints": {"route_ids": [route.route_id for route in total_routes]},
                "max_members": 2,
                "wait": True,
                "timeout": 2,
            },
        )
        self.assertEqual(total["status"], "failed")
        self.assertEqual(total["successful_count"], 0)
        self.assertEqual(total["failed_count"], 2)
        self.assertTrue(all(item["answer"] is None for item in total["members"]))

    def test_modern_route_rpc_keeps_unknown_quota_gated_and_filters_unavailable(self):
        calls = []
        unknown = self._modern_web_route(
            "web:unknown-quota",
            provider_key="unknown-quota-provider",
            profile_id="unknown-quota-profile",
            quota_consent="unknown",
        )
        unavailable = RuntimeRouteDescriptor.from_value(
            {
                **unknown.to_dict(),
                "route_id": "web:unavailable",
                "provider_profile_id": "unavailable-profile",
                "provider_key": "unavailable-provider",
                "status": "unavailable",
                "routable": False,
            }
        )
        self._install_modern_web_routes(
            [unknown, unavailable],
            lambda dispatch, route, cancel_event: calls.append(route.route_id) or {"status": "completed", "answer": "must not run"},
        )

        catalog = self.application.route_supervisor.catalog(include_unavailable=False)
        self.assertEqual(
            [item["route_id"] for item in catalog["routes"] if item["route_id"] in {unknown.route_id, unavailable.route_id}],
            [unknown.route_id],
        )
        gated = self.application.rpc(
            "sumika.consultation.start",
            {
                "consultation_id": "consultation-rpc-unknown-quota",
                "parent_session_id": "session-rpc-unknown-quota",
                "question": "unknown quota must ask",
                "decision_kind": "small-answer",
                "max_members": 1,
            },
        )
        self.assertEqual(gated["status"], "waiting-human")
        self.assertEqual(gated["members"][0]["status"], "waiting-human")
        self.assertEqual(gated["members"][0]["error_code"], "confirmation-required")
        self.assertEqual(calls, [])

    def test_legacy_profile_occupancy_updates_modern_route_projection(self):
        calls = []
        route = self._modern_web_route(
            "web:lease-profile",
            provider_key="lease-provider",
            profile_id="lease-profile",
        )
        self._install_modern_web_routes(
            [route],
            lambda dispatch, selected, cancel_event: calls.append(selected.route_id) or {"status": "completed", "answer": "ok"},
        )

        occupied = self.application.rpc(
            "sumika.route.occupancy",
            {"profile_id": "lease-profile", "owner": "manual"},
        )
        self.assertEqual(occupied["occupancy"], "manual")
        projected = next(
            item for item in self.application.route_supervisor.catalog()["routes"]
            if item["route_id"] == route.route_id
        )
        self.assertEqual(projected["occupancy"], "manual")
        self.assertFalse(projected["available"])

        blocked = self.application.rpc(
            "sumika.consultation.start",
            {
                "consultation_id": "consultation-rpc-lease-blocked",
                "parent_session_id": "session-rpc-lease",
                "question": "do not race manual operator",
                "decision_kind": "small-answer",
                "max_members": 1,
            },
        )
        self.assertEqual(blocked["status"], "failed")
        self.assertEqual(calls, [])

        released = self.application.rpc(
            "sumika.route.occupancy",
            {"profile_id": "lease-profile", "owner": "idle"},
        )
        self.assertEqual(released["occupancy"], "idle")
        projected = next(
            item for item in self.application.route_supervisor.catalog()["routes"]
            if item["route_id"] == route.route_id
        )
        self.assertTrue(projected["available"])
        resumed = self.application.rpc(
            "sumika.consultation.start",
            {
                "consultation_id": "consultation-rpc-lease-released",
                "parent_session_id": "session-rpc-lease",
                "question": "run after release",
                "decision_kind": "small-answer",
                "max_members": 1,
                "wait": True,
                "timeout": 2,
            },
        )
        self.assertEqual(resumed["status"], "completed")
        self.assertEqual(calls, [route.route_id])

    def test_model_policy_confirmation_precedes_provider_binding_and_model_selection(self):
        profile = {
            "id": "profile-zhipu",
            "status": "available",
            "name": "Zhipu fixture",
            "config": {"model": "glm-4.5-air"},
        }
        decision = {
            "status": "needs-confirmation",
            "selected_route": "profile:profile-zhipu:glm-4.5-air",
            "selected_entry": {
                "route_id": "profile:profile-zhipu:glm-4.5-air",
                "provider_profile_id": "profile-zhipu",
                "model_id": "glm-4.5-air",
            },
            "requires_confirmation": True,
        }
        with (
            patch.object(self.application.model_policy, "preflight", return_value={"decision": decision}),
            patch.object(
                self.application.agent,
                "supports",
                side_effect=lambda capability: capability == AgentCapability.PROVIDER_BRIDGE,
            ),
            patch.object(self.application, "_agent_provider_profile", return_value=profile) as provider_profile,
            patch.object(
                self.application.agent,
                "sync_provider_profile",
                return_value={"profile_id": profile["id"], "route_id": "zhipu-fixture", "model": "glm-4.5-air"},
            ) as sync_provider,
            patch.object(self.application.agent, "create_session", return_value={"sessionId": "session-confirmed"}) as create_session,
            patch.object(
                self.application.agent,
                "select_model",
                return_value={"selected": {"provider": "zhipu-fixture", "model": "glm-4.5-air"}},
            ) as select_model,
        ):
            pending = self.application.rpc(
                "agent.session.create",
                {"routing": {"taskKind": "code"}},
            )
            self.assertFalse(pending["accepted"])
            self.assertFalse(pending["session_created"])
            provider_profile.assert_not_called()
            sync_provider.assert_not_called()
            create_session.assert_not_called()
            select_model.assert_not_called()

            result = self.application.rpc(
                "agent.session.create",
                {
                    "routing": {"taskKind": "code"},
                    "routingApproved": True,
                },
            )

        self.assertEqual(result["sessionId"], "session-confirmed")
        provider_profile.assert_called_once()
        provider_params = provider_profile.call_args.args[0]
        self.assertEqual(provider_params["provider_profile_id"], "profile-zhipu")
        self.assertTrue(provider_profile.call_args.kwargs["refresh_health"])
        sync_provider.assert_called_once_with(profile)
        create_session.assert_called_once()
        select_model.assert_called_once_with(
            {
                "session_id": "session-confirmed",
                "provider": "zhipu-fixture",
                "model": "glm-4.5-air",
            }
        )

    def test_prompt_preflight_failure_does_not_create_a_workspace_checkpoint(self):
        decision = {
            "status": "no-compatible-route",
            "selected_route": None,
            "selected_entry": None,
            "requires_confirmation": True,
            "reason_codes": ["quality_gate"],
        }
        with (
            patch.object(self.application.model_policy, "preflight", return_value={"decision": decision}) as preflight,
            patch.object(self.application, "_agent_workspace_safety_active", return_value=True),
            patch.object(self.application.workspace, "create_checkpoint") as create_checkpoint,
            patch.object(self.application.agent, "prompt") as prompt,
        ):
            result = self.application.rpc(
                "agent.session.prompt",
                {
                    "sessionId": "session-1",
                    "mode": "execute",
                    "text": "make a change",
                    "routing": {"taskKind": "code"},
                },
            )

        self.assertFalse(result["accepted"])
        self.assertIn("routing", result)
        preflight.assert_called_once()
        create_checkpoint.assert_not_called()
        prompt.assert_not_called()

    def test_agent_task_projection_rpc_is_read_only_and_bounded(self):
        projection = {
            "available": True,
            "runtime_id": "dsh",
            "read_only": True,
            "tasks": [{"id": "agent:dsh:s1", "session_id": "s1", "read_only": True}],
            "errors": [],
        }
        with patch.object(self.application.agent_tasks, "project", return_value=projection) as project:
            result = self.application.rpc("agent.task.projections", {"limit": 12})
        project.assert_called_once_with(limit=12)
        self.assertTrue(result["tasks"][0]["read_only"])
        self.assertEqual(self.application.tasks.list()[0]["id"], "core-service")

        for value in (0, 65, True, "12"):
            with self.assertRaises(JsonRpcError) as error:
                self.application.rpc("agent.task.projections", {"limit": value})
            self.assertEqual(error.exception.code, -32602)

    def test_agent_presets_subagents_and_goals_are_exposed_as_runtime_capabilities(self):
        with patch.object(
            self.application.agent,
            "list_presets",
            return_value={"presets": [{"id": "standard", "trust": "system", "is_default": True}], "authorable": False, "has_document": False},
        ):
            presets = self.application.rpc("agent.presets", {})
        self.assertEqual(presets["presets"][0]["id"], "standard")

        with patch.object(
            self.application.agent,
            "list_subagents",
            return_value={"entries": [{"kind": "child", "id": "child-1", "mode": "continuable"}], "parent_available": True},
        ):
            children = self.application.rpc("agent.subagent.list", {"parentSessionId": "parent-1"})
        self.assertTrue(children["parent_available"])

        with patch.object(
            self.application.agent,
            "goal_action",
            return_value={"ref": {"id": "goal-1", "revision": 2}},
        ):
            goal = self.application.rpc(
                "agent.goal.pause",
                {"session_id": "s1", "ref": {"id": "goal-1", "revision": 1}},
            )
        self.assertEqual(goal["ref"]["revision"], 2)
        events = self.application.storage.list_events(5)
        self.assertIn("agent.goal.changed", str(events))
        self.assertNotIn("objective", str(events))

    def test_agent_preset_copy_and_open_are_validated_and_audited_without_paths(self):
        with patch.object(
            self.application.agent,
            "copy_preset",
            return_value={"agent_preset": "sumika-work", "source": "standard"},
        ) as copy:
            copied = self.application.rpc(
                "agent.preset.copy",
                {"from": "standard", "agentPreset": "sumika-work", "name": "Sumika 工作"},
            )
        copy.assert_called_once_with(
            {"from": "standard", "agentPreset": "sumika-work", "name": "Sumika 工作"}
        )
        self.assertEqual(copied, {"agent_preset": "sumika-work", "source": "standard"})

        with patch.object(
            self.application.agent,
            "open_preset_document",
            return_value={
                "agent_preset": "sumika-work",
                "opened": False,
                "path": "D:\\private\\agent-presets\\sumika-work",
            },
        ) as open_document:
            opened = self.application.rpc(
                "agent.preset.open",
                {"agentPreset": "sumika-work"},
            )
        open_document.assert_called_once_with({"agentPreset": "sumika-work"})
        self.assertEqual(opened, {"agent_preset": "sumika-work", "opened": False})

        events = str(self.application.storage.list_events(10))
        self.assertIn("agent.preset.copied", events)
        self.assertIn("agent.preset.document.opened", events)
        self.assertIn("sumika-work", events)
        self.assertNotIn("private", events)
        self.assertNotIn("Sumika 工作", events)

        for method, params in (
            ("agent.preset.copy", {"from": "..\\secret", "agentPreset": "sumika-work"}),
            ("agent.preset.copy", {"from": "standard", "agentPreset": "standard"}),
            ("agent.preset.open", {"agentPreset": "D:\\secret"}),
        ):
            with self.assertRaises(JsonRpcError) as error:
                self.application.rpc(method, params)
            self.assertEqual(error.exception.code, -32602)

    def test_agent_preset_mount_validation_is_path_free_and_audited(self):
        workspace_path = str(Path.cwd().resolve())
        with patch.object(
            self.application.agent,
            "validate_preset_mount",
            return_value={
                "agent_preset": "sumika-work",
                "mountable": True,
                "validation_session_archived": True,
            },
        ) as validate:
            result = self.application.rpc(
                "agent.preset.validate",
                {"agentPreset": "sumika-work", "cwd": workspace_path},
            )
        self.assertTrue(result["mountable"])
        self.assertTrue(result["validation_session_archived"])
        validate.assert_called_once_with(
            {"agentPreset": "sumika-work", "cwd": workspace_path}
        )
        events = str(self.application.storage.list_events(5))
        self.assertIn("agent.preset.mount.validated", events)
        self.assertIn("sumika-work", events)
        self.assertNotIn(workspace_path, events)

        for params in (
            {"agentPreset": "D:\\secret"},
            {"agentPreset": "sumika-work", "workspaceId": "workspace-1", "cwd": workspace_path},
            {"agentPreset": "sumika-work", "cwd": "relative"},
        ):
            with self.assertRaises(JsonRpcError) as error:
                self.application.rpc("agent.preset.validate", params)
            self.assertEqual(error.exception.code, -32602)

    def test_agent_preset_remove_requires_exact_confirmation_and_explicit_user_trust(self):
        roster = {
            "presets": [
                {"id": "standard", "trust": "system", "name": "System Preset"},
                {"id": "untrusted", "trust": "unknown"},
                {
                    "id": "sumika-work",
                    "trust": "user",
                    "name": "Private display name",
                    "path": "D:\\private\\agent-presets\\sumika-work",
                    "composition": "must not enter audit",
                },
            ]
        }
        with (
            patch.object(self.application.agent, "list_presets", return_value=roster),
            patch.object(
                self.application.agent,
                "remove_preset",
                return_value={"agent_preset": "sumika-work", "removed": True},
            ) as remove,
        ):
            for params in (
                {"agentPreset": "sumika-work"},
                {"agentPreset": "sumika-work", "approved": True, "confirm_agent_preset": "other"},
            ):
                with self.assertRaises(JsonRpcError) as error:
                    self.application.rpc("agent.preset.remove", params)
                self.assertEqual(error.exception.code, -32031)

            with self.assertRaises(JsonRpcError) as error:
                self.application.rpc(
                    "agent.preset.remove",
                    {"agentPreset": "standard", "approved": True, "confirm_agent_preset": "standard"},
                )
            self.assertEqual(error.exception.code, -32031)

            with self.assertRaises(JsonRpcError) as error:
                self.application.rpc(
                    "agent.preset.remove",
                    {"agentPreset": "untrusted", "approved": True, "confirm_agent_preset": "untrusted"},
                )
            self.assertEqual(error.exception.code, -32031)

            with self.assertRaises(JsonRpcError) as error:
                self.application.rpc(
                    "agent.preset.remove",
                    {"agentPreset": "missing", "approved": True, "confirm_agent_preset": "missing"},
                )
            self.assertEqual(error.exception.code, -32602)

            removed = self.application.rpc(
                "agent.preset.remove",
                {
                    "agentPreset": "sumika-work",
                    "approved": True,
                    "confirm_agent_preset": "sumika-work",
                },
            )

        remove.assert_called_once_with({"agentPreset": "sumika-work"})
        self.assertEqual(removed, {"agent_preset": "sumika-work", "removed": True})
        events = str(self.application.storage.list_events(10))
        self.assertIn("agent.preset.removed", events)
        self.assertIn("sumika-work", events)
        self.assertNotIn("Private display name", events)
        self.assertNotIn("private", events)
        self.assertNotIn("composition", events)

        with self.assertRaises(JsonRpcError) as error:
            self.application.rpc(
                "agent.preset.remove",
                {"agentPreset": "D:\\secret", "approved": True, "confirm_agent_preset": "D:\\secret"},
            )
        self.assertEqual(error.exception.code, -32602)

    def test_agent_workspace_registration_validates_and_audits_metadata(self):
        workspace = {
            "id": "workspace-1",
            "path": "D:\\Code\\Sumika",
            "title": "Sumika",
            "session_ids": [],
        }
        with patch.object(self.application.agent, "list_workspaces", return_value={"workspaces": [workspace], "archived_session_ids": []}):
            listed = self.application.rpc("agent.workspaces", {})
        self.assertEqual(listed["workspaces"][0]["id"], "workspace-1")
        with self.assertRaises(JsonRpcError) as error:
            self.application.rpc("agent.workspace.create", {"path": "\n"})
        self.assertEqual(error.exception.code, -32602)
        with patch.object(self.application.agent, "create_workspace", return_value={"workspace": workspace, "created": True}):
            created = self.application.rpc("agent.workspace.create", {"path": "D:\\Code\\Sumika"})
        self.assertTrue(created["created"])
        events = self.application.storage.list_events(5)
        serialized = str(events)
        self.assertIn("agent.workspace.registered", serialized)
        self.assertIn("workspace-1", serialized)
        self.assertNotIn("D:\\Code\\Sumika", serialized)

    def test_workspace_checkpoint_rpc_is_separate_approval_gated_and_path_free_in_audit(self):
        workspace_path = str(Path.cwd().resolve())
        checkpoint_id = "wschk-" + "a" * 20
        preview_token = "b" * 64
        workspace = {
            "id": "ws-safe",
            "title": "Sumika",
            "path": workspace_path,
            "branch": "codex/dsh-agent-runtime",
            "head": "2f0655d",
            "dirty": True,
            "files": [{"path": "frontend/main.js", "status": "modified"}],
            "file_count": 1,
        }
        checkpoint = {
            "id": checkpoint_id,
            "name": "before Agent turn",
            "workspace_id": "ws-safe",
            "file_count": 2,
            "total_bytes": 20,
        }
        diff = {
            "checkpoint": checkpoint,
            "workspace": workspace,
            "changed": True,
            "counts": {"added": 0, "removed": 0, "changed": 1, "changed_total": 1},
            "files": [{"path": "frontend/main.js", "status": "changed"}],
            "preview_token": preview_token,
        }
        preview = {
            **diff,
            "restore": {
                "archive_count": 1,
                "write_count": 1,
                "archive_paths": ["frontend/main.js"],
                "write_paths": ["frontend/main.js"],
                "preview_token": preview_token,
            },
        }
        restored = {
            "checkpoint": checkpoint,
            "pre_restore_checkpoint": {**checkpoint, "id": "wschk-" + "c" * 20},
            "diff": diff,
            "archive": {
                "root": str(Path(workspace_path) / "deprecated" / "timestamp" / "workspace-restore"),
                "entries": [{"original_path": "frontend/main.js", "archive_path": "deprecated/timestamp/workspace-restore/frontend/main.js"}],
            },
            "restored": True,
        }
        with (
            patch.object(self.application.workspace, "inspect", return_value={"workspace": workspace, "checkpoint_count": 1}),
            patch.object(self.application.workspace, "list_checkpoints", return_value={"checkpoints": [checkpoint]}),
            patch.object(self.application.workspace, "create_checkpoint", return_value={"checkpoint": checkpoint}),
            patch.object(self.application.workspace, "diff_checkpoint", return_value=diff),
            patch.object(self.application.workspace, "restore_preview", return_value=preview),
            patch.object(self.application.workspace, "restore", return_value=restored) as restore,
        ):
            self.assertEqual(self.application.rpc("workspace.inspect", {"path": workspace_path})["workspace"]["id"], "ws-safe")
            self.assertEqual(self.application.rpc("workspace.checkpoints", {"path": workspace_path})["checkpoints"][0]["id"], checkpoint_id)
            self.application.rpc("workspace.checkpoint.create", {"path": workspace_path, "name": "before Agent turn"})
            self.application.rpc("workspace.checkpoint.diff", {"path": workspace_path, "checkpoint_id": checkpoint_id})
            self.application.rpc("workspace.restore.preview", {"path": workspace_path, "checkpoint_id": checkpoint_id})
            with self.assertRaises(JsonRpcError) as error:
                self.application.rpc(
                    "workspace.restore",
                    {"path": workspace_path, "checkpoint_id": checkpoint_id},
                )
            self.assertEqual(error.exception.code, -32031)
            result = self.application.rpc(
                "workspace.restore",
                {
                    "path": workspace_path,
                    "checkpoint_id": checkpoint_id,
                    "preview_token": preview_token,
                    "approved": True,
                    "confirm_checkpoint": checkpoint_id,
                },
            )
        self.assertTrue(result["restored"])
        restore.assert_called_once_with(
            checkpoint_id,
            path=workspace_path,
            approved=True,
            confirm_checkpoint=checkpoint_id,
            preview_token=preview_token,
        )
        events = str(self.application.storage.list_events(20))
        self.assertIn("workspace.checkpoint.created", events)
        self.assertIn("workspace.restore.previewed", events)
        self.assertIn("workspace.restored", events)
        self.assertIn(checkpoint_id, events)
        self.assertNotIn(workspace_path, events)
        self.assertNotIn("frontend/main.js", events)

    def test_workspace_worktree_and_commit_rpc_require_preview_and_keep_audit_content_free(self):
        source_path = str(Path.cwd().resolve())
        destination_path = str((Path.cwd().resolve().parent / "sumika-agent-test-worktree").resolve())
        checkpoint_id = "wschk-" + "d" * 20
        worktree_token = "e" * 64
        commit_token = "f" * 64
        branch = "codex/agent-daily-test"
        source = {
            "id": "ws-source",
            "title": "Sumika",
            "path": source_path,
            "branch": "codex/dsh-agent-runtime",
            "head": "1" * 40,
            "dirty": True,
        }
        worktree = {
            "id": "ws-linked",
            "title": "sumika-agent-test-worktree",
            "path": destination_path,
            "branch": branch,
            "head": "1" * 40,
            "kind": "linked",
        }
        worktree_preview = {
            "source": source,
            "worktree": worktree,
            "preview_token": worktree_token,
            "requires_approval": True,
            "includes_uncommitted_changes": False,
        }
        checkpoint = {
            "id": checkpoint_id,
            "workspace_id": worktree["id"],
            "branch": branch,
            "head": worktree["head"],
            "baseline_clean": True,
        }
        commit_preview = {
            "checkpoint": checkpoint,
            "workspace": {**worktree, "dirty": True, "file_count": 1},
            "counts": {"added": 0, "removed": 0, "changed": 1, "changed_total": 1},
            "files": [{"path": "private-change.txt", "status": "changed"}],
            "patch": "PRIVATE PATCH BODY",
            "message_summary": "Private commit title",
            "message_sha256": "2" * 64,
            "preview_token": commit_token,
            "requires_approval": True,
        }
        committed = {
            "workspace": {**worktree, "dirty": False, "file_count": 0},
            "checkpoint": checkpoint,
            "commit": "3" * 40,
            "branch": branch,
            "file_count": 1,
            "files": ["private-change.txt"],
            "pushed": False,
        }
        with (
            patch.object(self.application.workspace, "preview_worktree", return_value=worktree_preview) as preview_worktree,
            patch.object(self.application.workspace, "create_worktree", return_value={"source": source, "worktree": worktree, "created": True}) as create_worktree,
            patch.object(self.application.workspace, "preview_commit", return_value=commit_preview) as preview_commit,
            patch.object(self.application.workspace, "commit", return_value=committed) as commit,
        ):
            self.application.rpc(
                "workspace.worktree.preview",
                {"source_path": source_path, "destination_path": destination_path, "branch": branch},
            )
            with self.assertRaises(JsonRpcError) as worktree_error:
                self.application.rpc(
                    "workspace.worktree.create",
                    {"source_path": source_path, "destination_path": destination_path, "branch": branch},
                )
            self.assertEqual(worktree_error.exception.code, -32031)
            created = self.application.rpc(
                "workspace.worktree.create",
                {
                    "source_path": source_path,
                    "destination_path": destination_path,
                    "branch": branch,
                    "approved": True,
                    "confirm_branch": branch,
                    "confirm_destination": destination_path,
                    "preview_token": worktree_token,
                },
            )
            previewed = self.application.rpc(
                "workspace.commit.preview",
                {"path": destination_path, "checkpoint_id": checkpoint_id, "message": "Private commit title"},
            )
            with self.assertRaises(JsonRpcError) as commit_error:
                self.application.rpc(
                    "workspace.commit",
                    {"path": destination_path, "checkpoint_id": checkpoint_id, "message": "Private commit title"},
                )
            self.assertEqual(commit_error.exception.code, -32031)
            result = self.application.rpc(
                "workspace.commit",
                {
                    "path": destination_path,
                    "checkpoint_id": checkpoint_id,
                    "message": "Private commit title",
                    "approved": True,
                    "confirm_branch": branch,
                    "preview_token": commit_token,
                },
            )

        self.assertTrue(created["created"])
        self.assertEqual(previewed["patch"], "PRIVATE PATCH BODY")
        self.assertEqual(result["commit"], "3" * 40)
        preview_worktree.assert_called_once_with(source_path, destination_path, branch)
        create_worktree.assert_called_once_with(
            source_path,
            destination_path,
            branch,
            approved=True,
            confirm_branch=branch,
            confirm_destination=destination_path,
            preview_token=worktree_token,
        )
        preview_commit.assert_called_once_with(checkpoint_id, path=destination_path, message="Private commit title")
        commit.assert_called_once_with(
            checkpoint_id,
            path=destination_path,
            message="Private commit title",
            approved=True,
            confirm_branch=branch,
            preview_token=commit_token,
        )
        events = str(self.application.storage.list_events(20))
        self.assertIn("workspace.worktree.previewed", events)
        self.assertIn("workspace.worktree.created", events)
        self.assertIn("workspace.commit.previewed", events)
        self.assertIn("workspace.committed", events)
        self.assertIn(checkpoint_id, events)
        self.assertNotIn(source_path, events)
        self.assertNotIn(destination_path, events)
        self.assertNotIn("PRIVATE PATCH BODY", events)
        self.assertNotIn("Private commit title", events)
        self.assertNotIn("private-change.txt", events)

    def test_agent_interactions_are_exposed_and_question_answers_are_audited_without_content(self):
        self.application.agent.normalize_event(
            {
                "type": "question/requested",
                "rpcId": "question-1",
                "sessionId": "session-1",
                "questions": [{"id": "choice", "question": "选择", "options": [{"label": "A"}]}],
            }
        )
        listed = self.application.rpc("agent.interactions", {"session_id": "session-1"})
        self.assertEqual(listed["interactions"][0]["id"], "question-1")
        with patch.object(self.application.agent, "respond_interaction", return_value={"accepted": True, "kind": "question"}):
            result = self.application.rpc(
                "agent.question.respond",
                {
                    "rpcId": "question-1",
                    "sessionId": "session-1",
                    "answer": {"answers": [{"id": "choice", "selected": ["A"]}]},
                },
            )
        self.assertTrue(result["accepted"])
        events = self.application.storage.list_events(5)
        self.assertIn("agent.question.answered", str(events))
        self.assertNotIn('"selected"', str(events))

    def test_agent_plan_review_approval_checkpoints_before_runtime_execution(self):
        checkpoint = {
            "id": "wschk-plan-0123456789",
            "workspace_id": "workspace-plan",
            "file_count": 3,
            "total_bytes": 2048,
        }
        interaction = {
            "id": "plan-review-1",
            "kind": "question",
            "session_id": "session-plan",
            "plan_review": {"approve": "Approve", "keep_planning": "Keep planning"},
            "questions": [
                {
                    "id": "plan-review",
                    "intent": {"kind": "plan-review", "approve": "Approve"},
                }
            ],
        }
        call_order = []
        with patch.object(
            self.application,
            "_agent_workspace_safety_active",
            return_value=True,
        ), patch.object(
            self.application.agent,
            "interactions",
            return_value={"interactions": [interaction]},
        ), patch.object(
            self.application,
            "_agent_workspace_binding",
            return_value=({"id": "workspace-plan"}, "D:\\private\\plan-workspace"),
        ) as workspace_binding, patch.object(
            self.application.workspace,
            "create_checkpoint",
            side_effect=lambda *args, **kwargs: call_order.append("checkpoint") or {"checkpoint": checkpoint},
        ) as create_checkpoint, patch.object(
            self.application.agent,
            "respond_interaction",
            side_effect=lambda params: call_order.append("approve") or {"accepted": True, "kind": "question"},
        ) as respond:
            result = self.application.rpc(
                "agent.question.respond",
                {
                    "rpcId": "plan-review-1",
                    "sessionId": "session-plan",
                    "workspaceId": "workspace-plan",
                    "answer": {
                        "answers": [
                            {"id": "plan-review", "selected": ["Approve"]}
                        ]
                    },
                },
            )

        self.assertEqual(call_order, ["checkpoint", "approve"])
        workspace_binding.assert_called_once_with(
            {
                "rpcId": "plan-review-1",
                "sessionId": "session-plan",
                "workspaceId": "workspace-plan",
                "answer": {
                    "answers": [
                        {"id": "plan-review", "selected": ["Approve"]}
                    ]
                },
            },
            session_id="session-plan",
        )
        create_checkpoint.assert_called_once_with(
            "D:\\private\\plan-workspace",
            name="Agent plan approval · session-plan",
        )
        respond.assert_called_once()
        self.assertEqual(result["workspace_checkpoint"], checkpoint)
        events = str(self.application.storage.list_events(10))
        self.assertIn("workspace.checkpoint.created", events)
        self.assertIn("agent.plan.approval", events)
        self.assertIn("agent.question.answered", events)
        self.assertNotIn('"selected"', events)

    def test_agent_plan_review_checkpoint_failure_does_not_approve(self):
        interaction = {
            "id": "plan-review-1",
            "kind": "question",
            "session_id": "session-plan",
            "plan_review": {"approve": "Approve"},
            "questions": [
                {
                    "id": "plan-review",
                    "intent": {"kind": "plan-review", "approve": "Approve"},
                }
            ],
        }
        with patch.object(
            self.application,
            "_agent_workspace_safety_active",
            return_value=True,
        ), patch.object(
            self.application.agent,
            "interactions",
            return_value={"interactions": [interaction]},
        ), patch.object(
            self.application,
            "_agent_workspace_binding",
            return_value=({"id": "workspace-plan"}, "D:\\private\\plan-workspace"),
        ), patch.object(
            self.application.workspace,
            "create_checkpoint",
            side_effect=WorkspaceError("checkpoint unavailable"),
        ), patch.object(self.application.agent, "respond_interaction") as respond:
            with self.assertRaises(JsonRpcError) as error:
                self.application.rpc(
                    "agent.question.respond",
                    {
                        "rpcId": "plan-review-1",
                        "sessionId": "session-plan",
                        "workspaceId": "workspace-plan",
                        "answer": {
                            "answers": [
                                {"id": "plan-review", "selected": ["Approve"]}
                            ]
                        },
                    },
                )

        self.assertEqual(error.exception.code, -32033)
        respond.assert_not_called()
        self.assertIn("agent.plan.approval_rejected", str(self.application.storage.list_events(5)))

    def test_agent_real_acceptance_evidence_is_bounded_and_correlates_restore(self):
        session_id = "session-real-evidence"
        checkpoint_id = "wschk-0123456789abcdef0123"
        events = [
            {
                "event_type": "workspace.restored",
                "session_id": None,
                "timestamp": "2026-08-29T00:00:08+00:00",
                "payload": {"checkpoint_id": checkpoint_id, "changed_total": 1, "archive_count": 1, "path": "D:\\private"},
            },
            {
                "event_type": "workspace.restore.previewed",
                "session_id": None,
                "timestamp": "2026-08-29T00:00:07+00:00",
                "payload": {"checkpoint_id": checkpoint_id, "archive_count": 1},
            },
            {
                "event_type": "workspace.checkpoint.diffed",
                "session_id": None,
                "timestamp": "2026-08-29T00:00:06+00:00",
                "payload": {"checkpoint_id": checkpoint_id, "changed": True, "changed_total": 1},
            },
            {
                "event_type": "agent.session.event",
                "session_id": session_id,
                "timestamp": "2026-08-29T00:00:05+00:00",
                "payload": {"status": "turn/end", "content": "private output", "extensions": {"turn": {"state": "completed"}}},
            },
            {
                "event_type": "agent.session.event",
                "session_id": session_id,
                "timestamp": "2026-08-29T00:00:04.5+00:00",
                "payload": {"status": "tool/result", "extensions": {"tool": {"status": "completed"}}},
            },
            {
                "event_type": "agent.session.event",
                "session_id": session_id,
                "timestamp": "2026-08-29T00:00:04+00:00",
                "payload": {"status": "tool/call", "extensions": {"tool": {"name": "write", "path": "D:\\private"}}},
            },
            {
                "event_type": "agent.question.answered",
                "session_id": session_id,
                "timestamp": "2026-08-29T00:00:03+00:00",
                "payload": {"request_id": "request-private", "plan_approved": True, "workspace_checkpoint_id": checkpoint_id},
            },
            {
                "event_type": "workspace.checkpoint.created",
                "session_id": session_id,
                "timestamp": "2026-08-29T00:00:02.9+00:00",
                "payload": {"checkpoint_id": checkpoint_id, "trigger": "agent.plan.approval", "path": "D:\\private"},
            },
            {
                "event_type": "agent.question.requested",
                "session_id": session_id,
                "timestamp": "2026-08-29T00:00:01+00:00",
                "payload": {"extensions": {"rpcId": "request-private"}, "detail": "private plan"},
            },
        ]
        with patch.object(self.application.storage, "list_events", return_value=events) as list_events:
            result = self.application.rpc("agent.acceptance.evidence", {"sessionId": session_id})

        list_events.assert_called_once_with(1000)
        self.assertEqual(result["status"], "passed")
        self.assertTrue(result["plan_review"]["checkpoint_before_approval"])
        self.assertEqual(result["execution"]["turn_state"], "completed")
        self.assertTrue(result["execution"]["write_tool_seen"])
        self.assertEqual(result["workspace"]["changed_file_count"], 1)
        self.assertTrue(result["workspace"]["restored"])
        serialized = str(result)
        for forbidden in (session_id, checkpoint_id, "request-private", "private plan", "D:\\private"):
            self.assertNotIn(forbidden, serialized)

    def test_agent_real_acceptance_evidence_does_not_pass_an_empty_read_only_round(self):
        session_id = "session-read-only-evidence"
        checkpoint_id = "wschk-11111111111111111111"
        events = [
            {
                "event_type": "workspace.restored",
                "timestamp": "2026-08-29T00:00:08+00:00",
                "payload": {"checkpoint_id": checkpoint_id, "archive_count": 0},
            },
            {
                "event_type": "workspace.restore.previewed",
                "timestamp": "2026-08-29T00:00:07+00:00",
                "payload": {"checkpoint_id": checkpoint_id},
            },
            {
                "event_type": "workspace.checkpoint.diffed",
                "timestamp": "2026-08-29T00:00:06+00:00",
                "payload": {"checkpoint_id": checkpoint_id, "changed_total": 0},
            },
            {
                "event_type": "agent.session.event",
                "session_id": session_id,
                "timestamp": "2026-08-29T00:00:05+00:00",
                "payload": {
                    "status": "turn/end",
                    "extensions": {"turn": {"state": "completed"}},
                },
            },
            {
                "event_type": "agent.session.event",
                "session_id": session_id,
                "timestamp": "2026-08-29T00:00:04.5+00:00",
                "payload": {"status": "tool/result", "extensions": {"tool": {"status": "completed"}}},
            },
            {
                "event_type": "agent.session.event",
                "session_id": session_id,
                "timestamp": "2026-08-29T00:00:04+00:00",
                "payload": {"status": "tool/call", "extensions": {"tool": {"name": "read"}}},
            },
            {
                "event_type": "agent.question.answered",
                "session_id": session_id,
                "timestamp": "2026-08-29T00:00:03+00:00",
                "payload": {
                    "request_id": "request-read-only",
                    "plan_approved": True,
                    "workspace_checkpoint_id": checkpoint_id,
                },
            },
            {
                "event_type": "workspace.checkpoint.created",
                "session_id": session_id,
                "timestamp": "2026-08-29T00:00:02.9+00:00",
                "payload": {"checkpoint_id": checkpoint_id, "trigger": "agent.plan.approval"},
            },
            {
                "event_type": "agent.question.requested",
                "session_id": session_id,
                "timestamp": "2026-08-29T00:00:01+00:00",
                "payload": {"extensions": {"rpcId": "request-read-only"}},
            },
        ]

        with patch.object(self.application.storage, "list_events", return_value=events):
            result = self.application.rpc("agent.acceptance.evidence", {"sessionId": session_id})

        self.assertEqual(result["status"], "needs-action")
        self.assertFalse(result["execution"]["write_tool_seen"])
        self.assertEqual(result["execution"]["tool_result_count"], 1)
        self.assertEqual(result["workspace"]["changed_file_count"], 0)

    def test_agent_real_acceptance_evidence_fails_when_checkpoint_follows_approval(self):
        session_id = "session-order-failure"
        checkpoint_id = "wschk-fedcba98765432100123"
        events = [
            {
                "event_type": "agent.question.answered",
                "session_id": session_id,
                "timestamp": "2026-08-29T00:00:03+00:00",
                "payload": {"request_id": "request-1", "plan_approved": True, "workspace_checkpoint_id": checkpoint_id},
            },
            {
                "event_type": "workspace.checkpoint.created",
                "session_id": session_id,
                "timestamp": "2026-08-29T00:00:04+00:00",
                "payload": {"checkpoint_id": checkpoint_id, "trigger": "agent.plan.approval"},
            },
        ]
        with patch.object(self.application.storage, "list_events", return_value=events):
            result = self.application.rpc("agent.acceptance.evidence", {"sessionId": session_id})

        self.assertEqual(result["status"], "failed")
        self.assertTrue(result["plan_review"]["approved"])
        self.assertTrue(result["plan_review"]["checkpoint_created"])
        self.assertFalse(result["plan_review"]["checkpoint_before_approval"])

    def test_agent_plan_review_cancel_is_explicitly_audited_without_question_content(self):
        with patch.object(
            self.application.agent,
            "cancel_interaction",
            return_value={"accepted": True, "kind": "question", "cancelled": True},
        ) as cancel_interaction:
            result = self.application.rpc(
                "agent.question.cancel",
                {"rpcId": "plan-review-1", "sessionId": "session-plan"},
            )
        self.assertTrue(result["accepted"])
        cancel_interaction.assert_called_once_with(
            {"rpcId": "plan-review-1", "sessionId": "session-plan"}
        )
        events = self.application.storage.list_events(5)
        self.assertIn("agent.question.cancelled", str(events))
        self.assertIn("plan-review-1", str(events))
        self.assertNotIn("Approve this plan", str(events))

    def test_new_agent_session_binds_the_active_sumika_provider(self):
        profile = self.application.provider_profiles.save(
            {
                "id": "local-test",
                "name": "Local test",
                "template_id": "ollama",
                "processing_location": "local",
                "base_url": "http://127.0.0.1:11434/v1",
                "model": "qwen3:4b",
            }
        )
        self.application.storage.update_provider_profile_state(profile["id"], status="available")
        self.application.storage.upsert_module_setting(
            "llm",
            enabled=True,
            implementation_id="openai-compatible",
            config={"profile_id": profile["id"]},
        )
        with patch.object(self.application.provider_profiles, "health", return_value={"ok": True, "profile": profile}) as health, patch.object(self.application.agent, "sync_provider_profile", return_value={"profile_id": profile["id"], "route_id": "sumika-local-test", "model": "qwen3:4b", "changed": True, "active": True}), patch.object(self.application.agent, "create_session", return_value={"sessionId": "dsh-session"}), patch.object(self.application.agent, "select_model", return_value={"selected": {"provider": "sumika-local-test", "model": "qwen3:4b"}}):
            result = self.application.rpc("agent.session.create", {"cwd": "."})
        health.assert_called_once_with(profile["id"])
        self.assertEqual(result["provider"]["route_id"], "sumika-local-test")
        self.assertEqual(result["selected_model"]["model"], "qwen3:4b")
        self.assertNotIn("secrets", result["provider"])

    def test_agent_provider_status_rejects_an_unavailable_active_profile_before_runtime(self):
        profile = self.application.provider_profiles.save(
            {
                "id": "offline-provider",
                "name": "Offline provider",
                "template_id": "openai-compatible",
                "processing_location": "cloud",
                "base_url": "https://example.test/v1",
                "model": "model-a",
                "api_key": "test-secret",
            }
        )
        self.application.storage.upsert_module_setting(
            "llm",
            enabled=True,
            implementation_id="openai-compatible",
            config={"profile_id": profile["id"]},
        )
        with patch.object(self.application.agent, "provider_status") as provider_status:
            result = self.application.rpc("agent.provider.status", {})
        self.assertEqual(result["state"], "unavailable")
        self.assertFalse(result["ready"])
        self.assertEqual(result["profile_id"], profile["id"])
        self.assertIn("模块页测试连接", result["reason"])
        self.assertNotIn("test-secret", str(result))
        provider_status.assert_not_called()

    def test_agent_provider_status_refreshes_a_stale_available_profile_before_runtime(self):
        profile = self.application.provider_profiles.save(
            {
                "id": "stale-provider",
                "name": "Stale provider",
                "template_id": "ollama",
                "processing_location": "local",
                "base_url": "http://127.0.0.1:11434/v1",
                "model": "qwen3:4b",
            }
        )
        self.application.storage.update_provider_profile_state(profile["id"], status="available")
        self.application.storage.upsert_module_setting(
            "llm",
            enabled=True,
            implementation_id="openai-compatible",
            config={"profile_id": profile["id"]},
        )

        def mark_unavailable(profile_id):
            updated = self.application.storage.update_provider_profile_state(
                profile_id, status="unavailable"
            )
            return {"ok": False, "profile": updated, "error": "connection failed"}

        with patch.object(
            self.application.provider_profiles,
            "health",
            side_effect=mark_unavailable,
        ) as health, patch.object(self.application.agent, "provider_status") as provider_status:
            result = self.application.rpc("agent.provider.status", {})

        health.assert_called_once_with(profile["id"])
        self.assertEqual(result["state"], "unavailable")
        self.assertFalse(result["ready"])
        self.assertEqual(result["profile"]["status"], "unavailable")
        provider_status.assert_not_called()

    def test_enabling_llm_rechecks_a_stale_provider_profile(self):
        profile = self.application.provider_profiles.save(
            {
                "id": "stale-enable-provider",
                "name": "Stale enable provider",
                "template_id": "ollama",
                "processing_location": "local",
                "base_url": "http://127.0.0.1:11434/v1",
                "model": "qwen3:4b",
            }
        )
        self.application.storage.update_provider_profile_state(profile["id"], status="available")

        def mark_unavailable(profile_id):
            updated = self.application.storage.update_provider_profile_state(
                profile_id, status="unavailable"
            )
            return {"ok": False, "profile": updated, "error": "connection failed"}

        with patch.object(
            self.application.provider_profiles,
            "health",
            side_effect=mark_unavailable,
        ) as health:
            with self.assertRaises(JsonRpcError) as error:
                self.application.rpc(
                    "module.update",
                    {
                        "module_id": "llm",
                        "enabled": True,
                        "implementation_id": "openai-compatible",
                        "config": {"profile_id": profile["id"]},
                    },
                )

        health.assert_called_once_with(profile["id"])
        self.assertEqual(error.exception.code, -32602)
        self.assertFalse(self.application.storage.get_module_setting("llm")["enabled"])

    def test_module_listing_refreshes_active_provider_reachability(self):
        profile = self.application.provider_profiles.save(
            {
                "id": "stale-module-provider",
                "name": "Stale module provider",
                "template_id": "ollama",
                "processing_location": "local",
                "base_url": "http://127.0.0.1:11434/v1",
                "model": "qwen3:4b",
            }
        )
        self.application.storage.update_provider_profile_state(profile["id"], status="available")
        self.application.storage.upsert_module_setting(
            "llm",
            enabled=True,
            implementation_id="openai-compatible",
            config={"profile_id": profile["id"]},
        )

        def mark_unavailable(profile_id):
            updated = self.application.storage.update_provider_profile_state(
                profile_id, status="unavailable"
            )
            return {"ok": False, "profile": updated, "error": "connection failed"}

        with patch.object(
            self.application.provider_profiles,
            "health",
            side_effect=mark_unavailable,
        ) as health:
            modules = self.application.rpc("module.list", {})

        health.assert_called_once_with(profile["id"])
        llm = next(item for item in modules if item["id"] == "llm")
        self.assertEqual(llm["status"], "error")
        self.assertEqual(llm["profile"]["status"], "unavailable")

    def test_workspace_capable_agent_requires_a_registered_git_workspace_for_new_sessions(self):
        workspace_path = str(Path.cwd().resolve())
        roster = {
            "workspaces": [
                {
                    "id": "workspace-1",
                    "path": workspace_path,
                    "title": "Sumika",
                    "session_ids": [],
                }
            ]
        }

        with (
            patch.object(
                self.application.agent,
                "supports",
                side_effect=lambda capability: capability == AgentCapability.WORKSPACES,
            ),
            patch.object(self.application.agent, "status", return_value={"ready": True}),
            patch.object(self.application.agent, "list_workspaces", return_value=roster),
            patch.object(
                self.application.workspace,
                "inspect",
                return_value={"workspace": {"id": "git-workspace", "path": workspace_path}},
            ) as inspect,
            patch.object(
                self.application.agent,
                "create_session",
                return_value={"sessionId": "session-1"},
            ) as create,
        ):
            for params in ({}, {"cwd": workspace_path}, {"workspaceId": "missing"}):
                with self.subTest(params=params), self.assertRaises(JsonRpcError) as error:
                    self.application.rpc("agent.session.create", params)
                self.assertIn(error.exception.code, {-32602, -32033})

            result = self.application.rpc(
                "agent.session.create",
                {"workspaceId": "workspace-1", "characterId": "sumika"},
            )

        self.assertEqual(result["sessionId"], "session-1")
        create.assert_called_once_with(
            {"workspaceId": "workspace-1", "characterId": "sumika"}
        )
        inspect.assert_called_once_with(workspace_path)

    def test_execute_turn_creates_a_checkpoint_for_the_bound_workspace(self):
        workspace_path = str(Path.cwd().resolve())
        roster = {
            "workspaces": [
                {
                    "id": "workspace-1",
                    "path": workspace_path,
                    "title": "Sumika",
                    "session_ids": ["session-1"],
                }
            ]
        }
        checkpoint = {
            "id": "wschk-1234567890abcdef1234",
            "workspace_id": "git-workspace",
            "name": "Agent execute",
        }
        call_order = []

        def create_checkpoint(path, *, name):
            call_order.append(("checkpoint", path, name))
            return {"checkpoint": checkpoint}

        def prompt(params):
            call_order.append(("prompt", params["sessionId"], params["mode"]))
            return {"id": "turn-1", "accepted": True}

        with (
            patch.object(
                self.application.agent,
                "supports",
                side_effect=lambda capability: capability == AgentCapability.WORKSPACES,
            ),
            patch.object(self.application.agent, "status", return_value={"ready": True}),
            patch.object(self.application.agent, "list_workspaces", return_value=roster),
            patch.object(self.application.workspace, "create_checkpoint", side_effect=create_checkpoint),
            patch.object(self.application.agent, "prompt", side_effect=prompt),
        ):
            for params in (
                {"sessionId": "session-1", "mode": "execute", "text": "edit"},
                {
                    "sessionId": "session-1",
                    "workspaceId": "missing",
                    "mode": "execute",
                    "text": "edit",
                },
            ):
                with self.subTest(params=params), self.assertRaises(JsonRpcError):
                    self.application.rpc("agent.session.prompt", params)

            result = self.application.rpc(
                "agent.session.prompt",
                {
                    "sessionId": "session-1",
                    "workspaceId": "workspace-1",
                    "mode": "execute",
                    "text": "edit",
                },
            )

        self.assertEqual(result["workspace_checkpoint"], checkpoint)
        self.assertEqual(call_order[0][0], "checkpoint")
        self.assertEqual(call_order[1], ("prompt", "session-1", "execute"))
        self.assertIn("agent.turn.started", str(self.application.storage.list_events(5)))
        self.assertIn(checkpoint["id"], str(self.application.storage.list_events(5)))

    def test_plan_turn_requires_the_bound_workspace_without_creating_a_checkpoint(self):
        workspace_path = str(Path.cwd().resolve())
        roster = {
            "workspaces": [
                {
                    "id": "workspace-1",
                    "path": workspace_path,
                    "title": "Sumika",
                    "session_ids": ["session-1"],
                }
            ]
        }

        with (
            patch.object(
                self.application.agent,
                "supports",
                side_effect=lambda capability: capability == AgentCapability.WORKSPACES,
            ),
            patch.object(self.application.agent, "status", return_value={"ready": True}),
            patch.object(self.application.agent, "list_workspaces", return_value=roster),
            patch.object(self.application.workspace, "create_checkpoint") as create_checkpoint,
            patch.object(
                self.application.agent,
                "prompt",
                return_value={"id": "plan-1", "accepted": True},
            ) as prompt,
        ):
            with self.assertRaises(JsonRpcError):
                self.application.rpc(
                    "agent.session.prompt",
                    {"sessionId": "session-1", "mode": "plan", "text": "plan"},
                )

            result = self.application.rpc(
                "agent.session.prompt",
                {
                    "sessionId": "session-1",
                    "workspaceId": "workspace-1",
                    "mode": "plan",
                    "text": "plan",
                },
            )

        self.assertTrue(result["accepted"])
        self.assertNotIn("workspace_checkpoint", result)
        create_checkpoint.assert_not_called()
        prompt.assert_called_once_with(
            {
                "sessionId": "session-1",
                "workspaceId": "workspace-1",
                "mode": "plan",
                "text": "plan",
            }
        )
        events = str(self.application.storage.list_events(5))
        self.assertIn("agent.turn.started", events)
        self.assertIn("workspace-1", events)

    def test_workspace_registration_fails_before_runtime_mutation_when_git_check_fails(self):
        workspace_path = str(Path.cwd().resolve())
        with (
            patch.object(
                self.application.workspace,
                "inspect",
                side_effect=WorkspaceError("workspace is not a Git repository"),
            ),
            patch.object(self.application.agent, "create_workspace") as create,
        ):
            with self.assertRaises(JsonRpcError) as error:
                self.application.rpc("agent.workspace.create", {"path": workspace_path})

        self.assertEqual(error.exception.code, -32033)
        create.assert_not_called()


if __name__ == "__main__":
    unittest.main()
