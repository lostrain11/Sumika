import unittest
from datetime import datetime, timezone

from tools.register_openrouter_free_candidates import free_rows, register, PROFILE_ID
from sumika_core.model_policy import ModelPolicyService
from sumika_core.storage import Storage
from sumika_core.provider_profiles import ProviderProfileManager
from sumika_core.credentials import MemoryCredentialStore


class FreeCatalogTests(unittest.TestCase):
    def model(self, **changes):
        return {"id": "vendor/model:free", "pricing": {"prompt": "0", "completion": "0"},
                "context_length": 32000, "architecture": {"input_modalities": ["text", "image"]}, **changes}

    def test_exact_free_variant_and_all_price_components_required(self):
        self.assertEqual(len(free_rows({"data": [self.model()]})), 1)
        for changes in ({"id": "vendor/model"}, {"pricing": {"prompt": "0"}},
                        {"pricing": {"prompt": "0", "completion": "0", "request": "0.01"}},
                        {"pricing": {"prompt": False, "completion": "0"}},
                        {"pricing": {"prompt": "NaN", "completion": "0"}},
                        {"pricing": {"prompt": "0", "completion": "unknown"}},
                        {"architecture": {"input_modalities": ["image"]}}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                free_rows({"data": [self.model(**changes)]})

    def test_duplicate_free_identity_is_not_silently_accepted(self):
        with self.assertRaises(ValueError):
            free_rows({"data": [self.model(), self.model()]})

    def test_registration_creates_only_unauthorized_untested_candidates(self):
        storage = Storage(":memory:")
        self.addCleanup(storage.close)
        report = {"observed_at": datetime.now(timezone.utc).isoformat(), "models": free_rows({"data": [self.model()]})}
        profile = register(storage, report)
        self.assertFalse(profile["has_secrets"])
        self.assertNotEqual(profile["status"], "available")
        policy = ModelPolicyService(ProviderProfileManager(storage, MemoryCredentialStore()))
        self.addCleanup(policy.close)
        entry = next(entry for entry in policy.catalog()["entries"] if entry["provider_profile_id"] == PROFILE_ID)
        self.assertFalse(entry["metadata"]["routable"])
        self.assertEqual(entry["cost_class"], "unknown")
        self.assertEqual(entry["capabilities"], ["chat"])
        with self.assertRaises(ValueError):
            register(storage, report)
