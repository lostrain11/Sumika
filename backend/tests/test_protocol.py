import unittest

from sumika_core.protocol.jsonrpc import JsonRpcError, parse_request, success
from sumika_core.protocol.models import EventEnvelope, Message


class ProtocolTests(unittest.TestCase):
    def test_message_and_event_are_serialisable(self):
        message = Message("user", "hello")
        event = EventEnvelope("message.created", {"message": message.to_dict()})
        self.assertEqual(event.to_dict()["event_type"], "message.created")
        self.assertEqual(event.to_dict()["payload"]["message"]["content"], "hello")

    def test_jsonrpc_request(self):
        request = parse_request({"jsonrpc": "2.0", "id": 1, "method": "core.health", "params": {}})
        self.assertEqual(request.method, "core.health")
        self.assertEqual(success(request.request_id, {"ok": True})["result"]["ok"], True)

    def test_jsonrpc_rejects_invalid_version(self):
        with self.assertRaises(JsonRpcError):
            parse_request({"jsonrpc": "1.0", "id": 1, "method": "core.health"})
