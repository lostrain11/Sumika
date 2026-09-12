import io
import json
import secrets
import os
import re
import shutil
import subprocess
import threading
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from http.client import HTTPConnection
from unittest.mock import patch

from sumika_core.host_authorization import CONFIRMATION_METHODS, CallerContext, HostAuthorization, HostAuthorizationError, confirmation_digest, read_bootstrap, requires_confirmation
from sumika_core.server import create_server


class AuthorizationTests(unittest.TestCase):
    def test_conditional_policy_and_frontend_parity(self):
        cases = [
            ("audio.permission.set", {"permission": "microphone", "granted": False}, False),
            ("vision.permission.set", {"permission_id": "camera.read", "granted": False}, False),
            ("module.update", {"module_id": "tools", "enabled": False}, False),
            ("module.update", {"module_id": "tools", "enabled": False, "config": {}}, True),
            ("module.update", {"module_id": "tools", "enabled": False, "implementation_id": "external-process"}, True),
            ("skill.builtin.set", {"skill_id": "fixture", "enabled": False, "sha256": "abc"}, False),
            ("schedule.pause", {"schedule_id": "fixture", "paused": True}, False),
            ("schedule.pause", {"schedule_id": "fixture", "paused": False}, True),
            ("browser.web_chat.profile.consent", {"profile_id": "fixture", "enabled": False}, False),
            ("browser.web_chat.profile.consent", {"enabled": False, "allowed_actions": ["chat.send"]}, True),
            ("sumika.route.bridge_tools", {}, False),
            ("sumika.route.bridge_tools", {"register": False, "unregister": True}, False),
            ("sumika.route.bridge_tools", {"register": True}, True),
            ("model.policy.refresh", {"kind": "catalog"}, False),
            ("model.policy.refresh", {"interactive_allowed": True}, True),
            ("tool.run", {"approved": False, "input": {"approved": True}}, False),
            ("tool.run", {"approved": False, "request": {"approved": True}}, True),
            ("browser.action.execute", {"approved": False}, True),
            ("desktop.automation.act", {"approved": False, "request": {"approved": True}}, True),
            ("browser.action.check", {"approved": True}, False),
        ]
        for method in ("plugin.revoke", "plugin.reject",
                       "audio.stop", "vision.stop", "core.health", "agent.runtime.binding"):
            cases.append((method, {}, False))
        for method in ("agent.skills.revoke", "agent.skill.revoke"):
            cases.append((method, {}, True))
        for operation in ("list", "status", "revoke", "deny", "grant", "resolve", "approve", [], {}, ["deny"], None, 1):
            cases.append(("desktop.automation.approval", {"operation": operation},
                          operation not in ("list", "status", "revoke", "deny")))
        cases.extend([
            ("desktop.automation.approval", {"action": " REVOKE "}, False),
            ("desktop.automation.approval", {"operation": {}, "action": "grant"}, True),
            ("desktop.automation.approval", {"operation": "list", "action": []}, True),
        ])
        for value in (True, "false", "true", 0, 1, None, [], {}, {"approved": False}):
            for method, field in (("audio.permission.set", "granted"), ("vision.permission.set", "granted"),
                                  ("module.update", "enabled"), ("tool.run", "approved"),
                                  ("model.policy.refresh", "interactive_allowed"),
                                  ("sumika.route.bridge_tools", "register")):
                cases.append((method, {field: value}, True))
        authority = HostAuthorization()
        for method, params, expected in cases:
            with self.subTest(method=method, params=params):
                self.assertIs(requires_confirmation(method, params), expected)
                if expected:
                    with self.assertRaises(HostAuthorizationError):
                        authority.require(None, method, params)
                else:
                    authority.require(None, method, params)
        node = shutil.which("node")
        if node is None:
            self.skipTest("Node is required for cross-language policy parity")
        root = Path(__file__).resolve().parents[2]
        module = (root / "frontend/src/host-confirmation.js").as_uri()
        script = f'import {{ requiresHostConfirmation }} from {json.dumps(module)}; '
        script += 'let input=""; for await (const chunk of process.stdin) input += chunk; '
        script += 'process.stdout.write(JSON.stringify(JSON.parse(input).map(([method,params]) => requiresHostConfirmation(method,params))));'
        result = subprocess.run([node, "--input-type=module", "-e", script], input=json.dumps(cases),
                                text=True, capture_output=True, check=True, timeout=20)
        self.assertEqual(json.loads(result.stdout), [expected for _, _, expected in cases])

    def test_finite_native_and_frontend_allowlists_match_backend(self):
        root = Path(__file__).resolve().parents[2]
        frontend = (root / "frontend/src/host-confirmation.js").read_text(encoding="utf-8")
        native = (root / "src-tauri/src/host_authorization.rs").read_text(encoding="utf-8")
        js_methods = set(re.findall(r'"([a-z][a-z_.]+)"', frontend.split("]);", 1)[0]))
        native_methods = set(re.findall(r'"([a-z][a-z_.]+)"', native.split("fn allowed_action", 1)[1].split("#[tauri::command]", 1)[0]))
        expected = CONFIRMATION_METHODS - {"agent.event.ingest", "work.task.merge.apply", "work.task.merge.undo"}
        self.assertEqual(js_methods, expected)
        self.assertEqual(native_methods, expected)
        for method in CONFIRMATION_METHODS:
            authority = HostAuthorization("a" * 64)
            params = {"approved": True}
            digest = confirmation_digest(method, params)
            caller = authority.authenticate("a" * 64, method, params, digest)
            authority.require(caller, method, params)

    def test_process_proof_vector_and_challenge_binding(self):
        authority = HostAuthorization("a" * 64)
        proof = authority.process_proof("b" * 64, 1234)
        self.assertEqual(proof["proof"], "ab00a98b18dfb2d71ebf89c76313b693a35a32e2fb448929a2cdc332f3bd668b")
        for changed in (authority.process_proof("c" * 64, 1234), authority.process_proof("b" * 64, 1235),
                        HostAuthorization("d" * 64).process_proof("b" * 64, 1234)):
            self.assertNotEqual(proof["proof"], changed["proof"])
        self.assertNotIn("a" * 64, str(proof))

    def test_process_proof_requires_bootstrap_and_bounded_challenge(self):
        with self.assertRaises(HostAuthorizationError):
            HostAuthorization().process_proof("b" * 64, 1234)
        authority = HostAuthorization("a" * 64)
        for nonce in (None, "", "b" * 65, "B" * 64, "中文" * 32, {"nonce": "b" * 64}):
            with self.assertRaises(HostAuthorizationError):
                authority.process_proof(nonce, 1234)
        for pid in (True, 0, -1, "1234", 2**32):
            with self.assertRaises(HostAuthorizationError):
                authority.process_proof("b" * 64, pid)

    def test_action_and_payload_binding_and_restart(self):
        secret = secrets.token_hex(32)
        authority = HostAuthorization(secret)
        method = "work.authorization.confirm"
        params = {"request_id": "request", "revision": 1, "max_cny": "1"}
        caller = authority.authenticate(secret, method, params, confirmation_digest(method, params))
        authority.require(caller, method, params)
        for invalid in (None, CallerContext(method, caller.request_digest, object())):
            with self.assertRaises(HostAuthorizationError):
                authority.require(invalid, method, params)
        with self.assertRaises(HostAuthorizationError):
            authority.require(caller, method, {**params, "max_cny": "2"})
        with self.assertRaises(HostAuthorizationError):
            HostAuthorization(secret).require(caller, method, params)
        with self.assertRaises(HostAuthorizationError):
            HostAuthorization(secrets.token_hex(32)).authenticate(secret, method, params, caller.request_digest)

    def test_bootstrap_only_explicit_bounded_schema(self):
        secret = secrets.token_hex(32)
        self.assertEqual(read_bootstrap(io.StringIO(json.dumps({"schema": "sumika-host/v1", "secret": secret}) + "\n")), secret)
        for frame in ('{}\n', '{"schema":"sumika-host/v1","secret":null}\n', 'x' * 1025, ''):
            with self.assertRaises(HostAuthorizationError):
                read_bootstrap(io.StringIO(frame))

    def test_secret_is_not_a_general_rpc_credential(self):
        secret = secrets.token_hex(32)
        with self.assertRaisesRegex(HostAuthorizationError, "unsupported"):
            HostAuthorization(secret).authenticate(secret, "chat.send", {}, "a" * 64)

    def test_schedules_and_agent_permissions_require_trusted_caller(self):
        authority = HostAuthorization()
        for method in ("schedule.create", "schedule.update", "schedule.pause", "agent.approval.respond",
                       "agent.question.respond", "quality.task.budget", "work.task.merge.apply", "work.task.merge.undo"):
            with self.subTest(method=method), self.assertRaises(HostAuthorizationError):
                authority.require(None, method, {"approved": True, "outcome": "allow"})


class AuthorizationHttpTests(unittest.TestCase):
    def test_sensitive_rpc_rejects_before_dispatch_even_with_forged_nested_approval(self):
        params = {"approved": True, "trusted": True, "actor": "host", "register": True,
                  "request": {"approved": True}, "operation": "grant", "interactive_allowed": True}
        with patch.object(self.app, "_rpc") as dispatch:
            for method in sorted(CONFIRMATION_METHODS):
                for supplied in (None, self.secret):
                    with self.subTest(method=method, secret=bool(supplied)):
                        result = self.post("/rpc", {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}, supplied)
                        self.assertEqual(result["error"]["code"], -32041)
            dispatch.assert_not_called()

    def test_pure_revocations_reach_dispatch_without_host_and_mutations_do_not(self):
        cases = [("module.update", {"module_id": "tools", "enabled": False}),
                 ("audio.permission.set", {"permission_id": "microphone", "granted": False}),
                 ("vision.permission.set", {"permission_id": "screen.read", "granted": False}),
                 ("schedule.pause", {"assistant_id": "sumika", "schedule_id": "fixture", "paused": True}),
                 ("browser.web_chat.profile.consent", {"profile_id": "fixture", "enabled": False}),
                 ("desktop.automation.approval", {"operation": "deny", "approval_id": "fixture"})]
        with patch.object(self.app, "_rpc", return_value={"accepted": True}) as dispatch:
            for method, params in cases:
                with self.subTest(method=method):
                    result = self.post("/rpc", {"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
                    self.assertTrue(result["result"]["accepted"])
            self.assertEqual(dispatch.call_count, len(cases))

    def test_native_bridge_requires_bound_origin_but_no_user_approval_field(self):
        for operation in ("attach", "poll", "complete", "alive", "bind_portal"):
            method = f"browser.embedded.{operation}"
            params = {"token": "fixture", "attempt_id": "attempt"}
            with self.subTest(operation=operation), patch.object(self.app, "_rpc", return_value={"accepted": True}) as dispatch:
                payload = {"method": method, "params": params, "digest": confirmation_digest(method, params)}
                changed = {**payload, "params": {**params, "attempt_id": "other"}}
                self.assertEqual(self.post("/internal/host-confirm/v1", changed, self.secret)["error"]["code"], -32041)
                dispatch.assert_not_called()
                self.assertTrue(self.post("/internal/host-confirm/v1", payload, self.secret)["result"]["accepted"])
                dispatch.assert_called_once_with(method, params)

    def test_unapproved_tool_call_cannot_resolve_launcher_or_start_process(self):
        module = {"enabled": True, "implementation_id": "external-process", "config": {"require_approval": False}}
        with patch.object(self.app.modules, "get", return_value=module), \
                patch("sumika_core.tools.runtime._resolve_config") as resolve, \
                patch("sumika_core.tools.runtime.subprocess.Popen") as process:
            for params in ({"approved": False}, {"input": {"approved": True}}):
                result = self.post("/rpc", {"jsonrpc": "2.0", "id": 1, "method": "tool.run", "params": params})
                self.assertEqual(result["error"]["code"], -32014)
            resolve.assert_not_called()
            process.assert_not_called()

    def setUp(self):
        self.env = patch.dict("os.environ", {"SUMIKA_AGENT_RUNTIME": "none", "SUMIKA_AGENT_AUTOSTART": "0"})
        self.env.start()
        self.secret = secrets.token_hex(32)
        self.server, self.app = create_server("127.0.0.1", 0, ":memory:", host_secret=self.secret)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)
        self.app.close()
        self.env.stop()

    def post(self, path, payload, secret=None):
        connection = HTTPConnection("127.0.0.1", self.server.server_address[1], timeout=5)
        try:
            headers = {"Content-Type": "application/json"}
            if secret:
                headers["X-Sumika-Host"] = secret
            connection.request("POST", path, json.dumps(payload), headers)
            return json.loads(connection.getresponse().read())
        finally:
            connection.close()

    def test_http_body_cannot_forge_confirmation_and_token_not_valid_on_rpc(self):
        with patch.object(self.app.work, "confirm") as confirm:
            for secret in (None, self.secret):
                result = self.post("/rpc", {"jsonrpc": "2.0", "id": 1, "method": "work.authorization.confirm",
                                  "params": {"approved": True, "trusted": True, "actor": "host"}}, secret)
                self.assertEqual(result["error"]["code"], -32041)
            confirm.assert_not_called()

    def test_identity_endpoint_uses_own_pid_and_never_accepts_requested_pid(self):
        nonce = secrets.token_hex(32)
        result = self.post("/internal/host-identity/v1", {"nonce": nonce})
        self.assertEqual(result, HostAuthorization(self.secret).process_proof(nonce, os.getpid()))
        rejected = self.post("/internal/host-identity/v1", {"nonce": nonce, "pid": 1234})
        self.assertEqual(rejected["error"]["code"], -32602)
        rejected = self.post("/internal/host-identity/v1", {"nonce": "bad"})
        self.assertEqual(rejected["error"]["code"], -32041)
        self.assertNotIn(self.secret, str(result))
        with patch.object(self.app, "host_authorization", HostAuthorization()):
            self.assertEqual(self.post("/internal/host-identity/v1", {"nonce": nonce})["error"]["code"], -32041)

    def test_authenticated_transport_calls_only_bound_action_once(self):
        params = {"request_id": "fixture", "revision": 1}
        method = "work.authorization.confirm"
        payload = {"method": method, "params": params, "digest": confirmation_digest(method, params)}
        with patch.object(self.app.work, "confirm", return_value={"status": "ready"}) as confirm:
            self.assertEqual(self.post("/internal/host-confirm/v1", payload)["error"]["code"], -32041)
            self.assertEqual(self.post("/internal/host-confirm/v1", payload, self.secret)["result"]["status"], "ready")
            confirm.assert_called_once_with(params)
            changed = {**payload, "params": {**params, "revision": 2}}
            self.assertEqual(self.post("/internal/host-confirm/v1", changed, self.secret)["error"]["code"], -32041)
            self.assertEqual(confirm.call_count, 1)

    def test_plan_review_cannot_bypass_native_confirmation(self):
        params = {"rpcId": "plan", "sessionId": "session", "approved": True,
                  "answer": {"answers": [{"id": "plan-review", "selected": ["Approve"]}]}}
        method = "agent.question.respond"
        with patch.object(self.app.agent, "respond_interaction") as respond, \
                patch.object(self.app.workspace, "create_checkpoint") as checkpoint:
            result = self.post("/rpc", {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}, self.secret)
            self.assertEqual(result["error"]["code"], -32041)
            respond.assert_not_called()
            checkpoint.assert_not_called()

    def test_mcp_preview_and_approved_body_are_not_authorization(self):
        method = "agent.mcp.configuration.apply"
        params = {"agentPreset": "sumika-work", "previewToken": "fixture-preview", "approved": True,
                  "confirm_agent_preset": "sumika-work", "credentialValue": "fixture-secret"}
        with patch.object(self.app.agent, "apply_mcp_configuration", return_value={"applied": True}) as apply:
            for secret in (None, self.secret):
                result = self.post("/rpc", {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}, secret)
                self.assertEqual(result["error"]["code"], -32041)
            apply.assert_not_called()
            payload = {"method": method, "params": params, "digest": confirmation_digest(method, params)}
            changed = {**payload, "params": {**params, "credentialValue": "changed"}}
            self.assertEqual(self.post("/internal/host-confirm/v1", changed, self.secret)["error"]["code"], -32041)
            apply.assert_not_called()
            self.assertTrue(self.post("/internal/host-confirm/v1", payload, self.secret)["result"]["applied"])
            apply.assert_called_once_with({"agentPreset": "sumika-work", "previewToken": "fixture-preview", "credentialValue": "fixture-secret"})
            self.assertNotIn("fixture-secret", str(self.app.storage.list_events(20)))

    def test_workspace_write_methods_reject_forged_confirmation_before_file_access(self):
        params = {"approved": True, "trusted": True, "actor": "host", "preview_token": "a" * 64,
                  "path": "D:/fixture", "source_path": "D:/fixture", "destination_path": "D:/fixture-copy",
                  "branch": "codex/fixture", "confirm_branch": "codex/fixture",
                  "confirm_destination": "D:/fixture-copy", "checkpoint_id": "wschk-" + "a" * 20,
                  "confirm_checkpoint": "wschk-" + "a" * 20, "message": "fixture"}
        for method, operation in (("workspace.worktree.create", "create_worktree"),
                                  ("workspace.commit", "commit"), ("workspace.restore", "restore")):
            with self.subTest(method=method), patch.object(self.app.workspace, operation) as write:
                for secret in (None, self.secret):
                    result = self.post("/rpc", {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}, secret)
                    self.assertEqual(result["error"]["code"], -32041)
                payload = {"method": method, "params": params, "digest": confirmation_digest(method, params)}
                changed = {**payload, "params": {**params, "path": "D:/changed"}}
                self.assertEqual(self.post("/internal/host-confirm/v1", changed, self.secret)["error"]["code"], -32041)
                write.assert_not_called()

    def test_skill_aliases_require_host_and_revoke_retains_source(self):
        with TemporaryDirectory() as directory:
            source = Path(directory) / "SKILL.md"
            source.write_text("---\nname: Fixture\ndescription: fixture\n---\nPrivate body\n", encoding="utf-8")
            candidate = self.app.rpc("agent.skills.discover", {"paths": [directory]})["skills"][0]
            params = {"candidate_id": candidate["candidate_id"], "approved": True,
                      "confirm_skill_id": candidate["candidate_id"]}
            for prefix in ("agent.skills", "agent.skill"):
                for action, state in (("approve", "approved"), ("revoke", "revoked")):
                    method = f"{prefix}.{action}"
                    with self.subTest(method=method):
                        with patch.object(self.app.skills, action) as mutation:
                            for secret in (None, self.secret):
                                denied = self.post("/rpc", {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}, secret)
                                self.assertEqual(denied["error"]["code"], -32041)
                            mutation.assert_not_called()
                        payload = {"method": method, "params": params, "digest": confirmation_digest(method, params)}
                        result = self.post("/internal/host-confirm/v1", payload, self.secret)
                        self.assertEqual(result["result"]["state"], state)
                        self.assertTrue(source.exists())
            self.assertNotIn("Private body", str(self.app.storage.list_events(20)))

    def test_retry_is_blocked_before_quote_checkpoint_or_replay_even_with_host_confirmation(self):
        method = "agent.session.retry"
        with patch.object(self.app.legacy_work, "dispatch") as dispatch, \
                patch.object(self.app.agent, "execution_quote") as quote, \
                patch.object(self.app.agent, "retry_prompt") as replay, \
                patch.object(self.app.workspace, "create_checkpoint") as checkpoint:
            for state in ("failed", "cancelled", "unknown", "definitely-not-sent"):
                params = {"sessionId": "fixture", "approved": True, "confirmSessionId": "fixture",
                          "submission_state": state, "possibly_sent": False, "revision": 999}
                with self.subTest(state=state):
                    denied = self.post("/rpc", {"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
                    self.assertEqual(denied["error"]["code"], -32041)
                    payload = {"method": method, "params": params, "digest": confirmation_digest(method, params)}
                    for _attempt in range(2):
                        result = self.post("/internal/host-confirm/v1", payload, self.secret)
                        self.assertEqual(result["error"]["code"], -32042)
            preflight = self.post("/rpc", {"jsonrpc": "2.0", "id": 1,
                                          "method": "agent.session.retry.preflight", "params": {"session_id": "fixture"}})["result"]
            self.assertFalse(preflight["retry_allowed"])
            self.assertEqual(preflight["allowed_actions"], ["inspect"])
            self.assertEqual(preflight["submission"], "unverified")
            for operation in (dispatch, quote, replay, checkpoint):
                operation.assert_not_called()
