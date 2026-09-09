import copy
import json
import time
import unittest

from sumika_core.credentials import MemoryCredentialStore
from sumika_core.provider_profiles import ProviderProfileManager, provider_execution_revision
from sumika_core.quality.selection import SelectionEvidenceStore
from sumika_core.storage import Storage
from tools.activate_model_roles import CASES, SETTINGS_KEY, activate, validate_report


class RoleImportTests(unittest.TestCase):
    def setUp(self):
        self.storage = Storage()
        self.addCleanup(self.storage.close)
        self.storage.create_character("sumika", "Sumika")
        self.storage.create_character("other", "Other")
        profiles = ProviderProfileManager(self.storage, MemoryCredentialStore())
        self.profile = profiles.save({"name": "test", "base_url": "https://example.test/v1", "model": "model"})
        self.report = {"schema": "sumika-role-evaluation/v1", "profile_id": self.profile["id"], "model_id": "model",
            "model_version": "model-v1", "purpose": "role", "qualified": True, "model_calls": 3,
            "checked_at": time.time() - 5,
            "execution_revision": provider_execution_revision(self.profile, "model"),
            "samples": [{"id": case, "passed": True, "observed_at": time.time() - 10, "finish_reason": "stop",
                         "response_digest": "a" * 64, "usage": {"input_tokens": 10, "output_tokens": 10}} for case in CASES["role"]]}

    def report_for(self, purpose):
        report = copy.deepcopy(self.report)
        report["purpose"] = purpose
        report["samples"] = [{**sample, "id": case} for sample, case in zip(report["samples"], sorted(CASES[purpose]))]
        return report

    def test_current_complete_reviewed_reports_only(self):
        self.assertEqual(validate_report(self.report, self.profile, reviewed=True), "profile:" + self.profile["id"] + ":model")
        for updates in ({"execution_revision": "old"}, {"qualified": False}, {"model_calls": 2}, {"model_version": "unknown model"}):
            with self.subTest(updates=updates), self.assertRaises(ValueError):
                validate_report({**self.report, **updates}, self.profile, reviewed=True)
        with self.assertRaises(ValueError):
            validate_report(self.report, self.profile)

    def test_reject_stale_duplicate_or_truncated_cases(self):
        for key, value in (("observed_at", time.time() - 86401), ("id", "duplicate"), ("finish_reason", "length")):
            report = copy.deepcopy(self.report)
            report["samples"][0][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_report(report, self.profile, reviewed=True)

    def test_activate_is_idempotent_and_preserves_unrelated_settings(self):
        original = {
            "assistants": {
                "sumika": {"budget": {"limit_cny": "9"}, "candidate_pool": ["existing-candidate"], "custom": "keep"},
                "other": {"budget": {"limit_cny": "3"}, "candidate_pool": ["other-candidate"], "custom": "other-keep"},
            }
        }
        self.storage.set_meta(SETTINGS_KEY, json.dumps(original, sort_keys=True))
        reports = [self.report_for("leader"), self.report_for("role")]
        candidate_id = "profile:" + self.profile["id"] + ":model"
        first = activate(self.storage, reports, leader_id=candidate_id, reviewed=True)
        evidence = SelectionEvidenceStore(self.storage)
        cohorts, _, samples = evidence.read("sumika")
        self.assertEqual(set(cohorts), {"leader", "role"})
        self.assertEqual(len(samples), 6)
        second = activate(self.storage, reports, leader_id=candidate_id, reviewed=True)
        self.assertEqual(first, second)
        self.assertEqual(len(evidence.read("sumika")[2]), 6)
        settings = json.loads(self.storage.get_meta(SETTINGS_KEY))
        self.assertEqual(settings["assistants"]["sumika"]["budget"], original["assistants"]["sumika"]["budget"])
        self.assertEqual(settings["assistants"]["sumika"]["custom"], "keep")
        self.assertEqual(settings["assistants"]["sumika"]["candidate_pool"], sorted([candidate_id, "existing-candidate"]))
        self.assertEqual(settings["assistants"]["other"], original["assistants"]["other"])

    def test_activate_rejects_report_after_execution_revision_changes(self):
        reports = [self.report_for("leader"), self.report_for("role")]
        profile = self.storage.get_provider_profile(self.profile["id"])
        updated_config = copy.deepcopy(profile["config"])
        updated_config["active_base_url"] = "https://changed.example.test/v1"
        self.storage.update_provider_profile_config(self.profile["id"], updated_config)
        candidate_id = "profile:" + self.profile["id"] + ":model"
        with self.assertRaisesRegex(ValueError, "binding changed"):
            activate(self.storage, reports, leader_id=candidate_id, reviewed=True)
        self.assertEqual(SelectionEvidenceStore(self.storage).read("sumika")[2], ())


if __name__ == "__main__":
    unittest.main()
