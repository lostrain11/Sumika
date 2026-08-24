import unittest

from sumika_core.events import EventBus
from sumika_core.storage import Storage
from sumika_core.tasks import TaskError, TaskManager, TaskRunner


class TaskRunnerTests(unittest.TestCase):
    def setUp(self):
        self.storage = Storage()
        self.events = EventBus(self.storage)
        self.tasks = TaskManager(self.storage, self.events)
        self.runner = TaskRunner(self.tasks, self.events)

    def tearDown(self):
        self.storage.close()

    def test_unapproved_run_waits_then_approved_handler_completes(self):
        seen = []

        def handler(task):
            seen.append(task["id"])
            return {"summary": "测试完成", "checks": {"ok": True}}

        self.runner.register("test", handler)
        task = self.tasks.create(title="需要批准", autonomy_level="L2")
        waiting = self.runner.run(task["id"], handler_id="test")
        self.assertEqual(waiting["status"], "waiting_approval")
        self.assertEqual(seen, [])
        completed = self.runner.run(task["id"], handler_id="test", approved=True)
        self.assertEqual(completed["status"], "completed")
        self.assertEqual(completed["result"]["summary"], "测试完成")
        self.assertEqual(seen, [task["id"]])
        event_types = {event["event_type"] for event in self.storage.list_events()}
        self.assertIn("task.started", event_types)
        self.assertIn("task.completed", event_types)

    def test_handler_failure_is_recorded_without_escaping(self):
        def handler(task):
            raise RuntimeError("isolated failure")

        self.runner.register("fails", handler)
        task = self.tasks.create(title="会失败")
        result = self.runner.run(task["id"], handler_id="fails", approved=True)
        self.assertEqual(result["status"], "failed")
        self.assertIn("isolated failure", result["result"]["error"])

    def test_unknown_handler_is_rejected_before_running(self):
        task = self.tasks.create(title="未知执行器")
        with self.assertRaises(TaskError):
            self.runner.run(task["id"], handler_id="missing", approved=True)
        self.assertEqual(self.tasks.get(task["id"])["status"], "pending")
        with self.assertRaises(TaskError):
            self.runner.run(task["id"], handler_id="missing")
        self.assertEqual(self.tasks.get(task["id"])["status"], "pending")


if __name__ == "__main__":
    unittest.main()
