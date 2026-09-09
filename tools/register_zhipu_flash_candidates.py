"""Explicit local registration of tested Flash models, never quality promotion."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "backend/src"), str(ROOT / "packages/quality-routing/src")]

from tools.evaluate_zhipu_candidates import ALLOWED_MODELS, BASE_URL, VAULT_NAMESPACE, VAULT_REFERENCE
from sumika_core.credentials import WindowsCredentialStore, credential_namespace_for_data_dir
from sumika_core.model_policy import ModelPolicyService
from sumika_core.provider_profiles import ProviderProfileManager
from sumika_core.storage import Storage


def candidate_rows(reports):
    rows = []
    for report in reports:
        model = report.get("model_id")
        observed = datetime.fromisoformat(report["checked_at"])
        if (report.get("schema") != "zhipu-candidate-sanity/v1" or model not in ALLOWED_MODELS
                or observed.tzinfo is None or not 0 <= (datetime.now(timezone.utc) - observed).total_seconds() < 3600
                or report.get("health", {}).get("passed") is not True
                or not any(check.get("passed") is True for check in report.get("checks", []))):
            raise ValueError("fresh successful API evidence required")
        transport_failed = any(check.get("http_status") or check.get("failure_class") for check in report["checks"])
        rows.append({"id": model, "name": model, "enabled": True, "capabilities": ["chat"],
                     "health_state": "unavailable" if transport_failed else "healthy",
                     "last_tested_at": report["checked_at"], "quality_tier": "unknown", "cost_class": "unknown"})
    if {row["id"] for row in rows} != set(ALLOWED_MODELS) or len(rows) != 2:
        raise ValueError("one report per Flash model required")
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--reports", type=Path, nargs=2, required=True)
    parser.add_argument("--backup", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    rows = candidate_rows([json.loads(path.read_text(encoding="utf-8")) for path in args.reports])
    database = args.data_dir.resolve() / "sumika.sqlite3"
    if not database.is_file() or args.backup.exists():
        raise ValueError("existing database and new backup path required")
    if not args.apply:
        print(json.dumps({"apply": False, "models": rows, "automatic_routing": False}))
        return
    with sqlite3.connect(database) as source:
        if source.execute("SELECT 1 FROM provider_profiles WHERE id=?", ("zhipu-flash-candidates",)).fetchone():
            raise ValueError("candidate profile already exists; no overwrite")
        args.backup.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(args.backup) as target:
            source.backup(target)
    storage = Storage(database)
    try:
        key = WindowsCredentialStore(VAULT_NAMESPACE).read(VAULT_REFERENCE).get("api_key")
        if not key:
            raise ValueError("saved test credential unavailable")
        manager = ProviderProfileManager(storage, WindowsCredentialStore(credential_namespace_for_data_dir(args.data_dir.resolve())))
        profile = manager.save({"id": "zhipu-flash-candidates", "name": "Zhipu Flash candidates",
            "template_id": "zhipu-bigmodel", "base_url": BASE_URL, "model": "glm-4.6v-flash",
            "models": rows, "api_key": key})
        key = None
        storage.update_provider_profile_state(profile["id"], status="available")
        policy = ModelPolicyService(manager)
        try:
            entries = [entry for entry in policy.catalog()["entries"] if entry.get("provider_profile_id") == profile["id"]]
            if len(entries) != 2 or any(entry["metadata"].get("routable") is True for entry in entries):
                storage.update_provider_profile_state(profile["id"], status="unavailable")
                raise ValueError("candidate registration must retain evaluation gate")
            print(json.dumps({"profile_id": profile["id"], "models": [entry["model_id"] for entry in entries],
                              "automatic_routing": False, "state": "pending-evaluation", "default_bindings_changed": False}))
        finally:
            policy.close()
    finally:
        storage.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(json.dumps({"ok": False, "error_type": type(error).__name__}))
        raise SystemExit(1) from None
