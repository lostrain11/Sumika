"""Bounded, content-independent audit receipts for desktop automation."""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

from .contracts import hash_value, safe_text


AUDIT_SCHEMA_VERSION = 1
_MAX_RECORD_BYTES = 16 * 1024
_MAX_DAY_BYTES = 8 * 1024 * 1024


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _day(value: str | None = None) -> str:
    raw = value or _utc_now()
    return raw[:10]


def _token(value: Any, limit: int = 160) -> str:
    try:
        text = str(value or "").strip()
    except Exception:
        return ""
    if len(text) > limit:
        text = text[:limit]
    if any(ord(char) < 32 or ord(char) == 127 for char in text):
        return ""
    return text


class DesktopAuditSink:
    """Write hashes and bounded metadata, never action bodies or screenshots."""

    def __init__(self, data_dir: str | Path | None = None, *, logger: Any = None) -> None:
        self.logger = logger
        self.root = Path(data_dir) / "logs" / "desktop-automation" if data_dir else None
        self._lock = threading.RLock()
        self._closed = False
        self.records: list[dict[str, Any]] = []

    def record(
        self,
        *,
        app_id: str,
        adapter_id: str,
        transport: str,
        session_id: str | None,
        action: str,
        risk: str,
        status: str,
        duration_ms: float | None = None,
        target: str | None = None,
        input_sha256: str | None = None,
        output_sha256: str | None = None,
        error_code: str | None = None,
        approval: bool = False,
    ) -> dict[str, Any]:
        """Append one safe receipt and return the in-memory projection."""

        record: dict[str, Any] = {
            "schema_version": AUDIT_SCHEMA_VERSION,
            "audit_id": f"desktop-audit-{uuid4().hex[:16]}",
            "timestamp": _utc_now(),
            "app_id": _token(app_id, 160),
            "adapter_id": _token(adapter_id, 120),
            "transport": _token(transport, 80),
            "session_id": _token(session_id, 180) or None,
            "action": _token(action, 80),
            "risk": _token(risk, 40),
            "status": _token(status, 48),
            "approval": bool(approval),
        }
        if target not in (None, ""):
            target_text = _token(target, 600)
            record["target_sha256"] = hash_value(target_text)
            record["target_length"] = len(target_text)
        if input_sha256:
            record["input_sha256"] = _token(input_sha256, 128)
        if output_sha256:
            record["output_sha256"] = _token(output_sha256, 128)
        if duration_ms is not None:
            try:
                number = float(duration_ms)
            except (TypeError, ValueError):
                number = None
            if number is not None and number >= 0:
                record["duration_ms"] = round(min(number, 86_400_000), 3)
        if error_code:
            record["error_code"] = _token(error_code, 120)

        encoded = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if len(encoded.encode("utf-8")) > _MAX_RECORD_BYTES:
            # This should only be reachable if a future field is added without
            # a bound. Keep the audit channel usable and deterministic.
            record = {
                "schema_version": AUDIT_SCHEMA_VERSION,
                "audit_id": record["audit_id"],
                "timestamp": record["timestamp"],
                "app_id": record["app_id"],
                "adapter_id": record["adapter_id"],
                "transport": record["transport"],
                "session_id": record["session_id"],
                "action": record["action"],
                "risk": record["risk"],
                "status": record["status"],
                "input_sha256": record.get("input_sha256"),
                "output_sha256": record.get("output_sha256"),
                "error_code": record.get("error_code"),
            }
            encoded = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

        with self._lock:
            self.records.append(dict(record))
            if len(self.records) > 1000:
                del self.records[:-1000]
            if self.root is not None and not self._closed:
                try:
                    self.root.mkdir(parents=True, exist_ok=True)
                    target_path = self.root / f"{_day(record['timestamp'])}.jsonl"
                    current_size = target_path.stat().st_size if target_path.exists() else 0
                    if current_size + len(encoded.encode("utf-8")) + 1 <= _MAX_DAY_BYTES:
                        with target_path.open("a", encoding="utf-8", newline="\n") as stream:
                            stream.write(encoded + "\n")
                            stream.flush()
                except OSError as error:
                    if self.logger is not None:
                        try:
                            self.logger.warning("desktop audit write failed error_type=%s", type(error).__name__)
                        except Exception:
                            pass
        return dict(record)

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "enabled": self.root is not None,
                "schema_version": AUDIT_SCHEMA_VERSION,
                "relative_path": "logs/desktop-automation" if self.root is not None else None,
                "in_memory_records": len(self.records),
                "retention": "bounded metadata; no action bodies or screenshots",
            }

    def close(self) -> None:
        with self._lock:
            self._closed = True


__all__ = ["AUDIT_SCHEMA_VERSION", "DesktopAuditSink"]
