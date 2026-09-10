from __future__ import annotations

import threading
from decimal import Decimal

from quality_routing.contracts import amount

from .service import RUN_NAMESPACE, ScheduleService


class ScheduleRuntime:
    def __init__(self, storage, work, *, maintenance_reader=None) -> None:
        self.storage = storage
        self.work = work
        self.service = ScheduleService(storage, self.dispatch, maintenance_projection_reader=maintenance_reader)
        self._stopped = threading.Event()
        self._thread = threading.Thread(target=self._run, name="sumika-user-schedules", daemon=True)
        self._thread.start()

    def dispatch(self, payload):
        owner = payload["assistant_id"]
        session_id = "schedule-" + payload["schedule_id"]
        if not any(row["id"] == session_id for row in self.storage.list_sessions()):
            self.storage.create_session(session_id, title="定时工作", character_id=owner)
        request = self.work.preflight({"request_id": payload["execution_id"], "assistant_id": owner,
                                       "session_id": session_id, "goal": payload["payload"].get("goal"),
                                       "project_id": payload.get("project_id"), "source": "schedule"})
        if request["status"] == "unavailable" or request["quote"]["high_cny"] is None:
            return {"request_id": request["request_id"], "status": "rejected"}
        authorization = payload["authorization"]
        high = amount(request["quote"]["high_cny"])
        limit = Decimal(0)
        if authorization["paid"]:
            limits = [amount(authorization[key]) for key in ("per_run_limit",) if authorization.get(key) is not None]
            if authorization.get("total_limit") is not None:
                limits.append(amount(authorization["total_limit"]) - amount(authorization["total_spent"]))
            limit = min(limits)
        if high > limit:
            return {"request_id": request["request_id"], "status": "rejected"}
        if request["status"] == "awaiting-confirmation":
            self.work.confirm({"request_id": request["request_id"], "assistant_id": owner, "revision": request["revision"], "max_cny": str(limit)})
        result = self.work.submit({"request_id": request["request_id"], "assistant_id": owner})
        return {"request_id": request["request_id"], "status": "running" if result["status"] in {"planning", "executing"} else result["status"]}

    def _run(self):
        while not self._stopped.wait(5):
            for assistant in self.storage.list_characters():
                if self._stopped.is_set():
                    return
                owner = assistant["id"]
                try:
                    for run in self.storage.list_records(RUN_NAMESPACE, owner):
                        if run["state"] != "running" or not run.get("request_id"):
                            continue
                        request = self.work.get(run["request_id"], owner)
                        if request["status"] in {"completed", "failed", "cancelled"}:
                            authorization = request.get("authorization") or {}
                            if amount(authorization.get("reserved_cny", "0")) == 0 and not any(attempt["status"] == "reserved" for attempt in request.get("attempts", {}).values()):
                                self.service.complete_run(owner, run["id"], request["status"], spent=authorization.get("spent_cny", "0"))
                    self.service.tick(owner)
                except Exception:
                    continue

    def close(self):
        self._stopped.set()
        self._thread.join(timeout=10)
        self.service.close()
