import unittest

from sumika_core.events import EventBus
from sumika_core.storage import Storage
from sumika_core.tasks import TaskError, TaskManager, TaskStatus


class TaskManagerTests(unittest.TestCase):
    def setUp(self):
        self.storage = Storage()
        self.events = EventBus(self.storage)
        self.manager = TaskManager(self.storage, self.events)

    def tearDown(self):
        self.storage.close()

    def test_create_update_and_audit_fields(self):
        task = self.manager.create(
            title="模块基准",
            autonomy_level="L2",
            budget={"token_limit": 1000, "time_limit_seconds": 60},
            permissions=["network.read"],
        )
        self.assertEqual(task["status"], TaskStatus.PENDING.value)
        self.assertEqual(task["budget"]["token_limit"], 1000)
        updated = self.manager.update(task["id"], status="waiting_approval", log="等待用户批准")
        self.assertEqual(updated["status"], TaskStatus.WAITING_APPROVAL.value)
        self.assertEqual(updated["logs"][-1]["message"], "等待用户批准")
        self.assertIn("task.updated", {event["event_type"] for event in self.storage.list_events()})

    def test_terminal_status_cannot_be_reopened(self):
        task = self.manager.create(title="完成任务")
        self.manager.update(task["id"], status="running")
        self.manager.update(task["id"], status="completed")
        with self.assertRaises(TaskError):
            self.manager.update(task["id"], status="running")

    def test_budget_and_progress_are_validated(self):
        with self.assertRaises(TaskError):
            self.manager.create(title="坏预算", budget={"token_limit": -1})
        with self.assertRaises(TaskError):
            self.manager.create(title="坏进度", progress=2)
