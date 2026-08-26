import base64
from io import BytesIO
import json
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from http.client import HTTPConnection
from unittest.mock import patch

from sumika_core.server import CoreApplication, SumikaRequestHandler, create_server
from sumika_core.storage import Storage
from sumika_core.protocol.jsonrpc import JsonRpcError
from sumika_core.protocol.models import Message
from fixtures.providers import (
    FakeASRProvider,
    FakeProvider,
    FakeVisionProvider,
)


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.server, self.application = create_server(
            "127.0.0.1",
            0,
            ":memory:",
            test_providers={
                "llm": [FakeProvider("这是测试回复")],
                "asr": [FakeASRProvider("这是 Fake ASR 的演示转写。")],
                "vision": [FakeVisionProvider("不要写入事件的摘要")],
            },
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_address[1]

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.application.close()
        self.thread.join(timeout=2)

    def request(self, method, path, payload=None):
        connection = HTTPConnection("127.0.0.1", self.port, timeout=3)
        body = json.dumps(payload).encode() if payload is not None else None
        connection.request(method, path, body=body, headers={"Content-Type": "application/json"} if body else {})
        response = connection.getresponse()
        value = json.loads(response.read().decode())
        connection.close()
        return response.status, value

    def request_bytes(self, method, path):
        connection = HTTPConnection("127.0.0.1", self.port, timeout=3)
        connection.request(method, path)
        response = connection.getresponse()
        body = response.read()
        headers = dict(response.getheaders())
        connection.close()
        return response.status, headers, body

    def test_health_and_chat(self):
        status, health = self.request("GET", "/api/health")
        self.assertEqual(status, 200)
        self.assertTrue(health["ok"])
        status, diagnostics = self.request("GET", "/api/diagnostics")
        self.assertEqual(status, 200)
        self.assertEqual(diagnostics["data_dir"], ":memory:")
        self.assertGreater(diagnostics["pid"], 0)
        status, result = self.request("POST", "/rpc", {"jsonrpc": "2.0", "id": 1, "method": "chat.send", "params": {"session_id": "default", "provider_id": "fake", "messages": [{"role": "user", "content": "hello"}]}})
        self.assertEqual(status, 200)
        self.assertEqual(result["result"]["provider_id"], "fake")
        _, messages = self.request("GET", "/api/sessions/default/messages")
        self.assertEqual([message["role"] for message in messages], ["user", "assistant"])

    def test_agent_session_export_streams_dsh_zip_with_safe_headers(self):
        stream = BytesIO(b"PK-export")
        with patch.object(
            self.application.agent,
            "open_session_export",
            return_value={
                "stream": stream,
                "content_type": "application/zip",
                "content_length": 9,
            },
        ) as export:
            status, headers, body = self.request_bytes(
                "GET",
                "/api/agent/session.export?session_id=session-1&include_descendants=true",
            )
        self.assertEqual(status, 200)
        self.assertEqual(body, b"PK-export")
        self.assertEqual(headers["Content-Type"], "application/zip")
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual(headers["Content-Disposition"], 'attachment; filename="sumika-dsh-session-1.zip"')
        export.assert_called_once_with({"session_id": "session-1", "include_descendants": True})

        status, error = self.request("GET", "/api/agent/session.export?include_descendants=maybe")
        self.assertEqual(status, 400)
        self.assertIn("session_id", error["error"])

    def test_persona_context_and_first_greeting_are_temporary_provider_messages(self):
        status, updated = self.request(
            "POST",
            "/rpc",
            {
                "jsonrpc": "2.0",
                "id": 101,
                "method": "character.update",
                "params": {
                    "character_id": "sumika",
                    "name": "Saki",
                    "config": {
                        "language": "zh-CN",
                        "persona": {
                            "identity": "学习搭档",
                            "traits": "耐心、务实",
                            "relationship": "长期伙伴",
                            "speaking_style": "自然口语",
                            "behavior": "先确认目标",
                            "boundaries": "不编造事实",
                            "response_length": "concise",
                            "system_prompt": "结论优先",
                            "greeting": "欢迎回来",
                        },
                    },
                },
            },
        )
        self.assertEqual(status, 200)
        self.assertEqual(updated["result"]["config"]["persona"]["response_length"], "concise")

        status, response = self.request(
            "POST",
            "/api/chat",
            {
                "session_id": "default",
                "character_id": "sumika",
                "provider_id": "fake",
                "messages": [{"role": "user", "content": "开始吧"}],
            },
        )
        self.assertEqual(status, 200)
        provider = self.application.providers.get("fake")
        request = provider.requests[-1]
        self.assertEqual([message.role for message in request.messages], ["system", "assistant", "user"])
        self.assertIn("角色身份/定位：\n学习搭档", request.messages[0].content)
        self.assertIn("回答保持简洁", request.messages[0].content)
        self.assertEqual(request.messages[1].content, "欢迎回来")

        _, stored = self.request("GET", "/api/sessions/default/messages")
        self.assertEqual([message["role"] for message in stored], ["user", "assistant"])

        self.request(
            "POST",
            "/api/chat",
            {
                "session_id": "default",
                "character_id": "sumika",
                "provider_id": "fake",
                "messages": [{"role": "user", "content": "继续"}],
            },
        )
        second_request = provider.requests[-1]
        self.assertEqual([message.role for message in second_request.messages], ["system", "user"])

    def test_tauri_cross_origin_preflight_is_allowed(self):
        status, headers, body = self.request_bytes("OPTIONS", "/rpc")
        self.assertEqual(status, 204)
        self.assertEqual(body, b"")
        self.assertEqual(headers["Access-Control-Allow-Origin"], "*")
        self.assertIn("OPTIONS", headers["Access-Control-Allow-Methods"])
        self.assertIn("Content-Type", headers["Access-Control-Allow-Headers"])

    def test_json_body_limits_are_scoped_to_rpc_for_image_prompts(self):
        # Ordinary JSON endpoints keep the small default limit, while the RPC
        # boundary has enough room for one validated image prompt (base64 adds
        # roughly a third to the binary size).
        rpc_payload = {
            "jsonrpc": "2.0",
            "id": "large-rpc",
            "method": "core.health",
            "params": {"padding": "x" * 2_100_000},
        }
        status, response = self.request("POST", "/rpc", rpc_payload)
        self.assertEqual(status, 200)
        self.assertTrue(response["result"]["ok"])

        # Exercise both rejection thresholds without uploading deliberately
        # oversized bodies to the test socket (Windows can reset that socket
        # while the client is still writing the rejected payload).
        handler = object.__new__(SumikaRequestHandler)
        handler.path = "/api/chat"
        handler.headers = {"Content-Length": str(2_000_001)}
        handler.rfile = BytesIO(b"{}")
        with self.assertRaisesRegex(ValueError, "too large"):
            handler._read_json()

        handler = object.__new__(SumikaRequestHandler)
        handler.path = "/rpc"
        handler.headers = {"Content-Length": str(18 * 1024 * 1024 + 1)}
        handler.rfile = BytesIO(b"{}")
        with self.assertRaisesRegex(ValueError, "too large"):
            handler._read_json()

    def test_static_public_module_is_served_at_vite_root(self):
        status, headers, body = self.request_bytes("GET", "/vendor/sumika-vrm-viewer.js")
        self.assertEqual(status, 200)
        self.assertIn(headers["Content-Type"].split(";", 1)[0], {"text/javascript", "application/javascript"})
        self.assertEqual(headers["Access-Control-Allow-Origin"], "*")
        self.assertIn(b"mountVrmViewer", body)
        self.assertNotIn(b"<!doctype html>", body[:128].lower())

    def test_session_create_selects_character_and_lists_messages(self):
        status, created = self.request(
            "POST",
            "/rpc",
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "session.create",
                "params": {"id": "session-ui-test", "title": "UI 测试会话", "character_id": "sumika"},
            },
        )
        self.assertEqual(status, 200)
        self.assertEqual(created["result"]["id"], "session-ui-test")
        self.assertEqual(created["result"]["character_id"], "sumika")

        status, sessions = self.request("GET", "/api/sessions")
        self.assertEqual(status, 200)
        self.assertEqual(sessions[0]["id"], "session-ui-test")

        status, response = self.request(
            "POST",
            "/api/chat",
            {
                "session_id": "session-ui-test",
                "character_id": "sumika",
                "provider_id": "fake",
                "messages": [{"role": "user", "content": "新会话消息"}],
            },
        )
        self.assertEqual(status, 200)
        self.assertEqual(response["message"]["role"], "assistant")
        status, messages = self.request("GET", "/api/sessions/session-ui-test/messages")
        self.assertEqual(status, 200)
        self.assertEqual([message["role"] for message in messages], ["user", "assistant"])

    def test_module_api_updates_state(self):
        status, modules = self.request("GET", "/api/modules")
        self.assertEqual(status, 200)
        self.assertTrue(any(module["id"] == "llm" for module in modules))
        status, response = self.request(
            "POST",
            "/rpc",
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "module.update",
                "params": {"module_id": "memory", "enabled": True, "implementation_id": "sqlite-reference"},
            },
        )
        self.assertEqual(status, 200)
        self.assertTrue(response["result"]["enabled"])

    def test_provider_profile_rpc_keeps_module_decoupled_and_secrets_out_of_sqlite(self):
        raw = (
            "ccswitch://v1/import?resource=provider&app=codex&name=RPC%20Import"
            "&endpoint=https%3A%2F%2Fexample.invalid%2Fv1&model=test-model"
            "&futureToken=rpc-secret"
        )
        preview = self.application.rpc("provider.import.preview", {"raw": raw})
        self.assertEqual(preview["importer_id"], "ccswitch-v1")
        self.assertIn("source:futureToken", preview["secret_fields"])
        imported = self.application.rpc("provider.import.save", {"raw": raw})
        profile = imported["profile"]
        self.assertEqual(profile["status"], "unavailable")
        setting = self.application.storage.get_module_setting("llm")
        # Saving an imported draft never changes the currently selected
        # module; activation is the explicit operation that writes profile_id.
        self.assertNotIn("base_url", setting["config"])
        self.assertNotIn("model", setting["config"])
        row = self.application.storage.get_provider_profile(profile["id"])
        self.assertNotIn("rpc-secret", json.dumps(row, ensure_ascii=False))
        self.assertEqual(self.application.credentials.read(profile["id"])["source:futureToken"], "rpc-secret")

        with self.assertRaisesRegex(JsonRpcError, "connection failed"):
            self.application.rpc("provider.profile.activate", {"profile_id": profile["id"]})

    def test_provider_profile_rpc_health_activation_and_privacy_aggregation(self):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"data":[{"id":"rpc-model"}]}')

            def log_message(self, *_args):
                return None

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            profile = self.application.rpc(
                "provider.profile.save",
                {
                    "profile": {
                        "name": "RPC Local",
                        "base_url": f"http://127.0.0.1:{server.server_address[1]}/v1",
                        "model": "rpc-model",
                        "processing_location": "local",
                    }
                },
            )
            health = self.application.rpc("provider.profile.health", {"profile_id": profile["id"]})
            self.assertTrue(health["ok"])
            activated = self.application.rpc("provider.profile.activate", {"profile_id": profile["id"]})
            self.assertEqual(activated["module"]["config"], {"profile_id": profile["id"]})
            self.assertEqual(activated["privacy"]["label"], "本地处理")

            status = self.application.rpc("privacy.status", {})
            self.assertEqual(status["mode"], "local")
            listed = self.application.rpc("provider.profile.list", {})
            self.assertTrue(next(item for item in listed if item["id"] == profile["id"])["active"])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_plugin_discovery_requires_explicit_approval_and_never_runs_entrypoint(self):
        with tempfile.TemporaryDirectory() as directory:
            plugin_dir = Path(directory) / "plugin"
            plugin_dir.mkdir()
            marker = Path(directory) / "executed.txt"
            entrypoint = plugin_dir / "entry.py"
            entrypoint.write_text(
                "import json, sys\n"
                "from pathlib import Path\n"
                f"Path({str(marker)!r}).write_text('ran')\n"
                "request = json.loads(sys.stdin.readline())\n"
                "print(json.dumps({'type': 'result', 'result': {'received': request['input']}}))\n",
                encoding="utf-8",
            )
            (plugin_dir / "manifest.json").write_text(
                json.dumps(
                    {
                        "id": "server.test-plugin",
                        "version": "0.1.0",
                        "capabilities": ["tool"],
                        "entrypoint": "entry.py",
                    }
                ),
                encoding="utf-8",
            )
            status, discovered = self.request(
                "POST",
                "/rpc",
                {
                    "jsonrpc": "2.0",
                    "id": 46,
                    "method": "plugin.discover",
                    "params": {"paths": [str(plugin_dir)]},
                },
            )
            self.assertEqual(status, 200)
            candidate = discovered["result"][0]
            self.assertEqual(candidate["state"], "discovered")
            self.assertFalse(marker.exists())
            status, approved = self.request(
                "POST",
                "/rpc",
                {
                    "jsonrpc": "2.0",
                    "id": 47,
                    "method": "plugin.approve",
                    "params": {"candidate_id": candidate["candidate_id"]},
                },
            )
            self.assertEqual(status, 200)
            self.assertEqual(approved["result"]["state"], "approved")
            self.assertFalse(marker.exists())
            status, configured = self.request(
                "POST",
                "/rpc",
                {
                    "jsonrpc": "2.0",
                    "id": 48,
                    "method": "plugin.configure",
                    "params": {
                        "candidate_id": candidate["candidate_id"],
                        "launcher": {
                            "executable": sys.executable,
                            "arguments": [str(entrypoint)],
                            "working_directory": str(plugin_dir),
                            "timeout_seconds": 10,
                        },
                    },
                },
            )
            self.assertEqual(status, 200)
            self.assertTrue(configured["result"]["launcher"])
            self.assertFalse(marker.exists())
            self.request(
                "POST",
                "/rpc",
                {
                    "jsonrpc": "2.0",
                    "id": 49,
                    "method": "module.update",
                    "params": {
                        "module_id": "tools",
                        "enabled": True,
                        "implementation_id": "external-process",
                        "config": {"executable": sys.executable},
                    },
                },
            )
            status, blocked = self.request(
                "POST",
                "/rpc",
                {
                    "jsonrpc": "2.0",
                    "id": 50,
                    "method": "plugin.run",
                    "params": {"candidate_id": candidate["candidate_id"], "input": {"value": 7}},
                },
            )
            self.assertEqual(status, 400)
            self.assertIn("approval", blocked["error"]["message"])
            self.assertFalse(marker.exists())
            status, executed = self.request(
                "POST",
                "/rpc",
                {
                    "jsonrpc": "2.0",
                    "id": 51,
                    "method": "plugin.run",
                    "params": {
                        "candidate_id": candidate["candidate_id"],
                        "input": {"value": 7},
                        "approved": True,
                    },
                },
            )
            self.assertEqual(status, 200)
            self.assertEqual(executed["result"]["execution"]["result"], {"received": {"value": 7}})
            self.assertTrue(marker.exists())
            status, listed = self.request("GET", "/api/plugins")
            self.assertEqual(status, 200)
            self.assertEqual(listed[0]["state"], "approved")

    def test_revoking_running_audio_and_vision_plugin_reconciles_runtime_state(self):
        with tempfile.TemporaryDirectory() as directory:
            plugin_dir = Path(directory) / "provider-plugin"
            plugin_dir.mkdir()
            entrypoint = plugin_dir / "entry.py"
            entrypoint.write_text("# provider process is not started by this test\n", encoding="utf-8")
            (plugin_dir / "manifest.json").write_text(
                json.dumps(
                    {
                        "id": "server.provider-plugin",
                        "version": "0.1.0",
                        "capabilities": ["asr", "vision"],
                        "entrypoint": "entry.py",
                    }
                ),
                encoding="utf-8",
            )

            _, discovered = self.request(
                "POST",
                "/rpc",
                {"jsonrpc": "2.0", "id": 52, "method": "plugin.discover", "params": {"paths": [str(plugin_dir)]}},
            )
            candidate_id = discovered["result"][0]["candidate_id"]
            self.request(
                "POST",
                "/rpc",
                {"jsonrpc": "2.0", "id": 53, "method": "plugin.approve", "params": {"candidate_id": candidate_id}},
            )
            status, configured = self.request(
                "POST",
                "/rpc",
                {
                    "jsonrpc": "2.0",
                    "id": 54,
                    "method": "plugin.configure",
                    "params": {
                        "candidate_id": candidate_id,
                        "launcher": {
                            "executable": sys.executable,
                            "arguments": [str(entrypoint)],
                            "working_directory": str(plugin_dir),
                            "timeout_seconds": 10,
                        },
                    },
                },
            )
            self.assertEqual(status, 200)
            self.assertTrue(configured["result"]["launcher"])

            provider_id = f"plugin:{candidate_id}"
            for module_id in ("asr", "vision"):
                status, updated = self.request(
                    "POST",
                    "/rpc",
                    {
                        "jsonrpc": "2.0",
                        "id": 55 if module_id == "asr" else 56,
                        "method": "module.update",
                        "params": {"module_id": module_id, "enabled": True, "implementation_id": provider_id},
                    },
                )
                self.assertEqual(status, 200)
                self.assertEqual(updated["result"]["implementation_id"], provider_id)
            self.request(
                "POST",
                "/rpc",
                {"jsonrpc": "2.0", "id": 57, "method": "audio.permission.set", "params": {"permission_id": "microphone", "granted": True}},
            )
            self.request(
                "POST",
                "/rpc",
                {"jsonrpc": "2.0", "id": 58, "method": "vision.permission.set", "params": {"permission_id": "screen.read", "granted": True}},
            )
            status, audio_started = self.request(
                "POST",
                "/rpc",
                {"jsonrpc": "2.0", "id": 59, "method": "audio.start", "params": {"capability": "asr"}},
            )
            self.assertEqual(status, 200)
            self.assertTrue(next(item for item in audio_started["result"]["capabilities"] if item["id"] == "asr")["running"])
            status, vision_started = self.request(
                "POST",
                "/rpc",
                {"jsonrpc": "2.0", "id": 60, "method": "vision.start", "params": {"source": "screen"}},
            )
            self.assertEqual(status, 200)
            self.assertTrue(next(item for item in vision_started["result"]["sources"] if item["id"] == "screen")["running"])

            status, revoked = self.request(
                "POST",
                "/rpc",
                {"jsonrpc": "2.0", "id": 61, "method": "plugin.revoke", "params": {"candidate_id": candidate_id}},
            )
            self.assertEqual(status, 200)
            self.assertEqual(revoked["result"]["state"], "revoked")
            _, modules = self.request("GET", "/api/modules")
            self.assertFalse(next(item for item in modules if item["id"] == "asr")["enabled"])
            self.assertFalse(next(item for item in modules if item["id"] == "vision")["enabled"])
            self.assertNotIn(provider_id, {item.id for item in self.application.audio_providers.list()})
            self.assertNotIn(provider_id, {item.id for item in self.application.vision_providers.list()})
            _, audio_status = self.request("GET", "/api/audio/status")
            _, vision_status = self.request("GET", "/api/vision/status")
            self.assertFalse(next(item for item in audio_status["capabilities"] if item["id"] == "asr")["running"])
            self.assertFalse(next(item for item in vision_status["sources"] if item["id"] == "screen")["running"])

    def test_tool_rpc_requires_approval_and_runs_configured_process(self):
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / "echo_tool.py"
            script.write_text(
                "import json, sys\n"
                "request = json.loads(sys.stdin.readline())\n"
                "print(json.dumps({'type': 'result', 'result': {'received': request['input']}}))\n",
                encoding="utf-8",
            )
            status, configured = self.request(
                "POST",
                "/rpc",
                {
                    "jsonrpc": "2.0",
                    "id": 40,
                    "method": "module.update",
                    "params": {
                        "module_id": "tools",
                        "enabled": True,
                        "implementation_id": "external-process",
                        "config": {"executable": sys.executable, "arguments": [str(script)]},
                    },
                },
            )
            self.assertEqual(status, 200)
            self.assertTrue(configured["result"]["enabled"])

            status, blocked = self.request(
                "POST",
                "/rpc",
                {
                    "jsonrpc": "2.0",
                    "id": 41,
                    "method": "tool.run",
                    "params": {"tool_id": "echo", "input": {"value": 1}},
                },
            )
            self.assertEqual(status, 400)
            self.assertIn("approval", blocked["error"]["message"])

            status, result = self.request(
                "POST",
                "/rpc",
                {
                    "jsonrpc": "2.0",
                    "id": 42,
                    "method": "tool.run",
                    "params": {"tool_id": "echo", "input": {"value": 1}, "approved": True},
                },
            )
            self.assertEqual(status, 200)
            self.assertEqual(result["result"]["result"], {"received": {"value": 1}})

    def test_task_api_and_status_transition(self):
        status, tasks = self.request("GET", "/api/tasks")
        self.assertEqual(status, 200)
        self.assertTrue(any(task["id"] == "core-service" for task in tasks))
        status, created = self.request(
            "POST",
            "/rpc",
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "task.create",
                "params": {"title": "任务 API", "autonomy_level": "L2", "permissions": ["network.read"]},
            },
        )
        self.assertEqual(status, 200)
        task_id = created["result"]["id"]
        status, updated = self.request(
            "POST",
            "/rpc",
            {"jsonrpc": "2.0", "id": 4, "method": "task.update", "params": {"task_id": task_id, "status": "waiting_approval", "log": "请批准"}},
        )
        self.assertEqual(status, 200)
        self.assertEqual(updated["result"]["status"], "waiting_approval")

    def test_task_runner_requires_approval_and_records_reference_result(self):
        status, created = self.request(
            "POST",
            "/rpc",
            {
                "jsonrpc": "2.0",
                "id": 20,
                "method": "task.create",
                "params": {"title": "核心健康检查", "autonomy_level": "L2"},
            },
        )
        self.assertEqual(status, 200)
        task_id = created["result"]["id"]
        status, waiting = self.request(
            "POST",
            "/rpc",
            {"jsonrpc": "2.0", "id": 21, "method": "task.run", "params": {"task_id": task_id}},
        )
        self.assertEqual(status, 200)
        self.assertEqual(waiting["result"]["status"], "waiting_approval")
        status, completed = self.request(
            "POST",
            "/rpc",
            {"jsonrpc": "2.0", "id": 22, "method": "task.run", "params": {"task_id": task_id, "approved": True}},
        )
        self.assertEqual(status, 200)
        self.assertEqual(completed["result"]["status"], "completed")
        self.assertEqual(completed["result"]["result"]["runner"], "in-process-reference")

    def test_avatar_state_and_model_catalog_api(self):
        status, models = self.request("GET", "/api/avatar/models")
        self.assertEqual(status, 200)
        self.assertEqual(len(models), 1)
        default_model = next(model for model in models if model["metadata"].get("bundled"))
        self.assertEqual(Path(default_model["path"]).name, "AvatarSample_A.vrm")
        self.assertEqual(default_model["metadata"]["source_sha256"], "B86B0B8A66D48911431D6F920A5211A974226F83AA672ECA3F3DFADE58AC346E")
        self.assertEqual(default_model["kind"], "vrm")
        status, state = self.request(
            "POST",
            "/rpc",
            {"jsonrpc": "2.0", "id": 5, "method": "avatar.state", "params": {"character_id": "sumika"}},
        )
        self.assertEqual(status, 200)
        self.assertEqual(state["result"]["driver"], "vrm")
        self.assertEqual(state["result"]["model"]["id"], default_model["id"])
        status, headers, body = self.request_bytes("GET", f"/api/avatar/models/{default_model['id']}/thumbnail")
        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "image/png")
        self.assertTrue(body.startswith(b"\x89PNG\r\n\x1a\n"))
        status, headers, body = self.request_bytes("GET", f"/api/avatar/models/{default_model['id']}/file")
        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], "model/gltf-binary")
        self.assertEqual(len(body), default_model["size_bytes"])
        self.assertTrue(body[:4] == b"glTF")
        status, _, _ = self.request_bytes("GET", "/api/avatar/models/missing/thumbnail")
        self.assertEqual(status, 404)

    def test_avatar_inspection_rpc_and_http_endpoint(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest_path = root / "character.model3.json"
            (root / "character.moc3").write_bytes(b"moc")
            manifest_path.write_text(
                '{"Version": 3, "FileReferences": {"Moc": "character.moc3", '
                '"Textures": ["missing.png"]}}',
                encoding="utf-8",
            )
            status, imported = self.request(
                "POST",
                "/rpc",
                {
                    "jsonrpc": "2.0",
                    "id": 5,
                    "method": "avatar.import",
                    "params": {"path": str(manifest_path)},
                },
            )
            self.assertEqual(status, 200)
            model_id = imported["result"]["id"]

            status, inspected = self.request(
                "POST",
                "/rpc",
                {
                    "jsonrpc": "2.0",
                    "id": 6,
                    "method": "avatar.inspect",
                    "params": {"model_id": model_id},
                },
            )
            self.assertEqual(status, 200)
            self.assertEqual(inspected["result"]["status"], "warning")
            self.assertEqual(inspected["result"]["model_file"], "character.moc3")
            self.assertEqual(inspected["result"]["counts"]["textures"], 1)

            status, http_inspection = self.request("GET", f"/api/avatar/models/{model_id}/inspection")
            self.assertEqual(status, 200)
            self.assertEqual(http_inspection["referenced_files"][0]["reference"], "character.moc3")

            status, missing = self.request(
                "POST",
                "/rpc",
                {
                    "jsonrpc": "2.0",
                    "id": 7,
                    "method": "avatar.inspect",
                    "params": {"model_id": "missing"},
                },
            )
            self.assertEqual(status, 400)
            self.assertIn("Unknown Avatar model", missing["error"]["message"])

    def test_default_avatar_is_seeded_once_and_respects_clear(self):
        with tempfile.TemporaryDirectory() as directory:
            first = CoreApplication(directory)
            models = first.avatar.list_models()
            self.assertEqual(len(models), 1)
            default_model = next(model for model in models if model["metadata"].get("bundled"))
            model_id = default_model["id"]
            self.assertEqual(Path(default_model["path"]).name, "AvatarSample_A.vrm")
            first.avatar.select("sumika", model_id=None, driver_id="none")
            first.close()

            second = CoreApplication(directory)
            self.assertEqual(second.avatar.state()["driver"], "none")
            self.assertEqual(len(second.avatar.list_models()), 1)
            second.avatar.unregister_model(model_id)
            second.close()

            third = CoreApplication(directory)
            self.assertFalse(any(Path(model["path"]).name == "AvatarSample_A.vrm" for model in third.avatar.list_models()))
            self.assertEqual(third.avatar.state()["driver"], "none")
            third.close()

    def test_avatar_discover_rpc_lists_repository_models(self):
        status, discovered = self.request(
            "POST",
            "/rpc",
            {"jsonrpc": "2.0", "id": 26, "method": "avatar.discover", "params": {}},
        )
        self.assertEqual(status, 200)
        self.assertTrue(any(model["kind"] == "vrm" for model in discovered["result"]))

    def test_avatar_discovery_respects_unregister_for_managed_paths(self):
        with tempfile.TemporaryDirectory() as assets_directory, tempfile.TemporaryDirectory() as data_directory:
            model_path = Path(assets_directory) / "custom.vrm"
            model_path.write_bytes(b"glTF")
            with patch("sumika_core.server.AVATAR_ASSETS_DIR", Path(assets_directory)):
                first = CoreApplication(data_directory)
                custom = next(model for model in first.avatar.list_models() if model["path"] == str(model_path.resolve()))
                removed = first.rpc("avatar.unregister", {"model_id": custom["id"]})
                self.assertEqual(removed["model"]["id"], custom["id"])
                first.close()

                second = CoreApplication(data_directory)
                self.assertFalse(any(model["path"] == str(model_path.resolve()) for model in second.avatar.list_models()))
                ignored = second.rpc("avatar.ignored", {})
                self.assertEqual(len(ignored), 1)
                self.assertTrue(ignored[0]["available"])
                restored = second.rpc("avatar.restore", {"path": str(model_path)})
                self.assertEqual(restored["path"], str(model_path.resolve()))
                self.assertEqual(second.rpc("avatar.ignored", {}), [])
                second.close()

    def test_missing_ignored_tombstone_can_be_cleared_without_touching_files(self):
        with tempfile.TemporaryDirectory() as assets_directory, tempfile.TemporaryDirectory() as data_directory:
            missing_path = Path(assets_directory) / "missing.vrm"
            with patch("sumika_core.server.AVATAR_ASSETS_DIR", Path(assets_directory)):
                application = CoreApplication(data_directory)
                application._set_avatar_path_ignored(str(missing_path), True)

                ignored = application.rpc("avatar.ignored", {})
                self.assertEqual(len(ignored), 1)
                self.assertFalse(ignored[0]["available"])
                self.assertEqual(ignored[0]["reason"], "missing_or_inaccessible")

                cleared = application.rpc("avatar.ignored.clear", {"path": str(missing_path)})
                self.assertTrue(cleared["removed"])
                self.assertFalse(missing_path.exists())
                self.assertEqual(application.rpc("avatar.ignored", {}), [])
                self.assertIn(
                    "avatar.ignored.cleared",
                    {event["event_type"] for event in application.storage.list_events()},
                )
                application.close()

    def test_center_stage_migration_is_sumika_only_and_idempotent(self):
        with tempfile.TemporaryDirectory() as data_directory:
            database_path = Path(data_directory) / "sumika.sqlite3"
            storage = Storage(database_path)
            storage.create_character("sumika", "Sumika", {"avatar": {"position": "right", "scale": 0.75}})
            storage.create_character("other", "Other", {"avatar": {"position": "right"}})
            storage.close()

            first = CoreApplication(data_directory)
            self.assertEqual(first.storage.get_character("sumika")["config"]["avatar"]["position"], "center")
            self.assertEqual(first.storage.get_character("other")["config"]["avatar"]["position"], "right")
            first.close()

            second = CoreApplication(data_directory)
            self.assertEqual(second.storage.get_character("sumika")["config"]["avatar"]["position"], "center")
            self.assertEqual(second.storage.get_meta("avatar.presentation.center_migration.v1"), "done")
            second.close()

    def test_fresh_workspace_starts_with_llm_disabled_and_no_profile(self):
        with tempfile.TemporaryDirectory() as data_directory:
            with patch.dict(
                "os.environ",
                {
                    "SUMIKA_OPENAI_BASE_URL": "",
                    "SUMIKA_OPENAI_MODEL": "",
                    "SUMIKA_OPENAI_API_KEY": "",
                },
            ):
                application = CoreApplication(data_directory)
            llm = application.storage.get_module_setting("llm")
            self.assertFalse(llm["enabled"])
            self.assertEqual(llm["implementation_id"], "openai-compatible")
            self.assertEqual(llm["config"], {})
            self.assertEqual(application.storage.list_provider_profiles(), [])
            health = next(
                item
                for item in application.rpc("provider.health", {})
                if item["provider_id"] == "openai-compatible"
            )
            self.assertEqual(health["status"], "unconfigured")
            application.close()

    def test_fresh_workspace_ignores_legacy_provider_environment(self):
        with tempfile.TemporaryDirectory() as data_directory:
            with patch.dict(
                "os.environ",
                {
                    "SUMIKA_OPENAI_BASE_URL": "http://127.0.0.1:11434/v1",
                    "SUMIKA_OPENAI_MODEL": "legacy-environment-model",
                },
            ):
                application = CoreApplication(data_directory)
            llm = application.storage.get_module_setting("llm")
            self.assertFalse(llm["enabled"])
            self.assertEqual(llm["config"], {})
            self.assertEqual(application.storage.list_provider_profiles(), [])
            application.close()

    def test_legacy_empty_fake_provider_is_disabled_without_creating_profile(self):
        with tempfile.TemporaryDirectory() as data_directory:
            storage = Storage(Path(data_directory) / "sumika.sqlite3")
            storage.upsert_module_setting("llm", enabled=True, implementation_id="fake", config={})
            storage.upsert_module_setting("asr", enabled=True, implementation_id="fake-asr", config={})
            storage.close()

            with patch.dict(
                "os.environ",
                {
                    "SUMIKA_OPENAI_BASE_URL": "",
                    "SUMIKA_OPENAI_MODEL": "",
                    "SUMIKA_OPENAI_API_KEY": "",
                },
            ):
                first = CoreApplication(data_directory)
            llm = first.storage.get_module_setting("llm")
            asr = first.storage.get_module_setting("asr")
            self.assertEqual(llm["implementation_id"], "openai-compatible")
            self.assertFalse(llm["enabled"])
            self.assertEqual(llm["config"], {})
            self.assertEqual(first.storage.list_provider_profiles(), [])
            self.assertFalse(asr["enabled"])
            self.assertEqual(asr["implementation_id"], "none")
            migrated = [
                event
                for event in first.storage.list_events()
                if event["event_type"] == "provider.settings.migrated"
            ]
            self.assertEqual(len(migrated), 1)
            first.close()

            second = CoreApplication(data_directory)
            migrated_again = [
                event
                for event in second.storage.list_events()
                if event["event_type"] == "provider.settings.migrated"
            ]
            self.assertEqual(len(migrated_again), 1)
            second.close()

    def test_legacy_empty_openai_selection_is_disabled_once(self):
        with tempfile.TemporaryDirectory() as data_directory:
            storage = Storage(Path(data_directory) / "sumika.sqlite3")
            storage.upsert_module_setting(
                "llm",
                enabled=True,
                implementation_id="openai-compatible",
                config={},
            )
            storage.close()

            first = CoreApplication(data_directory)
            llm = first.storage.get_module_setting("llm")
            self.assertFalse(llm["enabled"])
            self.assertEqual(llm["config"], {})
            disabled_events = [
                event
                for event in first.storage.list_events()
                if event["event_type"] == "provider.unconfigured_default.disabled"
            ]
            self.assertEqual(len(disabled_events), 1)
            first.close()

            second = CoreApplication(data_directory)
            disabled_again = [
                event
                for event in second.storage.list_events()
                if event["event_type"] == "provider.unconfigured_default.disabled"
            ]
            self.assertEqual(len(disabled_again), 1)
            second.close()

    def test_legacy_empty_selection_ignores_environment_and_stays_disabled(self):
        with tempfile.TemporaryDirectory() as data_directory:
            storage = Storage(Path(data_directory) / "sumika.sqlite3")
            storage.upsert_module_setting(
                "llm",
                enabled=True,
                implementation_id="openai-compatible",
                config={},
            )
            storage.close()

            with patch.dict(
                "os.environ",
                {
                    "SUMIKA_OPENAI_BASE_URL": "http://127.0.0.1:11434/v1",
                    "SUMIKA_OPENAI_MODEL": "environment-model",
                },
            ):
                application = CoreApplication(data_directory)
            llm = application.storage.get_module_setting("llm")
            self.assertFalse(llm["enabled"])
            self.assertEqual(llm["config"], {})
            self.assertEqual(application.storage.list_provider_profiles(), [])
            application.close()

    def test_incomplete_legacy_provider_config_is_disabled_but_preserved(self):
        with tempfile.TemporaryDirectory() as data_directory:
            storage = Storage(Path(data_directory) / "sumika.sqlite3")
            storage.upsert_module_setting(
                "llm",
                enabled=True,
                implementation_id="openai-compatible",
                config={"base_url": "http://127.0.0.1:19090/v1", "timeout": 30},
            )
            storage.close()

            with patch.dict(
                "os.environ",
                {"SUMIKA_OPENAI_BASE_URL": "", "SUMIKA_OPENAI_MODEL": ""},
            ):
                application = CoreApplication(data_directory)
            llm = application.storage.get_module_setting("llm")
            self.assertFalse(llm["enabled"])
            self.assertEqual(
                llm["config"],
                {"base_url": "http://127.0.0.1:19090/v1", "timeout": 30},
            )
            self.assertEqual(application.storage.list_provider_profiles(), [])
            disabled_event = next(
                event
                for event in application.storage.list_events()
                if event["event_type"] == "provider.unconfigured_default.disabled"
            )
            self.assertEqual(disabled_event["payload"]["reason"], "incomplete-legacy-config")
            self.assertEqual(
                disabled_event["payload"]["retained_config_keys"],
                ["base_url", "timeout"],
            )
            application.close()

    def test_existing_profile_binding_is_not_changed(self):
        with tempfile.TemporaryDirectory() as data_directory:
            storage = Storage(Path(data_directory) / "sumika.sqlite3")
            storage.upsert_provider_profile(
                profile_id="user-connection",
                name="用户连接",
                capability="llm",
                adapter_id="openai-compatible",
                template_id="openai-compatible",
                processing_location="cloud",
                status="available",
                config={
                    "base_urls": ["https://example.invalid/v1"],
                    "active_base_url": "https://example.invalid/v1",
                    "model": "user-model",
                    "timeout": 45,
                    "headers": {},
                },
                credential_ref=None,
                secret_fields=[],
                source={"format": "sumika-provider-profile/v1", "kind": "manual"},
            )
            storage.upsert_module_setting(
                "llm",
                enabled=True,
                implementation_id="openai-compatible",
                config={"profile_id": "user-connection"},
            )
            storage.close()

            application = CoreApplication(data_directory)
            llm = application.storage.get_module_setting("llm")
            profile = application.storage.get_provider_profile("user-connection")
            self.assertTrue(llm["enabled"])
            self.assertEqual(llm["config"], {"profile_id": "user-connection"})
            self.assertEqual(profile["config"]["model"], "user-model")
            self.assertEqual(profile["status"], "available")
            self.assertNotIn(
                "provider.unconfigured_default.disabled",
                {event["event_type"] for event in application.storage.list_events()},
            )
            application.close()

    def test_missing_profile_binding_is_disabled_but_preserved(self):
        with tempfile.TemporaryDirectory() as data_directory:
            storage = Storage(Path(data_directory) / "sumika.sqlite3")
            storage.upsert_module_setting(
                "llm",
                enabled=True,
                implementation_id="openai-compatible",
                config={"profile_id": "temporarily-missing"},
            )
            storage.close()

            application = CoreApplication(data_directory)
            llm = application.storage.get_module_setting("llm")
            self.assertFalse(llm["enabled"])
            self.assertEqual(llm["config"], {"profile_id": "temporarily-missing"})
            disabled_event = next(
                event
                for event in application.storage.list_events()
                if event["event_type"] == "provider.unconfigured_default.disabled"
            )
            self.assertEqual(disabled_event["payload"]["reason"], "missing-profile")
            self.assertEqual(
                disabled_event["payload"]["retained_profile_id"],
                "temporarily-missing",
            )
            application.close()

    def test_legacy_explicit_provider_config_preserves_data_and_creates_profile(self):
        with tempfile.TemporaryDirectory() as data_directory:
            storage = Storage(Path(data_directory) / "sumika.sqlite3")
            storage.create_character("legacy-character", "Legacy", {})
            storage.create_session("legacy-session", "保留的会话", "legacy-character")
            storage.append_message(
                "legacy-session",
                Message(role="user", content="这条消息必须保留", character_id="legacy-character"),
            )
            storage.upsert_module_setting(
                "llm",
                enabled=True,
                implementation_id="openai-compatible",
                config={
                    "base_url": "https://legacy.example.invalid/v1",
                    "model": "legacy-model",
                    "timeout": 30,
                },
            )
            storage.close()

            application = CoreApplication(data_directory)
            llm = application.storage.get_module_setting("llm")
            self.assertTrue(llm["enabled"])
            profile = application.storage.get_provider_profile(llm["config"]["profile_id"])
            self.assertEqual(llm["config"]["profile_id"], "legacy-openai-compatible")
            self.assertEqual(profile["name"], "迁移的 OpenAI-compatible 连接")
            self.assertEqual(profile["processing_location"], "auto")
            self.assertEqual(profile["config"]["active_base_url"], "https://legacy.example.invalid/v1")
            self.assertEqual(profile["config"]["model"], "legacy-model")
            self.assertEqual(
                application.storage.list_messages("legacy-session")[0]["content"],
                "这条消息必须保留",
            )
            self.assertEqual(
                application.storage.list_sessions()[0]["title"],
                "保留的会话",
            )
            application.close()

    def test_avatar_motion_config_defaults_and_ranges(self):
        status, created = self.request(
            "POST",
            "/rpc",
            {
                "jsonrpc": "2.0",
                "id": 61,
                "method": "character.create",
                "params": {"id": "motion-defaults", "name": "动作默认值", "config": {}},
            },
        )
        self.assertEqual(status, 200)
        self.assertEqual(
            created["result"]["config"]["avatar"],
            {
                "position": "center",
                "opacity": 1,
                "scale": 1,
                "idle_motion": True,
                "auto_rotate": False,
                "rotation_speed": 0.12,
                "natural_pose": True,
                "look_at_enabled": True,
                "head_follow_enabled": True,
                "look_at_strength": 1.0,
                "head_follow_strength": 0.35,
            },
        )
        status, invalid = self.request(
            "POST",
            "/rpc",
            {
                "jsonrpc": "2.0",
                "id": 62,
                "method": "character.update",
                "params": {"character_id": "motion-defaults", "config": {"avatar": {"rotation_speed": 0.01}}},
            },
        )
        self.assertEqual(status, 400)
        self.assertIn("rotation_speed", invalid["error"]["message"])
        status, invalid = self.request(
            "POST",
            "/rpc",
            {
                "jsonrpc": "2.0",
                "id": 63,
                "method": "character.update",
                "params": {"character_id": "motion-defaults", "config": {"avatar": {"auto_rotate": "yes"}}},
            },
        )
        self.assertEqual(status, 400)
        self.assertIn("auto_rotate", invalid["error"]["message"])

    def test_avatar_restore_does_not_bind_character(self):
        with tempfile.TemporaryDirectory() as assets_directory, tempfile.TemporaryDirectory() as data_directory:
            model_path = Path(assets_directory) / "restore.model3.json"
            model_path.write_text("{}", encoding="utf-8")
            with patch("sumika_core.server.AVATAR_ASSETS_DIR", Path(assets_directory)):
                application = CoreApplication(data_directory)
                model = next(item for item in application.avatar.list_models() if item["path"] == str(model_path.resolve()))
                application.avatar.select("sumika", model_id=None, driver_id="none")
                application.rpc("avatar.unregister", {"model_id": model["id"]})
                restored = application.rpc("avatar.restore", {"path": str(model_path)})
                self.assertEqual(restored["path"], str(model_path.resolve()))
                self.assertEqual(restored["kind"], "live2d")
                self.assertIsNone(application.storage.get_character("sumika")["config"].get("avatar_model_id"))
                application.close()

    def test_avatar_model_lifecycle_rpc_and_events(self):
        with tempfile.TemporaryDirectory() as directory:
            model_path = Path(directory) / "sumika.model3.json"
            model_path.write_text("{}", encoding="utf-8")
            status, imported = self.request(
                "POST",
                "/rpc",
                {
                    "jsonrpc": "2.0",
                    "id": 27,
                    "method": "avatar.import",
                    "params": {"path": str(model_path)},
                },
            )
            self.assertEqual(status, 200)
            model_id = imported["result"]["id"]
            model_path.write_text('{"updated": true}', encoding="utf-8")

            status, refreshed = self.request(
                "POST",
                "/rpc",
                {
                    "jsonrpc": "2.0",
                    "id": 28,
                    "method": "avatar.refresh",
                    "params": {"model_id": model_id},
                },
            )
            self.assertEqual(status, 200)
            self.assertEqual(refreshed["result"]["size_bytes"], model_path.stat().st_size)

            status, selected = self.request(
                "POST",
                "/rpc",
                {
                    "jsonrpc": "2.0",
                    "id": 29,
                    "method": "avatar.select",
                    "params": {"character_id": "sumika", "model_id": model_id, "driver_id": "live2d"},
                },
            )
            self.assertEqual(status, 200)
            self.assertEqual(selected["result"]["state"]["model"]["id"], model_id)

            status, blocked = self.request(
                "POST",
                "/rpc",
                {
                    "jsonrpc": "2.0",
                    "id": 30,
                    "method": "avatar.unregister",
                    "params": {"model_id": model_id},
                },
            )
            self.assertEqual(status, 400)
            self.assertIn("Sumika", blocked["error"]["message"])

            self.request(
                "POST",
                "/rpc",
                {
                    "jsonrpc": "2.0",
                    "id": 31,
                    "method": "avatar.select",
                    "params": {"character_id": "sumika", "model_id": None, "driver_id": "none"},
                },
            )
            status, removed = self.request(
                "POST",
                "/rpc",
                {
                    "jsonrpc": "2.0",
                    "id": 32,
                    "method": "avatar.unregister",
                    "params": {"model_id": model_id},
                },
            )
            self.assertEqual(status, 200)
            self.assertEqual(removed["result"]["model"]["id"], model_id)
            self.assertTrue(model_path.exists())

            _, events = self.request("GET", "/api/events")
            event_types = {event["event_type"] for event in events}
            self.assertTrue({"avatar.model.imported", "avatar.model.refreshed", "avatar.model.unregistered"} <= event_types)

    def test_character_update_persists_persona_and_avatar_presentation(self):
        status, response = self.request(
            "POST",
            "/rpc",
            {
                "jsonrpc": "2.0",
                "id": 23,
                "method": "character.update",
                "params": {
                    "character_id": "sumika",
                    "name": "Sumika 新版",
                    "config": {
                        "persona": {"system_prompt": "保持简洁", "greeting": "欢迎回来"},
                        "avatar": {
                            "position": "right",
                            "opacity": 0.8,
                            "scale": 1.2,
                            "natural_pose": False,
                            "look_at_enabled": True,
                            "head_follow_enabled": False,
                            "look_at_strength": 0.75,
                            "head_follow_strength": 0.2,
                        },
                    },
                },
            },
        )
        self.assertEqual(status, 200)
        character = response["result"]
        self.assertEqual(character["name"], "Sumika 新版")
        self.assertEqual(character["config"]["avatar"]["position"], "right")
        self.assertEqual(character["config"]["persona"]["greeting"], "欢迎回来")
        self.assertFalse(character["config"]["avatar"]["natural_pose"])
        self.assertTrue(character["config"]["avatar"]["look_at_enabled"])
        self.assertFalse(character["config"]["avatar"]["head_follow_enabled"])
        self.assertEqual(character["config"]["avatar"]["look_at_strength"], 0.75)
        self.assertEqual(character["config"]["avatar"]["head_follow_strength"], 0.2)
        _, avatar_state = self.request(
            "POST",
            "/rpc",
            {"jsonrpc": "2.0", "id": 25, "method": "avatar.state", "params": {"character_id": "sumika"}},
        )
        self.assertEqual(avatar_state["result"]["presentation"]["opacity"], 0.8)
        status, response = self.request(
            "POST",
            "/rpc",
            {
                "jsonrpc": "2.0",
                "id": 26,
                "method": "character.update",
                "params": {"character_id": "sumika", "config": {"avatar": {"opacity": 2}}},
            },
        )
        self.assertEqual(status, 400)
        self.assertIn("opacity", response["error"]["message"])

        status, response = self.request(
            "POST",
            "/rpc",
            {
                "jsonrpc": "2.0",
                "id": 24,
                "method": "character.update",
                "params": {"character_id": "sumika", "config": {"avatar": {"look_at_strength": 1.1}}},
            },
        )
        self.assertEqual(status, 400)
        self.assertIn("look_at_strength", response["error"]["message"])

    def test_character_defaults_include_runtime_avatar_controls(self):
        status, characters = self.request("GET", "/api/characters")
        self.assertEqual(status, 200)
        avatar = next(item for item in characters if item["id"] == "sumika")["config"]["avatar"]
        self.assertTrue(avatar["natural_pose"])
        self.assertTrue(avatar["look_at_enabled"])
        self.assertTrue(avatar["head_follow_enabled"])
        self.assertEqual(avatar["look_at_strength"], 1)
        self.assertEqual(avatar["head_follow_strength"], 0.35)

    def test_snapshot_rpc_shows_diff_creates_pre_restore_snapshot_and_restores(self):
        status, created = self.request(
            "POST",
            "/rpc",
            {
                "jsonrpc": "2.0",
                "id": 33,
                "method": "snapshot.create",
                "params": {"name": "恢复测试基线", "scope": "system"},
            },
        )
        self.assertEqual(status, 200)
        snapshot_id = created["result"]["id"]
        self.assertEqual(created["result"]["scope"], "system")

        status, changed = self.request(
            "POST",
            "/rpc",
            {
                "jsonrpc": "2.0",
                "id": 34,
                "method": "character.update",
                "params": {"character_id": "sumika", "name": "临时名称"},
            },
        )
        self.assertEqual(status, 200)
        self.assertEqual(changed["result"]["name"], "临时名称")

        status, diff = self.request(
            "POST",
            "/rpc",
            {"jsonrpc": "2.0", "id": 35, "method": "snapshot.diff", "params": {"snapshot_id": snapshot_id}},
        )
        self.assertEqual(status, 200)
        self.assertTrue(diff["result"]["diff"]["changed"])

        status, restored = self.request(
            "POST",
            "/rpc",
            {"jsonrpc": "2.0", "id": 36, "method": "snapshot.restore", "params": {"snapshot_id": snapshot_id}},
        )
        self.assertEqual(status, 200)
        self.assertNotEqual(restored["result"]["pre_restore_snapshot"]["id"], snapshot_id)
        status, characters = self.request("GET", "/api/characters")
        self.assertEqual(status, 200)
        self.assertEqual(next(item for item in characters if item["id"] == "sumika")["name"], "Sumika")
        status, events = self.request("GET", "/api/events")
        self.assertEqual(status, 200)
        event_types = {event["event_type"] for event in events}
        self.assertTrue({"snapshot.created", "snapshot.restored"} <= event_types)

    def test_targeted_character_snapshot_rpc_does_not_change_other_characters(self):
        status, created = self.request(
            "POST",
            "/rpc",
            {
                "jsonrpc": "2.0",
                "id": 37,
                "method": "character.create",
                "params": {"id": "other", "name": "另一个角色", "config": {}},
            },
        )
        self.assertEqual(status, 200)
        status, snapshot = self.request(
            "POST",
            "/rpc",
            {
                "jsonrpc": "2.0",
                "id": 38,
                "method": "snapshot.create",
                "params": {"name": "只保存 Sumika", "scope": "characters", "target_id": "sumika"},
            },
        )
        self.assertEqual(status, 200)
        snapshot_id = snapshot["result"]["id"]
        self.request(
            "POST",
            "/rpc",
            {"jsonrpc": "2.0", "id": 39, "method": "character.update", "params": {"character_id": "sumika", "name": "Sumika 临时"}},
        )
        self.request(
            "POST",
            "/rpc",
            {"jsonrpc": "2.0", "id": 40, "method": "character.update", "params": {"character_id": "other", "name": "另一个角色·修改"}},
        )
        status, restored = self.request(
            "POST",
            "/rpc",
            {"jsonrpc": "2.0", "id": 41, "method": "snapshot.restore", "params": {"snapshot_id": snapshot_id}},
        )
        self.assertEqual(status, 200)
        self.assertEqual(restored["result"]["restored"]["scope"], "characters")
        _, characters = self.request("GET", "/api/characters")
        self.assertEqual(next(item for item in characters if item["id"] == "sumika")["name"], "Sumika")
        self.assertEqual(next(item for item in characters if item["id"] == "other")["name"], "另一个角色·修改")

    def test_snapshot_export_and_import_validate_checksum_without_restoring(self):
        status, created = self.request(
            "POST",
            "/rpc",
            {
                "jsonrpc": "2.0",
                "id": 42,
                "method": "snapshot.create",
                "params": {"name": "可移动快照", "scope": "characters", "target_id": "sumika"},
            },
        )
        self.assertEqual(status, 200)
        snapshot_id = created["result"]["id"]
        status, exported = self.request(
            "POST",
            "/rpc",
            {"jsonrpc": "2.0", "id": 43, "method": "snapshot.export", "params": {"snapshot_id": snapshot_id}},
        )
        self.assertEqual(status, 200)
        package = exported["result"]
        self.assertEqual(package["format"], "sumika.snapshot")
        status, imported = self.request(
            "POST",
            "/rpc",
            {"jsonrpc": "2.0", "id": 44, "method": "snapshot.import", "params": {"package": package}},
        )
        self.assertEqual(status, 200)
        self.assertNotEqual(imported["result"]["id"], snapshot_id)
        self.assertEqual(imported["result"]["imported_from_id"], snapshot_id)
        status, tampered = self.request(
            "POST",
            "/rpc",
            {
                "jsonrpc": "2.0",
                "id": 45,
                "method": "snapshot.import",
                "params": {"package": {**package, "sha256": "0" * 64}},
            },
        )
        self.assertEqual(status, 400)
        self.assertIn("checksum", tampered["error"]["message"])

    def test_audio_permissions_and_fake_asr_api(self):
        status, audio = self.request("GET", "/api/audio/status")
        self.assertEqual(status, 200)
        self.assertEqual({item["id"] for item in audio["capabilities"]}, {"asr", "tts", "vad"})
        _, response = self.request(
            "POST",
            "/rpc",
            {
                "jsonrpc": "2.0",
                "id": 6,
                "method": "module.update",
                "params": {"module_id": "asr", "enabled": True, "implementation_id": "fake-asr"},
            },
        )
        self.assertEqual(response["result"]["implementation_id"], "fake-asr")
        status, response = self.request(
            "POST",
            "/rpc",
            {"jsonrpc": "2.0", "id": 7, "method": "audio.start", "params": {"capability": "asr"}},
        )
        self.assertEqual(status, 400)
        self.assertIn("permission", response["error"]["message"])
        _, permission = self.request(
            "POST",
            "/rpc",
            {
                "jsonrpc": "2.0",
                "id": 8,
                "method": "audio.permission.set",
                "params": {"permission_id": "microphone", "granted": True},
            },
        )
        self.assertEqual(next(item for item in permission["result"]["permissions"] if item["permission_id"] == "microphone")["state"], "granted")
        status, started = self.request(
            "POST",
            "/rpc",
            {"jsonrpc": "2.0", "id": 9, "method": "audio.start", "params": {"capability": "asr"}},
        )
        self.assertEqual(status, 200)
        self.assertTrue(next(item for item in started["result"]["capabilities"] if item["id"] == "asr")["running"])
        status, transcribed = self.request(
            "POST",
            "/rpc",
            {
                "jsonrpc": "2.0",
                "id": 10,
                "method": "audio.asr.transcribe",
                "params": {"audio_base64": base64.b64encode(b"audio").decode("ascii")},
            },
        )
        self.assertEqual(status, 200)
        self.assertEqual(transcribed["result"]["text"], "这是 Fake ASR 的演示转写。")

    def test_memory_api_is_explicit_and_searchable(self):
        status, memory_status = self.request("GET", "/api/memory/status")
        self.assertEqual(status, 200)
        self.assertFalse(memory_status["enabled"])
        _, response = self.request(
            "POST",
            "/rpc",
            {
                "jsonrpc": "2.0",
                "id": 11,
                "method": "module.update",
                "params": {
                    "module_id": "memory",
                    "enabled": True,
                    "implementation_id": "sqlite-reference",
                    "config": {"categories": ["preferences"]},
                },
            },
        )
        self.assertTrue(response["result"]["enabled"])
        status, created = self.request(
            "POST",
            "/rpc",
            {
                "jsonrpc": "2.0",
                "id": 12,
                "method": "memory.add",
                "params": {"character_id": "sumika", "category": "preferences", "content": "喜欢绿茶", "source": "test"},
            },
        )
        self.assertEqual(status, 200)
        memory_id = created["result"]["id"]
        status, found = self.request(
            "POST",
            "/rpc",
            {"jsonrpc": "2.0", "id": 13, "method": "memory.search", "params": {"character_id": "sumika", "query": "绿茶"}},
        )
        self.assertEqual(status, 200)
        self.assertEqual(found["result"][0]["id"], memory_id)
        status, events = self.request("GET", "/api/events")
        self.assertEqual(status, 200)
        created_event = next(item for item in events if item["event_type"] == "memory.created")
        self.assertNotIn("喜欢绿茶", json.dumps(created_event["payload"], ensure_ascii=False))
        status, deleted = self.request(
            "POST",
            "/rpc",
            {"jsonrpc": "2.0", "id": 14, "method": "memory.delete", "params": {"memory_id": memory_id}},
        )
        self.assertEqual(status, 200)
        self.assertTrue(deleted["result"]["deleted"])

    def test_vision_api_is_permission_gated_and_redacts_observations(self):
        status, vision_status = self.request("GET", "/api/vision/status")
        self.assertEqual(status, 200)
        self.assertEqual({item["id"] for item in vision_status["sources"]}, {"screen", "camera"})
        _, response = self.request(
            "POST",
            "/rpc",
            {
                "jsonrpc": "2.0",
                "id": 15,
                "method": "module.update",
                "params": {"module_id": "vision", "enabled": True, "implementation_id": "fake-vision"},
            },
        )
        self.assertTrue(response["result"]["enabled"])
        status, response = self.request(
            "POST",
            "/rpc",
            {"jsonrpc": "2.0", "id": 16, "method": "vision.start", "params": {"source": "screen"}},
        )
        self.assertEqual(status, 400)
        self.assertIn("permission", response["error"]["message"])
        _, permission = self.request(
            "POST",
            "/rpc",
            {
                "jsonrpc": "2.0",
                "id": 17,
                "method": "vision.permission.set",
                "params": {"permission_id": "screen.read", "granted": True},
            },
        )
        self.assertEqual(next(item for item in permission["result"]["permissions"] if item["permission_id"] == "screen.read")["state"], "granted")
        status, started = self.request(
            "POST",
            "/rpc",
            {"jsonrpc": "2.0", "id": 18, "method": "vision.start", "params": {"source": "screen"}},
        )
        self.assertEqual(status, 200)
        self.assertTrue(next(item for item in started["result"]["sources"] if item["id"] == "screen")["running"])
        status, observed = self.request(
            "POST",
            "/rpc",
            {
                "jsonrpc": "2.0",
                "id": 19,
                "method": "vision.observe",
                "params": {"source": "screen", "mime_type": "image/png", "image_base64": "cHJpdmF0ZS1pbWFnZQ=="},
            },
        )
        self.assertEqual(status, 200)
        self.assertIn("summary", observed["result"])
        _, events = self.request("GET", "/api/events")
        event = next(item for item in events if item["event_type"] == "vision.observed")
        self.assertNotIn("private-image", json.dumps(event["payload"], ensure_ascii=False))
