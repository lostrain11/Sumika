from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from typing import Any, Mapping

from .contracts import Node, Plan, RoutingError


SCHEMA = "task-planning/v1"


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def node_digest(node: Node) -> str:
    return digest(asdict(node))


def validate_planning(value: Mapping[str, Any] | None, plan: Plan) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise RoutingError("planning must be an object")
    required = {"schema_version", "mode", "goal_contract_digest", "horizon_complete", "phases", "handoffs", "revision_reason"}
    if set(value) != required or value["schema_version"] != SCHEMA:
        raise RoutingError("unsupported planning schema or fields")
    if not isinstance(value["mode"], str) or value["mode"] not in {"rolling", "batch"} or type(value["horizon_complete"]) is not bool:
        raise RoutingError("invalid planning mode or horizon")
    if value["mode"] == "batch" and not value["horizon_complete"]:
        raise RoutingError("batch planning must cover the complete horizon")
    contract = value["goal_contract_digest"]
    if not isinstance(contract, str) or len(contract) != 64 or any(char not in "0123456789abcdef" for char in contract):
        raise RoutingError("invalid goal contract digest")
    if not isinstance(value["revision_reason"], str) or not value["revision_reason"].strip():
        raise RoutingError("planning revision reason is required")
    if not isinstance(value["phases"], list) or any(not isinstance(phase, dict) or
            set(phase) != {"goal", "prerequisites"} or not isinstance(phase["goal"], str) or
            not phase["goal"].strip() or not isinstance(phase["prerequisites"], list) or
            any(not isinstance(item, str) or not item.strip() for item in phase["prerequisites"])
            for phase in value["phases"]):
        raise RoutingError("invalid future phases")
    if not value["horizon_complete"] and not value["phases"]:
        raise RoutingError("rolling horizon requires remaining phases")
    handoffs = value["handoffs"]
    if not isinstance(handoffs, dict) or set(handoffs) - {node.node_id for node in plan.nodes}:
        raise RoutingError("handoff refers to an unknown node")
    try:
        return json.loads(json.dumps(value, allow_nan=False))
    except (TypeError, ValueError):
        raise RoutingError("planning must contain finite JSON data") from None


def handoff_errors(node: Node, planning: Mapping[str, Any] | None,
                   results: Mapping[str, Any], *, required: bool = False) -> tuple[str, ...]:
    if planning is None:
        return ("missing-planning",) if required else ()
    handoff = planning["handoffs"].get(node.node_id)
    if not isinstance(handoff, dict):
        return ("missing-handoff",)
    errors = []
    fields = {"node_digest", "inputs", "deliverables", "decisions", "constraints", "validation",
              "failure_policy", "blocking_questions", "review"}
    if set(handoff) != fields:
        errors.append("handoff-fields")
    if handoff.get("node_digest") != node_digest(node):
        errors.append("stale-node-digest")
    for field in ("deliverables", "decisions", "constraints", "validation", "failure_policy"):
        items = handoff.get(field)
        if not isinstance(items, list) or not items or any(not isinstance(item, str) or not item.strip() for item in items):
            errors.append("missing-" + field)
    if handoff.get("blocking_questions") != []:
        errors.append("blocking-questions")
    review = handoff.get("review")
    if (not isinstance(review, dict) or set(review) != {"kind", "reference", "accepted"} or
            not isinstance(review.get("kind"), str) or review["kind"] not in {"leader", "template"} or review.get("accepted") is not True or
            not isinstance(review.get("reference"), str) or not review["reference"].strip()):
        errors.append("missing-design-review")
    elif review["kind"] == "template" and (node.task_type != "bounded-text" or node.risk != "low" or
                                           review["reference"] != "bounded-text/v1"):
        errors.append("template-outside-capability")
    inputs = handoff.get("inputs")
    seen = set()
    if not isinstance(inputs, list) or not inputs:
        errors.append("missing-inputs")
    else:
        for item in inputs:
            if not isinstance(item, dict):
                errors.append("invalid-input")
            elif item.get("kind") == "literal" and set(item) == {"kind", "text"}:
                if not isinstance(item["text"], str) or not item["text"].strip():
                    errors.append("empty-input")
            elif item.get("kind") == "dependency" and set(item) == {"kind", "node_id"}:
                dependency = item["node_id"]
                if not isinstance(dependency, str) or dependency not in node.dependencies:
                    errors.append("invalid-dependency-reference")
                else:
                    seen.add(dependency)
                    result = results.get(dependency)
                    if not isinstance(result, dict) or result.get("status") != "completed":
                        errors.append("dependency-result-unavailable")
            else:
                errors.append("unsupported-input-reference")
    if set(node.dependencies) - seen:
        errors.append("missing-dependency-reference")
    return tuple(errors)
