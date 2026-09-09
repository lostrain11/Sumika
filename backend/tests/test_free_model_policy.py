import copy
from datetime import datetime, timezone
import tempfile
import unittest

from sumika_core.model_policy import ModelPolicyService
from sumika_core.provider_profiles import provider_account_revision


class Profiles:
    def __init__(self):
        self.profile = {"id": "xfyun", "name": "MaaS", "adapter_id": "openai-compatible", "template_id": "openai-compatible",
            "status": "available", "has_secrets": True, "processing_location": "cloud", "config": {
                "active_base_url": "https://maas-api.cn-huabei-1.xf-yun.com/v2", "model": "spark-x2.5-4b",
                "models": [{"id": "spark-x2.5-4b", "enabled": True, "quality_tier": "premium", "capabilities": ["chat", "code"]}]}}

    def get(self, profile_id):
        return copy.deepcopy(self.profile)

    def list(self, **kwargs):
        return [self.get("xfyun")]


class FreePolicyTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.profiles = Profiles()
        self.policy = ModelPolicyService(self.profiles, data_dir=self.directory.name)
        self.addCleanup(self.policy.free_models.close)
        self.snapshot = {"provider_id": "xfyun", "source_url": "https://maas.xfyun.cn/catalog", "models": ["spark-x2.5-4b"],
            "complete": True, "mode": "zero-price", "ttl_seconds": 43200, "observed_at": datetime.now(timezone.utc).isoformat()}
        self.policy.free_models.collector = lambda provider_id: self.snapshot
        self.policy.free_models.enroll("xfyun", "xfyun")
        self.policy.free_models.refresh()

    def qualify(self):
        self.policy.free_models.record_evaluation("xfyun", "spark-x2.5-4b", passed=True,
            revision=provider_account_revision(self.profiles.profile))

    def test_healthy_model_name_does_not_skip_evaluation(self):
        entry = self.policy.catalog()["entries"][0]
        self.assertFalse(entry["routable"])
        self.assertEqual(entry["quality_tier"], "unknown")

    def test_qualified_model_routes_basic_task_at_zero_estimate(self):
        self.qualify()
        result = self.policy.decide({"task_kind": "extraction", "difficulty": "basic", "task_text": "提取日期", "budget_policy": "free-only", "confirmation_mode": "automatic"})
        decision = result["decision"]
        self.assertEqual(decision["status"], "selected")
        self.assertEqual(decision["cost_estimate"]["cash_max"], 0)
        self.assertEqual(decision["quality_gate"]["selected"], "basic")
        self.assertNotIn("code", decision["selected_entry"]["capabilities"])
        self.assertIsNone(decision["selected_entry"]["metadata"]["free_model_remaining"])

    def test_complex_or_code_task_cannot_use_basic_free_evidence(self):
        self.qualify()
        for task in ({"task_kind": "chat", "difficulty": "complex"}, {"task_kind": "code", "difficulty": "basic"}):
            result = self.policy.decide({**task, "budget_policy": "free-only"})
            self.assertEqual(result["decision"]["status"], "no-compatible-route")

    def test_withdrawn_price_blocks_both_policies(self):
        self.qualify()
        self.snapshot["models"] = []
        self.policy.free_models.refresh(force=True)
        self.assertFalse(self.policy.official_free_projection("xfyun", "spark-x2.5-4b"))
        self.assertFalse(self.policy.catalog()["entries"][0]["routable"])

    def test_supervisor_projection_has_same_free_gate(self):
        self.assertFalse(self.policy._profile_entries()[0].routable)
        self.qualify()
        entry = self.policy._profile_entries()[0]
        self.assertTrue(entry.routable)
        self.assertTrue(entry.metadata["free_model_policy"])
        self.assertEqual(entry.quality_tier, "basic")

    def test_bounded_node_has_specific_baseline_without_general_equivalence(self):
        from sumika_core.quality.service import QualityRoutingService
        from quality_routing import RoutingError
        data = {"node_id": "extract", "goal": "Extract a date", "task_type": "bounded-text", "acceptance": ["Exact date"]}
        node = QualityRoutingService._nodes({"nodes": [data]}, "leader")[0]
        self.assertEqual(node.baseline_id, "bounded-text-v1")
        self.assertLessEqual(node.output_tokens, 2048)
        with self.assertRaises(RoutingError):
            QualityRoutingService._nodes({"nodes": [{**data, "risk": "critical"}]}, "leader")


if __name__ == "__main__":
    unittest.main()
