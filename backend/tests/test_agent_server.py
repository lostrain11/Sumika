import unittest
from unittest.mock import patch

from sumika_core.agent import AgentRuntimeError
from sumika_core.protocol.jsonrpc import JsonRpcError
from sumika_core.server import CoreApplication


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
            enabled=False,
            implementation_id="openai-compatible",
            config={"profile_id": profile["id"]},
        )
        with patch.object(self.application.agent, "sync_provider_profile", return_value={"profile_id": profile["id"], "route_id": "sumika-local-test", "model": "qwen3:4b", "changed": True, "active": True}), patch.object(self.application.agent, "create_session", return_value={"sessionId": "dsh-session"}), patch.object(self.application.agent, "select_model", return_value={"selected": {"provider": "sumika-local-test", "model": "qwen3:4b"}}):
            result = self.application.rpc("agent.session.create", {"cwd": "."})
        self.assertEqual(result["provider"]["route_id"], "sumika-local-test")
        self.assertEqual(result["selected_model"]["model"], "qwen3:4b")
        self.assertNotIn("secrets", result["provider"])


if __name__ == "__main__":
    unittest.main()
