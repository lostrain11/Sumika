import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from extensions.desktop.scheduler import Schedule
from ui.schedule import ScheduleController


class ScheduleControllerTests(unittest.TestCase):
    def _controller(self, folder):
        controller = ScheduleController(folder)
        controller.store.upsert(Schedule(id="daily-anime", kind="daily", expression="21:00",
                                        action="提醒小林看动画", mode="reminder",
                                        timezone_name="Asia/Shanghai"))
        controller.store.upsert(Schedule(id="exec-task", kind="daily", expression="09:00",
                                        action="运行每日构建", mode="execute",
                                        timezone_name="Asia/Shanghai"))
        return controller

    def test_state_lists_definitions_with_next_due_and_blocked_execution(self):
        with tempfile.TemporaryDirectory() as d:
            state = self._controller(d).state()
            ids = {item["id"] for item in state["definitions"]}
            self.assertEqual(ids, {"daily-anime", "exec-task"})
            reminder = next(i for i in state["definitions"] if i["id"] == "daily-anime")
            self.assertIsNotNone(reminder["next_due"])
            self.assertEqual(reminder["timezone_name"], "Asia/Shanghai")
            self.assertEqual([b["id"] for b in state["status"]["blocked"]], ["exec-task"])
            self.assertEqual(state["reminders"], [])

    def test_toggle_remove_and_unknown_id(self):
        with tempfile.TemporaryDirectory() as d:
            controller = self._controller(d)
            self.assertEqual(controller.toggle("daily-anime", False), {"id": "daily-anime", "enabled": False})
            disabled = next(i for i in controller.state()["definitions"] if i["id"] == "daily-anime")
            self.assertFalse(disabled["enabled"])
            self.assertEqual(controller.toggle("daily-anime", True), {"id": "daily-anime", "enabled": True})
            self.assertTrue(next(i for i in controller.state()["definitions"]
                                 if i["id"] == "daily-anime")["enabled"])
            controller.remove("exec-task")
            self.assertEqual([i["id"] for i in controller.state()["definitions"]], ["daily-anime"])
            with self.assertRaisesRegex(ValueError, "unknown schedule"):
                controller.toggle("missing", True)
            with self.assertRaises(ValueError):
                controller.toggle("daily-anime", "yes")
            with self.assertRaises(ValueError):
                controller.acknowledge("")

    def test_reminders_are_durable_and_acknowledged_locally(self):
        with tempfile.TemporaryDirectory() as d:
            controller = self._controller(d)
            service = controller._service()
            try:
                service._remind(next(s for s in controller.store.load() if s.id == "daily-anime"), "k1")
            finally:
                service.close()
            state = controller.state()
            self.assertEqual([r["key"] for r in state["reminders"]], ["k1"])
            self.assertFalse(state["reminders"][0]["seen"])
            self.assertEqual(controller.acknowledge("k1")["unread"], 0)
            self.assertTrue(controller.state()["reminders"][0]["seen"])
            reopened = ScheduleController(d).state()
            self.assertEqual(len(reopened["reminders"]), 1)


if __name__ == "__main__":
    unittest.main()
