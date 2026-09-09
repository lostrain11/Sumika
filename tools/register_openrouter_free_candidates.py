"""Discover explicit free variants without credentials; registration stays untested."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import sqlite3
import sys
from urllib.request import HTTPRedirectHandler, Request, build_opener

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend/src"))

from sumika_core.credentials import MemoryCredentialStore
from sumika_core.integrations.zhipu_pricing import read_bounded
from sumika_core.provider_profiles import ProviderProfileManager
from sumika_core.storage import Storage

CATALOG_URL = "https://openrouter.ai/api/v1/models"
PROFILE_ID = "openrouter-free-candidates"


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        raise ValueError("catalog redirect rejected")


def free_rows(payload):
    models = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(models, list) or not 1 <= len(models) <= 10000:
        raise ValueError("invalid model catalog")
    result = []
    seen = set()
    for model in models:
        if not isinstance(model, dict):
            raise ValueError("invalid model row")
        model_id = model.get("id")
        if not isinstance(model_id, str) or not model_id.endswith(":free"):
            continue
        if (not 1 <= len(model_id) <= 200 or not model_id.isascii()
                or any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789/._:-" for character in model_id)
                or model_id in seen):
            raise ValueError("ambiguous free model identity")
        seen.add(model_id)
        prices = model.get("pricing")
        if not isinstance(prices, dict) or not {"prompt", "completion"} <= prices.keys():
            continue
        try:
            values = [Decimal(value) for value in prices.values() if isinstance(value, str)]
            if len(values) != len(prices) or not all(value.is_finite() and value == 0 for value in values):
                continue
        except InvalidOperation:
            continue
        modalities = (model.get("architecture") or {}).get("input_modalities", [])
        if not isinstance(modalities, list) or "text" not in modalities:
            continue
        context = model.get("context_length")
        if type(context) is not int or not 0 < context <= 100000000:
            continue
        result.append({"model_id": model_id, "context_length": context,
                       "declared_input_modalities": [value for value in modalities if value in {"text", "image", "audio", "video"}],
                       "pricing": prices, "price_currency": "USD", "health": "untested", "quota": "unknown"})
    if not result or len(result) > 128:
        raise ValueError("no bounded verified free-price catalog")
    return sorted(result, key=lambda row: row["model_id"])


def fetch_catalog():
    request = Request(CATALOG_URL, headers={"Accept": "application/json", "Accept-Encoding": "identity"})
    with build_opener(NoRedirect()).open(request, timeout=20) as response:
        if response.status != 200 or response.geturl() != CATALOG_URL:
            raise ValueError("unexpected catalog response")
        if response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
            raise ValueError("JSON catalog required")
        payload = json.loads(read_bounded(response, 8000000, 20))
    return {"schema": "openrouter-free-observation/v1", "source_url": CATALOG_URL,
            "observed_at": datetime.now(timezone.utc).isoformat(), "models": free_rows(payload),
            "authority": "public-price-observation-only", "model_calls": 0}


def register(storage, report):
    if storage.get_provider_profile(PROFILE_ID) is not None:
        raise ValueError("profile already exists; no overwrite")
    rows = [{"id": row["model_id"], "name": row["model_id"], "enabled": True,
             "capabilities": ["chat"], "quality_tier": "unknown", "cost_class": "unknown",
             "health_state": "unknown", "discovered_at": report["observed_at"]} for row in report["models"]]
    manager = ProviderProfileManager(storage, MemoryCredentialStore())
    return manager.save({"id": PROFILE_ID, "name": "OpenRouter free candidates", "template_id": "openrouter",
                         "base_url": "https://openrouter.ai/api/v1", "model": rows[0]["id"], "models": rows,
                         "source": {"kind": "public-catalog", "url": CATALOG_URL}})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--backup", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.report.exists():
        raise ValueError("report exists; no overwrite")
    if args.apply and (not args.data_dir or not args.backup or args.backup.exists()
                       or not (args.data_dir / "sumika.sqlite3").is_file()):
        raise ValueError("existing data directory and new backup required")
    report = fetch_catalog()
    args.report.parent.mkdir(parents=True, exist_ok=True)
    with args.report.open("x", encoding="utf-8") as output:
        json.dump(report, output, indent=2, ensure_ascii=True, allow_nan=False)
    if args.apply:
        database = args.data_dir / "sumika.sqlite3"
        with sqlite3.connect(database) as source:
            if source.execute("SELECT 1 FROM provider_profiles WHERE id=?", (PROFILE_ID,)).fetchone():
                raise ValueError("profile already exists; no overwrite")
            args.backup.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(args.backup) as target:
                source.backup(target)
        storage = Storage(database)
        try:
            profile = register(storage, report)
            if profile.get("has_secrets") or profile.get("status") == "available":
                raise ValueError("unauthorized profile must remain unavailable")
        finally:
            storage.close()
    print(json.dumps({"registered": args.apply, "profile_id": PROFILE_ID, "count": len(report["models"]),
                      "model_ids": [row["model_id"] for row in report["models"]], "model_calls": 0,
                      "state": "needs-api-key-and-evaluation", "automatic_routing": False}))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(json.dumps({"ok": False, "error_type": type(error).__name__}))
        raise SystemExit(1) from None
