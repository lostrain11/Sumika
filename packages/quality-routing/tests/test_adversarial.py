from __future__ import annotations

import threading
import time
import unittest
from decimal import Decimal

from quality_routing import Budget, BudgetRule, Candidate, Coordinator, Node, Outcome, Plan, Quote, RoutingError, Scope, Verification


SCOPE = Scope("adversary", "session")
QUOTE = Quote("0", "0", "100", 3, 30)


def node(name: str = "first", **values):
    defaults = {
        "node_id": name,
        "goal": "Produce a bounded result",
        "task_type": "arithmetic",
        "baseline_id": "leader",
        "acceptance": ("result",),
    }
    defaults.update(values)
    return Node(**defaults)


def candidate(**values):
    defaults = {
        "candidate_id": "leader",
        "account_id": "shared-account",
        "model_id": "leader",
        "channel": "api",
        "authorized": True,
        "available": True,
        "external": False,
        "fixed_cash": "0",
    }
    defaults.update(values)
    return Candidate(**defaults)


class BudgetAdversarialTests(unittest.TestCase):
    def test_parallel_reservations_cannot_overrun_call_or_token_caps(self):
        budget = Budget(QUOTE, BudgetRule())
        barrier = threading.Barrier(8)
        accepted = []
        rejected = []

        def reserve(index):
            barrier.wait()
            try:
                budget.reserve(f"attempt-{index}", Decimal("0"), 10)
                accepted.append(index)
            except RoutingError:
                rejected.append(index)

        workers = [threading.Thread(target=reserve, args=(index,)) for index in range(8)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join()

        self.assertEqual(len(accepted), 3)
        self.assertEqual(len(rejected), 5)
        self.assertEqual(sum(item.tokens for item in budget.reservations.values()), 30)


class PlanAdversarialTests(unittest.TestCase):
    def test_duplicate_and_missing_dependencies_are_rejected_before_submission(self):
        with self.assertRaisesRegex(RoutingError, "duplicate"):
            Plan("duplicate", SCOPE, 1, (node("same"), node("same")))
        with self.assertRaisesRegex(RoutingError, "cyclic or missing"):
            Plan("missing", SCOPE, 1, (node("first", dependencies=("unknown",)),))


class AccountConcurrencyAdversarialTests(unittest.TestCase):
    def test_shared_account_cannot_run_more_than_its_single_slot(self):
        started = threading.Event()
        release = threading.Event()
        running = 0
        maximum = 0
        lock = threading.Lock()

        def execute(execution):
            nonlocal running, maximum
            with lock:
                running += 1
                maximum = max(maximum, running)
                started.set()
            release.wait(2)
            with lock:
                running -= 1
            return Outcome("completed", "done", cash_cny="0")

        engine = Coordinator(
            [candidate(account_concurrency=1)],
            executor=execute,
            verifier=lambda execution, outcome: Verification(True, ("checked",)),
            permission=lambda execution: True,
            max_concurrency=3,
        )
        try:
            for task_id in ("one", "two"):
                engine.submit(
                    Plan(task_id, SCOPE, 1, (node(task_id, input_tokens=1, output_tokens=1),)),
                    QUOTE,
                    BudgetRule(),
                    allowed_ids={"leader"},
                )
                engine.approve(task_id, SCOPE, 1)
            engine.advance("one", SCOPE)
            self.assertTrue(started.wait(2))
            engine.advance("two", SCOPE)
            time.sleep(0.05)
            self.assertEqual(maximum, 1)
            self.assertEqual(engine.status("two", SCOPE)["states"]["two"], "pending")
            release.set()
            engine.wait("one", SCOPE)
            engine.advance("two", SCOPE)
            engine.wait("two", SCOPE)
            self.assertEqual(maximum, 1)
        finally:
            release.set()
            engine.close()

    def test_unknown_outcome_reserves_shared_account_for_other_tasks(self):
        engine = Coordinator(
            [candidate(fixed_cash="3")],
            executor=lambda execution: Outcome("unknown", possibly_sent=True),
            verifier=lambda execution, outcome: Verification(True, ("checked",)),
            permission=lambda execution: True,
        )
        quote = Quote("0", "3", "10", 4, 100)
        try:
            engine.set_account_balance("shared-account", Decimal("5"))
            for task_id in ("one", "two"):
                engine.submit(
                    Plan(task_id, SCOPE, 1, (node(task_id, input_tokens=1, output_tokens=1),)),
                    quote,
                    BudgetRule(),
                    allowed_ids={"leader"},
                )
                engine.approve(task_id, SCOPE, 1)
            self.assertEqual(engine.wait("one", SCOPE)["states"]["one"], "unknown")
            blocked = engine.advance("two", SCOPE)
            self.assertEqual(blocked["states"]["two"], "pending")
            self.assertEqual(blocked["reason"], "account-balance-exhausted-or-unpriced")
        finally:
            engine.close()


class RevisionAdversarialTests(unittest.TestCase):
    def test_host_execution_revision_is_preserved_and_reconfirmation_is_required(self):
        calls = []
        engine = Coordinator([candidate(execution_revision="binding-v1")],
            executor=lambda execution: calls.append(execution),
            verifier=lambda execution, outcome: Verification(True, ("checked",)), permission=lambda execution: True)
        self.addCleanup(engine.close)
        engine.submit(Plan("binding", SCOPE, 1, (node(input_tokens=1, output_tokens=1),)),
                      Quote("0", "1", "3", 2, 100), BudgetRule(), allowed_ids={"leader"})
        engine.approve("binding", SCOPE, 1)
        snapshot = engine.snapshot("binding", SCOPE)
        self.assertEqual(snapshot["candidate_identities"]["leader"][-1], "binding-v1")
        engine.set_candidates([candidate(execution_revision="binding-v2")])
        self.assertEqual(engine.advance("binding", SCOPE)["states"]["first"], "pending")
        with self.assertRaisesRegex(RoutingError, "auxiliary candidate"):
            engine.reserve_auxiliary("binding", SCOPE, "auxiliary", Decimal(0), 1, "leader")
        self.assertEqual(calls, [])

    def test_unversioned_identity_remains_compatible_but_cannot_match_versioned(self):
        old = candidate()
        versioned = candidate(execution_revision="binding-v1")
        self.assertEqual(len(old.identity()), 6)
        self.assertNotEqual(old.identity(), versioned.identity())

    def test_valid_revision_reuses_existing_grant_without_expanding_boundaries(self):
        paid = candidate(candidate_id="paid", account_id="paid-account", model_id="paid", fixed_cash="9")
        engine = Coordinator(
            [candidate(fixed_cash="1"), paid],
            executor=lambda execution: Outcome("completed", "done", cash_cny="0"),
            verifier=lambda execution, outcome: Verification(True, ("checked",)),
            permission=lambda execution: True,
        )
        quote = Quote("0", "1", "3", 4, 100)
        try:
            engine.submit(
                Plan("task", SCOPE, 1, (node(input_tokens=1, output_tokens=1),)),
                quote,
                BudgetRule(),
                allowed_ids={"leader"},
            )
            engine.approve("task", SCOPE, 1)
            engine.wait("task", SCOPE)
            revised = Plan("task", SCOPE, 2, (node(goal="Changed bounded result", input_tokens=1, output_tokens=1),))
            self.assertEqual(engine.revise(revised)["status"], "ready")
            self.assertEqual(engine.wait("task", SCOPE)["status"], "completed")
            snapshot = engine.snapshot("task", SCOPE)
            self.assertEqual(snapshot["allowed_ids"], ["leader"])
            self.assertFalse(snapshot["external_allowed"])
            self.assertEqual(snapshot["budget"]["quote"], quote.to_dict())

            before = engine.snapshot("task", SCOPE)
            unauthorized_substitution = Plan("task", SCOPE, 3, (node(baseline_id="paid", input_tokens=1, output_tokens=1),))
            with self.assertRaisesRegex(RoutingError, "approved quality baseline"):
                engine.revise(unauthorized_substitution)
            with self.assertRaisesRegex(RoutingError, "approved file scope"):
                engine.revise(Plan("task", SCOPE, 3, (node(allowed_files=("outside.txt",), input_tokens=1, output_tokens=1),)))

            after = engine.snapshot("task", SCOPE)
            self.assertEqual(after["plan"], before["plan"])
            self.assertEqual(after["plan"]["revision"], 2)
            self.assertEqual(after["allowed_ids"], ["leader"])
            self.assertEqual(after["budget"]["quote"], quote.to_dict())
            self.assertEqual(after["quality_baselines"], ["leader"])
            self.assertEqual(after["file_grant"], [])

            with self.assertRaises(RoutingError):
                engine.revise(Plan("task", Scope("other", "session"), 4, (node(input_tokens=1, output_tokens=1),)))
        finally:
            engine.close()

    def test_candidate_identity_snapshot_blocks_replaced_allowed_id(self):
        engine = Coordinator(
            [candidate(model_id="original")],
            executor=lambda execution: Outcome("completed", "done", cash_cny="0"),
            verifier=lambda execution, outcome: Verification(True, ("checked",)),
            permission=lambda execution: True,
        )
        try:
            engine.submit(
                Plan("identity", SCOPE, 1, (node(input_tokens=1, output_tokens=1),)),
                Quote("0", "1", "3", 2, 100),
                BudgetRule(),
                allowed_ids={"leader"},
            )
            engine.approve("identity", SCOPE, 1)
            engine.set_candidates([candidate(model_id="replacement")])
            blocked = engine.advance("identity", SCOPE)
            self.assertEqual(blocked["states"]["first"], "pending")
            self.assertEqual(blocked["reason"], "no authorized quality-equivalent candidate")
        finally:
            engine.close()


if __name__ == "__main__":
    unittest.main()
