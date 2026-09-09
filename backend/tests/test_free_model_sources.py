"""Offline contracts for public price evidence; no model or credential access."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import io
import json
import subprocess
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError
from urllib.request import HTTPCookieProcessor, ProxyHandler, Request

from sumika_core import benefit_sources
from sumika_core.integrations import free_model_sources as sources, zhipu_pricing


FIELDS = {"provider_id", "source_url", "observed_at", "models", "complete", "mode", "ttl_seconds"}
AGNES_KEYS = """# Token Plan FAQ
## 3. 文本模型 RPM 限制
| 模型类型 | 用户类型 | 分辨率 / 规格 | 允许发起 RPM | 实际 RPM |
| 文本模型 | `default` | - | 30 | 20 |
## 7. API 密钥类型
| API 密钥类型 | 适用用户 | 限制方式 |
| 免费 / 默认密钥 | 所有用户 | 使用免费 / 默认 RPM 池 |
| Token Plan 密钥 | Token Plan 用户 | 使用 Token Plan RPM 和订阅配额池 |
## 8. 限制池说明
不同类型的密钥使用独立的限制池。
"""


def agnes_group(model="agnes-2.5-flash", current="0", deprecated=False, cache=None):
    dimensions = ([('输入缓存命中', cache)] if cache is not None else []) + [('输入 Token', current), ('输出 Token', current)]
    identity = f'<td rowSpan={{{len(dimensions)}}} style={{{{ verticalAlign: "middle" }}}}><code>{model}</code>'
    identity += ('<br /><strong>已废弃</strong>' if deprecated else '') + '</td>'
    return ''.join(f'<tr>{identity if index == 0 else ""}<td>{label}</td><td><del>$0.15 / M</del></td>'
                   f'<td><strong><code>\\${amount} / M</code></strong></td></tr>'
                   for index, (label, amount) in enumerate(dimensions))


def agnes_document(groups=None):
    groups = groups if groups is not None else (
        agnes_group('agnes-2.0-flash', deprecated=True) + agnes_group() + agnes_group('agnes-2.5-pro', '0.45', cache='0.045'))
    return ('# 模型定价\n## 文本模型\n<table><thead><tr><th>模型</th><th>计费项</th>'
            '<th>刊例价（原价）</th><th>现价（优惠价）</th></tr></thead><tbody>' + groups +
            '</tbody></table>\n## 图片模型\n' + agnes_group('agnes-image-2.5-flash'))


def router_model(model="vendor/exact-model:free", **changes):
    return {"id": model, "architecture": {"input_modalities": ["text"]},
            "pricing": {"prompt": "0", "completion": "0"}, **changes}


def router_catalog(rows=None, **changes):
    rows = [router_model()] if rows is None else rows
    return {"data": rows, "total_count": len(rows), "links": {"next": None}, **changes}


def xfyun_model(model="spark-x2.5-1.7b", **changes):
    pricing = {"showPrice": True}
    for field in ("inTokens", "outTokens", "cacheTokens"):
        pricing[field + "Price"] = 0
        pricing[field + "Unit"] = "元/百万tokens"
    return {"serviceId": model, "displayServiceId": "Spark-X2.5-1.7B", "name": "Display name",
            "categoryTree": [{"key": "modelCategory", "children": [{"name": "文本生成"}]}],
            "price": {"inferencePrice": pricing}, **changes}


def xfyun_catalog(rows=None, **changes):
    rows = [xfyun_model()] if rows is None else rows
    return {"code": 0, "succeed": True, "data": {"rows": rows, "total": len(rows), "page": 1, **changes}}


def silicon_row(model="Vendor/Exact-8B", labels=("免费", "免费", "-")):
    return '<div id="pricing-row-text-1"><div><span>' + model + '</span></div>' + ''.join(
        '<div>' + label + '</div>' for label in labels) + '</div>'


def zhipu_document(model="glm-4.7-flash", output="免费"):
    return ('<table><tr><th>模型</th><th>输入价格</th><th>输出价格</th></tr>'
            f'<tr><td>{model}</td><td>免费</td><td>{output}</td></tr></table>')


def spark_document():
    return ('<table><tr><th style="text-align:center;">语言模型版本</th><th>Ultra</th><th>Max</th><th>Pro</th><th>Lite</th></tr>'
            '<tr><td>模型介绍</td><td>收费</td><td>收费</td><td>收费</td>'
            '<td>轻量级大语言模型<br>具有更高的响应速度,支持<strong>免费使用</strong></td></tr></table>'
            '<table><tr><td>model</td><td>string</td><td>是</td><td>generalv3 lite</td>'
            '<td>指定访问的模型版本: generalv3指向Pro版本; lite指向Lite版本;</td></tr></table>')


class Response(io.BytesIO):
    def __init__(self, body, url, media_type="text/plain", status=200, **headers):
        super().__init__(body.encode() if isinstance(body, str) else body)
        self.url = url
        self.status = status
        self.headers = {"Content-Type": media_type, **headers}

    def geturl(self):
        return self.url


class FreeModelSourcesTests(unittest.TestCase):
    def setUp(self):
        self.network = patch.object(sources.urlrequest.OpenerDirector, "open", side_effect=AssertionError("unexpected network"))
        self.process = patch.object(sources.subprocess, "run", side_effect=AssertionError("unexpected subprocess"))
        self.network.start()
        self.process.start()
        self.addCleanup(self.network.stop)
        self.addCleanup(self.process.stop)

    def catalog(self, provider, body):
        encoded = json.dumps(body).encode() if isinstance(body, dict) else body.encode()
        with patch.object(benefit_sources, "_fetch", return_value=encoded) as fetch:
            result = sources.fetch_free_models(provider)
        fetch.assert_called_once_with(sources._BENEFIT_IDS[provider])
        self.contract(result, provider)
        return result

    def agnes(self, pricing=None, keys=AGNES_KEYS):
        pricing = agnes_document() if pricing is None else pricing
        with patch.object(sources, "_fetch_document", side_effect=[pricing.encode(), keys.encode()]) as fetch:
            result = sources.fetch_free_models("agnes")
        self.assertEqual([call.args[0] for call in fetch.call_args_list], [sources._ENDPOINTS["agnes"], sources._AGNES_KEYS_URL])
        self.contract(result, "agnes")
        return result

    def contract(self, result, provider):
        self.assertEqual(set(result), FIELDS)
        self.assertEqual(result["provider_id"], provider)
        self.assertEqual(result["source_url"], sources._ENDPOINTS[provider])
        observed = datetime.fromisoformat(result["observed_at"])
        self.assertEqual(observed.utcoffset(), timedelta(0))
        self.assertLess(abs((datetime.now(timezone.utc) - observed).total_seconds()), 5)
        self.assertEqual(result["models"], sorted(set(result["models"])))
        self.assertIs(type(result["complete"]), bool)
        self.assertIs(type(result["ttl_seconds"]), int)
        self.assertTrue(0 < result["ttl_seconds"] <= 43200)
        self.assertIn(result["mode"], {"zero-price", "free-key", "allowance"})

    def test_api_endpoints_are_separate_from_public_sources(self):
        self.assertEqual(sources.PROVIDER_ENDPOINTS, {
            "xfyun": "https://maas-api.cn-huabei-1.xf-yun.com/v2", "openrouter": "https://openrouter.ai/api/v1",
            "agnes": "https://apihub.agnes-ai.com/v1", "siliconflow": "https://api.siliconflow.cn/v1",
            "zhipu": "https://open.bigmodel.cn/api/paas/v4", "ollama-cloud": "https://ollama.com/v1",
            "modelscope": "https://api-inference.modelscope.cn/v1", "spark-lite": "https://spark-api-open.xf-yun.com/v1",
            "moark": "https://api.moark.com/v1"})

    def test_unknown_providers_and_profile_ids_never_fetch(self):
        for provider in (None, [], {}, "", "OpenRouter", "agnes-free-candidates", "https://example.org", "bing-ai-free-zh"):
            with self.subTest(provider=provider), self.assertRaises(ValueError):
                sources.fetch_free_models(provider)

    def test_allowance_placeholders_are_offline_and_never_free(self):
        for provider in ("ollama-cloud", "modelscope"):
            result = sources.fetch_free_models(provider)
            self.contract(result, provider)
            self.assertEqual(result["mode"], "allowance")
            self.assertEqual(result["models"], [])
            self.assertFalse(result["complete"])

    def test_export_mutation_does_not_change_network_targets(self):
        with patch.dict(sources.PROVIDER_ENDPOINTS, {"openrouter": "https://example.org/secret"}):
            result = self.catalog("openrouter", router_catalog())
        self.assertEqual(result["source_url"], "https://openrouter.ai/api/v1/models")

    def test_openrouter_requires_exact_free_variant_and_all_zero_dimensions(self):
        rows = [router_model("Vendor/Exact-New:free"), router_model("Vendor/Exact-New"),
                router_model("vendor/image:free", architecture={"input_modalities": ["image"]}),
                router_model("vendor/paid:free", pricing={"prompt": "0", "completion": "0.01"}),
                router_model("vendor/tool:free", pricing={"prompt": "0", "completion": "0", "web_search": "0.01"})]
        result = self.catalog("openrouter", router_catalog(rows))
        self.assertEqual(result["models"], ["Vendor/Exact-New:free"])
        self.assertTrue(result["complete"])

    def test_nonfree_router_sentinels_and_paid_tiers_do_not_break_free_catalog(self):
        rows = [router_model(), router_model("openrouter/auto", pricing={"prompt": "-1", "completion": "-1"}),
                router_model("~vendor/alias-latest", pricing={"prompt": "-1", "completion": "-1"}),
                router_model("vendor/paid", pricing={"prompt": "1", "completion": "2", "overrides": [{"prompt": "3"}]})]
        self.assertTrue(self.catalog("openrouter", router_catalog(rows))["complete"])

    def test_ambiguous_free_prices_are_not_claims_or_complete_evidence(self):
        for price in (None, True, "NaN", "Infinity", "free", "", [], {}, "-1"):
            with self.subTest(price=price):
                row = router_model(pricing={"prompt": "0", "completion": price})
                result = self.catalog("openrouter", router_catalog([row]))
                self.assertEqual(result["models"], [])
                self.assertFalse(result["complete"])

    def test_complete_catalog_can_be_empty_but_partial_absence_is_not_withdrawal(self):
        for body in (router_catalog([]), router_catalog([router_model(pricing={"prompt": "1", "completion": "1"})])):
            result = self.catalog("openrouter", body)
            self.assertEqual(result["models"], [])
            self.assertTrue(result["complete"])
        for change in ({"total_count": 10}, {"links": {"next": "https://example.org/next"}}, {"links": {}}):
            self.assertFalse(self.catalog("openrouter", router_catalog(**change))["complete"])
        self.assertFalse(self.catalog("openrouter", {"data": [router_model()]})["complete"])

    def test_old_catalog_pages_duplicate_json_ids_and_bad_totals_raise(self):
        bad = ['<html>Old pricing: free</html>', '{"data":[],"data":[]}',
               router_catalog([{"id": "vendor/model:free"}]), router_catalog([router_model(), router_model()]),
               router_catalog(total_count=True), router_catalog(total_count=0)]
        for body in bad:
            with self.subTest(body=body), self.assertRaises(ValueError):
                self.catalog("openrouter", body)

    def test_xfyun_uses_service_id_not_display_name_or_case_normalization(self):
        result = self.catalog("xfyun", xfyun_catalog([xfyun_model(), xfyun_model("spark-x2.5-4b")]))
        self.assertEqual(result["models"], ["spark-x2.5-1.7b", "spark-x2.5-4b"])
        self.assertTrue(result["complete"])

    def test_xfyun_nonzero_cache_unknown_units_and_hidden_prices_never_qualify(self):
        for changes in ({"outTokensPrice": 1}, {"cacheTokensPrice": "0.1"}, {"noCacheTokensPrice": 2},
                        {"newFeePrice": 1}, {"inTokensUnit": "元/千tokens"}, {"showPrice": False}, {"inTokensPrice": True}):
            with self.subTest(changes=changes):
                model = xfyun_model()
                model["price"]["inferencePrice"].update(changes)
                self.assertEqual(self.catalog("xfyun", xfyun_catalog([model]))["models"], [])

    def test_xfyun_pagination_and_missing_identity_are_incomplete(self):
        self.assertFalse(self.catalog("xfyun", xfyun_catalog(total=100))["complete"])
        self.assertFalse(self.catalog("xfyun", xfyun_catalog(page=2))["complete"])
        self.assertFalse(self.catalog("xfyun", xfyun_catalog([xfyun_model(), xfyun_model("")]))["complete"])
        self.assertTrue(self.catalog("xfyun", xfyun_catalog([]))["complete"])
        with self.assertRaises(ValueError):
            self.catalog("xfyun", {"code": 1, "succeed": False, "data": {"rows": []}})

    def test_siliconflow_exact_ids_not_size_heuristics_and_incomplete_scope(self):
        html = silicon_row("Vendor/Large-32B") + silicon_row("Vendor/Small-8B", ("0.1", "0.1", "-"))
        result = self.catalog("siliconflow", html)
        self.assertEqual(result["models"], ["Vendor/Large-32B"])
        self.assertFalse(result["complete"])
        self.assertEqual(self.catalog("siliconflow", silicon_row(labels=("0.1", "免费", "-")))["models"], [])

    def test_siliconflow_changed_or_ambiguous_markup_raises(self):
        for body in ('<html>models below 9B are free</html>', silicon_row()[:-6],
                     silicon_row("Vendor/Model<span>Other/Model</span>"), silicon_row() + silicon_row(),
                     silicon_row(labels=("免费",))):
            with self.subTest(body=body), self.assertRaises(ValueError):
                self.catalog("siliconflow", body)

    def test_agnes_current_website_excludes_historical_flash_and_paid_models(self):
        result = self.agnes()
        self.assertEqual(result["models"], ["agnes-2.5-flash"])
        self.assertEqual(result["mode"], "free-key")
        self.assertFalse(result["complete"])

    def test_agnes_list_is_parsed_not_hardcoded_and_cache_is_checked(self):
        result = self.agnes(agnes_document(agnes_group('agnes-3.5-flash') + agnes_group('agnes-3.5-pro', cache='0.01')))
        self.assertEqual(result["models"], ["agnes-3.5-flash"])
        result = self.agnes(agnes_document(agnes_group(current='0.1')))
        self.assertEqual(result["models"], [])
        self.assertFalse(result["complete"])

    def test_agnes_missing_key_scope_cannot_promote_all_keys(self):
        for keys in ('# Agnes AI Model Catalog\nFree / default\nagnes-2.0-flash',
                     AGNES_KEYS.replace('免费 / 默认密钥', 'Token Plan 密钥'),
                     AGNES_KEYS.replace('使用免费 / 默认 RPM 池', '使用 Token Plan RPM 和订阅配额池'),
                     AGNES_KEYS.replace('`default`', '`enterprise`')):
            with self.subTest(keys=keys), self.assertRaises(ValueError):
                self.agnes(keys=keys)

    def test_spark_lite_is_independent_of_maas_and_does_not_claim_account_entitlement(self):
        with patch.object(sources, '_fetch_document', return_value=spark_document().encode()) as fetch:
            result = sources.fetch_free_models('spark-lite')
        self.contract(result, 'spark-lite')
        self.assertEqual(result['models'], ['lite'])
        self.assertEqual(result['mode'], 'zero-price')
        self.assertFalse(result['complete'])
        fetch.assert_called_once_with(sources._ENDPOINTS['spark-lite'])
        self.assertNotIn('general', result['models'])
        self.assertNotIn('2036', json.dumps(result))
        self.assertNotEqual(sources.PROVIDER_ENDPOINTS['spark-lite'], sources.PROVIDER_ENDPOINTS['xfyun'])

    def test_spark_lite_rejects_old_docs_paid_or_trial_and_other_model_free_labels(self):
        document = spark_document()
        for body in (document.replace('免费使用', '免费额度'), document.replace('免费使用', '付费使用'),
                     document.replace('lite指向Lite版本;', 'general指向Lite版本;'),
                     document.replace('<th>Lite</th>', '<th>Pro</th>'),
                     document.replace('<td>轻量级', '<td hidden>轻量级'),
                     '<html>星火免费额度</html>', document + document):
            with patch.object(sources, '_fetch_document', return_value=body.encode()), self.assertRaises(ValueError):
                sources.fetch_free_models('spark-lite')

    def test_agnes_old_pages_nonzero_or_ambiguous_current_prices_are_not_free(self):
        for pricing in ('# Agnes AI Model Catalog\nagnes-2.0-flash Free / default', '<html>Sign in</html>',
                        agnes_document().replace('现价（优惠价）', '历史价格'),
                        agnes_document().replace('\\$0 / M', '免费试用'),
                        agnes_document().replace('rowSpan={2}', 'rowSpan={3}', 1),
                        agnes_document(agnes_group() + agnes_group()),
                        agnes_document().replace('<table>', '<table hidden>')):
            with self.subTest(pricing=pricing), self.assertRaises(ValueError):
                self.agnes(pricing)

    def test_source_failure_is_sanitized_and_never_falls_back_to_another_provider(self):
        with patch.object(sources, "_fetch_document", side_effect=ValueError('private failure detail')), \
                patch.object(benefit_sources, "_fetch", return_value=json.dumps(xfyun_catalog()).encode()) as fetch:
            with self.assertRaisesRegex(ValueError, '^agnes public free-price evidence unavailable or invalid$'):
                sources.fetch_free_models('agnes')
            self.assertEqual(sources.fetch_free_models('xfyun')['models'], ['spark-x2.5-1.7b'])
            fetch.assert_called_once_with('xfyun-public-catalog')

    def test_cross_provider_observations_are_rejected(self):
        for change in ({'provider_id': 'agnes'}, {'url': sources._ENDPOINTS['agnes']}, {'kind': 'lead'}):
            row = {'provider_id': 'openrouter', 'url': sources._ENDPOINTS['openrouter'],
                   'kind': 'free-model', 'model_id': 'vendor/model:free', **change}
            with patch.object(benefit_sources, '_fetch', return_value=json.dumps(router_catalog()).encode()), \
                    patch.dict(benefit_sources._PARSERS, {'openrouter-free-models': lambda *_args: [row]}), \
                    self.assertRaises(ValueError):
                sources.fetch_free_models('openrouter')

    def test_concurrent_catalog_refreshes_keep_source_id_and_results_separate(self):
        payloads = {'xfyun-public-catalog': json.dumps(xfyun_catalog()).encode(),
                    'openrouter-free-models': json.dumps(router_catalog()).encode()}
        with patch.object(benefit_sources, '_fetch', side_effect=payloads.__getitem__):
            with ThreadPoolExecutor(max_workers=2) as executor:
                results = list(executor.map(sources.fetch_free_models, ['xfyun', 'openrouter']))
        self.assertEqual([result['provider_id'] for result in results], ['xfyun', 'openrouter'])
        self.assertEqual([result['models'] for result in results], [['spark-x2.5-1.7b'], ['vendor/exact-model:free']])

    def test_zhipu_static_parser_reused_with_explicit_opener_and_normal_proxy(self):
        response = Response(zhipu_document(), sources._ENDPOINTS['zhipu'], 'text/html')
        opener = Mock()
        opener.open.return_value = response
        with patch.object(sources.urlrequest, 'build_opener', return_value=opener) as build, \
                patch.object(sources, '_render_zhipu') as render:
            result = sources.fetch_free_models('zhipu')
        self.contract(result, 'zhipu')
        self.assertEqual(result['models'], ['glm-4.7-flash'])
        self.assertFalse(result['complete'])
        self.assertIsInstance(build.call_args.args[0], benefit_sources._NoRedirect)
        self.assertFalse(any(isinstance(handler, ProxyHandler) for handler in build.call_args.args))
        render.assert_not_called()

    def test_zhipu_paid_cache_ambiguous_columns_and_duplicate_tiers_never_claim_free(self):
        documents = [zhipu_document(output='1'), zhipu_document(output='试用额度'),
                     zhipu_document().replace('</tr></table>', '<td>0.1</td></tr></table>'),
                     zhipu_document() + zhipu_document(output='1'),
                     zhipu_document().replace('<table>', '<table hidden>')]
        for document in documents:
            rows = zhipu_pricing.parse_pricing_observations(document, observed_at=datetime.now(timezone.utc).isoformat())
            with patch.object(zhipu_pricing, 'fetch_pricing_observations', return_value=rows):
                self.assertEqual(sources.fetch_free_models('zhipu')['models'], [])

    def test_zhipu_render_fallback_only_for_unsupported_static_page(self):
        rows = zhipu_pricing.parse_pricing_observations(zhipu_document(), observed_at=datetime.now(timezone.utc).isoformat())
        with patch.object(zhipu_pricing, 'fetch_pricing_observations', side_effect=zhipu_pricing.PricingNeedsReview(
                'no static exact-model pricing rows; SPA or unsupported markup needs review')), \
                patch.object(sources, '_render_zhipu', return_value=rows) as render:
            self.assertEqual(sources.fetch_free_models('zhipu')['models'], ['glm-4.7-flash'])
            render.assert_called_once_with()
        for message in ('public pricing HTTP request rejected', 'incomplete pricing table'):
            with patch.object(zhipu_pricing, 'fetch_pricing_observations', side_effect=zhipu_pricing.PricingNeedsReview(message)), \
                    patch.object(sources, '_render_zhipu') as render, self.assertRaises(ValueError):
                sources.fetch_free_models('zhipu')
            render.assert_not_called()

    def test_zhipu_rejects_stale_foreign_nonboolean_and_duplicate_observations(self):
        valid = zhipu_pricing.parse_pricing_observations(zhipu_document(), observed_at=datetime.now(timezone.utc).isoformat())[0]
        for changes in ({'provider_id': 'agnes'}, {'source_url': sources._ENDPOINTS['agnes']}, {'free_claim': 'true'},
                        {'model_id': 'glm-4.7-flash extra'}, {'observed_at': '2020-01-01T00:00:00+00:00'}):
            with patch.object(zhipu_pricing, 'fetch_pricing_observations', return_value=[{**valid, **changes}]), self.assertRaises(ValueError):
                sources.fetch_free_models('zhipu')
        for rows in ([], [valid, valid], {}, [None]):
            with patch.object(zhipu_pricing, 'fetch_pricing_observations', return_value=rows), self.assertRaises(ValueError):
                sources.fetch_free_models('zhipu')

    def test_document_transport_is_get_only_cookie_free_bounded_and_proxy_preserving(self):
        response = Response(agnes_document(), sources._ENDPOINTS['agnes'])
        opener = Mock()
        opener.open.return_value = response
        with patch.object(sources.urlrequest, 'build_opener', return_value=opener) as build:
            sources._fetch_document(sources._ENDPOINTS['agnes'])
        self.assertTrue(all(not isinstance(handler, (ProxyHandler, HTTPCookieProcessor)) for handler in build.call_args.args))
        request = opener.open.call_args.args[0]
        self.assertEqual(request.get_method(), 'GET')
        self.assertEqual(request.full_url, sources._ENDPOINTS['agnes'])
        self.assertIsNone(request.data)
        self.assertFalse({'authorization', 'cookie', 'x-api-key'} & {name.lower() for name, _ in request.header_items()})
        self.assertEqual(opener.open.call_args.kwargs['timeout'], 10)

    def test_document_transport_rejects_redirect_auth_html_compression_and_truncation(self):
        for settings in ({'status': 302}, {'status': 401}, {'url': 'https://example.org'},
                         {'media_type': 'text/html'}, {'Content-Encoding': 'gzip'},
                         {'Content-Length': '3000000'}, {'Content-Length': '100'}):
            arguments = {'url': sources._ENDPOINTS['agnes'], **settings}
            opener = Mock()
            opener.open.return_value = Response('body', **arguments)
            with patch.object(sources.urlrequest, 'build_opener', return_value=opener), self.assertRaises(ValueError):
                sources._fetch_document(sources._ENDPOINTS['agnes'])
        for url in ('https://example.org', sources.PROVIDER_ENDPOINTS['agnes'], sources._ENDPOINTS['agnes'] + '?key=x'):
            with self.assertRaises(ValueError):
                sources._fetch_document(url)

    def test_document_transport_network_errors_deadline_and_redirects_fail_closed(self):
        for error in (URLError('private network detail'), TimeoutError(), HTTPError('private-url', 403, 'denied', {}, None)):
            opener = Mock()
            opener.open.side_effect = error
            with patch.object(sources.urlrequest, 'build_opener', return_value=opener), self.assertRaises(ValueError):
                sources._fetch_document(sources._ENDPOINTS['agnes'])
        opener = Mock()
        opener.open.return_value = Response('body', sources._ENDPOINTS['agnes'])
        with patch.object(sources.urlrequest, 'build_opener', return_value=opener), \
                patch.object(sources.time, 'monotonic', side_effect=[0, 30, 30, 30]), self.assertRaises(ValueError):
            sources._fetch_document(sources._ENDPOINTS['agnes'])
        response = Mock()
        with self.assertRaises(ValueError):
            benefit_sources._NoRedirect().redirect_request(Request(sources._ENDPOINTS['agnes']), response, 302, '', {}, 'https://example.org')
        response.close.assert_called_once()

    def test_render_worker_excludes_secret_environment_and_has_timeout(self):
        with patch.dict(sources.os.environ, {'AGNES_API_KEY': 'test-private', 'NODE_OPTIONS': 'untrusted-preload'}), \
                patch.object(sources.shutil, 'which', return_value='node'), \
                patch.object(sources.Path, 'is_file', return_value=True), \
                patch.object(sources.urlrequest, 'getproxies', return_value={'https': 'http://127.0.0.1:8080'}), \
                patch.object(sources.urlrequest, 'proxy_bypass', return_value=False), \
                patch.object(sources.subprocess, 'run', return_value=Mock(returncode=0, stdout='[]')) as run:
            sources._render_zhipu()
        arguments = run.call_args.kwargs
        self.assertNotIn('AGNES_API_KEY', arguments['env'])
        self.assertNotIn('NODE_OPTIONS', arguments['env'])
        self.assertEqual(arguments['timeout'], 45)
        self.assertEqual(json.loads(arguments['input']), {'proxy': {'server': 'http://127.0.0.1:8080'}})
        for error in (subprocess.TimeoutExpired('node', 45), OSError()):
            with patch.object(sources.shutil, 'which', return_value='node'), \
                    patch.object(sources.Path, 'is_file', return_value=True), \
                    patch.object(sources.subprocess, 'run', side_effect=error), self.assertRaises(ValueError):
                sources._render_zhipu()


if __name__ == '__main__':
    unittest.main()
