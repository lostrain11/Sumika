from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from html.parser import HTMLParser
from urllib.request import Request, build_opener
from urllib.error import HTTPError

from ..benefit_sources import _NoRedirect
from ..route_pricing import PricingSnapshot
from .moark_catalog import fetch_catalog


DEEPSEEK_PRICING = "https://api-docs.deepseek.com/zh-cn/quick_start/pricing/"
ACCOUNT_URLS = {
    "deepseek": "https://api.deepseek.com/user/balance",
    "moark": "https://api.moark.com/v1/tokens/packages/balance",
}
BASE_URLS = {"deepseek": "https://api.deepseek.com/v1", "moark": "https://api.moark.com/v1"}
MOARK_RECEIPTS_URL = "https://moark.com/api/base/{account}/inference-logs"
MODELSCOPE_ACCOUNT_URLS = {
    "balance": "https://modelscope.cn/openapi/v1/magicubes/balance",
    "rates": "https://modelscope.cn/openapi/v1/magicubes/spend/rates",
}


def trace_fingerprint(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9._:-]{1,240}", value):
        raise ValueError("invalid provider trace")
    return hashlib.sha256(value.encode()).hexdigest()


def validate_moark_receipts(observation):
    """Accept only the metadata-only, lossless projection of finalized API logs."""
    if (not isinstance(observation, dict) or observation.get("schema") != "moark-receipts/v1"
            or observation.get("source_url") != MOARK_RECEIPTS_URL or observation.get("state") != "verified"):
        raise ValueError("verified official Moark receipt projection required")
    receipts = observation.get("receipts")
    if not isinstance(receipts, list) or len(receipts) > 2000:
        raise ValueError("bounded receipt list required")
    result, seen, traces = [], set(), set()
    for row in receipts:
        if not isinstance(row, dict):
            raise ValueError("invalid receipt")
        for field in ("evidence_id", "trace_fingerprint", "package_fingerprint"):
            if not isinstance(row.get(field), str) or not re.fullmatch(r"[a-f0-9]{64}", row[field]):
                raise ValueError("invalid receipt identity")
        if row["evidence_id"] in seen or row["trace_fingerprint"] in traces:
            raise ValueError("ambiguous or duplicate receipt")
        seen.add(row["evidence_id"])
        traces.add(row["trace_fingerprint"])
        if (not isinstance(row.get("model_id"), str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9/._:-]{0,239}", row["model_id"])
                or row.get("unit") != "CNY" or row.get("charge_source") != "resource-package"
                or row.get("finalized") is not True or type(row.get("amount")) is not str or len(row["amount"]) > 64):
            raise ValueError("unsupported receipt billing semantics")
        amount = decimal_amount(row["amount"])
        if amount > Decimal("1000000000") or amount.as_tuple().exponent < -18:
            raise ValueError("unbounded receipt amount")
        result.append({key: row[key] for key in ("evidence_id", "trace_fingerprint", "package_fingerprint", "model_id", "unit", "charge_source", "finalized")}
                      | {"amount": format(amount, "f")})
    return result


def _authenticated_json(url, runtime):
    request = Request(url, headers=runtime._request_headers(accept="application/json"))
    try:
        with build_opener(_NoRedirect()).open(request, timeout=20) as response:
            data = response.read(1000001)
            if response.geturl() != url or len(data) > 1000000:
                raise ValueError("invalid official account response")
    except HTTPError as error:
        status = error.code
        error.close()
        raise ValueError(f"official account HTTP {status}") from None
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate account field")
            result[key] = value
        return result
    raw = json.loads(data, parse_float=Decimal, object_pairs_hook=unique,
                     parse_constant=lambda value: (_ for _ in ()).throw(ValueError("nonfinite account value")))
    if not isinstance(raw, dict):
        raise ValueError("official account object required")
    return raw


def read_modelscope_funding(runtime):
    """Read token-authenticated balances and published scene rates, not model calls."""
    if runtime.base_url != "https://api-inference.modelscope.cn/v1":
        raise ValueError("account endpoint binding mismatch")
    responses = {key: _authenticated_json(url, runtime) for key, url in MODELSCOPE_ACCOUNT_URLS.items()}
    if any(row.get("success") is not True or not isinstance(row.get("data"), dict) for row in responses.values()):
        raise ValueError("ModelScope account authentication unverified")
    balance = responses["balance"]["data"]
    amounts = {key: decimal_amount(balance.get(key)) for key in ("total_balance", "available_balance", "frozen_amount")}
    if amounts["total_balance"] != amounts["available_balance"] + amounts["frozen_amount"]:
        raise ValueError("ModelScope balances do not reconcile")
    raw_rates = responses["rates"]["data"].get("rates")
    if not isinstance(raw_rates, list) or not 1 <= len(raw_rates) <= 128:
        raise ValueError("bounded ModelScope rates required")
    rates, seen = [], set()
    for row in raw_rates:
        if not isinstance(row, dict) or row.get("scene") != "api_inference":
            continue
        tier = row.get("model_tier")
        if tier not in {"lite", "standard", "ultra", "discount"} or tier in seen or row.get("unit") != "request":
            raise ValueError("ModelScope rate schema changed")
        seen.add(tier)
        rates.append({"scene": "api_inference", "model_tier": tier, "unit": "request",
                      "unit_price": str(decimal_amount(row.get("unit_price"))),
                      "min_charge": str(decimal_amount(row.get("min_charge")))})
    if not rates:
        raise ValueError("API inference rates unavailable")
    return {"source": "modelscope-magicube-api", "source_urls": list(MODELSCOPE_ACCOUNT_URLS.values()),
            "api_authenticated": True, "unit": "magicube", **{key: str(value) for key, value in amounts.items()},
            "rates": rates, "account_binding_verified": False, "routing_eligible": False,
            "routing_blockers": ["web-api-identity-unverified", "model-tier-binding-unverified"]}


class PublicText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.hidden += 1

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def read_public_text(url):
    with build_opener(_NoRedirect()).open(Request(url, headers={"Accept-Encoding": "identity"}), timeout=20) as response:
        data = response.read(1000001)
        if len(data) > 1000000 or response.geturl() != url:
            raise ValueError("invalid public response")
    parser = PublicText()
    parser.feed(data.decode("utf-8"))
    return re.sub(r"\s+", " ", " ".join(parser.parts)).strip()


def decimal_amount(value):
    if type(value) not in {str, int, float, Decimal}:
        raise ValueError("invalid amount")
    amount = Decimal(str(value))
    if not amount.is_finite() or amount < 0:
        raise ValueError("invalid amount")
    return amount


def parse_deepseek_prices(text, profile_id, now=None):
    now = now or datetime.now(timezone.utc)
    models = ("deepseek-v4-flash", "deepseek-v4-pro", "deepseek-v4-flash-vision-exp")
    if not all(model in text for model in models) or "北京时间周一至周五 9:00 - 12:00、14:00 - 18:00" not in text:
        raise ValueError("DeepSeek model or schedule changed")
    rows = re.findall(r"空闲时段\s+([\d.]+)元\s+([\d.]+)元\s+([\d.]+)元\s+高峰时段\s+([\d.]+)元\s+([\d.]+)元\s+([\d.]+)元", text)
    versions = re.search(r"模型版本\s+(DeepSeek-V4-Flash-[0-9]+)\s+(DeepSeek-V4-Pro-[0-9]+)\s+(DeepSeek-V4-Flash-Vision-Exp)", text)
    if len(rows) != 3 or not versions:
        raise ValueError("DeepSeek pricing schema changed")
    rates = [[decimal_amount(value) for value in row] for row in rows]
    if any(row[index + 3] != row[index] * 2 for row in rates for index in range(3)):
        raise ValueError("unexpected peak multiplier")
    revision = hashlib.sha256(json.dumps([rows, versions.groups()]).encode()).hexdigest()
    snapshots = []
    for index, model in enumerate(models):
        snapshots.append(PricingSnapshot("account-deepseek-" + model, profile_id, model, "official", "CNY",
            input_price_per_million=float(rates[1][index + 3]), output_price_per_million=float(rates[2][index + 3]),
            cache_read_price_per_million=float(rates[0][index + 3]), cash_currency="CNY", cash_rate=1,
            source_type="direct-official", source_url=DEEPSEEK_PRICING, source_version=revision,
            observed_at=now.isoformat(), expires_at=(now + timedelta(hours=12)).isoformat(), confidence="official",
            observations={"estimate_basis": "peak-rate-upper-bound", "off_peak_multiplier": 0.5,
                          "model_version": versions.groups()[index]}))
    return snapshots, dict(zip(models, versions.groups()))


def public_prices(source, profile_id):
    if source == "deepseek":
        return parse_deepseek_prices(read_public_text(DEEPSEEK_PRICING), profile_id)
    if source != "moark":
        raise ValueError("unsupported price source")
    catalog = fetch_catalog()
    now = datetime.now(timezone.utc)
    snapshots = []
    for row in catalog["models"]:
        rates = row["prices_cny"]
        if not row["text_generation"] or rates is None:
            continue
        version = hashlib.sha256(json.dumps(rates, sort_keys=True).encode()).hexdigest()
        expression = "max(" + rates["max_price"] + ", p * " + rates["max_input_million_tokens_price"] + " + c * " + rates["max_output_million_tokens_price"] + ")"
        snapshots.append(PricingSnapshot("account-moark-" + hashlib.sha256(row["model_id"].encode()).hexdigest()[:24],
            profile_id, row["model_id"], "official", "CNY", billing_expression=expression,
            cash_currency="CNY", cash_rate=1, source_type="manual", source_url=catalog["source_url"],
            source_version=version, observed_at=now.isoformat(), expires_at=(now + timedelta(hours=6)).isoformat(),
            confidence="published", observations={"estimate_basis": "public-operation-upper-bound"}))
    return snapshots, {}


def read_account(source, runtime):
    if source not in ACCOUNT_URLS or runtime.base_url != BASE_URLS[source]:
        raise ValueError("account endpoint binding mismatch")
    url = ACCOUNT_URLS[source]
    raw = _authenticated_json(url, runtime)
    if source == "deepseek":
        balances = [row for row in raw.get("balance_infos", []) if row.get("currency") == "CNY"]
        if len(balances) != 1:
            raise ValueError("unambiguous CNY balance required")
        row = balances[0]
        total, grant, cash = (decimal_amount(row[key]) for key in ("total_balance", "granted_balance", "topped_up_balance"))
        if total != grant + cash:
            raise ValueError("account balances do not reconcile")
        return {"source": source, "source_url": url, "unit": "CNY", "balance": str(total),
                "grant": str(grant), "cash": str(cash), "available": raw.get("is_available") is True}
    total, used, balance = (decimal_amount(raw[key]) for key in ("total_amount", "used_amount", "balance"))
    if total - used != balance:
        raise ValueError("package balances do not reconcile")
    details = raw.get("details")
    if not isinstance(details, list) or not 1 <= len(details) <= 128 or any(not row.get("ident") for row in details):
        raise ValueError("package identities required")
    fingerprints = [hashlib.sha256(str(row["ident"]).encode()).hexdigest() for row in details]
    if len(fingerprints) != len(set(fingerprints)):
        raise ValueError("duplicate package identity")
    return {"source": source, "source_url": url, "unit": "CNY", "balance": str(balance), "used": str(used),
            "total": str(total), "package_fingerprints": fingerprints}
