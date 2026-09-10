from __future__ import annotations

import json

from .contracts import BudgetRule, Candidate, Node, Outcome, Plan, Quote, Scope, Verification
from .engine import Coordinator


SCOPE = Scope("offline-owner", "offline-session")
QUOTE = Quote("0", "0", "0", 4, 10000)
RULE = BudgetRule()


def candidate() -> Candidate:
    return Candidate(
        "offline-fixture",
        "offline-account",
        "deterministic-fixture",
        "tool",
        authorized=True,
        available=True,
        external=False,
        fixed_cash="0",
    )


def plan(task_id: str) -> Plan:
    return Plan(
        task_id,
        SCOPE,
        1,
        (Node(
            "summarize",
            "Create a short offline summary",
            "summary",
            "offline-fixture",
            acceptance=("summary exists",),
        ),),
    )


def coordinator(*, save=None) -> Coordinator:
    return Coordinator(
        [candidate()],
        executor=lambda execution: Outcome(
            "completed",
            "offline-result",
            cash_cny="0",
            input_tokens=16,
            output_tokens=4,
        ),
        verifier=lambda execution, outcome: Verification(True, ("deterministic-offline-check",)),
        permission=lambda execution: execution.candidate.candidate_id == "offline-fixture",
        save=save,
        max_concurrency=1,
    )


def run() -> dict:
    snapshots = {}
    first = coordinator(save=lambda task_id, value: snapshots.__setitem__(task_id, value))
    try:
        complete_plan = plan("offline-complete")
        submitted = first.submit(complete_plan, QUOTE, RULE, allowed_ids={"offline-fixture"})
        approved = first.approve(complete_plan.task_id, SCOPE, complete_plan.revision)
        completed = first.wait(complete_plan.task_id, SCOPE)

        cancel_plan = plan("offline-cancel")
        first.submit(cancel_plan, QUOTE, RULE, allowed_ids={"offline-fixture"})
        cancelled = first.cancel(cancel_plan.task_id, SCOPE)

        restore_plan = plan("offline-restore")
        first.submit(restore_plan, QUOTE, RULE, allowed_ids={"offline-fixture"})
        restore_snapshot = first.snapshot(restore_plan.task_id, SCOPE)
    finally:
        first.close()

    restored = coordinator()
    try:
        restored.restore(restore_snapshot)
        recovered = restored.status(restore_plan.task_id, SCOPE)
        restored.approve(restore_plan.task_id, SCOPE, restore_plan.revision)
        resumed = restored.wait(restore_plan.task_id, SCOPE)
    finally:
        restored.close()

    return {
        "schema": "quality-routing/offline-example/v1",
        "fixture": True,
        "real_model": False,
        "complete": [submitted["status"], approved["status"], completed["status"]],
        "cancel": cancelled["status"],
        "restore": [recovered["status"], resumed["status"]],
        "verification": completed["results"]["summarize"]["evidence"],
    }


def main() -> None:
    print(json.dumps(run(), sort_keys=True))


if __name__ == "__main__":
    main()

