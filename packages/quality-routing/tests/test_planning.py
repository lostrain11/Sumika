from __future__ import annotations

import copy
import unittest
from dataclasses import replace
from unittest.mock import Mock

from quality_routing import BudgetRule, Coordinator, Outcome, Plan, RoutingError, Verification
from quality_routing.planning import digest, node_digest
from test_core import QUOTE, SCOPE, candidate, node


def planning_for(nodes, *, complete=True):
    return {"schema_version": "task-planning/v1", "mode": "rolling", "goal_contract_digest": digest("approved goal"),
            "horizon_complete": complete,
            "phases": [] if complete else [{"goal": "Deliver next stage", "prerequisites": ["first result"]}],
            "revision_reason": "initial reviewed plan",
            "handoffs": {item.node_id: {
                "node_digest": node_digest(item),
                "inputs": [{"kind": "literal", "text": "Compute exact result"}] +
                          [{"kind": "dependency", "node_id": dependency} for dependency in item.dependencies],
                "deliverables": ["plain text result"], "decisions": ["Use exact arithmetic"],
                "constraints": ["No file or network access"], "validation": ["Check exact value"],
                "failure_policy": ["Stop on missing input"], "blocking_questions": [],
                "review": {"kind": "leader", "reference": "fixture-review/1", "accepted": True}
            } for item in nodes}}


class PlanningTests(unittest.TestCase):
    def coordinator(self):
        executor = Mock(return_value=Outcome("completed", "42", cash_cny="0", input_tokens=1, output_tokens=1))
        permission = Mock(return_value=True)
        engine = Coordinator([candidate(fixed_cash="0")], executor=executor, permission=permission,
                             verifier=lambda *_: Verification(True, "checked"))
        self.addCleanup(engine.close)
        return engine, executor, permission

    def submit(self, engine, nodes, planning=None, **kwargs):
        plan = Plan("task", SCOPE, 1, tuple(nodes))
        engine.submit(plan, QUOTE, BudgetRule(), allowed_ids=["leader"],
                      planning=planning, planning_required=True, **kwargs)
        return plan

    def test_missing_handoff_blocks_before_permission_and_reservation(self):
        engine, executor, permission = self.coordinator()
        self.submit(engine, [node()])
        engine.approve("task", SCOPE, 1)
        state = engine.advance("task", SCOPE)
        self.assertEqual(state["reason"], "handoff-required")
        self.assertEqual(state["budget"]["reservations"], {})
        executor.assert_not_called()
        permission.assert_not_called()

    def test_ready_does_not_authorize_and_snapshots_are_detached(self):
        engine, executor, _ = self.coordinator()
        nodes = [node()]
        planning = planning_for(nodes)
        self.submit(engine, nodes, planning)
        planning["handoffs"].clear()
        state = engine.advance("task", SCOPE)
        self.assertEqual(state["status"], "awaiting-confirmation")
        executor.assert_not_called()
        state["planning"]["handoffs"].clear()
        engine.approve("task", SCOPE, 1)
        self.assertEqual(engine.wait("task", SCOPE)["status"], "completed")
        self.assertIsNotNone(executor.call_args.args[0].handoff)

    def test_future_phase_does_not_block_current_and_does_not_finish_goal(self):
        engine, executor, _ = self.coordinator()
        nodes = [node()]
        plan = self.submit(engine, nodes, planning_for(nodes, complete=False))
        engine.approve("task", SCOPE, 1)
        self.assertEqual(engine.wait("task", SCOPE)["status"], "needs-planning")
        nodes.append(node("next", dependencies=("first",)))
        engine.revise(replace(plan, revision=2, nodes=tuple(nodes)), planning=planning_for(nodes))
        self.assertEqual(engine.status("task", SCOPE)["states"]["first"], "completed")
        self.assertEqual(engine.wait("task", SCOPE)["status"], "completed")
        self.assertEqual(executor.call_count, 2)

    def test_stale_digest_and_template_cannot_dispatch(self):
        for field, replacement in (("node_digest", "wrong"), ("review", {"kind": "template", "reference": "bounded-text/v1", "accepted": True}),
                                   ("blocking_questions", ["Which data?"])):
            with self.subTest(field=field):
                engine, executor, _ = self.coordinator()
                nodes = [node()]
                planning = planning_for(nodes)
                planning["handoffs"]["first"][field] = replacement
                self.submit(engine, nodes, planning)
                engine.approve("task", SCOPE, 1)
                self.assertEqual(engine.advance("task", SCOPE)["reason"], "handoff-required")
                executor.assert_not_called()

    def test_restore_preserves_requirement_and_unknown(self):
        engine, _, _ = self.coordinator()
        nodes = [node()]
        self.submit(engine, nodes, planning_for(nodes))
        snapshot = engine.snapshot("task", SCOPE)
        snapshot["states"]["first"] = "running"
        restored, executor, _ = self.coordinator()
        restored.restore(snapshot)
        restored.approve("task", SCOPE, 1)
        self.assertEqual(restored.advance("task", SCOPE)["states"]["first"], "unknown")
        self.assertTrue(restored.snapshot("task", SCOPE)["planning_required"])
        executor.assert_not_called()

    def test_goal_change_and_initial_file_scope_expansion_rejected(self):
        engine, _, _ = self.coordinator()
        nodes = [node()]
        plan = self.submit(engine, nodes, planning_for(nodes), file_grant=["src/*"])
        changed = planning_for(nodes)
        changed["goal_contract_digest"] = digest("different goal")
        with self.assertRaisesRegex(RoutingError, "authorized goal"):
            engine.revise(replace(plan, revision=2), planning=changed)
        other, _, _ = self.coordinator()
        with self.assertRaisesRegex(RoutingError, "file scope"):
            self.submit(other, [node(allowed_files=("private.txt",))], file_grant=["src/*"])

    def test_invalid_future_phase_and_unknown_node_rejected(self):
        for change in ({"phases": [], "horizon_complete": False}, {"handoffs": {"other": {}}}):
            engine, _, _ = self.coordinator()
            nodes = [node()]
            planning = copy.deepcopy(planning_for(nodes))
            planning.update(change)
            with self.assertRaises(RoutingError):
                self.submit(engine, nodes, planning)

    def test_revision_cannot_disable_existing_readiness_requirement(self):
        engine, executor, _ = self.coordinator()
        nodes = [node()]
        plan = Plan("task", SCOPE, 1, tuple(nodes))
        engine.submit(plan, QUOTE, BudgetRule(), allowed_ids=["leader"], planning=planning_for(nodes))
        engine.approve("task", SCOPE, 1)
        engine.revise(replace(plan, revision=2, nodes=(replace(nodes[0], goal="Changed goal"),)))
        self.assertEqual(engine.advance("task", SCOPE)["reason"], "handoff-required")
        executor.assert_not_called()

    def test_missing_revision_metadata_cannot_erase_remaining_horizon(self):
        engine, _, _ = self.coordinator()
        nodes = [node()]
        plan = self.submit(engine, nodes, planning_for(nodes, complete=False))
        engine.approve("task", SCOPE, 1)
        self.assertEqual(engine.wait("task", SCOPE)["status"], "needs-planning")
        state = engine.revise(replace(plan, revision=2))
        self.assertEqual(state["status"], "needs-planning")

    def test_changed_handoff_invalidates_dependent_results_only(self):
        engine, executor, _ = self.coordinator()
        nodes = [node(), node("dependent", dependencies=("first",)), node("independent")]
        plan = self.submit(engine, nodes, planning_for(nodes))
        engine.approve("task", SCOPE, 1)
        self.assertEqual(engine.wait("task", SCOPE)["status"], "completed")
        changed = planning_for(nodes)
        changed["handoffs"]["first"]["deliverables"] = ["JSON result"]
        state = engine.revise(replace(plan, revision=2), planning=changed)
        self.assertEqual(state["states"], {"first": "pending", "dependent": "pending", "independent": "completed"})
        self.assertEqual(set(state["results"]), {"independent"})

    def test_future_nodes_use_task_grant_not_first_stage_files(self):
        engine, _, _ = self.coordinator()
        nodes = [node(allowed_files=("src/first.txt",))]
        plan = self.submit(engine, nodes, planning_for(nodes), file_grant=["src/*"])
        nodes.append(node("second", allowed_files=("src/next.txt",)))
        state = engine.revise(replace(plan, revision=2, nodes=tuple(nodes)), planning=planning_for(nodes))
        self.assertIn("second", state["states"])
        self.assertEqual(engine.snapshot("task", SCOPE)["file_grant"], ["src/*"])
