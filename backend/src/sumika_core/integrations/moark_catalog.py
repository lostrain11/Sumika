"""Public Moark service prices, separated by capability and billing dimension."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import json
import re
from urllib.error import HTTPError
from urllib.request import Request, build_opener

from ..benefit_sources import _NoRedirect
from .zhipu_pricing import read_bounded


CATALOG_URL = "https://moark.com/api/pay/services?type=serverless&status=1&size=1000"
API_URL = "https://api.moark.com/v1"
PRICE_FIELDS = tuple(edge + "_" + dimension for edge in ("min", "max")
                     for dimension in ("price", "input_million_tokens_price", "output_million_tokens_price"))


def amount(value):
    if type(value) not in (str, int, float, Decimal) or len(str(value)) > 64:
        raise ValueError("missing or invalid public price")
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        raise ValueError("invalid public price") from None
    if not number.is_finite() or number < 0:
        raise ValueError("invalid public price")
    return number


def parse_catalog(payload):
    if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
        raise ValueError("invalid Moark catalog")
    rows = payload["items"]
    total = payload.get("total")
    if type(total) is not int or not len(rows) <= total <= 10000 or len(rows) > 1000:
        raise ValueError("invalid Moark catalog total")
    result, seen = [], set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("invalid Moark service")
        model_id = row.get("ident")
        if not isinstance(model_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/+-]{0,191}", model_id):
            raise ValueError("invalid exact Moark model identity")
        if model_id in seen:
            raise ValueError("duplicate Moark model identity")
        seen.add(model_id)
        if row.get("status") != 1 or row.get("type") != "serverless":
            continue
        tags = row.get("tags")
        if tags is None:
            tags = []
        if not isinstance(tags, list) or any(not isinstance(tag, dict) for tag in tags):
            raise ValueError("missing Moark capability tags")
        categories = sorted({tag["slug"] for tag in tags if isinstance(tag.get("slug"), str)})
        summary = row.get("operation_summary")
        prices = None
        if isinstance(summary, dict):
            try:
                parsed = {field: amount(summary.get(field)) for field in PRICE_FIELDS}
                if any(parsed["min_" + dimension] > parsed["max_" + dimension] for dimension in
                       ("price", "input_million_tokens_price", "output_million_tokens_price")):
                    raise ValueError("reversed Moark price range")
                if type(summary.get("operation_count")) is not int or summary["operation_count"] < 1:
                    raise ValueError("missing Moark billing operations")
                prices = {field: str(value) for field, value in parsed.items()}
            except ValueError:
                pass
        result.append({"model_id": model_id, "service_id": row.get("id"), "categories": categories,
                       "text_generation": "text-generation" in categories, "prices_cny": prices,
                       "zero_price": prices is not None and all(amount(value) == 0 for value in prices.values())})
    return {"source_url": CATALOG_URL, "observed_at": datetime.now(timezone.utc).isoformat(),
            "reported_total": total, "returned_count": len(rows),
            "complete": len(rows) == total and len(result) == len(rows)
                        and all(row["prices_cny"] is not None for row in result), "models": result}


def fetch_catalog():
    request = Request(CATALOG_URL, headers={"Accept": "application/json", "Accept-Encoding": "identity"})
    try:
        with build_opener(_NoRedirect()).open(request, timeout=15) as response:
            if response.status != 200 or response.geturl() != CATALOG_URL:
                raise ValueError("unexpected Moark catalog response")
            if response.headers.get_content_type() != "application/json":
                raise ValueError("unexpected Moark catalog content type")
            if response.headers.get("Content-Encoding", "identity").lower() != "identity":
                raise ValueError("encoded Moark catalog rejected")
            payload = json.loads(read_bounded(response, 4000000, 20), parse_float=Decimal)
        return parse_catalog(payload)
    except HTTPError as error:
        error.close()
        raise ValueError("Moark public catalog unavailable") from None


def request_cost_upper(row, prompt, max_tokens):
    if (not row.get("text_generation") or row.get("prices_cny") is None
            or type(max_tokens) is not int or not 0 < max_tokens <= 2048
            or not isinstance(prompt, str) or len(prompt.encode("utf-8")) > 16000):
        raise ValueError("bounded text request and known prices required")
    prices = row["prices_cny"]
    input_upper = len(prompt.encode("utf-8")) + 1024
    token_cost = (amount(prices["max_input_million_tokens_price"]) * input_upper / 1000000
                  + amount(prices["max_output_million_tokens_price"]) * max_tokens / 1000000)
    return max(amount(prices["max_price"]), token_cost)
