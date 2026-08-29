import json
import threading
import unittest
from tempfile import TemporaryDirectory
from pathlib import Path

from sumika_core.agent import AgentCapability, AgentRuntime
from sumika_core.storage import Storage
from sumika_core.tasks import AgentTaskProjector


class ProjectionRuntime(AgentRuntime):
    runtime_id = "projection-test"
    capability_ids = frozenset({AgentCapability.INTERACTIONS, AgentCapability.WORKSPACES})

    def status(self):
        return {"ready": True, "state": "ready"}

    def health(self):
        return {"ok": True}

    def create_session(self, params):
        raise NotImplementedError

    def list_sessions(self, params=None):
        return {
            "sessions": [
                {"id": "running", "title": "Coding", "state": "running", "blank": False},
                {"id": "waiting", "title": "Approval", "state": "running", "blank": False},
            ]
        }

    def snapshot(self, params):
        session_id = params["sessionId"]
        return {
            "session_id": session_id,
            "state": "running" if session_id == "running" else "completed",
            "title": "Projected " + session_id,
            "plan": {"active": True, "steps": [{"status": "completed"}, {"status": "running"}]},
            "timeline": [{"type": "turn/start", "seq": 1}, {"type": "step/start", "seq": 2}],
            "artifacts": [{"type": "diff", "label": "workspace diff"}],
            "stats": {"turns": 2, "decodeTokens": 12},
            "token_usage": {
                "uncachedInputTokens": 100,
                "outputTokens": 12,
                "cacheReadTokens": 20,
            },
            "context": {"projectedTokens": 42, "contextWindow": 1000},
            "context_breakdown": {"systemTokens": 5, "toolsTokens": 7, "messageTokens": 30},
            "turns": [
                {
                    "id": "turn:1",
                    "status": "completed",
                    "mode": "execute",
                    "steps": 2,
                    "tools": 1,
                    "approvals": 1,
                    "artifacts": 1,
                }
            ],
        }

    def prompt(self, params):
        raise NotImplementedError

    def cancel(self, params):
        raise NotImplementedError

    def interactions(self, params=None):
        return {
            "interactions": [
                {"id": "approval-1", "kind": "approval", "session_id": "waiting", "action": "pwsh"}
            ]
        }

    def list_workspaces(self, params=None):
        return {
            "workspaces": [
                {"id": "workspace-1", "title": "Sumika", "path": "D:\\Code\\Sumika", "session_ids": ["running", "waiting"]}
            ]
        }


class ConcurrentProjectionRuntime(ProjectionRuntime):
    def __init__(self):
        self.barrier = threading.Barrier(2)
        self.completed_snapshots = 0

    def snapshot(self, params):
        self.barrier.wait(timeout=2)
        self.completed_snapshots += 1
        return super().snapshot(params)


class ConcurrentWorkspaceProjectionRuntime(ProjectionRuntime):
    def list_workspaces(self, params=None):
        return {
            "workspaces": [
                {"id": "workspace-1", "title": "Sumika A", "path": "D:\\Code\\Sumika-A", "session_ids": ["running"]},
                {"id": "workspace-2", "title": "Sumika B", "path": "D:\\Code\\Sumika-B", "session_ids": ["waiting"]},
            ]
        }


class WorkspaceProjectionStub:
    def __init__(self):
        self.calls = 0

    def inspect(self, path):
        self.calls += 1
        return {
            "workspace": {"branch": "codex/test", "head": "abc123", "dirty": True, "file_count": 2},
            "checkpoint_count": 3,
        }


class ConcurrentWorkspaceProjectionStub(WorkspaceProjectionStub):
    def __init__(self):
        super().__init__()
        self.barrier = threading.Barrier(2)

    def inspect(self, path):
        self.barrier.wait(timeout=2)
        return super().inspect(path)


class AgentTaskProjectionTests(unittest.TestCase):
    def test_snapshot_requests_are_read_concurrently_with_stable_task_order(self):
        runtime = ConcurrentProjectionRuntime()

        result = AgentTaskProjector(runtime).project()

        self.assertEqual([task["session_id"] for task in result["tasks"]], ["running", "waiting"])
        self.assertEqual(runtime.completed_snapshots, 2)
        self.assertEqual(result["errors"], [])

    def test_distinct_workspace_inspections_are_bounded_and_concurrent(self):
        workspace = ConcurrentWorkspaceProjectionStub()

        result = AgentTaskProjector(ConcurrentWorkspaceProjectionRuntime(), workspace).project()

        self.assertEqual(workspace.calls, 2)
        self.assertEqual(
            [task["workspace"]["id"] for task in result["tasks"]],
            ["workspace-1", "workspace-2"],
        )

    def test_projects_sessions_as_read_only_tasks_and_caches_workspace_evidence(self):
        workspace = WorkspaceProjectionStub()
        result = AgentTaskProjector(ProjectionRuntime(), workspace).project()

        self.assertTrue(result["available"])
        self.assertTrue(result["read_only"])
        self.assertEqual(len(result["tasks"]), 2)
        running, waiting = result["tasks"]
        self.assertEqual(running["status"], "running")
        self.assertEqual(running["progress"], 0.5)
        self.assertTrue(running["read_only"])
        self.assertEqual(running["metrics"]["stats"]["decodeTokens"], 12)
        self.assertEqual(running["metrics"]["token_usage"]["uncachedInputTokens"], 100)
        self.assertEqual(running["metrics"]["context_breakdown"]["toolsTokens"], 7)
        self.assertEqual(running["turns"][0]["id"], "turn:1")
        self.assertEqual(running["result"]["turns"][0]["tools"], 1)
        self.assertEqual(running["workspace"]["checkpoint_count"], 3)
        self.assertEqual(waiting["status"], "waiting_approval")
        self.assertEqual(waiting["permissions"], ["pwsh"])
        self.assertEqual(workspace.calls, 1)

    def test_unavailable_runtime_returns_no_fake_tasks(self):
        runtime = ProjectionRuntime()
        runtime.status = lambda: {"ready": False, "reason": "offline"}
        result = AgentTaskProjector(runtime).project()
        self.assertFalse(result["available"])
        self.assertEqual(result["tasks"], [])
        self.assertEqual(result["reason"], "offline")

    def test_projection_does_not_invent_a_zero_budget(self):
        result = AgentTaskProjector(ProjectionRuntime()).project()
        for task in result["tasks"]:
            self.assertFalse(task["budget"]["available"])
            self.assertNotIn("token_limit", task["budget"])
            self.assertIn("Runtime 未提供任务预算上限", task["budget"]["reason"])

    def test_projection_cache_survives_restart_and_is_explicitly_stale(self):
        with TemporaryDirectory() as directory:
            database = Path(directory) / "sumika.sqlite3"
            storage = Storage(database)
            runtime = ProjectionRuntime()
            live = AgentTaskProjector(runtime, storage=storage).project()
            self.assertEqual(live["projection_state"], "live")
            self.assertTrue(live["tasks"][0]["last_synced_at"])
            storage.close()

            reopened = Storage(database)
            offline = ProjectionRuntime()
            offline.status = lambda: {"ready": False, "reason": "runtime offline"}
            result = AgentTaskProjector(offline, storage=reopened).project()
            self.assertFalse(result["available"])
            self.assertEqual(result["projection_state"], "stale")
            self.assertEqual(len(result["tasks"]), 2)
            self.assertTrue(all(item["stale"] for item in result["tasks"]))
            self.assertTrue(all(item["projection_state"] == "stale" for item in result["tasks"]))
            self.assertTrue(all(item["title"] == "Agent 会话（最后已知）" for item in result["tasks"]))
            reopened.close()

    def test_cache_is_not_in_user_snapshot_and_drops_conversation_bearing_fields(self):
        storage = Storage()
        task = {
            "runtime_id": "projection-test",
            "session_id": "sensitive-session",
            "title": "用户密码 secret-title",
            "status": "running",
            "progress": 0.5,
            "result": {
                "summary": "private chat body",
                "plan": {
                    "active": True,
                    "pending": True,
                    "steps": [{"id": "step-1", "title": "do private thing", "status": "running"}],
                },
            },
            "permissions": ["private approval reason", "pwsh"],
            "logs": [{"type": "evil", "message": "chat body", "seq": 4}],
            "artifacts": [{"type": "diff", "label": "private patch", "path": "D:/private/file.py"}],
            "metrics": {"stats": {"turns": 1, "secret": 99}},
            "workspace": {
                "id": "D:/private/workspace",
                "title": "private workspace",
                "branch": "private-branch",
                "dirty": True,
                "file_count": 2,
            },
            "updated_at": "not-a-timestamp",
        }
        # The projector only writes its redacted shape; storage remains a
        # second validation boundary for callers that bypass it.
        stored = storage.upsert_agent_task_projection(task)
        serialized = json.dumps(stored, ensure_ascii=False)
        for secret in ("private", "secret", "chat body", "password", "D:/", "do private thing"):
            self.assertNotIn(secret, serialized)
        self.assertEqual(stored["result"]["plan"]["step_count"], 1)
        self.assertEqual(stored["permissions"], ["user-confirmation", "pwsh"])
        self.assertTrue(stored["workspace"]["id"].startswith("workspace-"))
        snapshot = storage.export_snapshot_state("system")
        self.assertNotIn("agent_task_projections", snapshot["tables"])
        storage.close()

    def test_cache_bounds_lists_numbers_and_non_finite_values(self):
        storage = Storage()
        projection = {
            "runtime_id": "dsh",
            "session_id": "s1",
            "status": "not-a-status",
            "progress": float("nan"),
            "permissions": ["unknown"] * 100,
            "logs": [{"type": "turn/start", "seq": index} for index in range(100)],
            "metrics": {"stats": {"turns": float("inf"), "steps": 3}},
            "result": {
                "turns": [
                    {
                        "id": "turn:1",
                        "status": "completed",
                        "steps": 2,
                        "tools": 1,
                        "approvals": 0,
                        "artifacts": 0,
                        "prompt": "must not persist",
                    },
                    {"id": "bad id", "status": "completed"},
                ]
            },
            "budget": {"available": True, "token_limit": -1, "time_limit_seconds": 20},
        }
        stored = storage.upsert_agent_task_projection(projection)
        self.assertEqual(stored["status"], "unknown")
        self.assertEqual(stored["progress"], 0.0)
        self.assertLessEqual(len(stored["permissions"]), 16)
        self.assertLessEqual(len(stored["logs"]), 16)
        self.assertNotIn("turns", stored["metrics"].get("stats", {}))
        self.assertNotIn("token_limit", stored["budget"])
        self.assertEqual(stored["budget"]["time_limit_seconds"], 20)
        self.assertEqual(stored["result"]["turns"][0]["id"], "turn:1")
        self.assertNotIn("must not persist", json.dumps(stored))
        self.assertEqual(len(stored["result"]["turns"]), 1)
        storage.close()


if __name__ == "__main__":
    unittest.main()
