"""Offline, host-neutral quality-routing SDK example."""

from quality_routing import BudgetRule, Candidate, Coordinator, Node, Outcome, Plan, Quote, Scope, Verification


def main() -> None:
    scope = Scope("demo-owner", "demo-session")
    candidate = Candidate(
        "demo",
        "demo-account",
        "demo-model",
        "api",
        authorized=True,
        available=True,
        external=False,
        fixed_cash="0",
    )
    coordinator = Coordinator(
        [candidate],
        executor=lambda execution: Outcome("completed", "offline-result", cash_cny="0"),
        verifier=lambda execution, outcome: Verification(True, ("offline-check",)),
        permission=lambda execution: True,
    )
    try:
        plan = Plan(
            "demo-task",
            scope,
            1,
            (Node("summarize", "Create a short offline summary", "summary", "demo", acceptance=("summary exists",)),),
        )
        coordinator.submit(plan, Quote("0", "0", "1", 2, 10000), BudgetRule(), allowed_ids={"demo"})
        coordinator.approve("demo-task", scope, 1)
        print(coordinator.wait("demo-task", scope)["status"])
    finally:
        coordinator.close()


if __name__ == "__main__":
    main()
