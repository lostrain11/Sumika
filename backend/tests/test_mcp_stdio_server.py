import json
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SERVER = ROOT / "backend" / "tests" / "fixtures" / "mcp_stdio_server.py"


class McpStdioServerTests(unittest.TestCase):
    def test_standard_handshake_lists_and_calls_echo_tool(self):
        requests = [
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "test", "version": "1"}},
            },
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "echo", "arguments": {"text": "roundtrip"}},
            },
        ]
        completed = subprocess.run(
            [sys.executable, str(SERVER)],
            input="".join(json.dumps(item) + "\n" for item in requests),
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        responses = [json.loads(line) for line in completed.stdout.splitlines()]
        self.assertEqual([item["id"] for item in responses], [1, 2, 3])
        self.assertEqual(responses[0]["result"]["protocolVersion"], "2025-06-18")
        self.assertEqual(responses[1]["result"]["tools"][0]["name"], "echo")
        self.assertEqual(
            responses[2]["result"]["structuredContent"]["marker"],
            "SUMIKA_MCP_ECHO:roundtrip",
        )


if __name__ == "__main__":
    unittest.main()
