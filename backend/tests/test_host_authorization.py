import io
import json
import secrets
import threading
import unittest
from http.client import HTTPConnection
from unittest.mock import patch

from sumika_core.host_authorization import CallerContext, HostAuthorization, HostAuthorizationError, confirmation_digest, read_bootstrap
from sumika_core.server import create_server


class AuthorizationTests(unittest.TestCase):
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
