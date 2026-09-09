import copy
import json
import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock

from sumika_core.benefits import BenefitsBusy, BenefitsError, BenefitsService, MODELSCOPE_PROFILE, _file_lock


SOURCES = [{"id": "fixture-rss", "title": "Public offers", "url": "https://news.example.org/feed.xml",
            "kind": "rss", "interval_seconds": 43200},
           {"id": "fixture-official", "title": "Official pricing", "url": "https://official.example.org/pricing",
            "kind": "official", "interval_seconds": 43200}]
ROW = {"title": "Free API trial", "url": "https://official.example.org/free", "provider_id": None,
       "model_id": None, "kind": "lead", "evidence": "Public announcement; eligibility unverified", "expires_at": None}
PROFILE = {"id": MODELSCOPE_PROFILE, "credential_ref": "vault-reference", "config": {}, "created_at": "2026-09-01"}


class BenefitsTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 9, 8, 7, tzinfo=timezone.utc)
        self.profile = copy.deepcopy(PROFILE)
        self.collector = Mock(return_value=[ROW])
        self.browser = Mock()
        self.browser.browsers.return_value = [{"instance_id": "browser-fixture", "browser_name": "edge"}]
        self.browser.read.side_effect = lambda *args: {
            "state": "verified", "checked_at": self.now.isoformat(), "available_balance": 242,
            "unit": "magicube", "grants": [{"kind": "daily-login", "amount": 200,
                "granted_date_display": "2026-09-08", "validity_days_display": 1, "expires_at": None}], "error": None}
        self.services = []
        self.service = self.make_service()

    def tearDown(self):
        for service in self.services:
            service.close()

    def make_service(self, path=None):
        service = BenefitsService(path, profile_reader=lambda profile_id: self.profile if profile_id == MODELSCOPE_PROFILE else None,
            browser_reader=self.browser, collector=self.collector, sources=SOURCES, now=lambda: self.now)
        self.services.append(service)
        return service

    def enable(self, service=None):
        return (service or self.service).configure({"enabled": True, "checkin_enabled": True,
                                                   "browser_instance_id": "browser-fixture"})

    def test_default_status_and_background_do_not_contact_any_source(self):
        self.service.run_once()
        self.assertFalse(self.service.status()["enabled"])
        self.collector.assert_not_called()
        self.browser.read.assert_not_called()
        self.browser.browsers.assert_not_called()

    def test_manual_discovery_does_not_enable_background_or_account_actions(self):
        self.service.run_once(kind="refresh", manual=True)
        result = self.service.status()
        self.assertEqual(len(result["offers"]), 2)
        self.assertFalse(result["enabled"])
        self.assertTrue(all(not item["automatic_routing_authorized"] for item in result["offers"]))
        self.browser.read.assert_not_called()

    def test_independent_source_failure_retains_old_evidence_as_stale(self):
        self.service.run_once(kind="refresh", manual=True)
        self.now += timedelta(minutes=2)
        self.collector.side_effect = lambda source_id: (_ for _ in ()).throw(RuntimeError("private response")) if source_id == SOURCES[0]["id"] else []
        self.service.run_once(kind="refresh", manual=True)
        result = self.service.status()
        failed, ready = result["sources"]
        self.assertEqual(failed["status"], "unavailable")
        self.assertEqual(ready["status"], "ready")
        offers = {item["source_id"]: item for item in result["offers"]}
        self.assertTrue(offers[failed["id"]]["stale"])
        self.assertEqual(offers[failed["id"]]["state"], "active")
        self.assertEqual(offers[ready["id"]]["state"], "withdrawn")
        self.assertNotIn("private response", json.dumps(result))

    def test_source_ttl_and_manual_cooldown(self):
        self.service.configure({"enabled": True})
        self.service.run_once()
        self.service.run_once(kind="refresh", manual=True)
        self.assertEqual(self.collector.call_count, 2)
        self.now += timedelta(hours=13)
        self.assertTrue(all(item["stale"] for item in self.service.status()["offers"]))
        self.service.run_once()
        self.assertEqual(self.collector.call_count, 4)

    def test_feed_rolloff_is_not_an_official_benefit_withdrawal(self):
        self.service.run_once(kind="refresh", manual=True)
        self.now += timedelta(minutes=2)
        self.collector.return_value = []
        self.service.run_once(kind="refresh", manual=True)
        offers = {item["source_id"]: item for item in self.service.status()["offers"]}
        self.assertEqual(offers["fixture-rss"]["state"], "active")
        self.assertTrue(offers["fixture-rss"]["stale"])
        self.assertEqual(offers["fixture-official"]["state"], "withdrawn")

    def test_background_failure_backoff(self):
        self.collector.side_effect = RuntimeError("unavailable")
        self.service.configure({"enabled": True})
        self.service.run_once()
        self.now += timedelta(minutes=5)
        self.service.run_once()
        self.assertEqual(self.collector.call_count, 2)
        self.now += timedelta(minutes=6)
        self.service.run_once()
        self.assertEqual(self.collector.call_count, 4)

    def test_discovery_is_deduplicated_and_expiry_is_not_invented(self):
        self.collector.return_value = [ROW, ROW]
        self.service.run_once(kind="refresh", manual=True)
        result = self.service.status()["offers"]
        self.assertEqual(len(result), 2)
        self.assertIsNone(result[0]["expires_at"])
        self.assertFalse(result[0]["expired"])

    def test_reject_secret_or_private_links_without_persisting_response(self):
        for value in ("http://official.example.org", "https://localhost/private", "https://127.0.0.1/x", "https://user:pass@example.org", "https://10.0.0.1/x"):
            with self.subTest(value=value):
                self.collector.return_value = [{**ROW, "url": value}]
                self.service.run_once(kind="refresh", manual=True)
                self.assertEqual(self.service.status()["offers"], [])
                self.now += timedelta(minutes=2)

    def test_unknown_settings_cannot_inject_url_cookie_or_grants(self):
        for key in ("url", "cookie", "grants", "account_revision", "sources"):
            with self.assertRaises(BenefitsError):
                self.service.configure({key: "forbidden"})
        for value in (1, "true", None):
            with self.assertRaises(BenefitsError):
                self.service.configure({"enabled": value})

    def test_checkin_requires_explicit_current_browser_and_profile(self):
        with self.assertRaises(BenefitsError):
            self.service.request("checkin")
        with self.assertRaises(BenefitsError):
            self.service.configure({"enabled": True, "checkin_enabled": True})
        with self.assertRaises(BenefitsError):
            self.service.configure({"browser_instance_id": "another-browser"})
        self.profile = None
        with self.assertRaises(BenefitsError):
            self.enable()
        self.browser.read.assert_not_called()

    def test_confirmed_profile_change_blocks_old_binding(self):
        self.enable()
        self.profile["config"]["active_base_url"] = "https://different.example.org"
        self.service.run_once(kind="checkin")
        self.assertEqual(self.service.status()["checkin"]["error"], "provider-binding-changed")
        self.browser.read.assert_not_called()

    def test_verified_grant_only_once_per_china_day(self):
        self.enable()
        self.service.run_once(kind="checkin")
        self.service.run_once(kind="checkin", manual=True)
        self.browser.read.assert_called_once()
        result = self.service.status()["checkin"]
        self.assertEqual(result["state"], "verified")
        self.assertEqual(result["available_balance"], 242)
        self.assertFalse(result["account_binding_verified"])
        self.assertFalse(result["automatic_routing_authorized"])
        self.assertIsNone(result["grants"][0]["expires_at"])
        self.now += timedelta(hours=10)
        self.assertTrue(self.service.status()["checkin"]["stale"])

    def test_yesterday_grants_cannot_verify_today(self):
        self.enable()
        self.now += timedelta(days=1)
        self.service.run_once(kind="checkin")
        result = self.service.status()["checkin"]
        self.assertEqual(result["state"], "needs-review")
        self.assertIsNone(result["available_balance"])

    def test_challenge_or_uncertainty_is_not_automatically_retried(self):
        for state in ("challenge", "interrupted", "needs-review", "login-required"):
            with self.subTest(state=state):
                service = self.make_service()
                self.enable(service)
                self.browser.read.side_effect = lambda *args: {"state": state, "error": "needs-user"}
                self.browser.read.reset_mock()
                service.run_once(kind="checkin")
                self.now += timedelta(days=1)
                service.run_once(kind="checkin")
                self.browser.read.assert_called_once()

    def test_configuring_another_browser_does_not_publish_previous_result(self):
        self.enable()
        def read(*args):
            self.browser.browsers.return_value = [{"instance_id": "browser-other", "browser_name": "edge"}]
            self.service.configure({"browser_instance_id": "browser-other"})
            return {"state": "verified", "checked_at": self.now.isoformat(), "available_balance": 5, "grants": []}
        self.browser.read.side_effect = read
        self.service.run_once(kind="checkin")
        self.assertEqual(self.service.status()["checkin"]["state"], "never")

    def test_two_services_share_state_and_single_flight(self):
        with tempfile.TemporaryDirectory() as directory:
            first, second = self.make_service(Path(directory)), self.make_service(Path(directory))
            entered, release = threading.Event(), threading.Event()
            def collect(source):
                entered.set()
                release.wait(5)
                return [ROW]
            self.collector.side_effect = collect
            thread = threading.Thread(target=first.run_once, kwargs={"kind": "refresh", "manual": True})
            thread.start()
            try:
                self.assertTrue(entered.wait(2))
                self.assertTrue(second.status()["running"])
                second.run_once(kind="refresh", manual=True)
                self.assertEqual(self.collector.call_count, 1)
            finally:
                release.set()
                thread.join(5)
            self.assertEqual(len(second.status()["offers"]), 2)
            self.assertFalse(second.status()["running"])
            first.close()
            second.close()

    def test_corrupt_store_is_preserved_without_network(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "benefits"
            root.mkdir()
            path = root / "state.json"
            path.write_text("broken", encoding="utf-8")
            service = self.make_service(Path(directory))
            service.run_once(kind="refresh", manual=True)
            self.assertEqual(service.status()["error"], "store-needs-review")
            self.assertEqual(path.read_text(), "broken")
            self.collector.assert_not_called()

    def test_close_prevents_new_network_and_requests(self):
        self.enable()
        self.service.close()
        self.service.run_once()
        self.collector.assert_not_called()
        self.browser.read.assert_not_called()
        with self.assertRaises(BenefitsError):
            self.service.request("refresh")

    def test_busy_manual_request_is_explicitly_rejected(self):
        self.enable()
        with self.service._operation:
            with self.assertRaises(BenefitsBusy):
                self.service.request("checkin")
        with tempfile.TemporaryDirectory() as directory:
            service = self.make_service(Path(directory))
            self.enable(service)
            with _file_lock(Path(directory) / "benefits" / "run.lock"):
                with self.assertRaises(BenefitsBusy):
                    service.request("checkin")
            service.close()

    def test_binding_change_before_running_does_not_visit_previous_browser(self):
        self.enable()
        original = self.service._check_binding
        def check():
            result = original()
            self.browser.browsers.return_value = [{"instance_id": "new-browser", "browser_name": "edge"}]
            self.service.configure({"browser_instance_id": "new-browser"})
            return result
        self.service._check_binding = check
        self.service.run_once(kind="checkin")
        self.browser.read.assert_not_called()
        self.assertEqual(self.service.status()["checkin"]["state"], "never")

    def test_disabling_master_switch_cancels_inflight_reader(self):
        self.enable()
        entered, release = threading.Event(), threading.Event()
        cancellations = []
        def read(browser, cancellation):
            entered.set()
            release.wait(3)
            cancellations.append(cancellation.is_set())
            return {"state": "interrupted", "error": "cancelled"}
        self.browser.read.side_effect = read
        self.service.request("checkin")
        try:
            self.assertTrue(entered.wait(2))
            self.service.configure({"enabled": False})
            self.assertFalse(self.service.status()["checkin_enabled"])
        finally:
            release.set()
            self.service.close()
        self.assertEqual(cancellations, [True])

    def test_other_instance_can_revoke_inflight_checkin(self):
        with tempfile.TemporaryDirectory() as directory:
            first, second = self.make_service(Path(directory)), self.make_service(Path(directory))
            self.enable(first)
            def read(browser, cancellation):
                second.configure({"enabled": False})
                self.assertTrue(cancellation.is_set())
                return {"state": "interrupted", "error": "cancelled"}
            self.browser.read.side_effect = read
            first.run_once(kind="checkin")
            self.assertEqual(first.status()["checkin"]["state"], "interrupted")
            first.close()
            second.close()

    def test_success_is_persisted_after_brief_state_lock_contention_without_replay(self):
        with tempfile.TemporaryDirectory() as directory:
            service = self.make_service(Path(directory))
            self.enable(service)
            ready = threading.Event()
            threads = []
            previous = self.browser.read.side_effect
            def read(*args):
                def lock_state():
                    with _file_lock(Path(directory) / "benefits" / "state.lock"):
                        ready.set()
                        time.sleep(0.1)
                thread = threading.Thread(target=lock_state)
                threads.append(thread)
                thread.start()
                self.assertTrue(ready.wait(2))
                return previous(*args)
            self.browser.read.side_effect = read
            service.run_once(kind="checkin")
            for thread in threads:
                thread.join(2)
            self.assertEqual(service.status()["checkin"]["state"], "verified")
            self.browser.read.assert_called_once()
            service.close()

    def test_persisted_store_stays_below_its_read_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            service = self.make_service(Path(directory))
            item = {**next(iter(service._project([ROW], SOURCES[0], self.now.isoformat()).values())),
                    "title": "\u4e2d" * 300, "evidence": "\u4e2d" * 800}
            with service._transaction():
                service._state["offers"] = {str(index): {**item, "id": str(index)} for index in range(1600)}
            self.assertLess(service.path.stat().st_size, 4_000_000)
            self.assertGreater(len(service.status()["offers"]), 0)
            second = self.make_service(Path(directory))
            self.assertIsNone(second.status()["error"])
            service.close()
            second.close()

    def test_enabled_worker_runs_due_jobs_and_restart_does_not_repeat_today(self):
        with tempfile.TemporaryDirectory() as directory:
            service = self.make_service(Path(directory))
            self.enable(service)
            service.start()
            deadline = time.monotonic() + 3
            while service.status()["checkin"]["state"] != "verified" and time.monotonic() < deadline:
                threading.Event().wait(0.01)
            self.assertEqual(service.status()["checkin"]["state"], "verified")
            service.close()
            self.assertFalse(service._worker.is_alive())
            self.assertEqual(self.collector.call_count, 2)
            self.browser.read.assert_called_once()
            second = self.make_service(Path(directory))
            modified = service.path.stat().st_mtime_ns
            second.run_once()
            self.assertEqual(self.collector.call_count, 2)
            self.browser.read.assert_called_once()
            self.assertEqual(service.path.stat().st_mtime_ns, modified)
            second.close()


if __name__ == "__main__":
    unittest.main()
