import unittest
import copy
import json
from dataclasses import replace
from unittest.mock import patch

from quality_routing import Outcome, Plan, RoutingError, Scope
from quality_routing.planning import digest, handoff_errors
from sumika_core.quality.service import QualityRoutingService
import test_quality_routing as fixtures


class QualityPlanningTests(unittest.TestCase):
    setUp = fixtures.QualityHostTests.setUp
    tearDown = fixtures.QualityHostTests.tearDown

    def raw_plan(self):
        return {"nodes": [{"node_id": "answer", "goal": "Calculate six times seven", "task_type": "arithmetic", "acceptance": ["42"]}],
                "planning": {"mode": "batch", "horizon_complete": True, "phases": [], "revision_reason": "fixture review",
                    "handoffs": {"answer": {"inputs": [{"kind": "literal", "text": "6 * 7"}],
                        "deliverables": ["plain text 42"], "decisions": ["Exact multiplication"],
                        "constraints": ["No files"], "validation": ["Verify 42"],
                        "failure_policy": ["Stop if unavailable"], "blocking_questions": [], "reviewed": True}}}}

    def test_host_binds_normalized_node_and_actual_response(self):
        from quality_routing import Scope
        raw = self.raw_plan()
        plan = Plan("task", Scope("one", "session-one"), 1, self.service._nodes(raw, "local-model"))
        metadata = QualityRoutingService._planning(raw, plan, digest("contract"), "actual response")
        self.assertEqual(handoff_errors(plan.nodes[0], metadata, {}, required=True), ())
        self.assertEqual(metadata["handoffs"]["answer"]["review"]["reference"], "response-sha256:" + digest("actual response"))
        changed = replace(plan.nodes[0], goal="A different task")
        self.assertIn("stale-node-digest", handoff_errors(changed, metadata, {}))

    def test_leader_cannot_supply_host_digest_or_review_receipt(self):
        from quality_routing import Scope
        raw = self.raw_plan()
        plan = Plan("task", Scope("one", "session-one"), 1, self.service._nodes(raw, "local-model"))
        raw["planning"]["handoffs"]["answer"]["review"] = {"accepted": True}
        with self.assertRaisesRegex(RoutingError, "leader handoff"):
            QualityRoutingService._planning(raw, plan, digest("contract"), "response")

    def test_missing_review_does_not_become_ready(self):
        from quality_routing import Scope
        raw = self.raw_plan()
        raw["planning"]["handoffs"]["answer"]["reviewed"] = False
        plan = Plan("task", Scope("one", "session-one"), 1, self.service._nodes(raw, "local-model"))
        metadata = QualityRoutingService._planning(raw, plan, digest("contract"), "response")
        self.assertIn("missing-design-review", handoff_errors(plan.nodes[0], metadata, {}))

    def test_absent_metadata_is_not_fabricated(self):
        from quality_routing import Scope
        raw = self.raw_plan()
        plan = Plan("task", Scope("one", "session-one"), 1, self.service._nodes(raw, "local-model"))
        self.assertIsNone(QualityRoutingService._planning({}, plan, digest("contract"), "response"))
        self.assertEqual(handoff_errors(plan.nodes[0], None, {}, required=True), ("missing-planning",))

    def test_actual_quality_loop_prepares_next_stage_without_reexecuting_first(self):
        plans = []
        executions = []
        def invoke(candidate, scope, prompt, cancelled, max_tokens):
            if "Return only a JSON object with nodes" in prompt:
                raw = self.raw_plan()
                raw["planning"]["mode"] = "rolling"
                if not plans:
                    raw["planning"]["horizon_complete"] = False
                    raw["planning"]["phases"] = [{"goal": "Report verified answer", "prerequisites": ["answer"]}]
                else:
                    raw["nodes"].append({"node_id": "report", "goal": "Report verified answer", "task_type": "arithmetic",
                                         "dependencies": ["answer"], "acceptance": ["42"]})
                    handoff = copy.deepcopy(raw["planning"]["handoffs"]["answer"])
                    handoff["inputs"] = [{"kind": "dependency", "node_id": "answer"}]
                    raw["planning"]["handoffs"]["report"] = handoff
                plans.append(raw)
                text = json.dumps(raw)
            elif "Verify the task result" in prompt:
                text = '{"passed":true,"reason":"exact result"}'
            else:
                executions.append(prompt)
                text = "42"
            return Outcome("completed", text, cash_cny="0", input_tokens=100, output_tokens=100)
        with patch.object(self.service, "_invoke", side_effect=invoke):
            task = self.service.plan({**self.params, "goal": "Calculate and report six times seven"})
            scope = Scope("one", "session-one")
            self.service.engine.approve(task["task_id"], scope, 1)
            self.service._run(task["task_id"], scope)
            result = self.service.status(task["task_id"], scope)
            self.assertEqual(result["status"], "completed", result)
            self.assertEqual(len(plans), 2)
            self.assertEqual(sum(prompt.startswith("Complete only this task") for prompt in executions), 2)
            self.assertEqual(result["revision"], 2)
            before = len(plans)
            self.service.status(task["task_id"], scope)
            self.assertEqual(len(plans), before)
