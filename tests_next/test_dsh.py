import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from sumika_next.authorization import AuthorizationError
from sumika_next.contracts import ToolRequest, WorkBinding
from sumika_next.contracts import HarnessInstance, Trust
from sumika_next.dsh import Dsh, DshError


class ResponseOpener:
    def __init__(self, transform):
        self.transform = transform

    def open(self, request, **kwargs):
        body = json.loads(request.data)
        result = {"type":"server-response", "rpcId":body["rpcId"], "result":{"ok":True, "value":{"accepted":True}}}
        return io.BytesIO(json.dumps(self.transform(result)).encode())


class DshTests(unittest.TestCase):
    def setUp(self):
        self.adapter = Dsh(Path.cwd(), Path.cwd()/".sumika-next/test-only")
        self.adapter.url = "http://127.0.0.1:12345"

    def test_unverified_adapter_cannot_execute(self):
        binding = WorkBinding(self.adapter.instance.instance_id, "r", 1, "s", "step")
        with self.assertRaises(AuthorizationError):
            self.adapter.execute(ToolRequest(binding, "session.create", "any"))

    def test_business_error_is_not_success(self):
        self.adapter._opener = ResponseOpener(lambda r: {**r, "result":{"ok":False,"error":{"code":"gateway/bad-request"}}})
        with self.assertRaises(DshError): self.adapter._rpc("session/create", {})

    def test_mismatched_reply_is_rejected(self):
        self.adapter._opener = ResponseOpener(lambda r: {**r,"rpcId":"another-request"})
        with self.assertRaises(DshError): self.adapter._rpc("session/create", {})

    def test_malformed_reply_is_rejected(self):
        self.adapter._opener = ResponseOpener(lambda r: {"approved":True})
        with self.assertRaises(DshError): self.adapter._rpc("session/create", {})

    def test_valid_reply_unwraps_value(self):
        self.adapter._opener = ResponseOpener(lambda r:r)
        self.assertEqual(self.adapter._rpc("session/cancel", {}), {"accepted":True})

    def test_prompt_has_no_implicit_model_dispatch(self):
        self.adapter.instance = HarnessInstance("dsh", "owned", Trust.MANAGED)
        binding = WorkBinding("owned", "r", 1, "s", "step")
        with patch.object(self.adapter, "_check_owner"), patch.object(self.adapter, "_rpc") as rpc:
            with self.assertRaises(AuthorizationError):
                self.adapter.execute(ToolRequest(binding, "session.prompt", "s", b'{}'))
            rpc.assert_not_called()

    def test_create_cannot_change_approved_workspace(self):
        self.adapter.instance = HarnessInstance("dsh", "owned", Trust.MANAGED)
        binding = WorkBinding("owned", "r", 1, "s", "step")
        args = json.dumps({"sessionId":"s", "cwd":str(Path.cwd())}).encode()
        with patch.object(self.adapter, "_check_owner"), patch.object(self.adapter, "_rpc") as rpc:
            with self.assertRaises(AuthorizationError):
                self.adapter.execute(ToolRequest(binding, "session.create", "different", args))
            rpc.assert_not_called()

    def test_session_mismatch_rejected_before_rpc(self):
        self.adapter.instance = HarnessInstance("dsh", "owned", Trust.MANAGED)
        binding = WorkBinding("owned", "r", 1, "s", "step")
        with patch.object(self.adapter, "_check_owner"), patch.object(self.adapter, "_rpc") as rpc:
            with self.assertRaises(AuthorizationError):
                self.adapter.execute(ToolRequest(binding, "session.cancel", "other", b'{"sessionId":"other"}'))
            rpc.assert_not_called()

    def test_release_tamper_rejected_before_launch(self):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime = root / "runtime/dsh"
            runtime.mkdir(parents=True)
            (runtime/"package.json").write_text("changed")
            (runtime/"release.json").write_text(json.dumps({"files":{"package.json":"wrong"}}))
            adapter = Dsh(root, root/"home")
            with patch("sumika_next.dsh.subprocess.Popen") as launch:
                with self.assertRaises(DshError): adapter.start()
                launch.assert_not_called()
