from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
import unittest

MCP_AVAILABLE = importlib.util.find_spec("mcp") is not None

_HOST_PROGRAM = r'''
from quality_routing import BudgetRule, Candidate, Coordinator, Outcome, Quote, Scope, Verification
from quality_routing.mcp_server import SubmissionAuthorization, create_server

scope = Scope("demo-owner", "demo-session")
coordinator = Coordinator(
    [Candidate("demo", "demo-account", "demo-model", "api", authorized=True, available=True, external=False, fixed_cash="0")],
    executor=lambda execution: Outcome("completed", "offline-result", cash_cny="0"),
    verifier=lambda execution, outcome: Verification(True, ("offline-check",)),
    permission=lambda execution: True,
)
def policy(action, bound_scope, value):
    if action == "submit":
        return SubmissionAuthorization(Quote("0", "0", "1", 2, 10000), BudgetRule(), frozenset({"demo"}))
    return action in {"revise", "advance"}
create_server(coordinator, scope, policy).run(transport="stdio")
'''


def _payload(result):
    structured = getattr(result, "structuredContent", None)
    if isinstance(structured, dict):
        return structured
    return json.loads(result.content[0].text)


@unittest.skipUnless(MCP_AVAILABLE, "optional mcp extra is not installed")
class McpStdioTests(unittest.TestCase):
    def test_stdio_contract_is_bounded_and_cannot_approve(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        async def exercise():
            params = StdioServerParameters(command=sys.executable, args=["-c", _HOST_PROGRAM])
            async with stdio_client(params) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    tools = await session.list_tools()
                    names = {tool.name for tool in tools.tools}
                    self.assertEqual(
                        names,
                        {
                            "quality_advance",
                            "quality_catalog",
                            "quality_result",
                            "quality_revise",
                            "quality_status",
                            "quality_submit",
                        },
                    )
                    self.assertFalse(any("approve" in name or "shell" in name or "key" in name for name in names))

                    catalog = _payload(await session.call_tool("quality_catalog"))
                    self.assertEqual(catalog["candidates"][0]["candidate_id"], "demo")
                    self.assertNotIn("account_id", catalog["candidates"][0])

                    plan = {
                        "task_id": "demo-task",
                        "revision": 1,
                        "nodes": [
                            {
                                "node_id": "first",
                                "goal": "Produce an offline value",
                                "task_type": "arithmetic",
                                "baseline_id": "demo",
                                "acceptance": ["value exists"],
                            }
                        ],
                    }
                    submitted = _payload(await session.call_tool("quality_submit", {"plan": plan}))
                    self.assertTrue(submitted["ok"])
                    self.assertEqual(submitted["task"]["status"], "awaiting-confirmation")

                    advanced = _payload(await session.call_tool("quality_advance", {"task_id": "demo-task"}))
                    self.assertFalse(advanced["ok"])
                    self.assertEqual(advanced["reason"], "task-not-preauthorized")

                    wrong_scope = dict(plan)
                    wrong_scope["task_id"] = "other-task"
                    wrong_scope["scope"] = {"owner_id": "other-owner", "session_id": "demo-session"}
                    rejected = _payload(await session.call_tool("quality_submit", {"plan": wrong_scope}))
                    self.assertFalse(rejected["ok"])
                    self.assertEqual(rejected["reason"], "invalid-plan")

        asyncio.run(exercise())

    def test_default_cli_starts_readonly_stdio_surface(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        async def exercise():
            params = StdioServerParameters(command=sys.executable, args=["-m", "quality_routing.mcp_server"])
            async with stdio_client(params) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    tools = await session.list_tools()
                    self.assertEqual({tool.name for tool in tools.tools}, {"quality_catalog", "quality_result", "quality_status"})
                    catalog = _payload(await session.call_tool("quality_catalog"))
                    self.assertEqual(catalog["candidates"], [])
                    self.assertEqual(
                        catalog["capabilities"],
                        {"read_only": True, "execution": "unavailable", "submission": "unavailable"},
                    )

        asyncio.run(exercise())


if __name__ == "__main__":
    unittest.main()
