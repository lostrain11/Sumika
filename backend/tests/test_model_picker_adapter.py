from __future__ import annotations

import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from sumika_core.integrations.model_picker import ModelPickerAdapter, ModelPickerAdapterError


def catalog_payload():
    return {
        "schema": "model-picker/catalog/v1",
        "generated_at": "2026-09-07T00:00:00+00:00",
        "freshness": {
            "openrouter": {"stale": False},
            "relay": {"stale": True},
        },
        "models": [
            {
                "id": "openai/gpt-5",
                "name": "GPT 5",
                "benchmarks": {"livebench_coding": 0.8},
                "reasoning_efforts": ["low", "high"],
                "default_reasoning_effort": "low",
                "offers": [
                    {
                        "vendor": "openrouter",
                        "channel": "api",
                        "remote_id": "openai/gpt-5",
                        "pricing_source": "official",
                        "price_in_usd_per_1m": 2,
                        "price_out_usd_per_1m": 8,
                        "price_known": True,
                    },
                    {
                        "vendor": "relay",
                        "channel": "api",
                        "remote_id": "gpt-5-relay",
                        "pricing_source": "relay",
                        "price_in_usd_per_1m": 1,
                        "price_out_usd_per_1m": 4,
                        "price_known": True,
                        "billing_group": "default",
                    },
                    {
                        "vendor": "relay",
                        "channel": "api",
                        "remote_id": "gpt-5-relay",
                        "pricing_source": "relay",
                        "price_in_usd_per_1m": 1,
                        "price_out_usd_per_1m": 4,
                        "price_known": True,
                        "billing_group": "default",
                    },
                ],
            },
            {
                "id": "free/web-model",
                "name": "Web model",
                "offers": [
                    {
                        "vendor": "web",
                        "channel": "web",
                        "remote_id": "web-model",
                        "pricing_source": "web",
                        "price_in_usd_per_1m": 0,
                        "price_out_usd_per_1m": 0,
                        "price_known": False,
                    }
                ],
            },
        ],
    }


def evaluation_payload():
    return {
        "schema": "model-picker/evaluations/v1",
        "models": [
            {
                "model_id": "openai/gpt-5",
                "benchmarks": {"livebench_coding": 0.8},
                "evidence": {
                    "freshness": {
                        "livebench": {"stale": False},
                        "relay": {"stale": True},
                    }
                },
            }
        ],
    }


class _PickerContractHandler(BaseHTTPRequestHandler):
    def _send(self, status, payload, headers=None):
        body = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def _response(self):
        path = urlparse(self.path).path
        state = self.server.state
        state["requests"].append({"method": self.command, "path": path, "headers": dict(self.headers)})
        response = state["responses"].get(path, (404, {"ok": False, "error": "missing"}, None))
        self._send(*response)

    def do_GET(self):  # noqa: N802
        self._response()

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length") or "0")
        raw_body = self.rfile.read(length)
        path = urlparse(self.path).path
        state = self.server.state
        state["requests"].append(
            {
                "method": self.command,
                "path": path,
                "headers": dict(self.headers),
                "body": json.loads(raw_body.decode("utf-8")),
            }
        )
        response = state["responses"].get(path, (404, {"ok": False, "error": "missing"}, None))
        self._send(*response)

    def log_message(self, *args):
        pass


class _PickerContractServer:
    def __init__(self):
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), _PickerContractHandler)
        self.httpd.state = {
            "requests": [],
            "responses": {
                "/catalog": (200, {"ok": True, "data": catalog_payload()}, None),
                "/pricing": (200, {"ok": True, "data": {"schema": "model-picker/pricing/v1", "offers": [], "freshness": {}}}, None),
                "/evaluations": (200, {"ok": True, "data": evaluation_payload()}, None),
                "/recommend": (200, {"ok": True, "data": {"picks": []}}, None),
                "/record": (200, {"ok": True, "data": {"recorded": True}}, None),
            },
        }
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    @property
    def url(self):
        return f"http://127.0.0.1:{self.httpd.server_address[1]}"

    @property
    def requests(self):
        return self.httpd.state["requests"]

    @property
    def responses(self):
        return self.httpd.state["responses"]

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)


class ModelPickerAdapterTests(unittest.TestCase):
    def make_adapter(self, payload=None):
        values = {
            "catalog": payload or catalog_payload(),
            "evaluations": {"schema": "model-picker/evaluations/v1", "models": []},
            "pricing": {"schema": "model-picker/pricing/v1", "offers": []},
        }

        def fetch(path, body=None):
            if path == "recommend":
                return {"ok": True, "data": {"picks": [], "request": body}}
            return {"ok": True, "data": values[path]}

        return ModelPickerAdapter(
            "http://127.0.0.1:8399",
            fetch_json=fetch,
            profile_map={"relay": "profile-relay"},
        )

    def test_catalog_preserves_offer_identity_and_separates_price_sources(self):
        adapter = self.make_adapter()
        entries = adapter.model_entries(refresh=True)

        self.assertEqual(len(entries), 3)
        official = next(item for item in entries if item.metadata["pricing_source"] == "official")
        relay = next(item for item in entries if item.metadata["pricing_source"] == "relay")
        web = next(item for item in entries if item.metadata["pricing_source"] == "web")
        self.assertEqual(official.model_id, "openai/gpt-5")
        self.assertEqual(relay.model_id, "openai/gpt-5")
        self.assertEqual(relay.metadata["remote_id"], "gpt-5-relay")
        self.assertEqual(relay.provider_profile_id, "profile-relay")
        self.assertTrue(relay.metadata["stale"])
        self.assertFalse(relay.metadata["evidence_fresh"])
        self.assertFalse(relay.metadata["routable"])
        self.assertEqual(web.cost_class, "unknown")
        self.assertEqual(web.quota_state, "unknown")
        self.assertFalse(web.routable)

    def test_failure_does_not_invent_entries_and_cached_entries_fail_closed(self):
        calls = {"failed": False}

        def fetch(path):
            if calls["failed"]:
                raise OSError("offline")
            return {"ok": True, "data": catalog_payload()}

        adapter = ModelPickerAdapter("http://localhost:8399", fetch_json=fetch)
        first = adapter.model_entries(refresh=True)
        self.assertTrue(first)
        calls["failed"] = True
        second = adapter.model_entries(refresh=True)
        self.assertEqual(len(second), len(first))
        self.assertTrue(all(item.health_state == "unavailable" for item in second))
        self.assertTrue(all(item.metadata["routable"] is False for item in second))

    def test_failed_refresh_persists_stale_cache_and_timestamp(self):
        calls = {"failed": False}

        def fetch(path):
            if calls["failed"]:
                raise OSError("offline")
            return {"ok": True, "data": catalog_payload()}

        adapter = ModelPickerAdapter("http://localhost:8399", fetch_json=fetch)
        adapter.model_entries(refresh=True)
        calls["failed"] = True
        stale = adapter.model_entries(refresh=True)
        stale_at = stale[0].metadata["stale_at"]

        cached = adapter.model_entries()
        self.assertTrue(stale_at)
        self.assertTrue(all(item.metadata["stale"] for item in cached))
        self.assertEqual(cached[0].metadata["stale_at"], stale_at)

    def test_duplicate_remote_identity_is_isolated(self):
        payload = catalog_payload()
        payload["models"].append(
            {
                "id": "openai/gpt-5-alias",
                "name": "Duplicate remote id",
                "offers": [
                    {
                        "vendor": "relay",
                        "channel": "api",
                        "remote_id": "gpt-5-relay",
                        "pricing_source": "relay",
                        "price_known": True,
                        "price_in_usd_per_1m": 1,
                        "billing_group": "default",
                    }
                ],
            }
        )
        entries = self.make_adapter(payload).model_entries(refresh=True)

        relay_entries = [item for item in entries if item.metadata["remote_id"] == "gpt-5-relay"]
        self.assertEqual(len(relay_entries), 1)
        self.assertEqual(relay_entries[0].model_id, "openai/gpt-5")

    def test_profile_mapping_is_not_authorization_or_quota_evidence(self):
        relay = next(
            item
            for item in self.make_adapter().model_entries(refresh=True)
            if item.provider_id == "relay"
        )

        self.assertEqual(relay.provider_profile_id, "profile-relay")
        self.assertEqual(relay.auth_state, "unknown")
        self.assertEqual(relay.quota_state, "unknown")
        self.assertFalse(relay.routable)

    def test_endpoint_must_be_allowlisted_and_without_credentials(self):
        with self.assertRaises(ModelPickerAdapterError):
            ModelPickerAdapter("https://example.invalid:443")
        with self.assertRaises(ModelPickerAdapterError):
            ModelPickerAdapter("http://user:pass@127.0.0.1:8399")

    def test_picker_never_claims_quota(self):
        adapter = self.make_adapter()
        value = adapter.quota_status()
        self.assertEqual(value["state"], "unknown")
        self.assertNotIn("remaining", value)

    def test_pricing_and_recommendation_are_advisory_projections(self):
        adapter = self.make_adapter()
        self.assertEqual(adapter.pricing_catalog()["schema"], "model-picker/pricing/v1")
        result = adapter.recommend(task_type="chat_light", est_in="1k", est_out="256")
        self.assertEqual(result["request"]["task_type"], "chat_light")

    def test_local_http_contract_posts_only_public_recommend_and_record_shapes(self):
        with _PickerContractServer() as server:
            adapter = ModelPickerAdapter(server.url, profile_map={"relay": "profile-relay"})
            entries = adapter.model_entries(refresh=True)
            recommendation = adapter.recommend(
                task_type="chat_light",
                est_in="1k",
                est_out=256,
                phase="bulk",
                prompt="must-not-leave-sumika",
            )
            writeback = adapter.record_evaluation(
                task_type="chat_light",
                model_id="openai/gpt-5",
                vendor="openrouter",
                verdict="ok",
                actual_in=1000,
                actual_out=256,
                cost_usd=0.004,
                session_id="local-contract",
            )
            pricing = adapter.pricing_catalog()
            evaluations = adapter.evaluation_catalog()

        self.assertEqual(len(entries), 3)
        self.assertEqual(recommendation["picks"], [])
        self.assertTrue(writeback["recorded"])
        self.assertTrue(pricing["available"])
        self.assertEqual(evaluations["models"][0]["evidence_freshness"], {"livebench": True, "relay": False})

        recommendation_request = next(request for request in server.requests if request["path"] == "/recommend")
        self.assertEqual(recommendation_request["method"], "POST")
        self.assertEqual(recommendation_request["body"], {"task_type": "chat_light", "est_in": "1k", "est_out": 256, "phase": "bulk"})
        self.assertEqual(recommendation_request["headers"]["Content-Type"], "application/json; charset=utf-8")
        writeback_request = next(request for request in server.requests if request["path"] == "/record")
        self.assertEqual(writeback_request["method"], "POST")
        self.assertEqual(writeback_request["body"]["model"], "openai/gpt-5")
        self.assertEqual(writeback_request["body"]["vendor"], "openrouter")
        self.assertNotIn("remote_id", writeback_request["body"])

    def test_local_http_rejects_cross_origin_redirect_and_allows_same_origin(self):
        with _PickerContractServer() as server:
            server.responses["/catalog"] = (302, {"ok": True}, {"Location": "/catalog-final"})
            server.responses["/catalog-final"] = (200, {"ok": True, "data": catalog_payload()}, None)
            self.assertEqual(len(ModelPickerAdapter(server.url).model_entries(refresh=True)), 3)

        with _PickerContractServer() as server:
            server.responses["/catalog"] = (302, {"ok": True}, {"Location": "http://localhost:1/catalog"})
            self.assertEqual(ModelPickerAdapter(server.url).model_entries(refresh=True), [])
            self.assertEqual([request["path"] for request in server.requests], ["/catalog"])

    def test_local_http_enforces_bounded_json_and_ipv6_origin(self):
        with _PickerContractServer() as server:
            server.responses["/catalog"] = (200, b" " * 1025, None)
            adapter = ModelPickerAdapter(server.url, max_bytes=1024)
            self.assertEqual(adapter.model_entries(refresh=True), [])

        adapter = ModelPickerAdapter("http://[::1]:8399")
        self.assertEqual(adapter.base_url, "http://[::1]:8399")

    def test_evaluation_does_not_export_freeform_notes(self):
        adapter = self.make_adapter()
        with self.assertRaises(ModelPickerAdapterError):
            adapter.record_evaluation(task_type="chat_light", model_id="model", vendor="relay", verdict="ok",
                                      note="private conversation or workspace content")


if __name__ == "__main__":
    unittest.main()
