"""Optional, host-bound MCP stdio adapter for quality-routing.

The adapter deliberately exposes a narrow task surface.  A host owns the
Coordinator, Scope, execution callbacks, and authorization decisions; MCP
callers cannot select a scope or approve a task.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from .contracts import BudgetRule, Candidate, Plan, Quote, RoutingError, Scope, identifier
from .engine import Coordinator


class McpUnavailableError(RuntimeError):
    """Raised when the optional ``mcp`` extra is not installed."""


@dataclass(frozen=True)
class SubmissionAuthorization:
    """Host-owned limits used when accepting one new task plan."""

    quote: Quote
    rule: BudgetRule
    allowed_ids: frozenset[str]
    external_allowed: bool = False

    def __post_init__(self) -> None:
        if type(self.external_allowed) is not bool:
            raise RoutingError("external authorization must be boolean")
        object.__setattr__(self, "allowed_ids", frozenset(identifier(value) for value in self.allowed_ids))


HostPolicy = Callable[[str, Scope, Plan | str], SubmissionAuthorization | bool | None]


def _compact_status(value: Mapping[str, Any]) -> dict[str, Any]:
    budget = value.get("budget") if isinstance(value.get("budget"), Mapping) else {}
    states = value.get("states") if isinstance(value.get("states"), Mapping) else {}
    return {
        "schema": "quality-routing/mcp-task/v1",
        "task_id": value.get("task_id"),
        "revision": value.get("revision"),
        "status": value.get("status"),
        "reason": value.get("reason") or None,
        "states": dict(states),
        "budget": {
            "spent_cny": budget.get("spent_cny"),
            "estimated_cny": budget.get("estimated_cny"),
            "calls": budget.get("calls"),
            "tokens": budget.get("tokens"),
            "unpriced_calls": budget.get("unpriced_calls"),
        },
    }


class _BoundMcpTools:
    def __init__(self, coordinator: Coordinator, scope: Scope, policy: HostPolicy, *, read_only: bool) -> None:
        self._coordinator = coordinator
        self._scope = scope
        self._policy = policy
        self._read_only = read_only

    def catalog(self) -> dict[str, Any]:
        """Return a bounded, credential-free catalog for this host."""
        rows = []
        for candidate in sorted(self._coordinator.candidates(), key=lambda item: item.candidate_id)[:128]:
            rows.append(self._catalog_candidate(candidate))
        return {
            "schema": "quality-routing/catalog/v1",
            "candidates": rows,
            "truncated": len(self._coordinator.candidates()) > len(rows),
            "capabilities": {
                "read_only": self._read_only,
                "execution": "unavailable" if self._read_only else "host-managed",
                "submission": "unavailable" if self._read_only else "host-policy-managed",
            },
        }

    @staticmethod
    def _catalog_candidate(candidate: Candidate) -> dict[str, Any]:
        return {
            "candidate_id": candidate.candidate_id,
            "model_id": candidate.model_id,
            "channel": candidate.channel,
            "reasoning_effort": candidate.reasoning_effort,
            "capabilities": list(candidate.capabilities),
            "authorized": candidate.authorized,
            "available": candidate.available,
            "external": candidate.external,
            "pricing_source": candidate.pricing_source,
        }

    def status(self, task_id: str) -> dict[str, Any]:
        try:
            return {"ok": True, "task": _compact_status(self._coordinator.status(identifier(task_id), self._scope))}
        except RoutingError:
            return {"ok": False, "reason": "task-unavailable"}

    def result(self, task_id: str, node_id: str) -> dict[str, Any]:
        try:
            status = self._coordinator.status(identifier(task_id), self._scope)
            node = identifier(node_id)
        except RoutingError:
            return {"ok": False, "reason": "task-unavailable"}
        if node not in status["states"]:
            return {"ok": False, "reason": "node-unavailable"}
        value = status["results"].get(node)
        if not isinstance(value, Mapping):
            return {"ok": True, "ready": False, "state": status["states"][node]}
        return {"ok": True, "ready": True, "state": status["states"][node], "result": dict(value)}

    def submit(self, plan: Mapping[str, Any]) -> dict[str, Any]:
        parsed = self._parse_plan(plan)
        if parsed is None:
            return {"ok": False, "reason": "invalid-plan"}
        if parsed.revision != 1:
            return {"ok": False, "reason": "scope-or-revision-denied"}
        decision = self._decide("submit", parsed)
        if not isinstance(decision, SubmissionAuthorization):
            return {"ok": False, "reason": "host-policy-denied"}
        try:
            value = self._coordinator.submit(
                parsed,
                decision.quote,
                decision.rule,
                allowed_ids=decision.allowed_ids,
                external_allowed=decision.external_allowed,
            )
        except RoutingError:
            return {"ok": False, "reason": "submission-rejected"}
        return {"ok": True, "task": _compact_status(value)}

    def revise(self, plan: Mapping[str, Any]) -> dict[str, Any]:
        parsed = self._parse_plan(plan)
        if parsed is None:
            return {"ok": False, "reason": "invalid-plan"}
        if self._decide("revise", parsed) is not True:
            return {"ok": False, "reason": "host-policy-denied"}
        try:
            value = self._coordinator.revise(parsed)
        except RoutingError:
            return {"ok": False, "reason": "revision-rejected"}
        return {"ok": True, "task": _compact_status(value)}

    def advance(self, task_id: str) -> dict[str, Any]:
        try:
            key = identifier(task_id)
            snapshot = self._coordinator.snapshot(key, self._scope)
        except RoutingError:
            return {"ok": False, "reason": "task-unavailable"}
        if snapshot["approved"] is not True:
            return {"ok": False, "reason": "task-not-preauthorized", "task": _compact_status(snapshot)}
        try:
            plan = Plan.from_dict(snapshot["plan"])
        except (KeyError, TypeError, RoutingError):
            return {"ok": False, "reason": "task-unavailable"}
        if self._decide("advance", plan) is not True:
            return {"ok": False, "reason": "host-policy-denied"}
        try:
            value = self._coordinator.advance(key, self._scope)
        except RoutingError:
            return {"ok": False, "reason": "advance-rejected"}
        return {"ok": True, "task": _compact_status(value)}

    def _decide(self, action: str, value: Plan | str) -> SubmissionAuthorization | bool | None:
        try:
            return self._policy(action, self._scope, value)
        except Exception:
            return None

    def _parse_plan(self, value: Mapping[str, Any]) -> Plan | None:
        if not isinstance(value, Mapping) or "scope" in value:
            return None
        try:
            return Plan.from_dict(
                {
                    **dict(value),
                    "scope": {"owner_id": self._scope.owner_id, "session_id": self._scope.session_id},
                }
            )
        except (KeyError, TypeError, RoutingError):
            return None


def create_server(coordinator: Coordinator, scope: Scope, policy: HostPolicy, *, read_only: bool = False) -> Any:
    """Create a FastMCP stdio server bound to one host Coordinator and Scope.

    The host must separately configure Coordinator execution, verification,
    permission, and approval.  This adapter cannot provide any of them.
    """
    if not isinstance(coordinator, Coordinator) or not isinstance(scope, Scope) or not callable(policy) or type(read_only) is not bool:
        raise TypeError("create_server requires a Coordinator, Scope, and host policy callback")
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as error:
        raise McpUnavailableError("install quality-routing[mcp] to use the MCP adapter") from error

    tools = _BoundMcpTools(coordinator, scope, policy, read_only=read_only)
    server = FastMCP(
        "quality-routing",
        instructions=(
            "Host-bound quality-routing task surface. Tasks require host approval; "
            "this server cannot configure providers, credentials, scopes, or execution."
        ),
    )
    server.tool(name="quality_catalog", description="List the bounded host catalog.")(tools.catalog)
    server.tool(name="quality_status", description="Read one task in the host-bound scope.")(tools.status)
    server.tool(name="quality_result", description="Read one completed node result in the host-bound scope.")(tools.result)
    if not read_only:
        server.tool(name="quality_submit", description="Submit a host-policy-authorized plan in the bound scope.")(tools.submit)
        server.tool(name="quality_revise", description="Revise a task only through host policy.")(tools.revise)
        server.tool(name="quality_advance", description="Advance only a host-preauthorized task.")(tools.advance)
    return server


def create_readonly_server() -> Any:
    """Create the standalone stdio surface with no executor or task authority."""
    coordinator = Coordinator()
    try:
        server = create_server(coordinator, Scope("local", "default"), lambda action, scope, value: False, read_only=True)
    except Exception:
        coordinator.close()
        raise
    setattr(server, "_quality_routing_owned_coordinator", coordinator)
    return server


def main() -> int:
    """Run a standalone, read-only stdio server with no execution authority."""
    try:
        server = create_readonly_server()
    except McpUnavailableError as error:
        print(str(error), file=sys.stderr)
        return 2
    coordinator = getattr(server, "_quality_routing_owned_coordinator")
    try:
        server.run(transport="stdio")
    finally:
        coordinator.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
