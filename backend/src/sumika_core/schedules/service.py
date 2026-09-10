"""Durable, host-driven user schedules.

This module deliberately owns neither a timer nor an execution runtime.  The
host invokes :meth:`ScheduleService.tick` and supplies the existing dispatch
entry point.
"""

from __future__ import annotations

import copy
import hashlib
import json
import threading
from datetime import UTC, datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Mapping, Protocol
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


SCHEDULE_NAMESPACE = "schedules/v1"
RUN_NAMESPACE = "schedule-runs/v1"
DEFAULT_TIMEZONE = "Asia/Shanghai"
_CHINA_FALLBACK = timezone(timedelta(hours=8), DEFAULT_TIMEZONE)
_RUNNING_STATES = frozenset({"dispatching", "running", "unknown"})
_TERMINAL_STATES = frozenset({"completed", "failed", "rejected", "cancelled", "skipped"})


class ScheduleError(RuntimeError):
    pass


class ScheduleBusy(ScheduleError):
    pass


class ScheduleValidationError(ScheduleError):
    pass


class ScheduleRepository(Protocol):
    def save_record(self, namespace: str, record_id: str, assistant_id: str, payload: dict[str, Any]) -> dict[str, Any]: ...

    def get_record(self, namespace: str, record_id: str, assistant_id: str) -> dict[str, Any] | None: ...

    def list_records(self, namespace: str, assistant_id: str) -> list[dict[str, Any]]: ...

    def delete_record(self, namespace: str, record_id: str, assistant_id: str) -> bool: ...


Dispatch = Callable[[dict[str, Any]], Mapping[str, Any]]
Clock = Callable[[], datetime]
MaintenanceProjectionReader = Callable[[], list[dict[str, Any]]]


class ScheduleService:
    """Schedule records with persistent dispatch identities and no timer thread.

    ``clock`` must return an aware datetime.  ``dispatch`` is the host's
    unified work entry point and receives a new dictionary for every call.
    """

    def __init__(
        self,
        repository: ScheduleRepository,
        dispatch: Dispatch,
        *,
        clock: Clock = lambda: datetime.now(UTC),
        maintenance_projection_reader: MaintenanceProjectionReader | None = None,
        max_lateness: timedelta = timedelta(minutes=5),
    ) -> None:
        if max_lateness < timedelta(0):
            raise ScheduleValidationError("max_lateness must not be negative")
        self._repository = repository
        self._dispatch = dispatch
        self._clock = clock
        self._maintenance_projection_reader = maintenance_projection_reader
        self._max_lateness = max_lateness
        self._lock = threading.RLock()
        self._tick_lock = threading.Lock()
        self._closed = False
        self._started_at = clock()

    def create(self, assistant_id: str, draft: Mapping[str, Any]) -> dict[str, Any]:
        """Create an enabled schedule after its recurring scope is confirmed."""
        assistant_id = _identifier(assistant_id, "assistant_id")
        if not isinstance(draft, Mapping):
            raise ScheduleValidationError("schedule draft must be an object")
        now = self._now()
        schedule_id = _identifier(str(draft.get("id") or f"schedule-{uuid4().hex}"), "schedule_id")
        record = self._build_schedule(assistant_id, schedule_id, draft, now)
        with self._lock:
            self._ensure_open()
            if self._repository.get_record(SCHEDULE_NAMESPACE, schedule_id, assistant_id) is not None:
                raise ScheduleValidationError("schedule already exists")
            return self._repository.save_record(SCHEDULE_NAMESPACE, schedule_id, assistant_id, record)

    def get(self, assistant_id: str, schedule_id: str) -> dict[str, Any] | None:
        return self._repository.get_record(SCHEDULE_NAMESPACE, _identifier(schedule_id, "schedule_id"), _identifier(assistant_id, "assistant_id"))

    def list(self, assistant_id: str) -> list[dict[str, Any]]:
        assistant_id = _identifier(assistant_id, "assistant_id")
        records = self._repository.list_records(SCHEDULE_NAMESPACE, assistant_id)
        return sorted(records, key=lambda item: (item.get("created_at", ""), item.get("id", "")))

    def update(self, assistant_id: str, schedule_id: str, changes: Mapping[str, Any]) -> dict[str, Any]:
        """Replace user-editable fields; any change requires fresh scope confirmation."""
        assistant_id = _identifier(assistant_id, "assistant_id")
        schedule_id = _identifier(schedule_id, "schedule_id")
        if not isinstance(changes, Mapping):
            raise ScheduleValidationError("schedule changes must be an object")
        forbidden = {"id", "assistant_id", "created_at", "next_at", "last_tick_at", "state"}
        if set(changes) & forbidden:
            raise ScheduleValidationError("schedule changes include a managed field")
        with self._lock:
            self._ensure_open()
            current = self.get(assistant_id, schedule_id)
            if current is None:
                raise ScheduleValidationError("schedule was not found")
            merged = {
                key: copy.deepcopy(value)
                for key, value in current.items()
                if key not in {"assistant_id", "created_at", "next_at", "last_tick_at", "state", "updated_at"}
            }
            merged.update(copy.deepcopy(dict(changes)))
            if "authorization" not in changes:
                raise ScheduleValidationError("schedule changes require confirmed authorization")
            updated = self._build_schedule(assistant_id, schedule_id, merged, self._now(), created_at=current["created_at"])
            prior_spent = _money(current["authorization"].get("total_spent", "0"), "total_spent")
            if prior_spent:
                if not updated["authorization"]["paid"]:
                    raise ScheduleValidationError("paid schedule spending cannot be removed")
                total_limit = _optional_money(updated["authorization"].get("total_limit"), "total_limit")
                if total_limit is not None and total_limit < prior_spent:
                    raise ScheduleValidationError("total limit cannot be below recorded spending")
                updated["authorization"]["total_spent"] = _money_text(prior_spent)
            return self._repository.save_record(SCHEDULE_NAMESPACE, schedule_id, assistant_id, updated)

    def set_paused(self, assistant_id: str, schedule_id: str, paused: bool) -> dict[str, Any]:
        if type(paused) is not bool:
            raise ScheduleValidationError("paused must be boolean")
        assistant_id = _identifier(assistant_id, "assistant_id")
        schedule_id = _identifier(schedule_id, "schedule_id")
        with self._lock:
            self._ensure_open()
            record = self.get(assistant_id, schedule_id)
            if record is None:
                raise ScheduleValidationError("schedule was not found")
            record["state"] = "paused" if paused else "active"
            record["updated_at"] = _iso(self._now())
            return self._repository.save_record(SCHEDULE_NAMESPACE, schedule_id, assistant_id, record)

    def run_now(self, assistant_id: str, schedule_id: str) -> dict[str, Any]:
        """Manually run a schedule once, including when its recurring trigger is paused."""
        assistant_id = _identifier(assistant_id, "assistant_id")
        schedule_id = _identifier(schedule_id, "schedule_id")
        with self._lock:
            self._ensure_open()
            record = self.get(assistant_id, schedule_id)
            if record is None:
                raise ScheduleValidationError("schedule was not found")
            return self._begin_run(record, "manual", self._now())

    def tick(self, assistant_id: str) -> dict[str, Any]:
        """Run due entries for one assistant.  The host calls this on its background tick."""
        assistant_id = _identifier(assistant_id, "assistant_id")
        if not self._tick_lock.acquire(blocking=False):
            return {"status": "busy", "dispatched": [], "skipped": [], "blocked": []}
        try:
            with self._lock:
                if self._closed:
                    return {"status": "closed", "dispatched": [], "skipped": [], "blocked": []}
                now = self._now()
                dispatched: list[dict[str, Any]] = []
                skipped: list[dict[str, Any]] = []
                blocked: list[dict[str, Any]] = []
                for record in self.list(assistant_id):
                    outcome = self._tick_record(record, now)
                    if outcome is not None:
                        if outcome["state"] == "dispatched":
                            dispatched.append(outcome)
                        elif outcome["state"] == "blocked":
                            blocked.append(outcome)
                        else:
                            skipped.append(outcome)
                return {"status": "ready", "dispatched": dispatched, "skipped": skipped, "blocked": blocked}
        finally:
            self._tick_lock.release()

    def history(self, assistant_id: str, schedule_id: str) -> list[dict[str, Any]]:
        assistant_id = _identifier(assistant_id, "assistant_id")
        schedule_id = _identifier(schedule_id, "schedule_id")
        records = self._repository.list_records(RUN_NAMESPACE, assistant_id)
        return sorted((item for item in records if item.get("schedule_id") == schedule_id), key=lambda item: item.get("created_at", ""), reverse=True)

    def complete_run(
        self,
        assistant_id: str,
        execution_id: str,
        status: str,
        *,
        spent: str | Decimal | int | None = None,
    ) -> dict[str, Any]:
        """Persist an outcome reported by the unified work entry point."""
        assistant_id = _identifier(assistant_id, "assistant_id")
        execution_id = _identifier(execution_id, "execution_id")
        normalized = _run_state(status)
        if normalized not in _TERMINAL_STATES | {"unknown", "running"}:
            raise ScheduleValidationError("unsupported execution status")
        with self._lock:
            record = self._repository.get_record(RUN_NAMESPACE, execution_id, assistant_id)
            if record is None:
                raise ScheduleValidationError("execution was not found")
            if record.get("state") in _TERMINAL_STATES and record.get("spent") is not None:
                prior_spent = _money(record["spent"], "spent")
                requested_spent = _money(spent, "spent") if spent is not None else prior_spent
                if normalized == record["state"] and requested_spent == prior_spent:
                    return record
                raise ScheduleValidationError("execution already has a terminal outcome")
            if record.get("state") in _TERMINAL_STATES and normalized != record["state"]:
                raise ScheduleValidationError("execution terminal outcome cannot change")
            schedule = self.get(assistant_id, record["schedule_id"])
            if schedule is None:
                raise ScheduleValidationError("schedule was not found")
            amount = _money(spent, "spent") if spent is not None else Decimal("0")
            authorization = schedule["authorization"]
            if amount and not authorization["paid"]:
                raise ScheduleValidationError("zero-cost schedule cannot record spending")
            per_run = _optional_money(authorization.get("per_run_limit"), "per_run_limit")
            total_limit = _optional_money(authorization.get("total_limit"), "total_limit")
            total_spent = _money(authorization.get("total_spent", "0"), "total_spent")
            if per_run is not None and amount > per_run:
                raise ScheduleValidationError("recorded spending exceeds per-run limit")
            if total_limit is not None and total_spent + amount > total_limit:
                raise ScheduleValidationError("recorded spending exceeds total limit")
            authorization["total_spent"] = _money_text(total_spent + amount)
            schedule["updated_at"] = _iso(self._now())
            record.update(state=normalized, completed_at=_iso(self._now()), spent=_money_text(amount))
            self._repository.save_record(SCHEDULE_NAMESPACE, schedule["id"], assistant_id, schedule)
            return self._repository.save_record(RUN_NAMESPACE, execution_id, assistant_id, record)

    def maintenance_projection(self) -> dict[str, Any]:
        """Return read-only existing maintenance state without registering work."""
        if self._maintenance_projection_reader is None:
            return {"read_only": True, "items": []}
        items = self._maintenance_projection_reader()
        if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
            raise ScheduleValidationError("maintenance projection must be a list of objects")
        return {"read_only": True, "items": copy.deepcopy(items)}

    def close(self) -> None:
        """Prevent future dispatches.  The host owns any background loop."""
        with self._lock:
            self._closed = True

    def _tick_record(self, record: dict[str, Any], now: datetime) -> dict[str, Any] | None:
        if record["state"] != "active" or record.get("next_at") is None:
            return None
        due = _instant(record["next_at"])
        if due is None:
            raise ScheduleValidationError("stored schedule has invalid next_at")
        if due > now:
            return None
        rule = record["rule"]
        if rule["kind"] == "once" and (due < self._started_at or now - due > self._max_lateness):
            record.update(state="needs_manual_run", next_at=None, updated_at=_iso(now), last_tick_at=_iso(now))
            self._repository.save_record(SCHEDULE_NAMESPACE, record["id"], record["assistant_id"], record)
            return self._skip(record, due, "once-missed", now)
        if rule["kind"] != "once" and (due < self._started_at or now - due > self._max_lateness):
            record.update(next_at=_iso(_next_periodic(rule, now, inclusive=False)), updated_at=_iso(now), last_tick_at=_iso(now))
            self._repository.save_record(SCHEDULE_NAMESPACE, record["id"], record["assistant_id"], record)
            return self._skip(record, due, "periodic-missed", now)
        if self._has_unresolved_run(record):
            return {"id": record["id"], "state": "blocked", "reason": "prior-run-unresolved"}
        if rule["kind"] == "once":
            record["next_at"] = None
        else:
            record["next_at"] = _iso(_next_periodic(rule, due, inclusive=False))
        record.update(updated_at=_iso(now), last_tick_at=_iso(now))
        self._repository.save_record(SCHEDULE_NAMESPACE, record["id"], record["assistant_id"], record)
        result = self._begin_run(record, "scheduled", now, scheduled_at=due)
        if result["state"] == "skipped":
            return {"id": record["id"], "state": "skipped", "reason": result["reason"], "execution_id": result["id"]}
        return {"id": record["id"], "state": "dispatched", "execution": result}

    def _begin_run(self, record: dict[str, Any], trigger: str, now: datetime, *, scheduled_at: datetime | None = None) -> dict[str, Any]:
        if self._has_unresolved_run(record):
            raise ScheduleBusy("schedule has a running or unknown execution")
        authorization = record["authorization"]
        if not authorization["scope_confirmed"]:
            raise ScheduleValidationError("schedule scope is not confirmed")
        total_limit = _optional_money(authorization.get("total_limit"), "total_limit")
        total_spent = _money(authorization.get("total_spent", "0"), "total_spent")
        if authorization["paid"] and total_limit is not None and total_spent >= total_limit:
            return self._skip(record, scheduled_at or now, "paid-total-limit", now)
        execution_id = _execution_id(record["id"], trigger, scheduled_at)
        existing = self._repository.get_record(RUN_NAMESPACE, execution_id, record["assistant_id"])
        if existing is not None:
            return existing
        run = {
            "id": execution_id,
            "schedule_id": record["id"],
            "assistant_id": record["assistant_id"],
            "trigger": trigger,
            "scheduled_at": _iso(scheduled_at) if scheduled_at else None,
            "created_at": _iso(now),
            "state": "dispatching",
            "request_id": None,
            "dispatch_status": "unknown",
            "spent": None,
        }
        self._repository.save_record(RUN_NAMESPACE, execution_id, record["assistant_id"], run)
        payload = {
            "schedule_id": record["id"],
            "execution_id": execution_id,
            "assistant_id": record["assistant_id"],
            "project_id": record["project_id"],
            "trigger": trigger,
            "payload": copy.deepcopy(record["payload"]),
            "authorization": copy.deepcopy(authorization),
        }
        try:
            response = self._dispatch(payload)
            if not isinstance(response, Mapping):
                raise TypeError("dispatch response must be an object")
            request_id = response.get("request_id")
            if request_id is not None:
                request_id = _identifier(str(request_id), "request_id")
            dispatch_status = str(response.get("status") or "unknown").strip().lower()
            run.update(request_id=request_id, dispatch_status=dispatch_status, state=_run_state(dispatch_status))
        except Exception:
            # A thrown dispatch may have reached the unified executor.  Keep the
            # conservative unknown marker durable so a restart cannot resend it.
            run.update(state="unknown", dispatch_status="unknown")
        return self._repository.save_record(RUN_NAMESPACE, execution_id, record["assistant_id"], run)

    def _skip(self, record: dict[str, Any], scheduled_at: datetime, reason: str, now: datetime) -> dict[str, Any]:
        execution_id = _execution_id(record["id"], "scheduled", scheduled_at)
        existing = self._repository.get_record(RUN_NAMESPACE, execution_id, record["assistant_id"])
        if existing is not None:
            return existing
        run = {
            "id": execution_id,
            "schedule_id": record["id"],
            "assistant_id": record["assistant_id"],
            "trigger": "scheduled",
            "scheduled_at": _iso(scheduled_at),
            "created_at": _iso(now),
            "completed_at": _iso(now),
            "state": "skipped",
            "reason": reason,
            "request_id": None,
            "dispatch_status": None,
            "spent": "0",
        }
        self._repository.save_record(RUN_NAMESPACE, execution_id, record["assistant_id"], run)
        return {"id": record["id"], "state": "skipped", "reason": reason, "execution_id": execution_id}

    def _has_unresolved_run(self, record: Mapping[str, Any]) -> bool:
        return any(run.get("state") in _RUNNING_STATES for run in self.history(record["assistant_id"], record["id"]))

    def _build_schedule(self, assistant_id: str, schedule_id: str, draft: Mapping[str, Any], now: datetime, *, created_at: str | None = None) -> dict[str, Any]:
        allowed = {"id", "title", "payload", "project_id", "rule", "authorization", "state"}
        unknown = set(draft) - allowed
        if unknown:
            raise ScheduleValidationError(f"unsupported schedule fields: {', '.join(sorted(unknown))}")
        title = _text(draft.get("title"), "title", required=True, maximum=240)
        payload = draft.get("payload")
        if not isinstance(payload, dict):
            raise ScheduleValidationError("schedule payload must be an object")
        _json_value(payload, "payload")
        project_id = draft.get("project_id")
        if project_id is not None:
            project_id = _identifier(str(project_id), "project_id")
        rule = _rule(draft.get("rule"), now)
        authorization = _authorization(draft.get("authorization"))
        if draft.get("state", "active") != "active":
            raise ScheduleValidationError("new schedules are active only after confirmation")
        next_at = _next_at(rule, now)
        return {
            "id": schedule_id,
            "assistant_id": assistant_id,
            "title": title,
            "payload": copy.deepcopy(payload),
            "project_id": project_id,
            "rule": rule,
            "authorization": authorization,
            "state": "active",
            "next_at": _iso(next_at) if next_at else None,
            "last_tick_at": None,
            "created_at": created_at or _iso(now),
            "updated_at": _iso(now),
        }

    def _now(self) -> datetime:
        value = self._clock()
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise ScheduleValidationError("clock must return an aware datetime")
        return value.astimezone(UTC)

    def _ensure_open(self) -> None:
        if self._closed:
            raise ScheduleError("schedule service is closed")


def _rule(value: Any, now: datetime) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ScheduleValidationError("rule must be an object")
    kind = value.get("kind")
    if kind not in {"once", "daily", "weekly"}:
        raise ScheduleValidationError("rule kind must be once, daily, or weekly")
    timezone_name = str(value.get("timezone") or DEFAULT_TIMEZONE)
    zone = _zone(timezone_name)
    if kind == "once":
        if set(value) - {"kind", "at", "timezone"} or not isinstance(value.get("at"), str):
            raise ScheduleValidationError("once rule requires at and optional timezone")
        at = _instant(value["at"], zone)
        if at is None:
            raise ScheduleValidationError("once rule at must be an ISO datetime")
        return {"kind": kind, "timezone": timezone_name, "at": _iso(at)}
    allowed = {"kind", "time", "timezone"} | ({"weekdays"} if kind == "weekly" else set())
    if set(value) - allowed:
        raise ScheduleValidationError("rule contains unsupported fields")
    local_time = _local_time(value.get("time"))
    result: dict[str, Any] = {"kind": kind, "timezone": timezone_name, "time": local_time.isoformat(timespec="seconds")}
    if kind == "weekly":
        weekdays = value.get("weekdays")
        if not isinstance(weekdays, list) or not weekdays or any(type(day) is not int or day < 0 or day > 6 for day in weekdays):
            raise ScheduleValidationError("weekly rule weekdays must contain integers from 0 through 6")
        result["weekdays"] = sorted(set(weekdays))
    return result


def _authorization(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping) or value.get("scope_confirmed") is not True:
        raise ScheduleValidationError("schedule scope must be explicitly confirmed")
    allowed = {"scope_confirmed", "paid", "per_run_limit", "total_limit"}
    if set(value) - allowed:
        raise ScheduleValidationError("authorization contains unsupported fields")
    paid = value.get("paid", False)
    if type(paid) is not bool:
        raise ScheduleValidationError("paid must be boolean")
    per_run = _optional_money(value.get("per_run_limit"), "per_run_limit")
    total = _optional_money(value.get("total_limit"), "total_limit")
    if paid and per_run is None and total is None:
        raise ScheduleValidationError("paid schedule needs a per-run or total limit")
    if not paid and (per_run is not None or total is not None):
        raise ScheduleValidationError("zero-cost schedule cannot have paid limits")
    return {"scope_confirmed": True, "paid": paid, "per_run_limit": _money_text(per_run) if per_run is not None else None, "total_limit": _money_text(total) if total is not None else None, "total_spent": "0"}


def _next_at(rule: Mapping[str, Any], now: datetime) -> datetime | None:
    if rule["kind"] == "once":
        return _instant(rule["at"])
    return _next_periodic(rule, now, inclusive=True)


def _execution_id(schedule_id: str, trigger: str, scheduled_at: datetime | None) -> str:
    if trigger == "manual":
        return f"execution-{uuid4().hex}"
    if scheduled_at is None:
        raise ScheduleValidationError("scheduled execution requires a scheduled time")
    identity = f"{schedule_id}\0{_iso(scheduled_at)}".encode("utf-8")
    return f"execution-{hashlib.sha256(identity).hexdigest()[:32]}"


def _next_periodic(rule: Mapping[str, Any], reference: datetime, *, inclusive: bool) -> datetime:
    zone = _zone(rule["timezone"])
    local_reference = reference.astimezone(zone)
    target_time = _local_time(rule["time"])
    for offset in range(8):
        date = local_reference.date() + timedelta(days=offset)
        if rule["kind"] == "weekly" and date.weekday() not in rule["weekdays"]:
            continue
        candidate = datetime.combine(date, target_time, zone).astimezone(UTC)
        if candidate > reference or (inclusive and candidate == reference):
            return candidate
    raise ScheduleValidationError("could not calculate next schedule time")


def _zone(name: str):
    if not isinstance(name, str) or not name.strip():
        raise ScheduleValidationError("timezone must not be empty")
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError as error:
        if name == DEFAULT_TIMEZONE:
            return _CHINA_FALLBACK
        raise ScheduleValidationError(f"timezone data is unavailable: {name}") from error


def _instant(value: Any, assumed_zone=None) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        if assumed_zone is None:
            return None
        parsed = parsed.replace(tzinfo=assumed_zone)
    return parsed.astimezone(UTC)


def _local_time(value: Any) -> time:
    if not isinstance(value, str):
        raise ScheduleValidationError("time must be an ISO local time")
    try:
        parsed = time.fromisoformat(value)
    except ValueError as error:
        raise ScheduleValidationError("time must be an ISO local time") from error
    if parsed.tzinfo is not None:
        raise ScheduleValidationError("time must not contain a timezone")
    return parsed


def _run_state(status: str) -> str:
    value = str(status).strip().lower()
    if value in {"completed", "complete", "success", "succeeded"}:
        return "completed"
    if value in {"failed", "error"}:
        return "failed"
    if value in {"rejected", "denied"}:
        return "rejected"
    if value in {"cancelled", "canceled", "aborted"}:
        return "cancelled"
    if value in {"skipped"}:
        return "skipped"
    if value in {"queued", "accepted", "pending", "running", "dispatching"}:
        return "running"
    return "unknown"


def _identifier(value: str, name: str) -> str:
    candidate = str(value).strip()
    if not candidate or len(candidate) > 180 or any(ord(char) < 32 or ord(char) == 127 for char in candidate):
        raise ScheduleValidationError(f"{name} is invalid")
    return candidate


def _text(value: Any, name: str, *, required: bool, maximum: int) -> str:
    if not isinstance(value, str) or (required and not value.strip()) or len(value) > maximum:
        raise ScheduleValidationError(f"{name} is invalid")
    return value.strip()


def _json_value(value: Any, name: str) -> None:
    try:
        json.dumps(value, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as error:
        raise ScheduleValidationError(f"{name} must be JSON-compatible") from error


def _money(value: str | Decimal | int | None, name: str) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise ScheduleValidationError(f"{name} is invalid")
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise ScheduleValidationError(f"{name} is invalid") from error
    if not amount.is_finite() or amount < 0:
        raise ScheduleValidationError(f"{name} is invalid")
    return amount


def _optional_money(value: Any, name: str) -> Decimal | None:
    return None if value is None else _money(value, name)


def _money_text(value: Decimal) -> str:
    return format(value.normalize(), "f") if value else "0"


def _iso(value: datetime | None) -> str | None:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z") if value is not None else None
