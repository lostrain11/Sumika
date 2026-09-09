"""Read two explicit zero-price MaaS entries, without credentials or model calls."""
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import sys
from urllib.request import Request, ProxyHandler, build_opener

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "backend/src"), str(ROOT / "packages/quality-routing/src")]

from sumika_core.integrations.zhipu_pricing import read_bounded
from tools.evaluate_zhipu_candidates import _json_loads
from tools.register_openrouter_free_candidates import NoRedirect

CATALOG_URL = "https://maas.xfyun.cn/api/v1/gpt-finetune/model/base/list-v2?page=1&size=9999"
BASE_URL = "https://maas-api.cn-huabei-1.xf-yun.com/v2"
MODELS = {"spark-x2.5-1.7b": "Spark-X2.5-1.7B", "spark-x2.5-4b": "Spark-X2.5-4B"}
PRICE_UNIT = "\u5143/\u767e\u4e07tokens"


def free_rows(payload):
    if not isinstance(payload, dict) or type(payload.get("code")) is not int or payload["code"] != 0 or payload.get("succeed") is not True:
        raise ValueError("successful public catalog required")
    data = payload.get("data")
    rows = data.get("rows") if isinstance(data, dict) else None
    if not isinstance(rows, list) or not 1 <= len(rows) <= 10000:
        raise ValueError("bounded catalog rows required")
    result = []
    seen = set()
    for row in rows:
        if not isinstance(row, dict) or row.get("serviceId") not in MODELS:
            continue
        model = row["serviceId"]
        if model in seen or row.get("name") != MODELS[model]:
            raise ValueError("ambiguous public model identity")
        seen.add(model)
        if row.get("urls", {}).get("api", {}).get("http") != BASE_URL:
            raise ValueError("unexpected official API endpoint")
        prices = row.get("price", {}).get("inferencePrice")
        if not isinstance(prices, dict) or prices.get("showPrice") is not True:
            raise ValueError("explicit inference price required")
        for field in ("inTokens", "outTokens", "cacheTokens"):
            raw = prices.get(field + "Price")
            try:
                value = Decimal(str(raw))
            except InvalidOperation:
                raise ValueError("numeric price required") from None
            if type(raw) not in (int, float, str) or not value.is_finite() or value != 0 or prices.get(field + "Unit") != PRICE_UNIT:
                raise ValueError("zero CNY inference price required")
        no_cache = prices.get("noCacheTokensPrice")
        if no_cache is not None and (type(no_cache) not in (int, float, str) or Decimal(str(no_cache)) != 0):
            raise ValueError("nonzero or unknown cache-miss price")
        tags = row.get("categoryTree", [])
        limited = any(isinstance(group, dict) and group.get("key") == "indexMarker"
                      and any(isinstance(child, dict) and child.get("name") == "\u9650\u65f6\u514d\u8d39"
                              for child in group.get("children", [])) for group in tags)
        result.append({"model_id": model, "name": MODELS[model], "base_url": BASE_URL,
                       "input_cny_per_million": "0", "output_cny_per_million": "0",
                       "cache_cny_per_million": "0", "limited_time": limited,
                       "expires_at": None, "account_quota": "unknown", "health": "untested"})
    if set(MODELS) != seen:
        raise ValueError("both expected models required")
    return sorted(result, key=lambda row: row["model_id"])


def fetch_catalog():
    request = Request(CATALOG_URL, headers={"Accept": "application/json", "Accept-Encoding": "identity"})
    with build_opener(ProxyHandler({}), NoRedirect()).open(request, timeout=20) as response:
        if response.status != 200 or response.geturl() != CATALOG_URL:
            raise ValueError("unexpected catalog response")
        if response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
            raise ValueError("JSON required")
        if response.headers.get("Content-Encoding", "identity").lower() != "identity":
            raise ValueError("encoded catalog rejected")
        rows = free_rows(_json_loads(read_bounded(response, 4000000, 20)))
    return {"schema": "xfyun-free-observation/v1", "source_url": CATALOG_URL,
            "observed_at": datetime.now(timezone.utc).isoformat(), "models": rows,
            "authority": "public-price-observation-only", "model_calls": 0}


if __name__ == "__main__":
    try:
        print(json.dumps(fetch_catalog(), allow_nan=False))
    except Exception as error:
        print(json.dumps({"ok": False, "failure_class": type(error).__name__}))
        raise SystemExit(1) from None
