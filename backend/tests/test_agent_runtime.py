import json
import base64
from io import BytesIO
import socket
import threading
import unittest
from tempfile import TemporaryDirectory
from pathlib import Path
from unittest.mock import patch

from sumika_core.agent.models import DSH_COMMIT, DSH_VERSION
from sumika_core.agent.runtime import (
    DSHAgentRuntime,
    UnavailableAgentRuntime,
    _compact_session_history,
    _dsh_route_id,
    _read_ws_messages,
)


class AgentRuntimeTests(unittest.TestCase):
    def test_unavailable_runtime_fails_closed(self):
        runtime = UnavailableAgentRuntime()
        self.assertFalse(runtime.status()["ready"])
        self.assertEqual(runtime.mcp_inventory()["status"], "unavailable")
        with self.assertRaisesRegex(RuntimeError, "not connected"):
            runtime.prompt({"text": "hello"})

    def test_managed_dsh_config_is_pinned_and_uses_isolated_profile(self):
        runtime = DSHAgentRuntime(":memory:", env={"SUMIKA_DSH_ENDPOINT": "http://127.0.0.1:1"})
        status = runtime.status()
        self.assertEqual(status["version"], DSH_VERSION)
        self.assertEqual(status["commit"], DSH_COMMIT)
        self.assertTrue(status["global_install_untouched"])
        self.assertTrue(status["profile_dir"].endswith("dsh-profile"))

    def test_diagnostics_distinguishes_missing_mcp_rpc_from_transport_failure(self):
        runtime = DSHAgentRuntime(":memory:", env={"SUMIKA_DSH_ENDPOINT": "http://127.0.0.1:1"})
        calls = []

        def probe(method, payload):
            calls.append((method, payload))
            if method == "host.describe":
                return {
                    "version": "0.0.1",
                    "attachedSessions": 1,
                    "provider": "sumika-local",
                    "model": "model-a",
                    "cwd": "D:\\private",
                    "home": "C:\\Users\\private",
                }
            if method == "session.list":
                return {"items": [{"sessionId": "session-1"}]}
            if method == "mcp.list":
                from sumika_core.agent.runtime import AgentRuntimeError

                raise AgentRuntimeError("not found", http_status=404)
            return {"value": []}

        runtime._call = probe
        report = runtime.diagnostics()
        self.assertTrue(report["runtime"]["ready"])
        self.assertEqual(report["mcp"]["status"], "not-exposed")
        self.assertFalse(report["mcp"]["available"])
        self.assertIn("未注册", report["mcp"]["reason"])
        self.assertNotIn("D:\\private", str(report))
        self.assertNotIn("C:\\Users\\private", str(report))
        self.assertIn(("skill.list", {"sessionId": "session-1"}), calls)
        self.assertIn(("commands/list", {"args": {"agentId": "session-1"}}), calls)

    def test_diagnostics_detects_mcp_client_only_from_managed_profile_manifest(self):
        with TemporaryDirectory() as directory:
            profile = Path(directory) / "profiles" / "web"
            profile.mkdir(parents=True)
            (profile / "package.json").write_text(
                json.dumps({"dependencies": {"@deepseek-ai/dsh-mcp-client": "0.1.1"}}),
                encoding="utf-8",
            )
            runtime = DSHAgentRuntime(
                ":memory:",
                env={
                    "SUMIKA_DSH_ENABLED": "0",
                    "SUMIKA_DSH_PROFILE_DIR": directory,
                },
            )
            report = runtime.diagnostics()
        self.assertTrue(report["mcp"]["client_installed"])
        self.assertEqual(report["mcp"]["client_version"], "0.1.1")

    def test_diagnostics_detects_mcp_client_from_managed_profile_node_modules(self):
        with TemporaryDirectory() as directory:
            package = Path(directory) / "profiles" / "node_modules" / "@deepseek-ai" / "dsh-mcp-client"
            package.mkdir(parents=True)
            (package / "package.json").write_text(
                json.dumps({"name": "@deepseek-ai/dsh-mcp-client", "version": "0.1.1-rc.2"}),
                encoding="utf-8",
            )
            runtime = DSHAgentRuntime(
                ":memory:",
                env={"SUMIKA_DSH_ENABLED": "0", "SUMIKA_DSH_PROFILE_DIR": directory},
            )
            report = runtime.diagnostics()
        self.assertTrue(report["mcp"]["client_installed"])
        self.assertEqual(report["mcp"]["client_version"], "0.1.1-rc.2")

    def test_event_normalization_preserves_extension_fields(self):
        runtime = DSHAgentRuntime(":memory:", env={"SUMIKA_DSH_ENABLED": "0"})
        event = runtime.normalize_event({"type": "session/event", "sessionId": "s1", "turnId": "t1", "custom": {"value": 3}})
        self.assertEqual(event["event_type"], "session/event")
        self.assertEqual(event["session_id"], "s1")
        self.assertEqual(event["extensions"]["custom"], {"value": 3})

    def test_queue_snapshot_hides_context_and_message_secrets(self):
        runtime = DSHAgentRuntime(":memory:", env={"SUMIKA_DSH_ENABLED": "0"})
        runtime.normalize_event(
            {
                "type": "session/queue",
                "sessionId": "s1",
                "items": [
                    {
                        "id": "queued-1",
                        "placement": "queued",
                        "message": {"content": [{"type": "text", "text": "run tests"}]},
                    },
                    {
                        "id": "context-1",
                        "placement": "context",
                        "message": {"content": [{"type": "text", "text": "private context"}]},
                    },
                    {
                        "id": "queued-2",
                        "placement": "queued",
                        "message": {"content": [{"type": "text", "text": "api_key=sk-1234567890"}]},
                    },
                ],
            }
        )
        result = runtime.queue({"session_id": "s1"})
        self.assertTrue(result["known"])
        self.assertEqual(result["hidden_context_count"], 1)
        self.assertEqual([item["id"] for item in result["items"]], ["queued-1", "queued-2"])
        self.assertNotIn("private context", str(result))
        self.assertNotIn("sk-1234567890", str(result))

    def test_queue_update_uses_typed_dsh_action_without_returning_text(self):
        runtime = DSHAgentRuntime(":memory:", env={"SUMIKA_DSH_ENDPOINT": "http://127.0.0.1:1"})
        calls = []
        runtime._call = lambda method, payload: calls.append((method, payload)) or {"accepted": True}
        result = runtime.update_queue({"session_id": "s1", "item_id": "item-1", "kind": "edit", "text": "new prompt"})
        self.assertEqual(result, {"accepted": True, "session_id": "s1", "item_id": "item-1", "action": "edit"})
        self.assertEqual(calls[0][0], "session.updateQueue")
        self.assertEqual(calls[0][1]["action"], {"kind": "edit", "content": [{"type": "text", "text": "new prompt"}]})
        self.assertNotIn("new prompt", str(result))

    def test_tool_event_view_is_whitelisted_and_raw_arguments_are_dropped(self):
        runtime = DSHAgentRuntime(":memory:", env={"SUMIKA_DSH_ENABLED": "0"})
        event = runtime.normalize_event(
            {
                "type": "session/event",
                "sessionId": "s1",
                "event": {
                    "type": "tool/call",
                    "data": {"name": "read", "callId": "call-1", "arguments": "secret raw args"},
                },
                "view": {
                    "for": "call",
                    "view": {
                        "card": "generic",
                        "title": "Read file",
                        "kind": "read",
                        "rawInput": {"path": "D:\\Code\\Sumika\\README.md"},
                        "locations": [{"path": "README.md", "line": 4}],
                    },
                },
            }
        )
        serialized = str(event)
        self.assertIn("Read file", serialized)
        self.assertIn("README.md", serialized)
        self.assertNotIn("secret raw args", serialized)
        self.assertNotIn("rawInput", serialized)

    def test_compact_history_merges_tool_call_and_result_presentation(self):
        history = {
            "events": [
                {
                    "seq": 1,
                    "event": {
                        "type": "tool/call",
                        "data": {"name": "bash", "callId": "call-1"},
                    },
                    "view": {"for": "call", "view": {"card": "terminal", "title": "pytest", "cwd": "D:\\Code\\Sumika"}},
                },
                {
                    "seq": 2,
                    "event": {
                        "type": "tool/result",
                        "data": {"callId": "call-1"},
                    },
                    "view": {"for": "result", "view": {"card": "terminal", "output": "ok", "exitCode": 0}},
                },
            ]
        }
        result = _compact_session_history("s1", history)
        self.assertEqual(len(result["tools"]), 1)
        self.assertEqual(result["tools"][0]["status"], "completed")
        self.assertEqual(result["tools"][0]["call"]["card"], "terminal")
        self.assertEqual(result["tools"][0]["result"]["exit_code"], 0)
        self.assertEqual(result["tools"][0]["result"]["output"], "ok")

    def test_compact_history_projects_diff_view_without_raw_patch(self):
        history = {
            "events": [
                {
                    "event": {"type": "tool/call", "seq": 1, "data": {"name": "edit", "callId": "diff-1"}},
                    "view": {"for": "call", "view": {"card": "diff", "title": "修改文件", "diffs": [{"path": "src/app.py", "patch": "private patch"}]}},
                },
                {
                    "event": {"type": "tool/result", "seq": 2, "data": {"callId": "diff-1", "isError": False}},
                    "view": {"for": "result", "view": {"card": "diff", "diffs": [{"path": "src/app.py", "patch": "private patch"}]}},
                },
            ]
        }
        result = _compact_session_history("s1", history)
        self.assertEqual(len(result["artifacts"]), 1)
        self.assertEqual(result["artifacts"][0]["status"], "completed")
        self.assertEqual(result["artifacts"][0]["file_count"], 1)
        self.assertEqual(result["artifacts"][0]["locations"], [{"path": "src/app.py"}])
        self.assertNotIn("private patch", str(result))

    def test_session_export_uses_dsh_streaming_download_endpoint(self):
        runtime = DSHAgentRuntime(":memory:", env={"SUMIKA_DSH_ENDPOINT": "http://127.0.0.1:3080"})

        class ExportResponse(BytesIO):
            headers = {"Content-Type": "application/zip", "Content-Length": "4"}

        response = ExportResponse(b"PK00")
        with patch("urllib.request.urlopen", return_value=response) as urlopen:
            export = runtime.open_session_export({"session_id": "session-1", "include_descendants": True})
        request = urlopen.call_args.args[0]
        self.assertEqual(
            request.full_url,
            "http://127.0.0.1:3080/api/session.export?sessionId=session-1&includeDescendants=true",
        )
        self.assertEqual(request.get_method(), "GET")
        self.assertEqual(export["content_type"], "application/zip")
        self.assertEqual(export["content_length"], 4)
        self.assertEqual(export["stream"].read(), b"PK00")

        with self.assertRaisesRegex(RuntimeError, "must be a boolean"):
            runtime.open_session_export({"session_id": "session-1", "include_descendants": "true"})

    def test_question_interaction_is_projected_and_answered_with_dsh_shape(self):
        runtime = DSHAgentRuntime(":memory:", env={"SUMIKA_DSH_ENDPOINT": "http://127.0.0.1:1"})
        calls = []

        def capture(path, body):
            calls.append((path, body))
            return {"ok": True, "value": {"accepted": True}}

        runtime._post = capture
        runtime.normalize_event(
            {
                "type": "question/requested",
                "rpcId": "question-1",
                "sessionId": "session-1",
                "questions": [
                    {
                        "id": "choice",
                        "question": "选择执行方式",
                        "options": [{"label": "现在执行"}, {"label": "稍后执行"}],
                    },
                    {"id": "note", "question": "补充说明"},
                ],
            }
        )
        pending = runtime.interactions({"session_id": "session-1"})["interactions"]
        self.assertEqual(pending[0]["kind"], "question")
        result = runtime.respond_interaction(
            {
                "rpcId": "question-1",
                "sessionId": "session-1",
                "answer": {"answers": [
                    {"id": "choice", "selected": ["现在执行"]},
                    {"id": "note", "selected": [], "custom": "无"},
                ]},
            }
        )
        self.assertTrue(result["accepted"])
        self.assertEqual(calls[0][0], "/api/respond")
        self.assertEqual(calls[0][1]["result"]["value"]["answer"]["answers"][0]["id"], "choice")
        self.assertEqual(runtime.interactions()["interactions"], [])

    def test_question_interaction_rejects_unknown_option_without_sending(self):
        runtime = DSHAgentRuntime(":memory:", env={"SUMIKA_DSH_ENDPOINT": "http://127.0.0.1:1"})
        calls = []
        runtime._post = lambda path, body: calls.append((path, body)) or {"ok": True, "value": {"accepted": True}}
        runtime.normalize_event({"type": "question/requested", "rpcId": "q", "sessionId": "s", "questions": [{"id": "x", "question": "x", "options": [{"label": "yes"}]}]})
        with self.assertRaisesRegex(RuntimeError, "invalid question response"):
            runtime.respond_interaction({"rpcId": "q", "sessionId": "s", "answer": {"answers": [{"id": "x", "selected": ["no"]}]}})
        self.assertEqual(calls, [])

    def test_approval_interaction_is_removed_by_resolved_event(self):
        runtime = DSHAgentRuntime(":memory:", env={"SUMIKA_DSH_ENABLED": "0"})
        runtime.normalize_event({"type": "approval/requested", "rpcId": "rpc", "sessionId": "s", "approvalId": "a", "toolName": "write"})
        self.assertEqual(len(runtime.interactions()["interactions"]), 1)
        runtime.normalize_event({"type": "approval/resolved", "sessionId": "s", "approvalId": "a", "outcome": "rejected"})
        self.assertEqual(runtime.interactions()["interactions"], [])

    def test_requests_use_pinned_dsh_wire_shapes(self):
        runtime = DSHAgentRuntime(":memory:", env={"SUMIKA_DSH_ENDPOINT": "http://127.0.0.1:1"})
        calls = []

        def capture(path, body):
            calls.append((path, body))
            if path == "/api/session.create":
                return {"type": "server-response", "rpcId": "x", "result": {"ok": True, "value": {"sessionId": "s1"}}}
            if path == "/api/commands/execute":
                return {
                    "type": "server-response",
                    "rpcId": "x",
                    "result": {
                        "ok": True,
                        "value": {"commandId": "cmd-1", "result": {"kind": "success"}},
                    },
                }
            return {"type": "server-response", "rpcId": "x", "result": {"ok": True, "value": {"accepted": True}}}

        runtime._post = capture
        self.assertEqual(runtime.create_session({"cwd": ".", "character_id": "sumika"})["sessionId"], "s1")
        runtime.prompt({"session_id": "s1", "text": "inspect files", "mode": "plan"})
        runtime.respond({"rpc_id": "request-1", "result": {"ok": True, "value": {"approved": True}}})
        self.assertEqual(calls[0][0], "/api/session.create")
        self.assertEqual(calls[0][1]["payload"], {"cwd": "."})
        self.assertEqual(calls[1], ("/api/commands/execute", {
            "type": "client-request",
            "rpcId": calls[1][1]["rpcId"],
            "method": "commands/execute",
            "payload": {"args": {"agentId": "s1", "line": "/plan inspect files", "images": []}},
        }))
        self.assertEqual(calls[2], ("/api/respond", {
            "type": "client-response",
            "rpcId": "request-1",
            "result": {"ok": True, "value": {"approved": True}},
        }))

    def test_capability_requests_are_session_scoped(self):
        runtime = DSHAgentRuntime(":memory:", env={"SUMIKA_DSH_ENDPOINT": "http://127.0.0.1:1"})
        calls = []
        runtime._post = lambda path, body: calls.append((path, body)) or {"ok": False, "error": "not mounted"}
        values = runtime.list_capabilities({"session_id": "s1"})
        self.assertFalse(values["skills"]["available"])
        self.assertEqual(calls[0][1]["payload"], {"sessionId": "s1"})
        self.assertEqual(calls[1][1]["payload"], {"parentSessionId": "s1"})
        self.assertFalse(values["mcp"]["available"])
        self.assertFalse(values["commands"]["available"])
        self.assertEqual(calls[2][1]["payload"], {"args": {"agentId": "s1"}})

    def test_mcp_inventory_groups_only_public_tools_observed_in_session_history(self):
        runtime = DSHAgentRuntime(":memory:", env={"SUMIKA_DSH_ENDPOINT": "http://127.0.0.1:1"})
        calls = []
        runtime._mcp_profile_info = lambda: {"installed": True, "version": "0.1.1-rc.2"}
        runtime.history = lambda params: calls.append(params) or {
            "events": [
                {"event": {"type": "tool/call", "seq": 1, "data": {"name": "mcp__github__search", "callId": "a", "arguments": "secret"}}},
                {"event": {"type": "tool/result", "seq": 2, "data": {"name": "mcp__github__search", "callId": "a", "result": "private"}}},
                {"event": {"type": "tool/call", "seq": 3, "data": {"name": "mcp__files__read", "callId": "b"}}},
                {"event": {"type": "tool/call", "seq": 4, "data": {"name": "bash", "callId": "c"}}},
            ]
        }

        result = runtime.mcp_inventory({"sessionId": "session-1"})

        self.assertEqual(calls, [{"session_id": "session-1", "maxMessages": 32}])
        self.assertTrue(result["available"])
        self.assertFalse(result["catalog_available"])
        self.assertEqual(result["status"], "observed")
        self.assertEqual(result["server_count"], 2)
        self.assertEqual(result["tool_count"], 2)
        self.assertEqual([entry["name"] for entry in result["entries"]], ["files", "github"])
        self.assertEqual(result["entries"][1]["tools"][0]["status"], "completed")
        self.assertNotIn("secret", str(result))
        self.assertNotIn("private", str(result))

    def test_mcp_inventory_without_session_reports_package_without_claiming_a_catalog(self):
        runtime = DSHAgentRuntime(":memory:", env={"SUMIKA_DSH_ENDPOINT": "http://127.0.0.1:1"})
        runtime._mcp_profile_info = lambda: {"installed": True, "version": "0.1.1-rc.2"}

        result = runtime.mcp_inventory({})

        self.assertFalse(result["available"])
        self.assertFalse(result["catalog_available"])
        self.assertTrue(result["client_installed"])
        self.assertEqual(result["client_version"], "0.1.1-rc.2")
        self.assertEqual(result["entries"], [])

    def test_execute_mode_never_sends_plan_exit_as_a_user_prompt(self):
        runtime = DSHAgentRuntime(":memory:", env={"SUMIKA_DSH_ENDPOINT": "http://127.0.0.1:1"})
        calls = []

        def capture(method, payload):
            calls.append((method, payload))
            if method == "commands/execute":
                raise RuntimeError("commands endpoint is not mounted")
            raise AssertionError(f"unexpected model request: {method}")

        runtime._call = capture
        with self.assertRaisesRegex(RuntimeError, "commands endpoint is not mounted"):
            runtime.prompt({"session_id": "s1", "text": "run the task", "mode": "execute"})
        self.assertEqual([method for method, _ in calls], ["commands/execute"])

    def test_command_error_is_reported_without_queueing_the_user_prompt(self):
        runtime = DSHAgentRuntime(":memory:", env={"SUMIKA_DSH_ENDPOINT": "http://127.0.0.1:1"})
        calls = []

        def capture(method, payload):
            calls.append((method, payload))
            if method == "commands/execute":
                return {"commandId": "cmd-1", "result": {"kind": "error", "text": "plan command rejected"}}
            raise AssertionError(f"unexpected model request: {method}")

        runtime._call = capture
        with self.assertRaisesRegex(RuntimeError, "plan command rejected"):
            runtime.prompt({"session_id": "s1", "text": "inspect files", "mode": "plan"})
        self.assertEqual([method for method, _ in calls], ["commands/execute"])

    def test_session_snapshot_drops_streaming_chunks_and_runtime_context(self):
        history = {
            "events": [
                {"event": {"type": "user/message", "seq": 1, "data": {"role": "user", "content": [{"type": "text", "text": "检查项目"}], "source": {"kind": "user"}}}},
                {"event": {"type": "user/message", "seq": 2, "data": {"role": "user", "content": [{"type": "text", "text": "D:\\secret\\workspace"}], "source": {"kind": "plugin"}}}},
                {"event": {"type": "assistant/chunk", "seq": 3, "data": {"chunk": {"type": "text-delta", "text": "很多片段"}}}},
                {"event": {"type": "assistant/message", "seq": 4, "data": {"turn": 1, "message": {"role": "assistant", "content": [{"type": "reasoning", "text": "hidden"}, {"type": "text", "text": "已完成，api_key=sk-1234567890"}]}}}},
                {"event": {"type": "tool/call", "seq": 5, "data": {"name": "read", "callId": "call-1", "arguments": "raw secret arguments"}}},
                {"event": {"type": "approval/requested", "seq": 6, "data": {"approvalId": "approval-1", "action": "write"}}},
                {"event": {"type": "turn/end", "seq": 7, "data": {"turn": 1, "reason": {"kind": "completed"}}}},
            ],
            "projections": {
                "values": {
                    "title": "检查项目",
                    "plan": {"active": False, "pending": False, "steps": [{"id": "1", "title": "读取文件", "status": "done"}]},
                    "sessionStats": {"turns": 1, "steps": 1, "outputTokens": 12},
                }
            },
        }
        snapshot = _compact_session_history("session-1", history)
        self.assertEqual(snapshot["state"], "completed")
        self.assertEqual([item["role"] for item in snapshot["messages"]], ["user", "assistant"])
        self.assertNotIn("hidden", str(snapshot))
        self.assertNotIn("raw secret arguments", str(snapshot))
        self.assertNotIn("sk-1234567890", str(snapshot))
        self.assertEqual(snapshot["tools"][0]["name"], "read")
        self.assertEqual(snapshot["approvals"][0]["status"], "pending")
        self.assertEqual(snapshot["stats"], {"turns": 1, "steps": 1, "outputTokens": 12})

    def test_session_snapshot_exposes_only_durable_image_references(self):
        history = {
            "events": [{
                "event": {
                    "type": "user/message",
                    "seq": 1,
                    "data": {
                        "role": "user",
                        "content": [{
                            "type": "image",
                            "attachment": {
                                "attachmentId": "att-1",
                                "mediaType": "image/png",
                                "bytes": 128,
                                "width": 16,
                                "height": 16,
                                "name": "capture.png",
                                "path": "D:\\private\\capture.png",
                            },
                        }],
                        "source": {"kind": "user"},
                    },
                }
            }],
        }
        snapshot = _compact_session_history("s1", history)
        self.assertEqual(snapshot["messages"][0]["content"], "")
        self.assertEqual(snapshot["messages"][0]["attachments"][0]["attachment_id"], "att-1")
        self.assertNotIn("path", str(snapshot))

    def test_session_snapshot_calls_history_with_bounded_request(self):
        runtime = DSHAgentRuntime(":memory:", env={"SUMIKA_DSH_ENDPOINT": "http://127.0.0.1:1"})
        calls = []
        runtime._call = lambda method, payload: calls.append((method, payload)) or {
            "items": [{"sessionId": "s1", "running": False, "projections": {"asOfSeq": 3, "values": {}}}]
        }
        runtime.history = lambda params: calls.append(params) or {"events": [], "projections": {"values": {}}}
        result = runtime.snapshot({"session_id": "s1", "maxMessages": 12})
        self.assertEqual(calls, [("session.list", {}), {"session_id": "s1", "maxMessages": 8}])
        self.assertEqual(result["session_id"], "s1")

    def test_parent_session_id_is_accepted_and_mcp_is_explicitly_unavailable(self):
        runtime = DSHAgentRuntime(":memory:", env={"SUMIKA_DSH_ENDPOINT": "http://127.0.0.1:1"})
        calls = []
        runtime._post = lambda path, body: calls.append((path, body)) or {"ok": False, "error": "not mounted"}
        values = runtime.list_capabilities({"parentSessionId": "parent-1"})
        subagent_call = next(body for path, body in calls if body["method"] == "subagent.list")
        self.assertIn("parentSessionId", subagent_call["payload"])
        self.assertFalse(values["mcp"]["available"])
        self.assertIn("tool catalog", values["mcp"]["error"])

    def test_sumika_provider_is_synced_as_an_isolated_dsh_route(self):
        runtime = DSHAgentRuntime(":memory:", env={"SUMIKA_DSH_ENDPOINT": "http://127.0.0.1:1"})
        calls = []
        route_id = _dsh_route_id("local-ollama")

        def capture(path, body):
            calls.append((path, body))
            method = body["method"]
            if method == "settings.describe":
                return {"ok": True, "value": {"namespaces": [{"ns": "llm-pi-ai", "value": {"providers": {}}, "revision": 0}]}}
            if method == "settings.mutate":
                return {"ok": True, "value": {}}
            if method == "credentials.set":
                return {"ok": True, "value": {}}
            if method == "llm.providers":
                return {"ok": True, "value": {"providers": [{"provider": route_id, "active": True}]}}
            raise AssertionError(method)

        runtime._post = capture
        result = runtime.sync_provider_profile(
            {
                "id": "local-ollama",
                "name": "本地 Ollama",
                "config": {
                    "active_base_url": "http://127.0.0.1:11434/v1",
                    "model": "qwen3:4b",
                    "headers": {},
                },
                "secrets": {},
            }
        )
        self.assertEqual(result["route_id"], route_id)
        self.assertTrue(result["active"])
        self.assertNotIn("secrets", result)
        mutate = next(body for path, body in calls if path == "/api/settings.mutate")
        route = mutate["payload"]["ops"][0]["value"]
        self.assertEqual(route["baseURL"], "http://127.0.0.1:11434/v1")
        self.assertEqual(route["models"][0]["id"], "qwen3:4b")
        # DSH's OpenAI-compatible adapter requires a credential reference even
        # for a local unauthenticated server; the value itself stays in DSH's
        # credential store and never appears in the bridge result.
        self.assertTrue(route["apiKeyEnv"].startswith("SUMIKA_"))
        credential = next(body for path, body in calls if path == "/api/credentials.set")
        self.assertEqual(credential["payload"]["value"], "sumika-local")
        self.assertEqual(result["credential_mode"], "local-placeholder")
        self.assertNotIn("secret_value", result)

    def test_provider_api_key_uses_dsh_credentials_without_returning_secret(self):
        runtime = DSHAgentRuntime(":memory:", env={"SUMIKA_DSH_ENDPOINT": "http://127.0.0.1:1"})
        calls = []
        route_id = _dsh_route_id("remote")

        def capture(path, body):
            calls.append((path, body))
            method = body["method"]
            if method == "settings.describe":
                return {"ok": True, "value": {"namespaces": [{"ns": "llm-pi-ai", "value": {"providers": {}}, "revision": 3}]}}
            if method == "settings.mutate":
                return {"ok": True, "value": {}}
            if method == "credentials.set":
                return {"ok": True, "value": {}}
            if method == "llm.providers":
                return {"ok": True, "value": {"providers": [{"provider": route_id, "active": True}]}}
            raise AssertionError(method)

        runtime._post = capture
        result = runtime.sync_provider_profile(
            {
                "id": "remote",
                "name": "Remote",
                "config": {"active_base_url": "https://example.test/v1", "model": "demo", "headers": {}},
                "secrets": {"api_key": "secret-value"},
            }
        )
        self.assertTrue(result["credential_configured"])
        self.assertNotIn("secret-value", str(result))
        credential = next(body for path, body in calls if path == "/api/credentials.set")
        self.assertEqual(credential["payload"]["value"], "secret-value")
        self.assertNotIn("secret-value", str(result))

    def test_session_model_selection_uses_dsh_session_select_model(self):
        runtime = DSHAgentRuntime(":memory:", env={"SUMIKA_DSH_ENDPOINT": "http://127.0.0.1:1"})
        calls = []
        runtime._post = lambda path, body: calls.append((path, body)) or {"ok": True, "value": {"selected": {"provider": "sumika-local", "model": "qwen3:4b"}}}
        result = runtime.select_model({"session_id": "s1", "provider": "sumika-local", "model": "qwen3:4b"})
        self.assertEqual(result["selected"]["model"], "qwen3:4b")
        self.assertEqual(calls[0][0], "/api/session.selectModel")
        self.assertEqual(calls[0][1]["payload"], {"sessionId": "s1", "provider": "sumika-local", "model": "qwen3:4b"})

    def test_session_models_are_compact_and_redact_sensitive_text(self):
        runtime = DSHAgentRuntime(":memory:", env={"SUMIKA_DSH_ENDPOINT": "http://127.0.0.1:1"})
        calls = []
        runtime._call = lambda method, payload: calls.append((method, payload)) or {
            "current": {"provider": "sumika-local", "model": "qwen3:4b", "reasoningEffort": "medium"},
            "routable": True,
            "groups": [
                {
                    "id": "sumika-local",
                    "name": "Local",
                    "models": [
                        {
                            "id": "qwen3:4b",
                            "name": "Qwen 3 4B",
                            "description": "api_key=sk-1234567890",
                            "reasoning": {
                                "efforts": [{"id": "medium", "name": "Medium"}],
                                "defaultEffort": "medium",
                            },
                            "internal": {"credentials": "must not pass"},
                        }
                    ],
                }
            ],
            "failures": [{"id": "offline", "name": "Offline", "message": "Bearer abcdefghijklmnop"}],
        }
        result = runtime.session_models({"session_id": "s1"})
        self.assertEqual(calls, [("session.models", {"sessionId": "s1"})])
        self.assertTrue(result["routable"])
        self.assertEqual(result["current"]["reasoning_effort"], "medium")
        self.assertEqual(result["groups"][0]["models"][0]["reasoning"]["default_effort"], "medium")
        self.assertNotIn("credentials", str(result))
        self.assertNotIn("sk-1234567890", str(result))
        self.assertNotIn("abcdefghijklmnop", str(result))

    def test_session_fork_uses_completed_turn_boundary_contract(self):
        runtime = DSHAgentRuntime(":memory:", env={"SUMIKA_DSH_ENDPOINT": "http://127.0.0.1:1"})
        calls = []
        runtime._call = lambda method, payload: calls.append((method, payload)) or {"sessionId": "child-1"}
        result = runtime.fork_session({"session_id": "parent-1", "at_seq": 42})
        self.assertEqual(result, {"sessionId": "child-1"})
        self.assertEqual(calls, [("session.fork", {"sessionId": "parent-1", "atSeq": 42})])
        with self.assertRaisesRegex(RuntimeError, "non-negative integer"):
            runtime.fork_session({"session_id": "parent-1", "at_seq": -1})

    def test_agent_preset_roster_is_compacted_and_selection_is_blank_session_scoped(self):
        runtime = DSHAgentRuntime(":memory:", env={"SUMIKA_DSH_ENDPOINT": "http://127.0.0.1:1"})
        calls = []

        def capture(method, payload):
            calls.append((method, payload))
            if method == "agentPreset.list":
                return {
                    "presets": [
                        {"id": "standard", "trust": "system", "isDefault": True, "name": "标准", "description": "可用", "path": "D:\\private"},
                        {"id": "broken", "trust": "user", "isDefault": False, "broken": "缺少插件", "composition": "secret"},
                        {"id": "D:\\private\\preset", "trust": "user"},
                    ],
                    "authorable": True,
                    "hasDocument": True,
                }
            if method == "agentPreset.select":
                return {"agentPreset": "standard"}
            raise AssertionError(method)

        runtime._call = capture
        roster = runtime.list_presets()
        self.assertEqual(roster["presets"][0]["id"], "standard")
        self.assertTrue(roster["authorable"])
        self.assertNotIn("path", str(roster))
        self.assertNotIn("composition", str(roster))
        self.assertNotIn("private", str(roster))
        selected = runtime.select_preset({"session_id": "blank-1", "agent_preset": "standard"})
        self.assertEqual(selected, {"session_id": "blank-1", "agent_preset": "standard"})
        self.assertEqual(calls[-1], ("agentPreset.select", {"sessionId": "blank-1", "agentPreset": "standard"}))

    def test_agent_preset_copy_and_open_are_slug_bounded_and_path_free(self):
        runtime = DSHAgentRuntime(":memory:", env={"SUMIKA_DSH_ENDPOINT": "http://127.0.0.1:1"})
        calls = []

        def capture(method, payload):
            calls.append((method, payload))
            if method == "agentPreset.copy":
                return {"agentPreset": "sumika-work"}
            if method == "agentPreset.openDocument":
                return {"opened": False, "path": "D:\\private\\agent-presets\\sumika-work"}
            raise AssertionError(method)

        runtime._call = capture
        copied = runtime.copy_preset(
            {"from": "standard", "agentPreset": "sumika-work", "name": "Sumika 工作"}
        )
        self.assertEqual(copied, {"agent_preset": "sumika-work", "source": "standard"})
        self.assertEqual(
            calls[0],
            (
                "agentPreset.copy",
                {"from": "standard", "agentPreset": "sumika-work", "name": "Sumika 工作"},
            ),
        )
        opened = runtime.open_preset_document({"agentPreset": "sumika-work"})
        self.assertEqual(opened, {"agent_preset": "sumika-work", "opened": False})
        self.assertNotIn("private", str(opened))
        self.assertEqual(calls[1], ("agentPreset.openDocument", {"agentPreset": "sumika-work"}))
        for params in (
            {"from": "..\\secret", "agentPreset": "sumika-work"},
            {"from": "standard", "agentPreset": "D:\\secret"},
            {"from": "standard", "agentPreset": "standard"},
            {"from": "standard", "agentPreset": "sumika-work", "name": "D:\\secret"},
        ):
            with self.assertRaisesRegex(RuntimeError, "preset|path"):
                runtime.copy_preset(params)

    def test_subagent_operations_keep_exact_parent_child_address_and_text_boundary(self):
        runtime = DSHAgentRuntime(":memory:", env={"SUMIKA_DSH_ENDPOINT": "http://127.0.0.1:1"})
        calls = []

        def capture(method, payload):
            calls.append((method, payload))
            if method == "subagent.list":
                return {"entries": [{"kind": "child", "id": "child-1", "mode": "continuable", "label": "检查", "activity": "running", "hasChildren": True}], "parentAvailable": True}
            if method == "subagent.history":
                return {"events": [{"event": {"type": "assistant/message", "seq": 1, "data": {"role": "assistant", "content": [{"type": "text", "text": "完成"}]}}}], "hasMore": False}
            if method == "subagent.prompt":
                return {"messageId": "message-1"}
            if method == "subagent.interrupt":
                return {"accepted": True}
            raise AssertionError(method)

        runtime._call = capture
        catalog = runtime.list_subagents({"parentSessionId": "parent-1"})
        self.assertTrue(catalog["parent_available"])
        self.assertEqual(catalog["entries"][0]["mode"], "continuable")
        history = runtime.subagent_history({"parentSessionId": "parent-1", "childSessionId": "child-1", "mode": "continuable"})
        self.assertEqual(history["messages"][0]["content"], "完成")
        receipt = runtime.prompt_subagent({"parentSessionId": "parent-1", "childSessionId": "child-1", "mode": "continuable", "text": "继续检查"})
        self.assertEqual(receipt["message_id"], "message-1")
        interrupted = runtime.interrupt_subagent({"parentSessionId": "parent-1", "childSessionId": "child-1", "mode": "continuable"})
        self.assertTrue(interrupted["accepted"])
        prompt_call = next(payload for method, payload in calls if method == "subagent.prompt")
        self.assertEqual(prompt_call, {"parentSessionId": "parent-1", "childSessionId": "child-1", "mode": "continuable", "content": [{"type": "text", "text": "继续检查"}]})
        with self.assertRaisesRegex(RuntimeError, "continuable"):
            runtime.prompt_subagent({"parentSessionId": "parent-1", "childSessionId": "child-1", "mode": "one-shot", "text": "不应发送"})

    def test_goal_mutations_use_compare_and_set_refs_and_never_accept_invalid_rounds(self):
        runtime = DSHAgentRuntime(":memory:", env={"SUMIKA_DSH_ENDPOINT": "http://127.0.0.1:1"})
        calls = []

        def capture(method, payload):
            calls.append((method, payload))
            if method == "goal.create":
                return {"ref": {"id": "goal-1", "revision": 0}}
            if method == "goal.pause":
                return {"ref": {"id": "goal-1", "revision": 1}}
            if method == "goal.clear":
                return {"cleared": True}
            raise AssertionError(method)

        runtime._call = capture
        created = runtime.goal_action("create", {"session_id": "s1", "objective": "完成测试", "max_goal_rounds": 4})
        self.assertEqual(created["ref"], {"id": "goal-1", "revision": 0})
        paused = runtime.goal_action("pause", {"session_id": "s1", "ref": {"id": "goal-1", "revision": 0}})
        self.assertEqual(paused["ref"]["revision"], 1)
        cleared = runtime.goal_action("clear", {"session_id": "s1", "ref": {"id": "goal-1", "revision": 1}})
        self.assertTrue(cleared["cleared"])
        self.assertEqual(calls[0], ("goal.create", {"sessionId": "s1", "objective": "完成测试", "maxGoalRounds": 4}))
        self.assertEqual(calls[1], ("goal.pause", {"sessionId": "s1", "ref": {"id": "goal-1", "revision": 0}}))
        with self.assertRaisesRegex(RuntimeError, "1 to 1000"):
            runtime.goal_action("create", {"session_id": "s1", "objective": "x", "max_goal_rounds": 0})

    def test_workspace_list_and_create_return_only_safe_projection(self):
        runtime = DSHAgentRuntime(":memory:", env={"SUMIKA_DSH_ENDPOINT": "http://127.0.0.1:1"})
        calls = []

        def capture(method, payload):
            calls.append((method, payload))
            workspace = {
                "workspaceId": "workspace-1",
                "path": "D:\\Code\\Sumika",
                "title": "Sumika",
                "sessionIds": ["s1"],
                "createdAt": "2026-08-26T00:00:00Z",
                "updatedAt": "2026-08-26T00:00:01Z",
                "privateMetadata": {"token": "secret"},
            }
            if method == "workspace.list":
                return {"items": [workspace], "archivedSessionIds": ["old-session"]}
            if method == "workspace.create":
                return {"workspace": workspace, "created": True}
            raise AssertionError(method)

        runtime._call = capture
        listed = runtime.list_workspaces()
        created = runtime.create_workspace({"path": "D:\\Code\\Sumika"})
        self.assertEqual(listed["workspaces"][0]["session_ids"], ["s1"])
        self.assertEqual(listed["archived_session_ids"], ["old-session"])
        self.assertTrue(created["created"])
        self.assertNotIn("privateMetadata", str(listed))
        self.assertEqual(calls[-1], ("workspace.create", {"path": "D:\\Code\\Sumika"}))

    def test_session_list_is_compact_and_sorted_without_projection_details(self):
        runtime = DSHAgentRuntime(":memory:", env={"SUMIKA_DSH_ENDPOINT": "http://127.0.0.1:1"})
        runtime._call = lambda method, payload: {
            "items": [
                {"sessionId": "old", "updatedAt": 1, "running": False, "blank": False, "agentPreset": "standard", "projections": {"values": {"title": "旧", "sessionStats": {"turns": 1}}}},
                {"sessionId": "new", "updatedAt": 2, "running": True, "blank": False, "agentPreset": "standard", "projections": {"values": {"title": "新", "sessionStats": {"turns": 2}, "system": "must not be copied"}}},
            ]
        }
        result = runtime.list_sessions()
        self.assertEqual([item["id"] for item in result["sessions"]], ["new", "old"])
        self.assertEqual(result["sessions"][0]["state"], "running")
        self.assertNotIn("system", str(result))

    def test_session_search_rename_and_attachment_use_pinned_wire_shapes(self):
        runtime = DSHAgentRuntime(":memory:", env={"SUMIKA_DSH_ENDPOINT": "http://127.0.0.1:1"})
        calls = []
        image_data = base64.b64encode(b"image-bytes").decode("ascii")

        def capture(method, payload):
            calls.append((method, payload))
            if method == "session.search":
                return {"items": [{"sessionId": "s1", "snippet": "matched text", "private": "drop"}], "hasMore": True}
            if method == "session.rename":
                return {"title": "Pinned title", "seq": 7, "private": "drop"}
            if method == "session.attachment":
                return {
                    "attachment": {
                        "attachmentId": "att-1",
                        "mediaType": "image/png",
                        "bytes": 11,
                        "width": 32,
                        "height": 32,
                        "name": "preview.png",
                        "path": "D:\\private\\preview.png",
                    },
                    "data": image_data,
                }
            raise AssertionError(method)

        runtime._call = capture
        searched = runtime.search_sessions({"query": "matched"})
        renamed = runtime.rename_session({"sessionId": "s1", "title": "Pinned title"})
        attachment = runtime.attachment({"sessionId": "s1", "attachmentId": "att-1"})

        self.assertEqual(searched, {"items": [{"session_id": "s1", "snippet": "matched text"}], "has_more": True})
        self.assertEqual(renamed, {"session_id": "s1", "title": "Pinned title", "seq": 7})
        self.assertEqual(attachment["attachment"]["media_type"], "image/png")
        self.assertEqual(attachment["data"], image_data)
        self.assertNotIn("path", str(attachment))
        self.assertEqual(calls[0], ("session.search", {"query": "matched"}))
        self.assertEqual(calls[1], ("session.rename", {"sessionId": "s1", "title": "Pinned title"}))
        self.assertEqual(calls[2], ("session.attachment", {"sessionId": "s1", "attachmentId": "att-1"}))

    def test_session_mutation_and_attachment_inputs_fail_closed(self):
        runtime = DSHAgentRuntime(":memory:", env={"SUMIKA_DSH_ENDPOINT": "http://127.0.0.1:1"})
        runtime._call = lambda method, payload: self.fail(f"unexpected DSH call: {method}")
        with self.assertRaisesRegex(RuntimeError, "must not be empty"):
            runtime.search_sessions({"query": "  "})
        with self.assertRaisesRegex(RuntimeError, "control characters"):
            runtime.rename_session({"sessionId": "s1", "title": "bad\ntitle"})
        with self.assertRaisesRegex(RuntimeError, "attachmentId is required"):
            runtime.attachment({"sessionId": "s1"})

    def test_prompt_accepts_bounded_image_content_without_logging_or_rewriting_it(self):
        runtime = DSHAgentRuntime(":memory:", env={"SUMIKA_DSH_ENDPOINT": "http://127.0.0.1:1"})
        calls = []
        image_data = base64.b64encode(b"small-image").decode("ascii")
        runtime._call = lambda method, payload: calls.append((method, payload)) or {"accepted": True}
        result = runtime.prompt(
            {
                "sessionId": "s1",
                "mode": "execute",
                "leave_plan": False,
                "content": [
                    {"type": "text", "text": "inspect this"},
                    {"type": "image", "mediaType": "image/png", "data": image_data, "name": "capture.png"},
                ],
            }
        )
        self.assertTrue(result["accepted"])
        self.assertEqual(calls[0][0], "session.prompt")
        self.assertEqual(calls[0][1]["content"][1]["data"], image_data)
        with self.assertRaisesRegex(RuntimeError, "invalid or oversized"):
            runtime.prompt(
                {
                    "sessionId": "s1",
                    "mode": "execute",
                    "leave_plan": False,
                    "content": [{"type": "image", "mediaType": "image/png", "data": "not-base64"}],
                }
            )

    def test_websocket_frame_parser_delivers_json_and_handles_ping(self):
        left, right = socket.socketpair()
        stop = threading.Event()
        received = []
        thread = threading.Thread(target=_read_ws_messages, args=(left, b"", stop, received.append))
        thread.start()
        payload = json.dumps({"type": "server-request", "rpcId": "r1", "payload": {"type": "approval/requested", "sessionId": "s1"}}).encode()
        right.sendall(bytes((0x81, len(payload))) + payload)
        self.assertTrue(self._wait_for(lambda: received, timeout=1.0))
        self.assertEqual(json.loads(received[0].decode())["payload"]["type"], "approval/requested")
        stop.set()
        right.close()
        left.close()
        thread.join(timeout=1.0)

    def _wait_for(self, predicate, timeout=1.0):
        deadline = __import__("time").monotonic() + timeout
        while __import__("time").monotonic() < deadline:
            if predicate():
                return True
            __import__("time").sleep(0.01)
        return bool(predicate())


if __name__ == "__main__":
    unittest.main()
