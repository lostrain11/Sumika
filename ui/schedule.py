"""Schedule panel backend: definitions, reminders and explicit enable/disable.

Definitions stay in a JSON store and reminders in the local SQLite inbox. This
module never dispatches a model task: execution still requires an explicitly
bound managed DSH bridge, so the UI reports such definitions as blocked.
"""
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from sumika_next.paths import user_data_directory

from extensions.desktop.schedule_runner import occurrence
from extensions.desktop.schedule_service import ScheduleService
from extensions.desktop.scheduler import ScheduleStore


def default_directory():
    return user_data_directory() / "schedules"


class ScheduleController:
    def __init__(self, directory=None):
        self.directory = Path(directory) if directory else default_directory()
        self.store = ScheduleStore(self.directory / "schedules.json")
        self.history = self.directory / "history.sqlite3"

    def _service(self):
        # No bridge: execution definitions are reported as blocked instead of
        # being submitted somewhere the host does not own.
        return ScheduleService(self.directory / "schedules.json", self.history,
                               bridge=None, enabled=True)

    def definitions(self, now=None):
        now = now or datetime.now(timezone.utc)
        result = []
        for item in self.store.load():
            entry = item.to_dict()
            try:
                entry["next_due"] = occurrence(item, now).isoformat()
            except (ValueError, TypeError):
                entry["next_due"] = None
            result.append(entry)
        return result

    def state(self):
        definitions = self.definitions()
        service = self._service()
        try:
            reminders = service.reminders(unread=False)
            status = service.status()
        finally:
            service.close()
        return {"directory": str(self.directory), "definitions": definitions,
                "reminders": reminders, "status": status}

    def toggle(self, schedule_id, enabled):
        if type(enabled) is not bool:
            raise ValueError("enabled must be boolean")
        if not isinstance(schedule_id, str) or not schedule_id.strip():
            raise ValueError("schedule id required")
        items = self.store.load()
        target = next((x for x in items if x.id == schedule_id), None)
        if target is None:
            raise ValueError("unknown schedule")
        if enabled:
            self.store.upsert(replace(target, enabled=True))
        else:
            self.store.disable(schedule_id)
        return {"id": schedule_id, "enabled": enabled}

    def remove(self, schedule_id):
        if not isinstance(schedule_id, str) or not schedule_id.strip():
            raise ValueError("schedule id required")
        self.store.remove(schedule_id)
        return {"removed": schedule_id}

    def acknowledge(self, key):
        if not isinstance(key, str) or not key.strip():
            raise ValueError("reminder key required")
        service = self._service()
        try:
            service.acknowledge(key)
            return {"acknowledged": key, "unread": len(service.reminders(unread=True))}
        finally:
            service.close()

    def tick(self, now=None):
        service = self._service()
        try:
            return {'occurrences': service.tick(now), 'status': service.status(),
                    'unread': len(service.reminders(unread=True))}
        finally:
            service.close()

    def cancel(self, schedule_id, due):
        service = self._service()
        try:
            return service.cancel(schedule_id, due)
        finally:
            service.close()

    def reconcile(self, schedule_id, due, outcome, evidence):
        service = self._service()
        try:
            return service.reconcile(schedule_id, due, outcome, evidence)
        finally:
            service.close()
