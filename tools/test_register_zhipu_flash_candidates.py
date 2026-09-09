import unittest
from datetime import datetime, timezone
from tools.register_zhipu_flash_candidates import candidate_rows, ALLOWED_MODELS


class RegistrationTests(unittest.TestCase):
    def reports(self):
        return [{"schema": "zhipu-candidate-sanity/v1", "model_id": model,
                 "checked_at": datetime.now(timezone.utc).isoformat(), "health": {"passed": True},
                 "checks": [{"passed": True}, {"passed": False}], "passed": False} for model in ALLOWED_MODELS]

    def test_successful_connection_does_not_claim_quality_or_price(self):
        rows = candidate_rows(self.reports())
        self.assertTrue(all(row["quality_tier"] == "unknown" and row["cost_class"] == "unknown" for row in rows))
        self.assertTrue(all(row["capabilities"] == ["chat"] for row in rows))

    def test_later_http_failure_is_not_healthy(self):
        reports = self.reports()
        reports[0]["checks"].append({"passed": False, "http_status": 429})
        self.assertEqual(candidate_rows(reports)[0]["health_state"], "unavailable")

    def test_invalid_duplicate_stale_or_unverified_evidence_rejected(self):
        for change in ({"model_id": "unrelated"}, {"checked_at": "2020-01-01T00:00:00+00:00"},
                       {"health": {"passed": False}}, {"checks": []}, {"checked_at": "2026-09-08"}):
            with self.subTest(change=change):
                reports = self.reports()
                reports[0].update(change)
                with self.assertRaises(ValueError):
                    candidate_rows(reports)
        report = self.reports()[0]
        with self.assertRaises(ValueError):
            candidate_rows([report, report])
