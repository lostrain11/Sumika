import base64
import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from sumika_core.credentials import MemoryCredentialStore
from sumika_core.provider_imports import ProviderImportError, ProviderImportRegistry
from sumika_core.provider_profiles import ProviderProfileManager
from sumika_core.storage import Storage


class ProviderProfileTests(unittest.TestCase):
    def setUp(self):
        self.storage = Storage()
        self.credentials = MemoryCredentialStore()
        self.profiles = ProviderProfileManager(self.storage, self.credentials)

    def tearDown(self):
        self.storage.close()

    def test_profile_secrets_are_isolated_and_edit_requires_retest(self):
        profile = self.profiles.save({
            "name": "Cloud test",
            "base_url": "https://example.invalid/v1",
            "model": "test-model",
            "processing_location": "cloud",
            "api_key": "sk-secret-value",
            "headers": {"X-Trace": "safe", "X-Api-Key": "header-secret"},
        })
        self.assertEqual(profile["status"], "unavailable")
        self.assertTrue(profile["has_secrets"])
        row = self.storage.get_provider_profile(profile["id"])
        self.assertNotIn("sk-secret-value", json.dumps(row, ensure_ascii=False))
        self.assertEqual(row["config"]["headers"], {"X-Trace": "safe"})
        secrets = self.credentials.read(profile["id"])
        self.assertEqual(secrets["api_key"], "sk-secret-value")
        self.assertEqual(secrets["header:X-Api-Key"], "header-secret")
        self.assertRegex(row["config"]["credential_revision"], r"^[a-f0-9]{32}$")

        edited = self.profiles.save({**profile, "name": "Cloud test renamed"})
        self.assertEqual(
            edited["config"]["credential_revision"],
            row["config"]["credential_revision"],
        )
        rotated = self.profiles.save({**edited, "api_key": "sk-new-secret-value"})
        self.assertNotEqual(
            rotated["config"]["credential_revision"],
            edited["config"]["credential_revision"],
        )

    def test_pricing_config_keeps_provider_and_cash_units_separate(self):
        profile = self.profiles.save({
            "name": "Relay pricing",
            "base_url": "https://relay.example.invalid/v1",
            "model": "fixture-model",
            "processing_location": "cloud",
            "pricing": {
                "source_type": "manual",
                "billing_group": "经济组",
                "rates": {
                    "currency": "USD-credit",
                    "input_price_per_million": 1,
                    "output_price_per_million": 4,
                },
                "cash_conversion": {
                    "paid_amount": 50,
                    "credited_amount": 100,
                    "currency": "CNY",
                },
            },
        })
        pricing = profile["config"]["pricing"]
        self.assertEqual(pricing["rates"]["currency"], "USD-credit")
        self.assertEqual(pricing["cash_conversion"]["currency"], "CNY")
        self.assertEqual(pricing["cash_conversion"]["paid_amount"], 50)

        with self.assertRaisesRegex(Exception, "cash_conversion"):
            self.profiles.save({
                **profile,
                "pricing": {
                    "source_type": "manual",
                    "cash_conversion": {"paid_amount": 10, "credited_amount": 0, "currency": "CNY"},
                },
            })

    def test_direct_official_pricing_cannot_be_attached_to_a_relay_endpoint(self):
        with self.assertRaisesRegex(Exception, "matching built-in Provider endpoint"):
            self.profiles.save({
                "name": "Relay with official price",
                "template_id": "openai-compatible",
                "base_url": "https://relay.example.invalid/v1",
                "model": "fixture-model",
                "processing_location": "cloud",
                "pricing": {
                    "source_type": "direct-official",
                    "rates": {
                        "currency": "CNY",
                        "input_price_per_million": 1,
                        "output_price_per_million": 2,
                    },
                },
            })

        profile = self.profiles.save({
            "name": "Official Zhipu price",
            "template_id": "zhipu-bigmodel",
            "base_url": "https://open.bigmodel.cn/api/paas/v4",
            "model": "glm-4.5-air",
            "processing_location": "cloud",
            "pricing": {
                "source_type": "direct-official",
                "rates": {
                    "currency": "CNY",
                    "input_price_per_million": 1,
                    "output_price_per_million": 2,
                },
            },
        })
        self.assertEqual(profile["config"]["pricing"]["source_type"], "direct-official")

    def test_health_marks_profile_available_and_archive_is_recoverable(self):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"data":[{"id":"ready-model"}]}')

            def log_message(self, *_args):
                return None

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            profile = self.profiles.save({
                "name": "Local test",
                "base_url": f"http://127.0.0.1:{server.server_address[1]}",
                "model": "ready-model",
            })
            health = self.profiles.health(profile["id"])
            self.assertTrue(health["ok"])
            self.assertEqual(health["profile"]["status"], "available")
            archived = self.profiles.archive(profile["id"])
            self.assertEqual(archived["status"], "archived")
            self.assertEqual(self.profiles.list(), [])
            restored = self.profiles.restore(profile["id"])
            self.assertEqual(restored["status"], "draft")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_health_marks_a_previously_available_profile_unavailable_after_endpoint_stops(self):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"data":[{"id":"ready-model"}]}')

            def log_message(self, *_args):
                return None

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        profile = self.profiles.save(
            {
                "name": "Endpoint lifecycle",
                "base_url": f"http://127.0.0.1:{server.server_address[1]}",
                "model": "ready-model",
            }
        )
        try:
            first = self.profiles.health(profile["id"])
            self.assertTrue(first["ok"])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

        second = self.profiles.health(profile["id"])
        self.assertFalse(second["ok"])
        self.assertEqual(second["profile"]["status"], "unavailable")

    def test_ccswitch_preview_masks_secrets_and_preserves_unknown_metadata(self):
        script = base64.urlsafe_b64encode(b"({request:{url:'{{baseUrl}}/usage'},extractor:function(r){return r}})").decode().rstrip("=")
        raw = (
            "ccswitch://v1/import?resource=provider&app=codex&name=SHUAI%20API"
            "&endpoint=https%3A%2F%2Fapi.example.com%2Fv1%2Chttps%3A%2F%2Fbackup.example.com%2Fv1"
            "&apiKey=sk-H1234567890&model=gpt-test&futureToken=do-not-show"
            f"&usageEnabled=true&usageScript={script}"
        )
        preview = ProviderImportRegistry().preview(raw)
        self.assertEqual(preview["importer_id"], "ccswitch-v1")
        self.assertEqual(len(preview["profile"]["base_urls"]), 2)
        self.assertNotIn("sk-H1234567890", json.dumps(preview, ensure_ascii=False))
        self.assertEqual(preview["unsupported_fields"][0]["value"], "[redacted]")
        self.assertIn("source:futureToken", preview["secret_fields"])
        self.assertNotIn("do-not-show", json.dumps(preview, ensure_ascii=False))
        self.assertIn("JavaScript", preview["warnings"][0])
        self.assertEqual(preview["profile"]["source"]["usage_script"]["execution"], "blocked_javascript")

    def test_ccswitch_unknown_sensitive_field_is_written_only_to_credential_store(self):
        raw = (
            "ccswitch://v1/import?resource=provider&app=codex&name=Custom"
            "&endpoint=https%3A%2F%2Fexample.invalid%2Fv1&model=test-model"
            "&futureToken=secret-value"
        )
        imported = ProviderImportRegistry().parse(raw)
        profile = self.profiles.save({**imported.profile, "secrets": imported.secrets})
        row = self.storage.get_provider_profile(profile["id"])
        self.assertNotIn("secret-value", json.dumps(row, ensure_ascii=False))
        self.assertEqual(self.credentials.read(profile["id"])["source:futureToken"], "secret-value")

    def test_unknown_ccswitch_version_and_non_codex_app_are_rejected(self):
        registry = ProviderImportRegistry()
        with self.assertRaisesRegex(ProviderImportError, "Unsupported CC Switch protocol version"):
            registry.preview("ccswitch://v2/import?resource=provider&app=codex&name=x")
        with self.assertRaisesRegex(ProviderImportError, "not an OpenAI-compatible Codex profile"):
            registry.preview("ccswitch://v1/import?resource=provider&app=claude&name=x")

    def test_provider_profiles_are_part_of_module_snapshots_without_secret_values(self):
        profile = self.profiles.save({
            "name": "Snapshot profile",
            "base_url": "https://example.invalid/v1",
            "model": "test-model",
            "api_key": "never-export-this",
        })
        payload = self.storage.export_snapshot_state("modules")
        self.assertEqual(payload["tables"]["provider_profiles"][0]["id"], profile["id"])
        self.assertNotIn("never-export-this", json.dumps(payload, ensure_ascii=False))

    def test_sumika_profile_import_accepts_public_nested_config(self):
        raw = json.dumps(
            {
                "format": "sumika-provider-profile/v1",
                "profile": {
                    "name": "Nested local",
                    "adapter_id": "openai-compatible",
                    "template_id": "ollama",
                    "config": {
                        "base_urls": ["http://127.0.0.1:11434/v1"],
                        "active_base_url": "http://127.0.0.1:11434/v1",
                        "model": "qwen3:4b",
                        "timeout": 45,
                    },
                },
                "secrets": {"api_key": "nested-secret"},
            }
        )
        imported = ProviderImportRegistry().parse(raw)
        profile = self.profiles.save({**imported.profile, "secrets": imported.secrets})
        self.assertEqual(profile["config"]["model"], "qwen3:4b")
        self.assertEqual(profile["config"]["timeout"], 45.0)
        self.assertEqual(self.credentials.read(profile["id"])["api_key"], "nested-secret")

    def test_templates_include_zhipu_models_without_credentials(self):
        template = next(
            item for item in self.profiles.templates() if item["id"] == "zhipu-bigmodel"
        )
        self.assertEqual(template["base_url"], "https://open.bigmodel.cn/api/paas/v4")
        self.assertEqual(template["model"], "glm-4.5-air")
        self.assertEqual(template["model_options"], ["glm-4.5-air", "glm-4.7", "glm-4.6v"])
        self.assertNotIn("api_key", template)

    def test_one_profile_can_discover_and_health_check_multiple_models(self):
        class Handler(BaseHTTPRequestHandler):
            models = ["glm-4.5-air", "glm-4.6", "glm-4.7"]

            def do_GET(self):  # noqa: N802
                if self.path.rstrip("/") != "/v1/models":
                    self.send_response(404)
                    self.end_headers()
                    return
                payload = {"data": [{"id": item} for item in self.models]}
                body = json.dumps(payload).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_args):
                return None

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            profile = self.profiles.save(
                {
                    "id": "zhipu-multi-model",
                    "name": "智谱多模型",
                    "base_url": f"http://127.0.0.1:{server.server_address[1]}/v1",
                    "model": "glm-4.5-air",
                    "models": ["glm-4.5-air"],
                    "api_key": "one-key-for-all-models",
                }
            )
            discovered = self.profiles.discover_models(profile["id"])
            self.assertEqual(
                [item["id"] for item in discovered["models"]],
                ["glm-4.5-air", "glm-4.6", "glm-4.7"],
            )
            # Directory discovery is not a chat health probe; the new rows
            # remain unknown until each model is explicitly tested.
            self.assertEqual(
                {item["health_state"] for item in discovered["models"]},
                {"unknown"},
            )
            first = self.profiles.health(profile["id"], model_id="glm-4.5-air")
            self.assertTrue(first["ok"])
            self.assertEqual(first["profile"]["status"], "available")
            selected = self.profiles.select_model(profile["id"], "glm-4.7")
            self.assertEqual(selected["profile"]["config"]["model"], "glm-4.7")
            self.assertEqual(self.credentials.read(profile["id"])["api_key"], "one-key-for-all-models")
            self.assertEqual(self.profiles.runtime(profile["id"], model_id="glm-4.6").model, "glm-4.6")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_failed_model_probe_does_not_disable_other_healthy_models(self):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                body = b'{"data":[{"id":"model-good"}]}'
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_args):
                return None

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            profile = self.profiles.save(
                {
                    "id": "partial-model-health",
                    "name": "部分模型健康",
                    "base_url": f"http://127.0.0.1:{server.server_address[1]}/v1",
                    "model": "model-good",
                    "models": ["model-good", "model-missing"],
                }
            )
            self.assertTrue(self.profiles.health(profile["id"], model_id="model-good")["ok"])
            failed = self.profiles.health(profile["id"], model_id="model-missing")
            self.assertFalse(failed["ok"])
            self.assertEqual(failed["profile"]["status"], "available")
            rows = {item["id"]: item for item in failed["profile"]["config"]["models"]}
            self.assertEqual(rows["model-good"]["health_state"], "healthy")
            self.assertEqual(rows["model-missing"]["health_state"], "unavailable")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_explicit_chat_probe_keeps_catalog_less_profile_available(self):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                self.send_response(404)
                self.end_headers()

            def do_POST(self):  # noqa: N802
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"choices":[{"message":{"content":"ok"}}]}')

            def log_message(self, *_args):
                return None

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            profile = self.profiles.save({
                "name": "Catalog-less test",
                "base_url": f"http://127.0.0.1:{server.server_address[1]}/v1",
                "model": "test-model",
            })
            first = self.profiles.health(profile["id"], allow_chat_probe=True)
            self.assertTrue(first["ok"])
            self.assertEqual(first["profile"]["status"], "available")
            passive = self.profiles.health(profile["id"])
            self.assertTrue(passive["ok"])
            self.assertEqual(passive["profile"]["status"], "available")
            self.assertEqual(passive["model_catalog"], "not-exposed")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
