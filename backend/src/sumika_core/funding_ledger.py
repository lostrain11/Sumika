"""A conservative, account-revision-scoped funding ledger.

Provider balance observations are evidence, not permission to release money that
may have been spent.  A refreshed balance absorbs a settled request only when
the observation explicitly identifies it (or its ledger sequence).
"""

from __future__ import annotations

import re
import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterator, Mapping


_SOURCES = {"grant", "purchased", "cash", "unknown"}
_IDENTIFIER = re.compile(r"[A-Za-z0-9._:-]{1,240}")
_UNIT = re.compile(r"[A-Za-z][A-Za-z0-9._:-]{0,79}")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _text(value: Any, name: str, pattern: re.Pattern[str] = _IDENTIFIER) -> str:
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise ValueError(f"invalid {name}")
    return value


def _decimal(value: Any, name: str, *, positive: bool = False) -> Decimal:
    if isinstance(value, bool) or isinstance(value, float):
        raise ValueError(f"{name} must be an exact decimal")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"invalid {name}") from exc
    if not result.is_finite() or result < 0 or (positive and result == 0):
        raise ValueError(f"invalid {name}")
    return result


def _stored_decimal(value: Decimal) -> str:
    return format(value, "f")


def _time(value: Any, name: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} requires a timezone-aware ISO timestamp")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"invalid {name}") from exc
    if result.tzinfo is None:
        raise ValueError(f"{name} requires a timezone-aware ISO timestamp")
    return result.astimezone(timezone.utc)


def _stored_time(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _row_amount(row: sqlite3.Row, key: str) -> Decimal | None:
    value = row[key]
    return Decimal(value) if value is not None else None


class FundingLedger:
    """Persistent reservations for cash and provider-specific credit balances.

    ``observe`` accepts a mapping with ``provider``, ``account_revision``,
    ``balance``, ``unit``, ``source``, ``pocket_id``, ``observed_at`` and ``expires_at``.
    ``entitlement_expires_at`` is optional and is separate from observation
    freshness.  Reconciliation is explicit through ``included_request_ids``
    and/or the integer ``includes_through`` returned by ``reserve``.
    """

    def __init__(self, data_dir: str | Path | None = None) -> None:
        self._lock = threading.RLock()
        self.path = Path(data_dir) / "funding-ledger-v1.sqlite3" if data_dir else None
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        database = str(self.path) if self.path else ":memory:"
        self._connection = sqlite3.connect(database, timeout=10, isolation_level=None, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA busy_timeout = 10000")
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._initialize()

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def _initialize(self) -> None:
        with self._lock:
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS snapshots (
                    provider TEXT NOT NULL,
                    account_revision TEXT NOT NULL,
                    unit TEXT NOT NULL,
                    source TEXT NOT NULL,
                    pocket_id TEXT NOT NULL,
                    balance TEXT NOT NULL,
                    observed_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    entitlement_expires_at TEXT,
                    unit_value_cny TEXT,
                    PRIMARY KEY (provider, account_revision, unit, source, pocket_id)
                );
                CREATE TABLE IF NOT EXISTS reservations (
                    request_id TEXT PRIMARY KEY,
                    provider TEXT NOT NULL,
                    account_revision TEXT NOT NULL,
                    unit TEXT NOT NULL,
                    source TEXT NOT NULL,
                    pocket_id TEXT NOT NULL,
                    amount TEXT NOT NULL,
                    sequence INTEGER NOT NULL UNIQUE,
                    reserved_at TEXT NOT NULL,
                    valid_until TEXT,
                    state TEXT NOT NULL,
                    actual TEXT,
                    settled_at TEXT,
                    estimated TEXT,
                    receipt_evidence_id TEXT,
                    receipt_recorded_at TEXT,
                    absorbed INTEGER NOT NULL DEFAULT 0 CHECK (absorbed IN (0, 1))
                );
                CREATE TABLE IF NOT EXISTS bundles (
                    request_id TEXT PRIMARY KEY,
                    allocations TEXT NOT NULL,
                    valid_until TEXT,
                    reserved_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS reservation_scope ON reservations
                    (provider, account_revision, unit, source, pocket_id, state, absorbed);
                CREATE TABLE IF NOT EXISTS request_traces (
                    request_id TEXT PRIMARY KEY,
                    provider TEXT NOT NULL,
                    account_revision TEXT NOT NULL,
                    model_id TEXT NOT NULL,
                    trace_fingerprint TEXT NOT NULL,
                    UNIQUE (provider, account_revision, trace_fingerprint)
                );
                """
            )
            columns = {row["name"] for row in self._connection.execute("PRAGMA table_info(reservations)")}
            if "settled_at" not in columns:
                self._connection.execute("ALTER TABLE reservations ADD COLUMN settled_at TEXT")
            if "estimated" not in columns:
                self._connection.execute("ALTER TABLE reservations ADD COLUMN estimated TEXT")
            if "receipt_evidence_id" not in columns:
                self._connection.execute("ALTER TABLE reservations ADD COLUMN receipt_evidence_id TEXT")
            if "receipt_recorded_at" not in columns:
                self._connection.execute("ALTER TABLE reservations ADD COLUMN receipt_recorded_at TEXT")
            self._connection.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS reservation_receipt_evidence "
                "ON reservations (receipt_evidence_id) WHERE receipt_evidence_id IS NOT NULL"
            )

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                yield self._connection
                self._connection.execute("COMMIT")
            except BaseException:
                self._connection.execute("ROLLBACK")
                raise

    @staticmethod
    def _scope(
        provider: Any, account_revision: Any, unit: Any, source: Any, pocket_id: Any = "default"
    ) -> tuple[str, str, str, str, str]:
        provider_text = _text(provider, "provider")
        revision_text = _text(account_revision, "account_revision")
        unit_text = _text(unit, "unit", _UNIT)
        if source not in _SOURCES:
            raise ValueError("invalid funding source")
        return provider_text, revision_text, unit_text, source, _text(pocket_id, "pocket_id")

    @staticmethod
    def _clock(value: datetime | None) -> datetime:
        if value is None:
            return _now()
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise ValueError("now must be timezone-aware")
        return value.astimezone(timezone.utc)

    def _snapshot(self, connection: sqlite3.Connection, scope: tuple[str, str, str, str, str]) -> sqlite3.Row | None:
        return connection.execute(
            """SELECT * FROM snapshots WHERE provider = ? AND account_revision = ? AND unit = ?
               AND source = ? AND pocket_id = ?""", scope
        ).fetchone()

    def _obligation(self, connection: sqlite3.Connection, scope: tuple[str, str, str, str, str]) -> Decimal:
        rows = connection.execute(
            """SELECT amount, actual, estimated FROM reservations
               WHERE provider = ? AND account_revision = ? AND unit = ? AND source = ? AND pocket_id = ?
                 AND absorbed = 0 AND state <> 'released'""",
            scope,
        ).fetchall()
        total = Decimal(0)
        for row in rows:
            actual = _row_amount(row, "actual")
            estimated = _row_amount(row, "estimated")
            total += actual if actual is not None else estimated if estimated is not None else Decimal(row["amount"])
        return total

    def _projection(self, connection: sqlite3.Connection, scope: tuple[str, str, str, str, str], now: datetime) -> dict[str, Any]:
        snapshot = self._snapshot(connection, scope)
        obligation = self._obligation(connection, scope)
        provider, account_revision, unit, source, pocket_id = scope
        if snapshot is None:
            return {
                "provider": provider, "account_revision": account_revision, "unit": unit, "source": source, "pocket_id": pocket_id,
                "state": "unknown", "balance": None, "inflight_and_unsettled": obligation,
                "available": Decimal(0), "fresh": False, "entitlement_active": False,
            }
        fresh = now < _time(snapshot["expires_at"], "expires_at")
        entitlement = snapshot["entitlement_expires_at"]
        entitlement_active = entitlement is None or now < _time(entitlement, "entitlement_expires_at")
        balance = Decimal(snapshot["balance"])
        available = max(Decimal(0), balance - obligation) if fresh and entitlement_active else Decimal(0)
        state = "available" if fresh and entitlement_active else "expired" if not entitlement_active else "stale"
        return {
            "provider": provider, "account_revision": account_revision, "unit": unit, "source": source, "pocket_id": pocket_id,
            "state": state, "balance": balance, "inflight_and_unsettled": obligation,
            "available": available, "fresh": fresh, "entitlement_active": entitlement_active,
            "observed_at": _time(snapshot["observed_at"], "observed_at"),
            "expires_at": _time(snapshot["expires_at"], "expires_at"),
            "entitlement_expires_at": _time(entitlement, "entitlement_expires_at") if entitlement else None,
            "unit_value_cny": _row_amount(snapshot, "unit_value_cny"),
        }

    def observe(self, snapshot: Mapping[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
        """Store a fresh authoritative balance observation and explicit reconciliation."""
        if not isinstance(snapshot, Mapping):
            raise ValueError("snapshot must be a mapping")
        provider = snapshot.get("provider", snapshot.get("provider_id"))
        balance = snapshot.get("balance", snapshot.get("amount"))
        scope = self._scope(
            provider, snapshot.get("account_revision"), snapshot.get("unit"), snapshot.get("source"),
            snapshot.get("pocket_id", snapshot.get("lot_id", "default")),
        )
        amount = _decimal(balance, "balance")
        observed = _time(snapshot.get("observed_at"), "observed_at")
        expires = _time(snapshot.get("expires_at"), "expires_at")
        entitlement_raw = snapshot.get("entitlement_expires_at", snapshot.get("entitlement_expires"))
        entitlement = _time(entitlement_raw, "entitlement_expires_at") if entitlement_raw is not None else None
        current = self._clock(now)
        if observed > current or expires <= observed or (entitlement is not None and entitlement <= observed):
            raise ValueError("invalid observation time bounds")
        unit_value = snapshot.get("unit_value_cny")
        value = _decimal(unit_value, "unit_value_cny") if unit_value is not None else None
        included = snapshot.get("included_request_ids", snapshot.get("observed_request_ids", ()))
        if not isinstance(included, (list, tuple)) or len(included) > 4096:
            raise ValueError("included_request_ids must be a bounded list")
        included_ids = tuple(_text(value, "included request id") for value in included)
        if len(set(included_ids)) != len(included_ids):
            raise ValueError("duplicate included request id")
        through = snapshot.get("includes_through")
        if through is not None and (type(through) is not int or through < 0):
            raise ValueError("includes_through must be a non-negative integer")
        with self._transaction() as connection:
            previous = self._snapshot(connection, scope)
            if previous is not None and observed <= _time(previous["observed_at"], "observed_at"):
                raise ValueError("observation is older or a replay")
            for request_id in included_ids:
                reservation = connection.execute("SELECT * FROM reservations WHERE request_id = ?", (request_id,)).fetchone()
                if reservation is None or tuple(reservation[key] for key in ("provider", "account_revision", "unit", "source", "pocket_id")) != scope:
                    raise ValueError("included request is not known for this balance")
                if reservation["state"] != "settled" or reservation["receipt_evidence_id"] is None:
                    raise ValueError("only receipt-confirmed requests may be reconciled")
                if observed < _time(reservation["settled_at"], "settled_at"):
                    raise ValueError("reconciliation predates settlement")
                connection.execute("UPDATE reservations SET absorbed = 1 WHERE request_id = ?", (request_id,))
            if through is not None:
                covered = connection.execute(
                    """SELECT settled_at, receipt_evidence_id FROM reservations
                       WHERE provider = ? AND account_revision = ? AND unit = ? AND source = ? AND pocket_id = ?
                         AND state = 'settled' AND sequence <= ?""",
                    (*scope, through),
                ).fetchall()
                if any(row["receipt_evidence_id"] is None for row in covered):
                    raise ValueError("only receipt-confirmed requests may be reconciled")
                if any(observed < _time(row["settled_at"], "settled_at") for row in covered):
                    raise ValueError("reconciliation predates settlement")
                connection.execute(
                    """UPDATE reservations SET absorbed = 1
                       WHERE provider = ? AND account_revision = ? AND unit = ? AND source = ? AND pocket_id = ?
                         AND state = 'settled' AND sequence <= ?""",
                    (*scope, through),
                )
            connection.execute(
                """INSERT INTO snapshots
                   (provider, account_revision, unit, source, pocket_id, balance, observed_at, expires_at, entitlement_expires_at, unit_value_cny)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(provider, account_revision, unit, source, pocket_id) DO UPDATE SET
                     balance = excluded.balance, observed_at = excluded.observed_at, expires_at = excluded.expires_at,
                     entitlement_expires_at = excluded.entitlement_expires_at, unit_value_cny = excluded.unit_value_cny""",
                (*scope, _stored_decimal(amount), _stored_time(observed), _stored_time(expires),
                 _stored_time(entitlement) if entitlement else None, _stored_decimal(value) if value is not None else None),
            )
            return self._projection(connection, scope, current)

    def quote(
        self, provider: str, account_revision: str, amount: Any, unit: str, *, source: str,
        pocket_id: str = "default", now: datetime | None = None,
    ) -> dict[str, Any]:
        """Return a conservative, non-mutating quote for one funding source."""
        requested = _decimal(amount, "amount", positive=True)
        scope = self._scope(provider, account_revision, unit, source, pocket_id)
        current = self._clock(now)
        with self._lock:
            projection = self._projection(self._connection, scope, current)
        return {**projection, "requested": requested, "sufficient": projection["available"] >= requested}

    def reserve(
        self,
        request_id: str,
        provider: str,
        account_revision: str,
        amount: Any,
        unit: str,
        *,
        source: str,
        pocket_id: str = "default",
        valid_until: str | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Atomically reserve an exact amount.  Reusing the same request is idempotent."""
        request = _text(request_id, "request_id")
        requested = _decimal(amount, "amount", positive=True)
        scope = self._scope(provider, account_revision, unit, source, pocket_id)
        current = self._clock(now)
        deadline = _time(valid_until, "valid_until") if valid_until is not None else None
        with self._transaction() as connection:
            existing = connection.execute("SELECT * FROM reservations WHERE request_id = ?", (request,)).fetchone()
            if existing is not None:
                expected = (*scope, _stored_decimal(requested), _stored_time(deadline) if deadline else None)
                actual = tuple(existing[key] for key in ("provider", "account_revision", "unit", "source", "pocket_id", "amount", "valid_until"))
                if actual != expected:
                    raise ValueError("request_id already has different reservation details")
                return self._reservation(existing)
            projection = self._projection(connection, scope, current)
            if projection["state"] != "available" or projection["available"] < requested:
                raise ValueError("insufficient fresh funding")
            if deadline is not None:
                if deadline <= current or deadline > projection["expires_at"]:
                    raise ValueError("reservation outlives observation freshness")
                entitlement = projection["entitlement_expires_at"]
                if entitlement is not None and deadline > entitlement:
                    raise ValueError("reservation outlives entitlement")
            sequence = connection.execute("SELECT COALESCE(MAX(sequence), 0) + 1 FROM reservations").fetchone()[0]
            connection.execute(
                """INSERT INTO reservations
                   (request_id, provider, account_revision, unit, source, pocket_id, amount, sequence, reserved_at, valid_until, state, actual)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'reserved', NULL)""",
                (request, *scope, _stored_decimal(requested), sequence, _stored_time(current), _stored_time(deadline) if deadline else None),
            )
            created = connection.execute("SELECT * FROM reservations WHERE request_id = ?", (request,)).fetchone()
            return self._reservation(created)

    def reserve_bundle(
        self, request_id: str, allocations: list[Mapping[str, Any]], *, valid_until: str | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Atomically reserve multiple isolated pockets under one idempotency key.

        Each allocation requires ``provider``, ``account_revision``, ``unit``,
        ``source`` and ``amount``; ``pocket_id`` defaults to ``default``.
        """
        request = _text(request_id, "request_id")
        if len(request) > 230:
            raise ValueError("bundle request_id is too long")
        if not isinstance(allocations, list) or not 1 <= len(allocations) <= 128:
            raise ValueError("allocations must be a bounded nonempty list")
        deadline = _time(valid_until, "valid_until") if valid_until is not None else None
        current = self._clock(now)
        normalized = []
        for allocation in allocations:
            if not isinstance(allocation, Mapping):
                raise ValueError("invalid allocation")
            scope = self._scope(
                allocation.get("provider", allocation.get("provider_id")), allocation.get("account_revision"),
                allocation.get("unit"), allocation.get("source"), allocation.get("pocket_id", "default"),
            )
            normalized.append({"scope": scope, "amount": _decimal(allocation.get("amount"), "amount", positive=True)})
        if len({item["scope"] for item in normalized}) != len(normalized):
            raise ValueError("bundle allocations must use distinct pockets")
        serialized = json.dumps(
            [{"provider": item["scope"][0], "account_revision": item["scope"][1], "unit": item["scope"][2],
              "source": item["scope"][3], "pocket_id": item["scope"][4], "amount": _stored_decimal(item["amount"])}
             for item in normalized],
            separators=(",", ":"), sort_keys=True,
        )
        child_ids = [f"{request}:{index}" for index in range(len(normalized))]
        with self._transaction() as connection:
            existing = connection.execute("SELECT * FROM bundles WHERE request_id = ?", (request,)).fetchone()
            if existing is not None:
                if existing["allocations"] != serialized or existing["valid_until"] != (_stored_time(deadline) if deadline else None):
                    raise ValueError("request_id already has different bundle details")
                rows = [connection.execute("SELECT * FROM reservations WHERE request_id = ?", (child_id,)).fetchone() for child_id in child_ids]
                if any(row is None for row in rows):
                    raise ValueError("incomplete bundle state")
                return self._bundle(request, rows)
            if connection.execute("SELECT 1 FROM reservations WHERE request_id = ?", (request,)).fetchone() is not None:
                raise ValueError("request_id already has a single reservation")
            if any(connection.execute("SELECT 1 FROM reservations WHERE request_id = ?", (child_id,)).fetchone() for child_id in child_ids):
                raise ValueError("bundle allocation request_id already exists")
            for item in normalized:
                projection = self._projection(connection, item["scope"], current)
                if projection["state"] != "available" or projection["available"] < item["amount"]:
                    raise ValueError("insufficient fresh funding")
                if deadline is not None:
                    if deadline <= current or deadline > projection["expires_at"]:
                        raise ValueError("reservation outlives observation freshness")
                    entitlement = projection["entitlement_expires_at"]
                    if entitlement is not None and deadline > entitlement:
                        raise ValueError("reservation outlives entitlement")
            sequence = connection.execute("SELECT COALESCE(MAX(sequence), 0) FROM reservations").fetchone()[0]
            for index, item in enumerate(normalized, start=1):
                connection.execute(
                    """INSERT INTO reservations
                       (request_id, provider, account_revision, unit, source, pocket_id, amount, sequence, reserved_at, valid_until, state, actual)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'reserved', NULL)""",
                    (child_ids[index - 1], *item["scope"], _stored_decimal(item["amount"]), sequence + index,
                     _stored_time(current), _stored_time(deadline) if deadline else None),
                )
            connection.execute(
                "INSERT INTO bundles (request_id, allocations, valid_until, reserved_at) VALUES (?, ?, ?, ?)",
                (request, serialized, _stored_time(deadline) if deadline else None, _stored_time(current)),
            )
            rows = [connection.execute("SELECT * FROM reservations WHERE request_id = ?", (child_id,)).fetchone() for child_id in child_ids]
            return self._bundle(request, rows)

    def settle(
        self, request_id: str, actual: Any | list[Any | None] | None = None, *,
        estimated: Any | list[Any | None] | None = None, request_not_sent: bool = False,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Record an unverified actual, a usage estimate, an unknown send, or a proven unsent request."""
        request = _text(request_id, "request_id")
        if (actual is not None and estimated is not None) or (request_not_sent and (actual is not None or estimated is not None)):
            raise ValueError("settlement accepts one outcome")
        current = self._clock(now)
        with self._transaction() as connection:
            row = connection.execute("SELECT * FROM reservations WHERE request_id = ?", (request,)).fetchone()
            bundle = None if row is not None else connection.execute("SELECT * FROM bundles WHERE request_id = ?", (request,)).fetchone()
            if row is None and bundle is None:
                raise ValueError("unknown request_id")
            if row is not None:
                rows = [row]
            else:
                expected_count = len(json.loads(bundle["allocations"]))
                rows = [
                    connection.execute("SELECT * FROM reservations WHERE request_id = ?", (f"{request}:{index}",)).fetchone()
                    for index in range(expected_count)
                ]
                if any(item is None for item in rows):
                    raise ValueError("incomplete bundle state")
            outcome = actual if actual is not None else estimated
            if bundle is not None:
                if outcome is None:
                    actuals = [None] * len(rows)
                elif isinstance(outcome, list) and len(outcome) == len(rows):
                    actuals = [_decimal(value, "amount", positive=False) if value is not None else None for value in outcome]
                elif len(rows) == 1:
                    actuals = [_decimal(outcome, "amount", positive=False)]
                else:
                    raise ValueError("bundle settlement requires one amount per allocation")
            else:
                actuals = [_decimal(outcome, "amount", positive=False) if outcome is not None else None]
            if request_not_sent:
                if all(item["state"] == "released" for item in rows):
                    return self._bundle(request, rows) if bundle is not None else self._reservation(rows[0])
                if any(item["state"] != "reserved" for item in rows):
                    raise ValueError("an uncertain or sent request cannot be released")
                for item in rows:
                    connection.execute("UPDATE reservations SET state = 'released', actual = NULL WHERE request_id = ?", (item["request_id"],))
            else:
                for item, exact in zip(rows, actuals):
                    if exact is None:
                        if item["state"] == "reserved":
                            connection.execute("UPDATE reservations SET state = 'unknown' WHERE request_id = ?", (item["request_id"],))
                        continue
                    if estimated is not None:
                        if item["state"] == "released":
                            raise ValueError("released request cannot be estimated")
                        if item["state"] == "estimated":
                            if Decimal(item["estimated"]) != exact:
                                raise ValueError("request already has a different usage estimate")
                            continue
                        if item["state"] == "settled":
                            raise ValueError("receipt or actual settlement cannot be replaced by an estimate")
                        connection.execute(
                            "UPDATE reservations SET state = 'estimated', estimated = ? WHERE request_id = ?",
                            (_stored_decimal(exact), item["request_id"]),
                        )
                        continue
                    if item["state"] == "released":
                        raise ValueError("released request cannot be settled")
                    if item["state"] == "settled":
                        if Decimal(item["actual"]) != exact:
                            raise ValueError("request already settled with a different amount")
                        continue
                    connection.execute(
                        "UPDATE reservations SET state = 'settled', actual = ?, settled_at = ? WHERE request_id = ?",
                        (_stored_decimal(exact), _stored_time(current), item["request_id"]),
                    )
            updated = [connection.execute("SELECT * FROM reservations WHERE request_id = ?", (item["request_id"],)).fetchone() for item in rows]
            return self._bundle(request, updated) if bundle is not None else self._reservation(updated[0])

    def record_request_trace(self, request_id: str, trace_fingerprint: str, model_id: str) -> None:
        """Bind a transport-observed upstream trace to a durable request, without its body."""
        request = _text(request_id, "request_id")
        trace = _text(trace_fingerprint, "trace_fingerprint", re.compile(r"[a-f0-9]{64}"))
        model = _text(model_id, "model_id", re.compile(r"[A-Za-z0-9][A-Za-z0-9/._:-]{0,239}"))
        with self._transaction() as connection:
            bundle = connection.execute("SELECT allocations FROM bundles WHERE request_id = ?", (request,)).fetchone()
            identifiers = [f"{request}:{index}" for index in range(len(json.loads(bundle["allocations"])))] if bundle else [request]
            rows = [connection.execute("SELECT * FROM reservations WHERE request_id = ?", (identifier,)).fetchone() for identifier in identifiers]
            if any(row is None or row["state"] == "released" for row in rows):
                raise ValueError("trace requires a sent reserved request")
            scopes = {(row["provider"], row["account_revision"]) for row in rows}
            if len(scopes) != 1:
                raise ValueError("trace cannot span provider accounts")
            provider, revision = scopes.pop()
            expected = (request, provider, revision, model, trace)
            existing = connection.execute("SELECT * FROM request_traces WHERE request_id = ?", (request,)).fetchone()
            if existing:
                if tuple(existing) != expected:
                    raise ValueError("request already has a different upstream trace")
                return
            duplicate = connection.execute("SELECT 1 FROM request_traces WHERE provider = ? AND account_revision = ? AND trace_fingerprint = ?",
                                           (provider, revision, trace)).fetchone()
            if duplicate:
                raise ValueError("upstream trace already belongs to another request")
            connection.execute("INSERT INTO request_traces VALUES (?, ?, ?, ?, ?)", expected)

    def match_request_trace(self, provider: str, account_revision: str, trace_fingerprint: str, model_id: str) -> list[dict[str, Any]]:
        """Return only exact transport-trace matches, never time or amount correlations."""
        with self._lock:
            trace = self._connection.execute(
                "SELECT request_id, model_id FROM request_traces WHERE provider = ? AND account_revision = ? AND trace_fingerprint = ?",
                (provider, account_revision, trace_fingerprint),
            ).fetchone()
            if trace is None:
                return []
            if trace["model_id"] != model_id:
                raise ValueError("receipt model does not match request")
            request = trace["request_id"]
            bundle = self._connection.execute("SELECT allocations FROM bundles WHERE request_id = ?", (request,)).fetchone()
            identifiers = [f"{request}:{index}" for index in range(len(json.loads(bundle["allocations"])))] if bundle else [request]
            return [self._reservation(self._connection.execute("SELECT * FROM reservations WHERE request_id = ?", (identifier,)).fetchone())
                    for identifier in identifiers]

    def reconcile_receipt(
        self, request_id: str, actual: Any, evidence_id: str, *, now: datetime | None = None
    ) -> dict[str, Any]:
        """Apply a receipt-confirmed amount without storing a receipt body.

        Bundle callers reconcile the allocation request IDs returned by
        ``reserve_bundle`` individually, because each provider receipt is scoped
        to one funding pocket.
        """
        request = _text(request_id, "request_id")
        evidence = _text(evidence_id, "evidence_id")
        exact = _decimal(actual, "actual", positive=False)
        current = self._clock(now)
        with self._transaction() as connection:
            row = connection.execute("SELECT * FROM reservations WHERE request_id = ?", (request,)).fetchone()
            if row is None:
                if connection.execute("SELECT 1 FROM bundles WHERE request_id = ?", (request,)).fetchone() is not None:
                    raise ValueError("bundle receipts must identify an allocation request_id")
                raise ValueError("unknown request_id")
            existing_evidence = row["receipt_evidence_id"]
            if existing_evidence is not None:
                if existing_evidence == evidence and Decimal(row["actual"]) == exact:
                    return self._reservation(row)
                raise ValueError("request already has a different receipt")
            duplicate = connection.execute(
                "SELECT request_id FROM reservations WHERE receipt_evidence_id = ?", (evidence,)
            ).fetchone()
            if duplicate is not None:
                raise ValueError("receipt evidence already belongs to another request")
            if row["state"] == "released":
                raise ValueError("released request cannot be receipt-reconciled")
            connection.execute(
                """UPDATE reservations SET state = 'settled', actual = ?, settled_at = ?,
                   receipt_evidence_id = ?, receipt_recorded_at = ? WHERE request_id = ?""",
                (_stored_decimal(exact), _stored_time(current), evidence, _stored_time(current), request),
            )
            updated = connection.execute("SELECT * FROM reservations WHERE request_id = ?", (request,)).fetchone()
            return self._reservation(updated)

    def status(self, *, now: datetime | None = None) -> dict[str, Any]:
        """Return all scoped projections and durable reservation records."""
        current = self._clock(now)
        with self._lock:
            scopes = self._connection.execute(
                "SELECT provider, account_revision, unit, source, pocket_id FROM snapshots ORDER BY provider, account_revision, unit, source, pocket_id"
            ).fetchall()
            reservations = self._connection.execute("SELECT * FROM reservations ORDER BY sequence").fetchall()
            return {
                "projections": [self._projection(self._connection, tuple(row), current) for row in scopes],
                "reservations": [self._reservation(row) for row in reservations],
            }

    def projection(
        self, provider: str, account_revision: str, unit: str, *, source: str, pocket_id: str = "default", now: datetime | None = None
    ) -> dict[str, Any]:
        """Return the current balance minus every unreconciled reservation."""
        scope = self._scope(provider, account_revision, unit, source, pocket_id)
        current = self._clock(now)
        with self._lock:
            return self._projection(self._connection, scope, current)

    @staticmethod
    def _reservation(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "request_id": row["request_id"], "provider": row["provider"], "account_revision": row["account_revision"],
            "unit": row["unit"], "source": row["source"], "pocket_id": row["pocket_id"], "amount": Decimal(row["amount"]),
            "sequence": row["sequence"], "reserved_at": _time(row["reserved_at"], "reserved_at"),
            "valid_until": _time(row["valid_until"], "valid_until") if row["valid_until"] else None,
            "state": row["state"], "actual": _row_amount(row, "actual"),
            "settled_at": _time(row["settled_at"], "settled_at") if row["settled_at"] else None,
            "estimated": _row_amount(row, "estimated"), "receipt_evidence_id": row["receipt_evidence_id"],
            "receipt_recorded_at": _time(row["receipt_recorded_at"], "receipt_recorded_at") if row["receipt_recorded_at"] else None,
            "absorbed": bool(row["absorbed"]),
        }

    def _bundle(self, request_id: str, rows: list[sqlite3.Row]) -> dict[str, Any]:
        return {"request_id": request_id, "allocations": [self._reservation(row) for row in rows]}
