"""Read-only public text-model price evidence; never account or send authority.

Only complete zero-price catalogs can withdraw a missing model's price claim.
HTML pricing observations and Agnes free/default-key evidence are incomplete:
absence says nothing about retirement. Free-key evidence requires independently
verified key type; allowance placeholders never establish permission to send.
No credentials, model requests, persistence, login, or automatic retries exist.

Agnes website pricing supersedes the July GitHub catalog: on 2026-09-08 it
explicitly marked 2.0 Flash historical/deprecated and only 2.5 Flash free.
The public dictionary is display metadata, not mutable network configuration.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from http.client import HTTPException
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
from urllib import error as urlerror, request as urlrequest

from .. import benefit_sources
from . import zhipu_pricing


_ENDPOINTS = {
    "xfyun": "https://maas.xfyun.cn/api/v1/gpt-finetune/model/base/list-v2?page=1&size=9999",
    "openrouter": "https://openrouter.ai/api/v1/models",
    "agnes": "https://agnes-ai.com/zh-Hans/docs/pricing.md",
    "siliconflow": "https://www.siliconflow.cn/pricing",
    "zhipu": "https://bigmodel.cn/pricing",
    "ollama-cloud": "https://ollama.com/pricing",
    "modelscope": "https://modelscope.cn/docs/model-service/API-Inference/intro",
    "spark-lite": "https://www.xfyun.cn/doc/spark/HTTP%E8%B0%83%E7%94%A8%E6%96%87%E6%A1%A3.html",
    "moark": "https://moark.com/api/pay/services?type=serverless&status=1&size=1000",
}
PROVIDER_ENDPOINTS: dict[str, str] = {
    "xfyun": "https://maas-api.cn-huabei-1.xf-yun.com/v2",
    "openrouter": "https://openrouter.ai/api/v1",
    "agnes": "https://apihub.agnes-ai.com/v1",
    "siliconflow": "https://api.siliconflow.cn/v1",
    "zhipu": "https://open.bigmodel.cn/api/paas/v4",
    "ollama-cloud": "https://ollama.com/v1",
    "modelscope": "https://api-inference.modelscope.cn/v1",
    "spark-lite": "https://spark-api-open.xf-yun.com/v1",
    "moark": "https://api.moark.com/v1",
}
_BENEFIT_IDS = {"xfyun": "xfyun-public-catalog", "openrouter": "openrouter-free-models",
                "siliconflow": "siliconflow-public-pricing"}
_AGNES_KEYS_URL = "https://agnes-ai.com/zh-Hans/docs/tokenplan.md"
_TTL = 21600
_TIMEOUT = 10
_DEADLINE = 20
_MAX_BYTES = 2_000_000
_MAX_MODELS = 512


def _fetch_document(url: str) -> bytes:
    if url not in {_ENDPOINTS["agnes"], _AGNES_KEYS_URL, _ENDPOINTS["spark-lite"]}:
        raise ValueError("public document URL is not allowed")
    request = urlrequest.Request(url, method="GET", headers={
        "Accept": "text/plain, text/markdown, text/html", "Accept-Encoding": "identity",
        "User-Agent": "Sumika-Free-Price-Evidence/1.0",
    })
    started = time.monotonic()
    try:
        with urlrequest.build_opener(benefit_sources._NoRedirect()).open(request, timeout=_TIMEOUT) as response:
            if response.status != 200 or response.geturl() != url:
                raise ValueError("unexpected public document response")
            media_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
            accepted = {"text/html"} if url == _ENDPOINTS["spark-lite"] else {"text/plain", "text/markdown"}
            if media_type not in accepted:
                raise ValueError("unexpected public document content type")
            if response.headers.get("Content-Encoding", "identity").lower() != "identity":
                raise ValueError("encoded public document rejected")
            body = zhipu_pricing.read_bounded(response, _MAX_BYTES, _DEADLINE - (time.monotonic() - started))
            if time.monotonic() - started >= _DEADLINE:
                raise ValueError("public document deadline exceeded")
            return body
    except urlerror.HTTPError as error:
        error.close()
        raise ValueError("public document HTTP request rejected") from None
    except (OSError, ValueError, HTTPException):
        raise ValueError("public document unavailable or rejected") from None


def _number(value) -> bool:
    if type(value) not in (str, int, Decimal) or len(str(value)) > 64:
        return False
    try:
        number = Decimal(value)
        return number.is_finite() and number >= 0
    except InvalidOperation:
        return False


def _catalog_complete(provider: str, body: bytes) -> bool:
    if provider == "siliconflow":
        parser = benefit_sources._PricingRows()
        parser.feed(body.decode("utf-8-sig"))
        parser.close()
        if not parser.rows or parser.stack or not any(
                len([cell for cell in row["children"] if isinstance(cell, dict)]) == 4 for row in parser.rows):
            raise ValueError("unsupported text pricing rows")
        return False
    payload = benefit_sources._json(body)
    container = payload if provider == "openrouter" else payload["data"]
    rows = container["data" if provider == "openrouter" else "rows"]
    id_key = "id" if provider == "openrouter" else "serviceId"
    covered = all(benefit_sources._model_id(row.get(id_key)) or (
        provider == "openrouter" and isinstance(row.get(id_key), str)
        and row[id_key].startswith("~") and not row[id_key].endswith(":free")
        and benefit_sources._model_id(row[id_key][1:])) for row in rows)
    for row in rows:
        if provider == "openrouter":
            architecture = row.get("architecture")
            pricing = row.get("pricing")
            if (not isinstance(architecture, dict) or not isinstance(architecture.get("input_modalities"), list)
                    or not isinstance(pricing, dict) or not {"prompt", "completion"} <= pricing.keys()):
                raise ValueError("incomplete public model pricing schema")
            if row.get("id", "").endswith(":free") and not all(_number(value) for value in pricing.values()):
                covered = False
        else:
            if not isinstance(row.get("categoryTree"), list):
                raise ValueError("missing public model category")
            if benefit_sources._has_tag(row, "modelCategory", "文本生成"):
                price = row.get("price")
                pricing = price.get("inferencePrice") if isinstance(price, dict) else None
                if not isinstance(pricing, dict) or type(pricing.get("showPrice")) is not bool:
                    raise ValueError("incomplete public text pricing schema")
                if pricing["showPrice"] and not all(
                        _number(pricing.get(field + "Price")) and pricing.get(field + "Unit") == "元/百万tokens"
                        for field in ("inTokens", "outTokens", "cacheTokens")):
                    covered = False
    total = container.get("total_count" if provider == "openrouter" else "total")
    if total is not None and (type(total) is not int or total < len(rows)):
        raise ValueError("invalid catalog total")
    if provider == "openrouter":
        links = payload.get("links")
        terminal = isinstance(links, dict) and "next" in links and links["next"] is None
    else:
        terminal = type(container.get("page")) is int and container["page"] == 1
    return covered and terminal and type(total) is int and total == len(rows)


def _collect_catalog(provider: str) -> tuple[list[str], bool]:
    source_id = _BENEFIT_IDS[provider]
    if benefit_sources._SOURCES[source_id][2] != _ENDPOINTS[provider]:
        raise ValueError("public source identity changed")
    body = benefit_sources._fetch(source_id)
    rows = benefit_sources._PARSERS[source_id](body, source_id)
    if not isinstance(rows, list) or len(rows) > benefit_sources._MAX_ROWS:
        raise ValueError("invalid public catalog result")
    models = []
    for row in rows:
        if (not isinstance(row, dict) or row.get("provider_id") != provider
                or row.get("url") != _ENDPOINTS[provider] or row.get("kind") != "free-model"
                or not benefit_sources._model_id(row.get("model_id"))):
            raise ValueError("public catalog source mismatch")
        models.append(row["model_id"])
    if len(set(models)) != len(models):
        raise ValueError("duplicate public model identity")
    return sorted(models), _catalog_complete(provider, body)


def _section(document: str, heading: str) -> str:
    matches = list(re.finditer(r"(?m)^## " + re.escape(heading) + r"\s*$", document))
    if len(matches) != 1:
        raise ValueError("required official document section missing or duplicated")
    remainder = document[matches[0].end():]
    return re.split(r"(?m)^## ", remainder, maxsplit=1)[0]


class _AgnesTable(zhipu_pricing._Tables):
    def __init__(self):
        super().__init__()
        self.spans = {}

    def handle_starttag(self, tag, attrs):
        span = dict(attrs).get("rowspan")
        if span is not None:
            if tag != "td" or self.row != [] or span not in {"{2}", "{3}", "2", "3"}:
                raise ValueError("ambiguous Agnes price grouping")
            self.spans[self.row_count - 1] = int(span.strip("{}"))
            attrs = [(name, value) for name, value in attrs if name != "rowspan"]
        super().handle_starttag(tag, attrs)


def _agnes_models(pricing_body: bytes, keys_body: bytes) -> list[str]:
    pricing = pricing_body.decode("utf-8-sig")
    keys = keys_body.decode("utf-8-sig")
    if not re.search(r"(?m)^# 模型定价\s*$", pricing) or not re.search(r"(?m)^# Token Plan FAQ\s*$", keys):
        raise ValueError("current Agnes website documentation required")
    key_section = _section(keys, "7. API 密钥类型")
    key_rows = [[cell.strip() for cell in line.strip().strip("|").split("|")]
                for line in key_section.splitlines() if line.strip().startswith("|")]
    if key_rows.count(["免费 / 默认密钥", "所有用户", "使用免费 / 默认 RPM 池"]) != 1:
        raise ValueError("Agnes free/default key scope not established")
    text_limits = _section(keys, "3. 文本模型 RPM 限制")
    if len(re.findall(r"(?m)^\|\s*文本模型\s*\|\s*`default`\s*\|\s*-\s*\|\s*[1-9][0-9]*\s*\|\s*[1-9][0-9]*\s*\|\s*$", text_limits)) != 1:
        raise ValueError("Agnes default text access not established")
    section = _section(pricing, "文本模型")
    tables = re.findall(r"<table>.*?</table>", section, re.S)
    if len(tables) != 1:
        raise ValueError("exact Agnes text price table required")
    parser = _AgnesTable()
    parser.feed(tables[0].replace(' style={{ verticalAlign: "middle" }}', ""))
    parser.close()
    if parser.table is not None or len(parser.tables) != 1 or parser.tables[0]["ambiguous"]:
        raise ValueError("ambiguous Agnes pricing markup")
    rows = parser.tables[0]["rows"]
    if not rows or rows[0] != ["模型", "计费项", "刊例价（原价）", "现价（优惠价）"]:
        raise ValueError("Agnes current price columns changed")
    models = []
    seen = set()
    index = 1
    while index < len(rows):
        cells = rows[index]
        span = parser.spans.get(index)
        if len(cells) != 4 or span not in {2, 3} or index + span > len(rows):
            raise ValueError("incomplete Agnes price dimensions")
        identity = re.fullmatch(r"(agnes-[0-9]+(?:[.-][a-z0-9]+)*)( 已废弃)?", cells[0])
        if not identity or identity[1] in seen:
            raise ValueError("ambiguous Agnes model identity")
        seen.add(identity[1])
        dimensions = [cells[1:], *rows[index + 1:index + span]]
        expected = {"输入 Token", "输出 Token"} | ({"输入缓存命中"} if span == 3 else set())
        if any(len(row) != 3 for row in dimensions) or {row[0] for row in dimensions} != expected:
            raise ValueError("ambiguous Agnes price dimensions")
        current = []
        for dimension in dimensions:
            amount = re.fullmatch(r"\\?\$(\d+(?:\.\d+)?) / M", dimension[2])
            if not amount:
                raise ValueError("ambiguous Agnes current price")
            current.append(Decimal(amount[1]))
        if not identity[2] and all(amount == 0 for amount in current):
            models.append(identity[1])
        index += span
    if not seen:
        raise ValueError("missing Agnes model pricing rows")
    return sorted(models)


def _spark_lite_models(body: bytes) -> list[str]:
    """Public HTTP Lite pricing only; no APIPassword, entitlement or response aliases."""
    parser = zhipu_pricing._Tables()
    parser.feed(body.decode("utf-8-sig").replace(' style="text-align:center;"', ""))
    parser.close()
    if parser.table is not None:
        raise ValueError("incomplete Spark HTTP documentation")
    descriptions = []
    mappings = []
    for table in parser.tables:
        rows = table["rows"]
        if table["ambiguous"] or not rows:
            continue
        if rows[0] == ["语言模型版本", "Ultra", "Max", "Pro", "Lite"]:
            descriptions.extend(row[4] for row in rows[1:] if len(row) == 5 and row[0] == "模型介绍")
        mappings.extend(row for row in rows if len(row) == 5 and row[0] == "model"
                        and "lite" in row[3].split() and "lite指向Lite版本;" in row[4])
    if len(descriptions) != 1 or len(mappings) != 1:
        raise ValueError("exact Spark HTTP Lite model evidence missing")
    if descriptions[0] != "轻量级大语言模型 具有更高的响应速度,支持免费使用":
        raise ValueError("Spark HTTP Lite free pricing not established")
    return ["lite"]


_RENDER_SCRIPT = r"""
const { createRequire } = await import('node:module');
const { pathToFileURL } = await import('node:url');
const { resolve } = await import('node:path');
const require = createRequire(resolve('frontend/package.json'));
const { chromium, request: apiRequest } = require('@playwright/test');
const { collectPricingRows } = await import(pathToFileURL(resolve('tools/zhipu-pricing-dom.mjs')));
let input = '';
for await (const chunk of process.stdin) input += chunk;
const { proxy } = JSON.parse(input);
const target = 'https://bigmodel.cn/pricing';
let browser;
let requestCount = 0;
let byteCount = 0;
let rejected = false;
const deadline = Date.now() + 35000;
try {
  browser = await chromium.launch({ headless: true, timeout: 10000 });
  const context = await browser.newContext({ permissions: [], serviceWorkers: 'block' });
  await context.routeWebSocket('**/*', socket => socket.close());
  await context.route('**/*', async route => {
    const request = route.request();
    const url = request.url();
    const allowed = url === target || /^https:\/\/static\.bigmodel\.cn\/wd-paas-front\/(?:js|css)\/[a-zA-Z0-9_.~-]+\.(?:js|css)$/.test(url);
    if (!allowed || request.method() !== 'GET' || request.redirectedFrom()) return route.abort();
    if (++requestCount > 40 || Date.now() >= deadline) { rejected = true; return route.abort(); }
    const client = await apiRequest.newContext({ ...(proxy ? { proxy } : {}), timeout: 10000 });
    try {
      const response = await client.get(url, { maxRedirects: 0, maxRetries: 0, headers: { 'Accept-Encoding': 'identity' } });
      if (response.status() !== 200) throw new Error('public asset rejected');
      const body = await response.body();
      byteCount += body.length;
      if (body.length > 8000000 || byteCount > 24000000 || Date.now() >= deadline) throw new Error('public asset limit');
      await route.fulfill({ status: 200, body, contentType: url === target ? 'text/html' : url.endsWith('.css') ? 'text/css' : 'application/javascript' });
    } catch { rejected = true; await route.abort(); }
    finally { await client.dispose(); }
  });
  const page = await context.newPage();
  await page.goto(target, { waitUntil: 'domcontentloaded', timeout: 20000 });
  await page.waitForSelector('.el-table__body-wrapper .name-box', { timeout: 5000 });
  const rows = await page.evaluate(collectPricingRows);
  if (rejected || !rows.length || rows.length > 512) throw new Error('invalid public render');
  const observedAt = new Date().toISOString();
  process.stdout.write(JSON.stringify(rows.map(row => ({ ...row, provider_id: 'zhipu-official', source_url: target, observed_at: observedAt }))));
} catch { process.exitCode = 2; }
finally { await browser?.close(); }
"""


def _render_zhipu() -> list[dict]:
    """Reuse the exact DOM parser in a fresh, GET-only, restricted browser."""
    executable = shutil.which("node")
    root = Path(__file__).resolve().parents[4]
    if not executable or not (root / "tools/zhipu-pricing-dom.mjs").is_file():
        raise ValueError("public pricing DOM reader is not installed")
    environment = {name: os.environ[name] for name in (
        "PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "LOCALAPPDATA", "USERPROFILE", "HOME",
        "PLAYWRIGHT_BROWSERS_PATH") if name in os.environ}
    proxies = urlrequest.getproxies()
    proxy_url = None if urlrequest.proxy_bypass("bigmodel.cn") else proxies.get("https")
    proxy = {"server": proxy_url} if proxy_url else None
    try:
        result = subprocess.run([executable, "--input-type=module", "-e", _RENDER_SCRIPT],
                                input=json.dumps({"proxy": proxy}), capture_output=True, text=True,
                                encoding="utf-8", timeout=45, env=environment, cwd=root,
                                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        if result.returncode or len(result.stdout) > _MAX_BYTES:
            raise ValueError("public pricing DOM reader failed")
        return benefit_sources._json(result.stdout)
    except (OSError, ValueError, subprocess.SubprocessError):
        raise ValueError("public pricing DOM reader unavailable or rejected") from None


def _zhipu_models() -> list[str]:
    try:
        rows = zhipu_pricing.fetch_pricing_observations(
            _ENDPOINTS["zhipu"], opener=urlrequest.build_opener(benefit_sources._NoRedirect()))
    except zhipu_pricing.PricingNeedsReview as error:
        if "no static exact-model pricing rows" not in str(error):
            raise
        rows = _render_zhipu()
    if not isinstance(rows, list) or not 1 <= len(rows) <= _MAX_MODELS:
        raise ValueError("missing or unbounded Zhipu price observations")
    models = []
    seen = set()
    now = datetime.now(timezone.utc)
    for row in rows:
        if (not isinstance(row, dict) or row.get("provider_id") != "zhipu-official"
                or row.get("source_url") != _ENDPOINTS["zhipu"]
                or type(row.get("free_claim")) is not bool
                or not isinstance(row.get("model_id"), str)
                or not zhipu_pricing.MODEL_ID.fullmatch(row["model_id"])
                or row["model_id"] != row["model_id"].lower() or row["model_id"] in seen):
            raise ValueError("invalid Zhipu price observation identity")
        observed = datetime.fromisoformat(row["observed_at"].replace("Z", "+00:00"))
        if observed.utcoffset() is None or not -5 <= (now - observed).total_seconds() <= 60:
            raise ValueError("stale Zhipu price observation")
        seen.add(row["model_id"])
        if row["free_claim"]:
            models.append(row["model_id"])
    return sorted(models)


def fetch_free_models(provider: str) -> dict:
    """Return exactly seven evidence fields, or raise ValueError on source failure.

    IDs are canonical provider IDs, never profile names or URLs. Models are exact,
    sorted text model IDs. TTL is freshness (six hours), not a free offer expiry.
    Allowance results are offline placeholders with models=[] and complete=False.
    """
    if not isinstance(provider, str) or provider not in _ENDPOINTS:
        raise ValueError("unknown free model provider")
    observed_at = datetime.now(timezone.utc).isoformat()
    mode = "zero-price"
    complete = False
    try:
        if provider in _BENEFIT_IDS:
            models, complete = _collect_catalog(provider)
        elif provider == "agnes":
            mode = "free-key"
            models = _agnes_models(_fetch_document(_ENDPOINTS[provider]), _fetch_document(_AGNES_KEYS_URL))
        elif provider == "zhipu":
            models = _zhipu_models()
        elif provider == "spark-lite":
            models = _spark_lite_models(_fetch_document(_ENDPOINTS[provider]))
        elif provider == "moark":
            from .moark_catalog import fetch_catalog
            catalog = fetch_catalog()
            models = sorted(row["model_id"] for row in catalog["models"] if row["text_generation"] and row["zero_price"])
            complete = catalog["complete"]
        else:
            mode = "allowance"
            models = []
    except (ValueError, KeyError, TypeError, AttributeError, RecursionError, OverflowError, InvalidOperation):
        raise ValueError(f"{provider} public free-price evidence unavailable or invalid") from None
    return {"provider_id": provider, "source_url": _ENDPOINTS[provider], "observed_at": observed_at,
            "models": models, "complete": complete, "mode": mode, "ttl_seconds": _TTL}
