from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from .contracts import RoutingError


SCHEMA = "development-journal/v1"


def evidence_digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False).encode("utf-8")).hexdigest()


def checked_event(event: dict) -> dict:
    fields = {"schema_version", "operation_id", "kind", "phase", "turn", "slot", "name",
              "input_digest", "output_digest", "outcome"}
    if not isinstance(event, dict) or set(event) - fields or event.get("schema_version") != SCHEMA:
        raise RoutingError("invalid development journal event")
    kind, phase, turn = event.get("kind"), event.get("phase"), event.get("turn")
    if kind not in {"model", "tool"} or phase not in {"started", "finished"} or type(turn) is not int or turn < 1:
        raise RoutingError("invalid development operation")
    expected_id = f"model-{turn}"
    if kind == "tool":
        slot = event.get("slot")
        if type(slot) is not int or not 0 <= slot < 4:
            raise RoutingError("invalid development tool slot")
        if not isinstance(event.get("name"), str) or not re.fullmatch(r"[a-z_]{1,64}", event["name"]):
            raise RoutingError("invalid development tool name")
        expected_id = f"tool-{turn}-{slot}"
    elif "slot" in event or "name" in event:
        raise RoutingError("invalid model operation fields")
    if event.get("operation_id") != expected_id:
        raise RoutingError("invalid development operation identity")
    for key in ("input_digest", "output_digest"):
        if key in event and (not isinstance(event[key], str) or not re.fullmatch(r"[0-9a-f]{64}", event[key])):
            raise RoutingError("invalid development evidence digest")
    if phase == "started":
        if "input_digest" not in event or "outcome" in event or "output_digest" in event:
            raise RoutingError("invalid development intent")
    elif event.get("outcome") not in {"returned", "rejected", "unknown"} or "output_digest" not in event:
        raise RoutingError("invalid development receipt")
    return dict(event)


def append_event(records: list, event: dict) -> list:
    event = checked_event(event)
    if not isinstance(records, list) or len(records) >= 10000:
        raise RoutingError("development journal limit exceeded")
    related = [record for record in records if record["operation_id"] == event["operation_id"]]
    if event["phase"] == "started":
        if related:
            raise RoutingError("development operation already dispatched")
    elif len(related) != 1 or related[0]["phase"] != "started" or any(
            related[0].get(key) != event.get(key) for key in ("kind", "turn", "slot", "name")):
        raise RoutingError("development receipt has no matching intent")
    return [*records, event]


def recovery_state(records: list) -> dict:
    checked = []
    for event in records:
        checked = append_event(checked, event)
    pending = {}
    for event in checked:
        if event["phase"] == "started":
            pending[event["operation_id"]] = event
        elif event["outcome"] != "unknown":
            pending.pop(event["operation_id"], None)
    return {"schema_version": SCHEMA, "state": "submission-unknown" if pending else "interrupted",
            "pending_operations": list(pending.values()), "automatic_replay": False}
