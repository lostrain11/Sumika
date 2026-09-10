from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from .contracts import BudgetRule, Candidate, Node, Outcome, Plan, Quote, RoutingError, Scope, Verification
from .engine import Coordinator


HELPER_SCHEMA = "quality-routing/dsh-helper/v1"
HELPER_VERSION = "0.1.0"


def capabilities() -> dict[str, Any]:
    return {
        "schema": HELPER_SCHEMA,
        "component": "quality-routing",
        "version": HELPER_VERSION,
        "sumika_core_dependency": False,
        "real_model_execution": {"available": False, "reason": "trusted-host-adapter-not-configured"},
        "offline_fixture": {"available": True, "real_model": False},
        "model_tool_can_approve": False,
    }


def run_offline_fixture() -> dict[str, Any]:
    scope = Scope("dsh-fixture", "offline")
    candidate = Candidate(
        "offline-fixture",
        "offline-account",
        "deterministic-fixture",
        "tool",
        authorized=True,
        available=True,
        external=False,
        fixed_cash="0",
    )
    coordinator = Coordinator(
        [candidate],
        executor=lambda execution: Outcome(
            "completed",
            "offline-fixture-result",
            cash_cny="0",
            input_tokens=8,
            output_tokens=4,
        ),
        verifier=lambda execution, outcome: Verification(True, ("deterministic-offline-check",)),
        permission=lambda execution: execution.candidate.candidate_id == "offline-fixture",
        max_concurrency=1,
    )
    try:
        plan = Plan(
            "dsh-offline-fixture",
            scope,
            1,
            (Node(
                "fixture",
                "Run the deterministic offline fixture",
                "offline-fixture",
                "offline-fixture",
                acceptance=("fixture result is verified",),
                input_tokens=8,
                output_tokens=4,
            ),),
        )
        submitted = coordinator.submit(
            plan,
            Quote("0", "0", "0", 2, 12),
            BudgetRule(),
            allowed_ids={"offline-fixture"},
        )
        approved = coordinator.approve(plan.task_id, scope, plan.revision)
        completed = coordinator.wait(plan.task_id, scope)
        result = completed["results"]["fixture"]
        return {
            "schema": HELPER_SCHEMA,
            "fixture": True,
            "real_model": False,
            "states": [submitted["status"], approved["status"], completed["status"]],
            "result": {"status": result["status"], "evidence": result["evidence"]},
        }
    finally:
        coordinator.close()


class HelperServer:
    def __init__(self, data_dir: Path) -> None:
        if not data_dir.is_absolute():
            raise RoutingError("data directory must be absolute")
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.lifecycle_path = self.data_dir / "lifecycle.json"
        self._write_lifecycle("ready")

    def _write_lifecycle(self, state: str) -> None:
        value = {"schema": HELPER_SCHEMA, "state": state, "pid": os.getpid()}
        self.lifecycle_path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")

    def handle(self, request: Any) -> tuple[dict[str, Any], bool]:
        if not isinstance(request, dict) or set(request) != {"id", "method", "params"}:
            raise RoutingError("invalid helper request")
        request_id = request["id"]
        method = request["method"]
        params = request["params"]
        if type(request_id) is not int or request_id < 1 or not isinstance(method, str) or not isinstance(params, dict):
            raise RoutingError("invalid helper request")
        if params:
            raise RoutingError("helper method does not accept parameters")
        if method == "health":
            result = {"schema": HELPER_SCHEMA, "status": "ready"}
        elif method == "capabilities":
            result = capabilities()
        elif method == "offline_fixture":
            result = run_offline_fixture()
        elif method == "shutdown":
            result = {"schema": HELPER_SCHEMA, "status": "stopping"}
            return {"id": request_id, "result": result}, True
        else:
            raise RoutingError("unsupported helper method")
        return {"id": request_id, "result": result}, False

    def close(self) -> None:
        self._write_lifecycle("stopped")


def serve(data_dir: Path) -> int:
    server = HelperServer(data_dir)
    try:
        for line in sys.stdin:
            request = None
            try:
                request = json.loads(line)
                response, stopping = server.handle(request)
            except (json.JSONDecodeError, RoutingError, TypeError, ValueError):
                request_id = request.get("id") if isinstance(request, dict) else None
                response = {"id": request_id, "error": "invalid-or-unsupported-request"}
                stopping = False
            sys.stdout.write(json.dumps(response, sort_keys=True) + "\n")
            sys.stdout.flush()
            if stopping:
                break
        return 0
    finally:
        server.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Managed stdio helper for the independent quality-routing DSH plugin")
    parser.add_argument("--data-dir", required=True, type=Path)
    arguments = parser.parse_args()
    raise SystemExit(serve(arguments.data_dir))


if __name__ == "__main__":
    main()

