"""Schedule panel backend: definitions, reminders and explicit enable/disable.

Definitions stay in a JSON store and reminders in the local SQLite inbox. This
module never dispatches a model task: execution still requires an explicitly
bound managed DSH bridge, so the UI reports such definitions as blocked.
"""
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from sumika_next.paths import user_data_directory

from extensions.desktop.schedule_runner import next_occurrence
from extensions.desktop.schedule_service import ScheduleService
from extensions.desktop.scheduler import ScheduleStore


def native_request(definition, now=None):
    """Translate the existing editor contract; never dispatch or persist locally."""
    from extensions.desktop.scheduler import Schedule
    import re
    if not isinstance(definition, dict):
        raise ValueError('schedule definition required')
    item = Schedule(**definition)
    if item.mode != 'execute':
        raise ValueError('native scheduling is only for explicitly confirmed execution')
    if len(item.action) > 20000:
        raise ValueError('task content exceeds 20000 characters')
    result = {'title': item.action.strip().splitlines()[0][:120], 'prompt': item.action}
    if item.kind == 'once':
        due = datetime.fromisoformat(item.expression).astimezone(timezone.utc)
        if due <= (now or datetime.now(timezone.utc)):
            raise ValueError('one-shot execution must be in the future')
        result['at'] = due.isoformat(timespec='milliseconds').replace('+00:00', 'Z')
    else:
        clock = item.expression.split()[-1]
        if not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', clock):
            raise ValueError('time must use HH:MM')
        rule = {'time': clock + ':00', 'time_zone': item.timezone_name}
        if item.kind == 'weekly':
            rule['weekdays'] = [int(item.expression.split()[0]) + 1]
        result[item.kind] = rule
    return result


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
                due = next_occurrence(item, now) if item.enabled else None
                entry["next_due"] = due.isoformat() if due is not None else None
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

    def notify(self, key, text):
        if not isinstance(key, str) or not key.startswith('reference-research/'):
            raise ValueError('reference notification key required')
        if not isinstance(text, str) or not text or len(text) > 20000:
            raise ValueError('bounded reference notification required')
        service = self._service()
        try:
            with service.runner.db:
                service.runner.db.execute('INSERT OR IGNORE INTO reminders(key,text) VALUES (?,?)', (key,text))
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
