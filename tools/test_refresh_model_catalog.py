"""Offline fixtures and loopback-only checks; never call a provider or install tasks."""

import hashlib
import io
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import Mock, patch

from tools import refresh_model_catalog as cli
from sumika_core.integrations import zhipu_pricing as pricing
from sumika_core.model_refresh import RefreshCoordinator


OBSERVED_AT = "2024-01-02T03:04:05+00:00"
HEALTH = {"ok": True, "version": cli.__version__, "transport": ["http", "websocket"], "uptime_seconds": 1.25}


def table(rows, headers=("模型", "输入价格", "输出价格")):
    heading = "<tr>" + "".join(f"<th>{header}</th>" for header in headers) + "</tr>"
    content = "".join("<tr>" + "".join(f"<td>{cell}</td>" for cell in row) + "</tr>" for row in rows)
    return "<table>" + heading + content + "</table>"


def model_row(model_id="glm-4.5-flash"):
    return {"provider_id": "zhipu-official", "model_id": model_id, "source_url": pricing.PRICING_URL,
            "observed_at": OBSERVED_AT, "source_version": "fixture", "free_claim": False, "availability_state": "observed"}


def resource_observation():
    return {"ok": True, "source_url": "https://open.bigmodel.cn/finance/resourcepack",
            "provider_profile_id": "zhipu-official", "observed_at": OBSERVED_AT, "source": "authenticated-page-dom",
            "displayed_timezone": "+08:00", "packs": [{"pack_id": "fixture-pack", "name": "GLM pack",
                "applicability": "glm-4.5-flash", "available_balance": "1,000 tokens", "status": "active",
                "expires_at_display": "2024-02-01 00:00:00"}]}


class Response(io.BytesIO):
    def __init__(self, body, *, status=200, url=pricing.PRICING_URL, headers=None):
        super().__init__(body)
        self.status = status
        self.url = url
        self.headers = headers if headers is not None else {"Content-Type": "text/html"}

    def geturl(self):
        return self.url


@contextmanager
def loopback_server(reply):
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append({"payload": request, "headers": dict(self.headers), "path": self.path})
            status, headers, result = reply(request)
            body = json.dumps(result).encode()
            self.send_response(status)
            for key, value in headers.items():
                self.send_header(key, value)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def core_reply(request):
    result = HEALTH if request["method"] == "core.health" else {"ok": True, "fixture": True,
        "refresh": {"jobs": {kind: {"state": "ready"} for kind in ("resources", "pricing", "catalog")}}}
    return 200, {"Content-Type": "application/json"}, {"jsonrpc": "2.0", "id": request["id"], "result": result}


class PricingParserTests(unittest.TestCase):
    def parse(self, document):
        return pricing.parse_pricing_observations(document, observed_at=OBSERVED_AT)

    def test_exact_flash_flashx_and_neighbors_are_independent(self):
        document = "免费模型" + table([
            ("GLM-4.5-FlashX", "0.8", "0.8"), ("GLM-4.5-Flash", "免费", "0.000元/百万tokens"),
            ("GLM-5.3-Flash", "0.8", "免费"), ("GLM-4.6V-Flash", "待公布", "待公布"),
        ])
        rows = self.parse(document)
        self.assertEqual({row["model_id"]: row["free_claim"] for row in rows}, {
            "glm-4.5-flash": True, "glm-4.5-flashx": False, "glm-5.3-flash": False, "glm-4.6v-flash": False,
        })
        self.assertEqual([row["model_id"] for row in rows], sorted(row["model_id"] for row in rows))

    def test_all_dimensions_including_cache_must_be_explicitly_free(self):
        for cache, expected in (("免费", True), ("0", True), ("0.8", False), ("—", False), ("", False)):
            with self.subTest(cache=cache):
                row = self.parse(table([("glm-4.5-flash", "0", "0", cache)], ("模型", "输入", "输出", "缓存写入")))[0]
                self.assertIs(row["free_claim"], expected)

    def test_partial_unknown_conditional_and_unsupported_dimensions_are_not_free(self):
        cases = [
            table([("glm-4.5-flash", "免费")], ("模型", "输入")),
            table([("glm-4.5-flash", "免费")], ("模型", "价格")),
            table([("glm-4.5-flash", "免费", "")]),
            table([("glm-4.5-flash", "0", "0", "0")], ("模型", "输入", "输出", "音频输入")),
            table([("glm-4.5-flash", "0", "0")], ("模型", "输入(前1000token免费)", "输出")),
        ]
        for document in cases:
            with self.subTest(document=document):
                self.assertFalse(self.parse(document)[0]["free_claim"])

    def test_nonzero_and_ambiguous_prices_never_match_zero(self):
        for price in ("0.8", "0.00001元/百万tokens", "10", "免费额度", "0起", "0~0.8", "免费(限时)", "0/0.8", "输入0.8，缓存免费"):
            with self.subTest(price=price):
                self.assertFalse(self.parse(table([("glm-4.5-flash", price, "免费")]))[0]["free_claim"])

    def test_explicit_zero_units_and_english_headers(self):
        for value in ("0", "0.00", "￥0元/百万tokens", "$0.000/1M tokens", "free"):
            with self.subTest(value=value):
                row = self.parse(table([("GLM-4.5-Flash", value, value)], ("Model ID", "Input price (per million tokens)", "Output price (per million tokens)")))[0]
                self.assertTrue(row["free_claim"])

    def test_no_model_substring_or_page_text_scanning(self):
        for document in ("glm-4.5-flash 输入0 输出0", table([("glm-4.5-flashx and glm-4.5-flash", "0", "0")]),
                         "<script>" + table([("glm-4.5-flash", "0", "0")]) + "</script>"):
            with self.subTest(document=document), self.assertRaises(pricing.PricingNeedsReview):
                self.parse(document)

    def test_duplicate_tier_rows_are_combined_conservatively(self):
        for second in ("0.8", "unknown"):
            rows = self.parse(table([("glm-4.5-flash", "0", "0"), ("glm-4.5-flash", second, "0")]))
            self.assertEqual(len(rows), 1)
            self.assertFalse(rows[0]["free_claim"])

    def test_merged_malformed_and_hidden_rows_cannot_certify_free(self):
        document = table([("glm-4.5-flash", "0", "0")])
        for modified in (document.replace("<td>0", '<td rowspan="2">0', 1),
                         document.replace("<table>", '<table hidden>'),
                         document.replace("<td>0", '<td style="display:none">0', 1),
                         document.replace("<td>0</td><td>0</td>", "<td>0<td>0</td>")):
            with self.subTest(document=modified):
                self.assertFalse(self.parse(modified)[0]["free_claim"])

    def test_evidence_has_only_observed_pricing_fields_and_hash(self):
        document = table([("glm-4.5-flash", "0", "0")]).encode()
        row = self.parse(document)[0]
        self.assertEqual(set(row), {"provider_id", "model_id", "source_url", "observed_at", "source_version", "free_claim", "availability_state"})
        self.assertEqual(row["provider_id"], "zhipu-official")
        self.assertEqual(row["source_url"], pricing.PRICING_URL)
        self.assertEqual(row["observed_at"], OBSERVED_AT)
        self.assertEqual(row["source_version"], hashlib.sha256(document).hexdigest())
        self.assertEqual(row["availability_state"], "observed")
        coordinator = RefreshCoordinator(None)
        coordinator.ingest_models([row])
        self.assertFalse(next(item for item in coordinator.observations() if item.model_id == row["model_id"]).routable)

    def test_spa_needs_review_without_synthetic_observations(self):
        with self.assertRaises(pricing.PricingNeedsReview) as caught:
            self.parse('<div id="app"></div><script src="/app.js"></script>')
        self.assertEqual(caught.exception.state, "needs-review")

    def test_parser_bounds_and_timestamp_are_enforced(self):
        for document in (b"x" * (pricing.MAX_BODY_BYTES + 1),
                         table([(f"glm-{index}", "0", "0") for index in range(pricing.MAX_ROWS + 1)]),
                         table([("glm-4.5-flash", "0" * 2049, "0")]),
                         table([("glm-4.5-flash", "0", "0")])[:-8]):
            with self.subTest(size=len(document)), self.assertRaises(pricing.PricingNeedsReview):
                self.parse(document)
        with self.assertRaises(pricing.PricingNeedsReview):
            pricing.parse_pricing_observations(table([]), observed_at="2024-01-01")


class PricingFetchTests(unittest.TestCase):
    def test_fixed_public_get_no_credentials_proxy_or_cookies_and_actual_time(self):
        document = table([("glm-4.5-flash", "0", "0")]).encode()
        opener = Mock()
        opener.open.return_value = Response(document)
        before = datetime.now(timezone.utc)
        with patch.dict(os.environ, {"HTTPS_PROXY": "http://fixture:secret@proxy.invalid:3128", "ZHIPU_API_KEY": "fixture-secret"}), patch.object(pricing.urllib.request, "build_opener", return_value=opener) as factory:
            rows = pricing.fetch_pricing_observations(url=pricing.PRICING_URL)
        after = datetime.now(timezone.utc)
        request = opener.open.call_args.args[0]
        self.assertEqual(request.full_url, pricing.PRICING_URL)
        self.assertEqual(request.method, "GET")
        self.assertIsNone(request.data)
        self.assertEqual({key.lower() for key, _ in request.header_items()}, {"user-agent", "accept", "accept-encoding"})
        self.assertEqual(factory.call_args.args[0].proxies, {})
        self.assertIsInstance(factory.call_args.args[1], pricing.NoRedirect)
        self.assertEqual(opener.open.call_args.kwargs["timeout"], 15)
        self.assertEqual(opener.open.call_count, 1)
        self.assertLessEqual(before, datetime.fromisoformat(rows[0]["observed_at"]))
        self.assertLessEqual(datetime.fromisoformat(rows[0]["observed_at"]), after)

    def test_allowlist_rejects_credentials_query_fragment_and_other_paths_before_request(self):
        urls = ["http://bigmodel.cn/pricing", "https://open.bigmodel.cn/pricing", "https://bigmodel.cn:443/pricing",
                "https://user:secret@bigmodel.cn/pricing", "https://bigmodel.cn/pricing?key=secret",
                "https://bigmodel.cn/pricing#fragment", "https://bigmodel.cn/other", "https://bigmodel.cn.evil.invalid/pricing"]
        with patch.object(pricing.urllib.request, "build_opener") as factory:
            for url in urls:
                with self.subTest(url=url), self.assertRaises(pricing.PricingNeedsReview):
                    pricing.fetch_pricing_observations(url=url)
            factory.assert_not_called()

    def test_redirect_handler_denies_before_followup_request(self):
        handler = pricing.NoRedirect()
        handler.parent = Mock()
        for status in (301, 302, 303, 307, 308):
            for target in (pricing.PRICING_URL, "https://user:secret@evil.invalid/private"):
                with self.subTest(status=status, target=target), self.assertRaises(ValueError):
                    handler.http_error_302(urllib.request.Request(pricing.PRICING_URL), io.BytesIO(), status, "redirect", {"location": target})
        handler.parent.open.assert_not_called()

    def test_bad_status_type_encoding_length_and_oversize_fail_closed(self):
        document = table([("glm-4.5-flash", "0", "0")]).encode()
        cases = [Response(document, status=206), Response(document, status=302), Response(document, status=500),
                 Response(document, url="https://evil.invalid/"), Response(document, headers={"Content-Type": "application/json"}),
                 Response(document, headers={"Content-Type": "text/html", "Content-Encoding": "gzip"}),
                 Response(document, headers={"Content-Type": "text/html", "Content-Length": "2000001"}),
                 Response(document, headers={"Content-Type": "text/html", "Content-Length": str(len(document) + 5)}),
                 Response(b"x" * (pricing.MAX_BODY_BYTES + 1))]
        for response in cases:
            with self.subTest(status=response.status, headers=response.headers), patch.object(pricing.urllib.request, "build_opener") as factory:
                factory.return_value.open.return_value = response
                with self.assertRaises(pricing.PricingNeedsReview):
                    pricing.fetch_pricing_observations()

    def test_fetch_errors_do_not_expose_response_or_url_secrets(self):
        with patch.object(pricing.urllib.request, "build_opener") as factory:
            factory.return_value.open.side_effect = urllib.error.HTTPError("https://fixture:secret@invalid/", 403, "secret-body", {}, io.BytesIO(b"secret-html"))
            with self.assertRaises(pricing.PricingNeedsReview) as caught:
                pricing.fetch_pricing_observations()
            self.assertNotIn("secret", str(caught.exception))

    def test_read_deadline_is_bounded(self):
        with patch.object(pricing.time, "monotonic", side_effect=[0, 16]), self.assertRaises(ValueError):
            pricing.read_bounded(Response(b"x"), 100, 15)


class RefreshCliTests(unittest.TestCase):
    def call(self, args):
        output, errors = io.StringIO(), io.StringIO()
        with redirect_stdout(output), redirect_stderr(errors):
            result = cli.main(args)
        return result, output.getvalue(), errors.getvalue()

    def write_json(self, directory, name, payload):
        path = Path(directory) / name
        path.write_text(json.dumps(payload), encoding="utf-8")
        return str(path)

    def test_core_url_validation_has_no_dns_or_credentials(self):
        for url in ("http://localhost:8771", "http://127.0.0.1:8771/", "http://[::1]:8771"):
            self.assertTrue(cli.validate_core_url(url).startswith("http://"))
        for url in ("http://localhost", "http://127.0.0.1:0", "http://127.0.0.1:65536", "http://2130706433:80",
                    "http://127.0.0.1:8771/path", "http://127.0.0.1:8771?", "http://127.0.0.1:8771#",
                    "http://127.0.0.1:8771\\@remote.invalid", "http://user:secret@127.0.0.1:8771",
                    "http://remote.invalid:8771", "https://10.0.0.1:8771", "http://127.0.0.1:\n8771"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                cli.validate_core_url(url)

    def test_all_dry_run_modes_have_no_network_or_persistent_coordinator(self):
        with patch.object(cli.urllib.request, "build_opener", side_effect=AssertionError("network")), patch.object(cli, "RefreshCoordinator", side_effect=AssertionError("store")):
            for kind in ("resources", "pricing", "catalog", "all", "status"):
                with self.subTest(kind=kind):
                    code, output, _ = self.call(["--" + kind, "--noninteractive", "--core-url", "http://127.0.0.1:8771", "--dry-run", "--force"])
                    self.assertEqual(code, 0)
                    self.assertTrue(json.loads(output)["dry_run"])

    def test_offline_dry_run_validates_both_files_without_writing(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(cli.urllib.request, "build_opener", side_effect=AssertionError("network")):
            resources = self.write_json(directory, "resources.json", resource_observation())
            models = self.write_json(directory, "models.json", [model_row()])
            destination = Path(directory) / "not-created"
            before = {path.name: path.read_bytes() for path in Path(directory).iterdir()}
            code, output, _ = self.call(["--data-dir", str(destination), "--resource-file", resources, "--model-file", models, "--dry-run"])
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(output)["counts"], {"resources": 1, "catalog": 1})
            self.assertFalse(destination.exists())
            self.assertEqual(before, {path.name: path.read_bytes() for path in Path(directory).iterdir()})

    def test_offline_import_preserves_stale_time_even_with_force_and_does_not_retire_missing_rows(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(cli.urllib.request, "build_opener", side_effect=AssertionError("network")):
            destination = Path(directory) / "data"
            models = self.write_json(directory, "models.json", [model_row(), model_row("glm-4.5-flashx")])
            self.assertEqual(self.call(["--data-dir", str(destination), "--model-file", models, "--force"])[0], 0)
            partial = self.write_json(directory, "partial.json", [model_row()])
            self.assertEqual(self.call(["--data-dir", str(destination), "--models", partial])[0], 0)
            status = RefreshCoordinator(destination).status()
            self.assertEqual(status["jobs"]["catalog"]["last_success_at"], OBSERVED_AT)
            self.assertEqual(status["jobs"]["catalog"]["state"], "stale")
            rows = {row["model_id"]: row for row in status["observations"]}
            self.assertEqual(rows["glm-4.5-flashx"]["availability_state"], "observed")
            self.assertEqual(rows["glm-4.5-flash"]["observed_at"], OBSERVED_AT)
            self.assertFalse(rows["glm-4.5-flash"]["fresh"])
            self.assertTrue((destination / "model-policy" / "refresh-v1.json").is_file())

    def test_legacy_resource_import_keeps_source_time_and_unknown_expiry(self):
        observation = resource_observation()
        observation.pop("displayed_timezone")
        with tempfile.TemporaryDirectory() as directory:
            source = self.write_json(directory, "resource.json", observation)
            destination = Path(directory) / "data"
            self.assertEqual(self.call(["--resources", source, "--data-dir", str(destination), "--force"])[0], 0)
            status = RefreshCoordinator(destination).status()
            self.assertEqual(status["jobs"]["resources"]["last_success_at"], OBSERVED_AT)
            self.assertIsNone(status["resources"][0]["expires_at"])
            self.assertFalse(status["resources"][0]["available"])

    def test_missing_timestamps_and_fabricated_quality_are_rejected_without_write(self):
        for update in ({"observed_at": None}, {"observed_at": "2024-01-01"}, {"health_state": "healthy"},
                       {"evaluation_count": 3}, {"quality_tier": "premium"}, {"availability_state": "routable"}):
            with self.subTest(update=update), tempfile.TemporaryDirectory() as directory:
                source = self.write_json(directory, "models.json", [{**model_row(), **update}])
                destination = Path(directory) / "data"
                self.assertEqual(self.call(["--models", source, "--data-dir", str(destination)])[0], 2)
                self.assertFalse(destination.exists())

    def test_scheduled_cannot_import_or_write_live_files(self):
        with patch.object(cli.urllib.request, "build_opener", side_effect=AssertionError("network")), patch.object(cli, "RefreshCoordinator", side_effect=AssertionError("store")):
            for args in (["--all", "--data-dir", "unused"], ["--model-file", "unused", "--data-dir", "unused"], ["--status", "--data-dir", "unused"]):
                self.assertEqual(self.call([*args, "--noninteractive", "--core-url", "http://127.0.0.1:8771"])[0], 2)

    def test_live_core_unreachable_never_contacts_upstream_or_constructs_store(self):
        with socket.socket() as bound:
            bound.bind(("127.0.0.1", 0))
            url = f"http://127.0.0.1:{bound.getsockname()[1]}"
            with patch.object(pricing, "fetch_pricing_observations", side_effect=AssertionError("upstream")), patch.object(cli, "RefreshCoordinator", side_effect=AssertionError("store")):
                code, _, errors = self.call(["--all", "--noninteractive", "--core-url", url])
            self.assertEqual(code, 2)
            self.assertIn("no upstream fallback", errors)

    def test_verified_live_core_gets_only_kind_force_and_no_import_payload(self):
        with loopback_server(core_reply) as (url, requests), patch.object(cli, "RefreshCoordinator", side_effect=AssertionError("store")), patch.object(pricing, "fetch_pricing_observations", side_effect=AssertionError("upstream")):
            for kind in ("all", "resources", "catalog", "pricing"):
                code, _, _ = self.call(["--" + kind, "--core-url", url, "--noninteractive", "--force"])
                self.assertEqual(code, 0)
                self.assertEqual([entry["payload"]["method"] for entry in requests[-2:]], ["core.health", "model.policy.refresh"])
                self.assertEqual(requests[-1]["payload"]["params"], {"kind": kind, "force": True})
                self.assertNotIn("Authorization", requests[-1]["headers"])
                self.assertNotIn("Cookie", requests[-1]["headers"])
            self.assertEqual(self.call(["--status", "--core-url", url])[0], 0)
            self.assertEqual(requests[-1]["payload"]["method"], "model.policy.refresh.status")

    def test_invalid_identity_stops_before_refresh(self):
        for change in ({"version": "other"}, {"ok": False}, {"transport": []}, {"uptime_seconds": True}):
            def reply(request):
                return 200, {"Content-Type": "application/json"}, {"jsonrpc": "2.0", "id": request["id"], "result": {**HEALTH, **change}}
            with self.subTest(change=change), loopback_server(reply) as (url, requests):
                self.assertEqual(self.call(["--all", "--core-url", url])[0], 2)
                self.assertEqual(len(requests), 1)

    def test_missing_or_never_observed_jobs_do_not_report_success(self):
        for refresh in ({}, {"jobs": {"pricing": {"state": "never"}}}):
            def reply(request):
                result = HEALTH if request["method"] == "core.health" else {"refresh": refresh}
                return 200, {"Content-Type": "application/json"}, {"jsonrpc": "2.0", "id": request["id"], "result": result}
            with self.subTest(refresh=refresh), loopback_server(reply) as (url, _requests):
                self.assertEqual(self.call(["--pricing", "--core-url", url])[0], 2)

    def test_core_redirects_are_not_followed(self):
        with loopback_server(core_reply) as (target, target_requests):
            def reply(request):
                return 302, {"Location": target + "/rpc", "Content-Type": "application/json"}, {}
            with loopback_server(reply) as (url, requests):
                self.assertEqual(self.call(["--all", "--core-url", url])[0], 2)
                self.assertEqual(len(requests), 1)
                self.assertEqual(target_requests, [])

    def test_legacy_pricing_url_is_core_only_and_dry_run_never_fetches(self):
        with patch.object(cli.urllib.request, "build_opener", side_effect=AssertionError("network")):
            code, _, _ = self.call(["--pricing-url", pricing.PRICING_URL, "--core-url", "http://127.0.0.1:8771", "--dry-run"])
            self.assertEqual(code, 0)
            self.assertEqual(self.call(["--pricing-url", pricing.PRICING_URL, "--data-dir", "unused"])[0], 2)

    def test_cli_errors_never_echo_secret_input(self):
        code, _, errors = self.call(["--all", "--core-url", "https://user:secret-marker@127.0.0.1:8771"])
        self.assertEqual(code, 2)
        self.assertNotIn("secret-marker", errors)

    def test_core_reported_refresh_failure_has_nonzero_exit_but_status_remains_readable(self):
        report = {"refresh": {"jobs": {"pricing": {"state": "needs-review"}}}}
        with patch.object(cli.CoreClient, "verify_identity"), patch.object(cli.CoreClient, "rpc", return_value=report):
            self.assertEqual(self.call(["--pricing", "--core-url", "http://127.0.0.1:8771"])[0], 2)
            self.assertEqual(self.call(["--status", "--core-url", "http://127.0.0.1:8771"])[0], 0)

    def test_rpc_wrong_id_or_error_is_not_accepted_as_identity(self):
        for payload in ({"jsonrpc": "2.0", "id": 999, "result": HEALTH},
                        {"jsonrpc": "2.0", "id": 1, "result": HEALTH, "error": {"message": "fixture"}}):
            with self.subTest(payload=payload), patch.object(cli.urllib.request, "build_opener") as factory:
                factory.return_value.open.return_value = Response(json.dumps(payload).encode(), url="http://127.0.0.1:8771/rpc", headers={"Content-Type": "application/json"})
                self.assertEqual(self.call(["--all", "--core-url", "http://127.0.0.1:8771"])[0], 2)
                self.assertEqual(factory.return_value.open.call_count, 1)

    def test_dry_run_disables_bytecode_writes_without_requiring_python_B_flag(self):
        command = (
            "import runpy,sys; sys.argv=['refresh_model_catalog.py','--all','--dry-run',"
            "'--core-url','http://127.0.0.1:8771']; "
            "\ntry: runpy.run_path(sys.argv[0],run_name='__main__')"
            "\nexcept SystemExit as result: assert result.code == 0 and sys.dont_write_bytecode"
        ).replace("'refresh_model_catalog.py'", repr(str(cli.ROOT / "tools" / "refresh_model_catalog.py")))
        result = subprocess.run([sys.executable, "-c", command], capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)


@unittest.skipUnless(os.name == "nt" and shutil.which("pwsh"), "Windows PowerShell checks")
class WindowsRefreshTests(unittest.TestCase):
    def powershell(self, command):
        return subprocess.run([shutil.which("pwsh"), "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", command],
                              capture_output=True, text=True, encoding="utf-8", timeout=30, cwd=cli.ROOT)

    def test_scripts_parse_and_registration_whatif_has_no_scheduler_side_effect(self):
        command = r"""
$ErrorActionPreference = 'Stop'
foreach ($path in @('tools/refresh_model_catalog.ps1', 'tools/register_model_refresh_tasks.ps1')) {
    $tokens = $null; $errors = $null
    $null = [System.Management.Automation.Language.Parser]::ParseFile((Join-Path (Get-Location) $path), [ref]$tokens, [ref]$errors)
    if ($errors.Count) { throw 'PowerShell syntax failure' }
}
function Get-ScheduledTask { throw 'Scheduler should not be read in WhatIf' }
function Register-ScheduledTask { throw 'Scheduler should not be modified' }
function Unregister-ScheduledTask { throw 'Scheduler should not be modified' }
& ./tools/register_model_refresh_tasks.ps1 -CoreUrl http://127.0.0.1:8771 -Python '__PYTHON__' -WhatIf
& ./tools/register_model_refresh_tasks.ps1 -Unregister -WhatIf
""".replace("__PYTHON__", sys.executable.replace("'", "''"))
        result = self.powershell(command)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--all --noninteractive --core-url", result.stdout)
        self.assertIn("pythonw.exe", result.stdout)

    def test_wrapper_dry_run_forwards_modes(self):
        result = self.powershell("& ./tools/refresh_model_catalog.ps1 -All -NonInteractive -CoreUrl http://127.0.0.1:8771 -DryRun -Force -Python '" + sys.executable.replace("'", "''") + "'")
        self.assertEqual(result.returncode, 0, result.stderr)
        result_json = json.loads(result.stdout)
        self.assertEqual(result_json["kind"], "all")
        self.assertTrue(result_json["dry_run"])
        self.assertTrue(result_json["force"])

    def test_existing_task_is_never_silently_replaced(self):
        command = r"""
$ErrorActionPreference = 'Stop'
function Get-ScheduledTask { return @{ TaskName = 'ModelPricingRefresh' } }
function Register-ScheduledTask { throw 'Unexpected registration attempt' }
try {
    & ./tools/register_model_refresh_tasks.ps1 -CoreUrl http://127.0.0.1:8771 -Python '__PYTHON__' -Confirm:$false
    throw 'Existing task was not rejected'
} catch {
    if ($_.Exception.Message -notlike 'Task already exists*') { throw }
    Write-Output 'existing-task-rejected'
}
""".replace("__PYTHON__", sys.executable.replace("'", "''"))
        result = self.powershell(command)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("existing-task-rejected", result.stdout)


if __name__ == "__main__":
    unittest.main()
