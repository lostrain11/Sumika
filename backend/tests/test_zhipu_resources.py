from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock

from sumika_core.integrations.zhipu_resources import (
    DOM_EXPRESSION, FIELDS, HEADERS, MAX_RESPONSE_BYTES, PAGE_CONTEXT_JS, RESOURCE_TABLE_JS,
    ResourceNeedsReview, ZhipuResourceReader,
)
from sumika_core.model_refresh import parse_resource_observation


SOURCE_URL = "https://open.bigmodel.cn/finance/resourcepack"
ROW = ["GLM 固定夹具资源包", "模型资源包", "生效中", "适用于glm-4.7模型的推理", "1,234 tokens", "1,200 tokens",
       "2026-01-01 09:00:00", "2026-01-01 09:00:00", "2099-11-20 20:12:08"]


def observation(**changes):
    return {"ok": True, "schema": "zhipu-resource-pack-page-observation/v1", "source_url": SOURCE_URL,
            "observed_at": "2000-01-01T00:00:00Z", "source": "authenticated-page-dom",
            "packs": [dict(zip(FIELDS, ROW))], **changes}


def envelope(value):
    return {"ok": True, "value": json.dumps(value, ensure_ascii=False)}


class ResourceReaderTests(unittest.TestCase):
    def reader(self, runner=None, **kwargs):
        return ZhipuResourceReader(runner or Mock(return_value=envelope(observation())), session="fixture-session", tab_id=12,
                                   provider_profile_id="fixture-official", **kwargs)

    def test_dom_tool_argv_is_readonly_explicit_and_injection_free(self):
        runner = Mock(return_value=envelope(observation()))
        self.reader(runner)()
        runner.assert_called_once_with(("evaluate", "--session", "fixture-session", "--tab-id", "12", DOM_EXPRESSION, "--json"), timeout=15)

    def test_default_projection_parses_but_does_not_claim_account_or_timezone(self):
        result = self.reader()()
        pack = parse_resource_observation(result)[0]
        self.assertEqual(pack.remaining, 1200)
        self.assertEqual(pack.provider_profile_id, "fixture-official")
        self.assertEqual(pack.applies_to, ("glm-4.7",))
        self.assertIsNone(pack.expires_at)
        self.assertFalse(pack.available)
        self.assertIsNone(result["account_scope_id"])
        self.assertFalse(result["account_binding_verified"])
        self.assertFalse(result["automatic_routing_authorized"])
        self.assertEqual(result["displayed_timezone"], "unspecified-by-page")
        self.assertEqual(result["billing_reconciliation"], "unverified")
        self.assertFalse(result["complete"])
        self.assertEqual(result["scope"], "current-rendered-table-only")
        self.assertLess(abs((datetime.now(timezone.utc) - datetime.fromisoformat(result["observed_at"])).total_seconds()), 5)

    def test_host_injected_binding_permission_and_timezone_are_the_only_authority(self):
        result = self.reader(account_scope_id="fixture-account", account_binding_verified=True,
                             automatic_routing_authorized=True, displayed_timezone="+08:00")()
        pack = parse_resource_observation(result)[0]
        self.assertTrue(pack.available)
        self.assertEqual(pack.expires_at, "2099-11-20T12:12:08+00:00")
        self.assertEqual(pack.account_scope_id, "fixture-account")

    def test_page_cannot_self_authorize_or_supply_paths_cookies_and_balances(self):
        raw = observation(account_binding_verified=True, automatic_routing_authorized=True, account_scope_id="page-claims-account",
                          provider_profile_id="page-claims-profile", displayed_timezone="+08:00", complete=True,
                          observed_at="2099-01-01T00:00:00Z", cookie="not-a-real-cookie", screenshot_path="C:\\private\\image.png")
        raw["packs"][0].update(remaining=9999999, unit="requests", expires_at="2099-12-31T00:00:00Z", pack_id="page-pick", applies_to=["glm-other"])
        result = self.reader(Mock(return_value=envelope(raw)))()
        self.assertFalse(result["account_binding_verified"])
        self.assertFalse(result["automatic_routing_authorized"])
        self.assertEqual(result["displayed_timezone"], "unspecified-by-page")
        self.assertEqual(result["provider_profile_id"], "fixture-official")
        self.assertNotIn("cookie", result)
        self.assertNotIn("screenshot_path", result)
        self.assertEqual(set(result["packs"][0]), set(FIELDS))
        self.assertEqual(parse_resource_observation(result)[0].remaining, 1200)

    def test_quantity_zero_is_preserved_and_unknown_is_never_filled(self):
        for value in ("0 tokens", "25 次"):
            raw = observation()
            raw["packs"][0]["available_balance"] = value
            pack = parse_resource_observation(self.reader(Mock(return_value=envelope(raw)))())[0]
            self.assertEqual(pack.remaining, 0 if value == "0 tokens" else 25)
        for value in ("", "unknown", "1.2万 tokens", "1,20 tokens", "12O0 tokens", "1200", "-1 tokens"):
            raw = observation()
            raw["packs"][0]["available_balance"] = value
            with self.subTest(value=value), self.assertRaises(ResourceNeedsReview):
                self.reader(Mock(return_value=envelope(raw)))()

    def test_empty_duplicate_and_excessive_rows_reject_without_zero_balance(self):
        for packs in ([], [dict(zip(FIELDS, ROW))] * 2, [dict(zip(FIELDS, ROW))] * 101):
            with self.subTest(count=len(packs)), self.assertRaises(ResourceNeedsReview):
                self.reader(Mock(return_value=envelope(observation(packs=packs))))()

    def test_missing_cells_and_secret_or_path_cells_reject(self):
        for value in (None, True, "x" * 2001, "sk-" + "x" * 30, "C:\\private\\balance.txt", "/tmp/private", "../private", "bad\x00cell"):
            raw = observation()
            raw["packs"][0]["name"] = value
            with self.subTest(value=value), self.assertRaises(ResourceNeedsReview):
                self.reader(Mock(return_value=envelope(raw)))()

    def test_wrong_origin_path_and_schema_do_not_use_ocr(self):
        for changes in ({"source_url": "http://open.bigmodel.cn/finance/resourcepack"},
                        {"source_url": [SOURCE_URL]},
                        {"source_url": SOURCE_URL + "?access_token=not-a-secret"},
                        {"source_url": "https://open.bigmodel.cn.evil.invalid/finance/resourcepack"},
                        {"source_url": "https://open.bigmodel.cn/login"}, {"schema": "wrong-schema"}):
            ocr = Mock()
            with self.subTest(changes=changes), self.assertRaises(ResourceNeedsReview):
                self.reader(Mock(return_value=envelope(observation(**changes))), ocr_reader=ocr)()
            ocr.assert_not_called()

    def test_logged_out_or_wrong_page_never_invokes_fallback(self):
        for reason in ("wrong-page", "select-my-resource-packs-after-login", "unknown-failure", ["wrong-page"]):
            ocr = Mock()
            runner = Mock(return_value=envelope({"ok": False, "reason": reason}))
            with self.subTest(reason=reason), self.assertRaises(ResourceNeedsReview):
                self.reader(runner, ocr_reader=ocr)()
            runner.assert_called_once()
            ocr.assert_not_called()

    def test_tool_transport_formats_are_explicitly_supported(self):
        encoded = json.dumps(envelope(observation()), ensure_ascii=False)
        for value in (encoded, encoded.encode(), subprocess.CompletedProcess(["fixture"], 0, stdout=encoded)):
            with self.subTest(kind=type(value).__name__):
                self.assertEqual(self.reader(Mock(return_value=value))()["packs"][0]["available_balance"], "1,200 tokens")

    def test_tool_failure_is_bounded_and_does_not_echo_sensitive_output(self):
        for value in ({"ok": False, "error": "private content"}, "not json", b"\xff", "x" * (MAX_RESPONSE_BYTES + 1),
                      {"ok": True, "value": "not json"}, subprocess.CompletedProcess(["fixture"], 1, stdout="private", stderr="secret")):
            with self.subTest(kind=type(value).__name__), self.assertRaises(ResourceNeedsReview) as raised:
                self.reader(Mock(return_value=value))()
            self.assertNotIn("private", str(raised.exception))
            self.assertNotIn("secret", str(raised.exception))
        with self.assertRaises(ResourceNeedsReview):
            self.reader(Mock(side_effect=TimeoutError("private tool error")))()

    def test_ocr_fallback_has_before_and_after_page_checks_and_literal_grid(self):
        context = envelope({"ok": True, "source_url": SOURCE_URL})
        runner = Mock(side_effect=[envelope({"ok": False, "reason": "table-schema-changed"}), context, context])
        ocr = Mock(return_value={"headers": list(HEADERS), "rows": [ROW.copy()], "account_binding_verified": True, "displayed_timezone": "+08:00"})
        result = self.reader(runner, ocr_reader=ocr)()
        self.assertEqual(result["source"], "local-ocr")
        self.assertFalse(result["account_binding_verified"])
        self.assertEqual(result["displayed_timezone"], "unspecified-by-page")
        self.assertEqual(parse_resource_observation(result)[0].remaining, 1200)
        ocr.assert_called_once_with(session="fixture-session", tab_id=12)
        self.assertEqual([call.args[0][-2] for call in runner.call_args_list], [DOM_EXPRESSION, PAGE_CONTEXT_JS, PAGE_CONTEXT_JS])

    def test_dom_transport_failure_can_use_explicit_local_ocr_after_context_check(self):
        context = envelope({"ok": True, "source_url": SOURCE_URL})
        runner = Mock(side_effect=[TimeoutError(), context, context])
        ocr = Mock(return_value={"headers": list(HEADERS), "rows": [ROW.copy()]})
        self.assertEqual(self.reader(runner, ocr_reader=ocr)()["source"], "local-ocr")
        self.assertEqual(runner.call_count, 3)

    def test_ocr_page_change_or_failed_context_never_produces_observation(self):
        first = envelope({"ok": False, "reason": "incomplete-row"})
        for context in (envelope({"ok": False, "reason": "wrong-page"}), envelope({"ok": True, "source_url": "https://evil.invalid"})):
            ocr = Mock()
            with self.assertRaises(ResourceNeedsReview):
                self.reader(Mock(side_effect=[first, context]), ocr_reader=ocr)()
            ocr.assert_not_called()
        contexts = [envelope({"ok": True, "source_url": SOURCE_URL}),
                    envelope({"ok": True, "source_url": "https://open.bigmodel.cn/finance-center/resource-package/package-mgmt"})]
        with self.assertRaisesRegex(ResourceNeedsReview, "page changed"):
            self.reader(Mock(side_effect=[first, *contexts]), ocr_reader=Mock(return_value={"headers": list(HEADERS), "rows": [ROW.copy()]}))()

    def test_ocr_unknown_cells_missing_headers_and_guessed_balances_reject(self):
        bad_balance = ROW.copy()
        bad_balance[5] = "about 1200 tokens"
        for grid in ({"text": "looks like 1200"}, {"headers": list(HEADERS), "rows": [ROW[:-1]]},
                     {"headers": list(reversed(HEADERS)), "rows": [ROW]}, {"headers": list(HEADERS), "rows": [bad_balance]}):
            runner = Mock(side_effect=[envelope({"ok": False, "reason": "incomplete-row"}),
                                      envelope({"ok": True, "source_url": SOURCE_URL}), envelope({"ok": True, "source_url": SOURCE_URL})])
            with self.subTest(grid=grid), self.assertRaises(ResourceNeedsReview):
                self.reader(runner, ocr_reader=Mock(return_value=grid))()

    def test_invalid_host_options_fail_before_any_tools(self):
        runner = Mock()
        for changes in ({"session": "--tab-id"}, {"session": "session; command"}, {"tab_id": True}, {"tab_id": -1},
                        {"tab_id": "12"}, {"timeout": float("nan")}, {"timeout": 0}, {"timeout": 61},
                        {"account_binding_verified": True}, {"account_binding_verified": 1},
                        {"automatic_routing_authorized": "true"}, {"displayed_timezone": "+09:00"},
                        {"account_scope_id": "C:\\private"}, {"ocr_reader": "remote-model"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                ZhipuResourceReader(runner, **{"session": "fixture", "tab_id": 12, "provider_profile_id": "official", **changes})
        runner.assert_not_called()


_NODE_DOM_FIXTURE = r"""
const fs = require('node:fs');
const fixture = JSON.parse(fs.readFileSync(0, 'utf8'));
const table = {};
const otherTable = {};
const cells = values => values.map(textContent => ({textContent}));
globalThis.location = new URL(fixture.url);
globalThis.document = {
    querySelector(selector) {
        if (selector !== '#tab-my') throw new Error('unexpected DOM query');
        return fixture.noTab ? null : {getAttribute: name => {
            if (name !== 'aria-selected') throw new Error('unexpected attribute');
            return fixture.selected;
        }};
    },
    querySelectorAll(selector) {
        switch (selector) {
            case '.el-table__header-wrapper':
                return Array.from({length: fixture.tableCount}, () => ({closest: () => fixture.noTable ? null : table}));
            case '.el-table__body-wrapper':
                return [{closest: () => fixture.splitTable ? otherTable : table}];
            case '.el-table__header-wrapper th': return cells(fixture.headers);
            case '.el-table__body-wrapper tbody tr':
                return fixture.rows.map(row => ({querySelectorAll: query => {
                    if (query !== 'td') throw new Error('unexpected row query');
                    return cells(row);
                }}));
            case '.el-pagination': return [{innerText: '共 2 页'}];
            default: throw new Error('unexpected DOM query');
        }
    }
};
Object.defineProperty(document, 'cookie', {get() {throw new Error('cookie access forbidden');}});
globalThis.fetch = () => {throw new Error('network forbidden');};
globalThis.open = () => {throw new Error('navigation forbidden');};
const result = eval(fixture.expression);
process.stdout.write(result);
"""


class ResourceScriptTests(unittest.TestCase):
    def test_fixed_resource_js_matches_existing_powershell_tool_exactly(self):
        script = (Path(__file__).resolve().parents[2] / "tools" / "read_zhipu_resource_packs.ps1").read_text(encoding="utf-8-sig")
        fixed = script.split("$expression = @'\n", 1)[1].split("\n'@", 1)[0]
        self.assertEqual(RESOURCE_TABLE_JS, fixed)

    def evaluate(self, **changes):
        node = shutil.which("node")
        if node is None:
            self.skipTest("Node.js is required for the isolated DOM fixture")
        fixture = {"expression": DOM_EXPRESSION, "url": SOURCE_URL, "selected": "true", "tableCount": 1,
                   "headers": list(HEADERS), "rows": [ROW.copy()], **changes}
        result = subprocess.run([node, "-e", _NODE_DOM_FIXTURE], input=json.dumps(fixture), text=True,
                                encoding="utf-8", capture_output=True, timeout=5, check=True)
        return json.loads(result.stdout)

    def test_real_js_reads_expected_table_without_cookie_or_network_access(self):
        result = self.evaluate()
        self.assertTrue(result["ok"])
        self.assertEqual(result["packs"], [dict(zip(FIELDS, ROW))])
        self.assertFalse(result["account_binding_verified"])
        self.assertFalse(result["automatic_routing_authorized"])
        self.assertEqual(result["scope"], "current-rendered-table-only")

    def test_real_js_supports_second_exact_official_path(self):
        result = self.evaluate(url="https://open.bigmodel.cn/finance-center/resource-package/package-mgmt")
        self.assertTrue(result["ok"])

    def test_real_js_rejects_other_origins_ports_protocols_and_paths(self):
        for url in ("http://open.bigmodel.cn/finance/resourcepack", "https://open.bigmodel.cn:444/finance/resourcepack",
                    "https://open.bigmodel.cn.evil.invalid/finance/resourcepack", "https://evil.invalid/finance/resourcepack",
                    "https://open.bigmodel.cn/login", SOURCE_URL + "/"):
            with self.subTest(url=url):
                self.assertEqual(self.evaluate(url=url), {"ok": False, "reason": "wrong-page"})

    def test_real_js_requires_selected_my_packs_tab(self):
        for changes in ({"selected": "false"}, {"noTab": True}, {"selected": None}):
            with self.subTest(changes=changes):
                self.assertEqual(self.evaluate(**changes)["reason"], "select-my-resource-packs-after-login")

    def test_real_js_requires_headers_and_rows_in_one_unambiguous_table(self):
        for changes in ({"tableCount": 2}, {"splitTable": True}, {"noTable": True}, {"tableCount": 0}):
            with self.subTest(changes=changes):
                self.assertEqual(self.evaluate(**changes)["reason"], "ambiguous-table")

    def test_real_js_rejects_schema_drift_and_extra_columns(self):
        for changes in ({"headers": list(reversed(HEADERS))}, {"headers": list(HEADERS) + ["extra"]},
                        {"rows": [ROW[:-1]]}, {"rows": [ROW + ["extra"]]}):
            with self.subTest(changes=changes):
                self.assertEqual(self.evaluate(**changes)["reason"], "table-schema-changed")

    def test_real_js_rejects_empty_unbounded_and_incomplete_rows(self):
        for rows, reason in (([], "empty-or-unbounded-table"), ([ROW] * 101, "empty-or-unbounded-table"),
                             ([ROW[:-1] + [""]], "incomplete-row"), ([ROW[:-1] + ["x" * 2001]], "incomplete-row")):
            with self.subTest(reason=reason):
                self.assertEqual(self.evaluate(rows=rows)["reason"], reason)


if __name__ == "__main__":
    unittest.main()
