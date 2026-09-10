import copy
import threading
import unittest
from datetime import UTC, datetime, timedelta

from sumika_core.schedules import ScheduleBusy, ScheduleError, ScheduleService, ScheduleValidationError


class MemoryRepository:
    def __init__(self):
        self.records = {}
        self.lock = threading.RLock()

    def save_record(self, namespace, record_id, assistant_id, payload):
        with self.lock:
            self.records[namespace, record_id, assistant_id] = copy.deepcopy(payload)
            return copy.deepcopy(payload)

    def get_record(self, namespace, record_id, assistant_id):
        with self.lock:
            value = self.records.get((namespace, record_id, assistant_id))
            return copy.deepcopy(value) if value is not None else None

    def list_records(self, namespace, assistant_id):
        with self.lock:
            return [copy.deepcopy(value) for (scope, _, owner), value in self.records.items() if scope == namespace and owner == assistant_id]

    def delete_record(self, namespace, record_id, assistant_id):
        with self.lock:
            return self.records.pop((namespace, record_id, assistant_id), None) is not None


class MutableClock:
    def __init__(self, value):
        self.value = value

    def __call__(self):
        return self.value


class ScheduleServiceTests(unittest.TestCase):
    assistant_id = "assistant-a"

    def setUp(self):
        self.clock = MutableClock(datetime(2026, 9, 7, 0, 0, tzinfo=UTC))
        self.repository = MemoryRepository()
        self.calls = []
        self.service = self.make_service()

    def make_service(self, dispatch=None, **kwargs):
        def default_dispatch(payload):
            self.calls.append(copy.deepcopy(payload))
            return {"request_id": f"request-{len(self.calls)}", "status": "completed"}
        return ScheduleService(self.repository, dispatch or default_dispatch, clock=self.clock, **kwargs)

    def draft(self, rule, **extra):
        value = {
            "id": "schedule-daily",
            "title": "Morning review",
            "payload": {"task": "review inbox"},
            "rule": rule,
            "authorization": {"scope_confirmed": True},
        }
        value.update(extra)
        return value

    def test_daily_default_shanghai_zone_dispatches_at_local_time(self):
        created = self.service.create(self.assistant_id, self.draft({"kind": "daily", "time": "08:00"}))
        self.assertEqual(created["rule"]["timezone"], "Asia/Shanghai")
        self.assertEqual(created["next_at"], "2026-09-07T00:00:00Z")

        result = self.service.tick(self.assistant_id)

        self.assertEqual(result["status"], "ready")
        self.assertEqual(len(result["dispatched"]), 1)
        self.assertEqual(len(self.calls), 1)
        self.assertFalse(self.calls[0]["authorization"]["paid"])
        self.assertEqual(self.service.history(self.assistant_id, created["id"])[0]["state"], "completed")

    def test_weekly_uses_explicit_default_zone_and_weekday(self):
        created = self.service.create(
            self.assistant_id,
            self.draft({"kind": "weekly", "time": "09:30", "timezone": "Asia/Shanghai", "weekdays": [2]}, id="schedule-weekly"),
        )
        self.assertEqual(created["next_at"], "2026-09-09T01:30:00Z")

    def test_missing_non_default_timezone_is_not_silently_replaced(self):
        with self.assertRaises(ScheduleValidationError):
            self.service.create(
                self.assistant_id,
                self.draft({"kind": "weekly", "time": "09:30", "timezone": "UTC", "weekdays": [2]}),
            )

    def test_once_missed_requires_manual_run_and_does_not_dispatch_on_restart(self):
        created = self.service.create(
            self.assistant_id,
            self.draft({"kind": "once", "at": "2026-09-07T01:00:00Z"}, id="schedule-once"),
        )
        self.clock.value += timedelta(hours=2)
        restarted = self.make_service()

        result = restarted.tick(self.assistant_id)

        self.assertEqual(result["skipped"][0]["reason"], "once-missed")
        self.assertEqual(self.service.get(self.assistant_id, created["id"])["state"], "needs_manual_run")
        self.assertEqual(self.calls, [])
        run = restarted.run_now(self.assistant_id, created["id"])
        self.assertEqual(run["state"], "completed")
        self.assertEqual(len(self.calls), 1)

    def test_periodic_miss_is_skipped_instead_of_caught_up(self):
        created = self.service.create(self.assistant_id, self.draft({"kind": "daily", "time": "08:00"}))
        self.clock.value += timedelta(minutes=6)

        result = self.service.tick(self.assistant_id)

        self.assertEqual(result["skipped"][0]["reason"], "periodic-missed")
        self.assertEqual(self.calls, [])
        self.assertEqual(self.service.get(self.assistant_id, created["id"])["next_at"], "2026-09-08T00:00:00Z")

    def test_unknown_dispatch_is_durable_and_not_resent_after_restart(self):
        def uncertain(payload):
            self.calls.append(copy.deepcopy(payload))
            raise ConnectionError("response lost")

        uncertain_service = self.make_service(uncertain)
        uncertain_service.create(self.assistant_id, self.draft({"kind": "daily", "time": "08:00"}))

        first = uncertain_service.tick(self.assistant_id)
        self.assertEqual(first["dispatched"][0]["execution"]["state"], "unknown")
        first_id = first["dispatched"][0]["execution"]["id"]
        self.assertEqual(len(self.calls), 1)

        self.clock.value += timedelta(days=1)
        restarted = self.make_service(uncertain)
        second = restarted.tick(self.assistant_id)
        self.assertEqual(second["blocked"][0]["reason"], "prior-run-unresolved")
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(restarted.history(self.assistant_id, "schedule-daily")[0]["id"], first_id)

    def test_tick_is_single_flight(self):
        entered = threading.Event()
        release = threading.Event()

        def delayed(payload):
            self.calls.append(copy.deepcopy(payload))
            entered.set()
            release.wait(2)
            return {"request_id": "request-1", "status": "completed"}

        service = self.make_service(delayed)
        service.create(self.assistant_id, self.draft({"kind": "daily", "time": "08:00"}))
        worker_result = []
        worker = threading.Thread(target=lambda: worker_result.append(service.tick(self.assistant_id)))
        worker.start()
        self.assertTrue(entered.wait(1))
        self.assertEqual(service.tick(self.assistant_id)["status"], "busy")
        release.set()
        worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertEqual(len(worker_result[0]["dispatched"]), 1)
        self.assertEqual(len(self.calls), 1)

    def test_close_prevents_future_tick_and_mutation(self):
        self.service.create(self.assistant_id, self.draft({"kind": "daily", "time": "08:00"}))
        self.service.close()

        self.assertEqual(self.service.tick(self.assistant_id)["status"], "closed")
        self.assertEqual(self.calls, [])
        with self.assertRaises(ScheduleError):
            self.service.run_now(self.assistant_id, "schedule-daily")

    def test_authorization_requires_scope_and_explicit_paid_cap(self):
        with self.assertRaises(ScheduleValidationError):
            self.service.create(self.assistant_id, self.draft({"kind": "daily", "time": "08:00"}, authorization={}))
        with self.assertRaises(ScheduleValidationError):
            self.service.create(self.assistant_id, self.draft({"kind": "daily", "time": "08:00"}, authorization={"scope_confirmed": True, "paid": True}))

        created = self.service.create(
            self.assistant_id,
            self.draft(
                {"kind": "daily", "time": "08:00"},
                authorization={"scope_confirmed": True, "paid": True, "per_run_limit": "2", "total_limit": "3"},
            ),
        )
        run = self.service.tick(self.assistant_id)["dispatched"][0]["execution"]
        completed = self.service.complete_run(self.assistant_id, run["id"], "completed", spent="2")
        self.assertEqual(self.service.complete_run(self.assistant_id, run["id"], "completed", spent="2"), completed)
        with self.assertRaises(ScheduleValidationError):
            self.service.complete_run(self.assistant_id, run["id"], "completed", spent="3")
        with self.assertRaises(ScheduleValidationError):
            self.service.update(
                self.assistant_id,
                created["id"],
                {"authorization": {"scope_confirmed": True, "paid": True, "total_limit": "1"}},
            )
        updated = self.service.update(
            self.assistant_id,
            created["id"],
            {"authorization": {"scope_confirmed": True, "paid": True, "total_limit": "3"}},
        )
        self.assertEqual(updated["authorization"]["total_spent"], "2")
        self.assertEqual(created["authorization"]["total_spent"], "0")

    def test_update_requires_new_authorization_and_maintenance_is_read_only(self):
        created = self.service.create(self.assistant_id, self.draft({"kind": "daily", "time": "08:00"}))
        with self.assertRaises(ScheduleValidationError):
            self.service.update(self.assistant_id, created["id"], {"title": "Changed"})
        updated = self.service.update(
            self.assistant_id,
            created["id"],
            {"title": "Changed", "authorization": {"scope_confirmed": True}},
        )
        self.assertEqual(updated["title"], "Changed")
        projected = self.make_service(maintenance_projection_reader=lambda: [{"id": "benefits", "state": "ready"}]).maintenance_projection()
        self.assertEqual(projected, {"read_only": True, "items": [{"id": "benefits", "state": "ready"}]})
        self.assertEqual(self.calls, [])

    def test_running_execution_blocks_manual_duplicate_until_completed(self):
        service = self.make_service(lambda payload: {"request_id": "request-1", "status": "running"})
        service.create(self.assistant_id, self.draft({"kind": "daily", "time": "08:00"}))
        run = service.tick(self.assistant_id)["dispatched"][0]["execution"]
        with self.assertRaises(ScheduleBusy):
            service.run_now(self.assistant_id, "schedule-daily")
        service.complete_run(self.assistant_id, run["id"], "completed")
        self.assertEqual(service.run_now(self.assistant_id, "schedule-daily")["state"], "running")
