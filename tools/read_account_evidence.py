"""Read official account evidence without model calls or changes to the daily database.

Credentials stay in process memory. Browser receipts contain hashes and exact
amounts only; the selected browser is never silently changed or signed in.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))

from sumika_core.browser.runtime import BrowserSkillClient
from sumika_core.credentials import WindowsCredentialStore, credential_namespace_for_data_dir
from sumika_core.integrations.account_portals import AccountPortalReader
from sumika_core.integrations.account_sources import BASE_URLS, read_account, read_modelscope_funding
from sumika_core.providers.openai_compatible import OpenAICompatibleProvider


def read_evidence(provider, data_dir, browser_id=None, bsk=r"D:\Tools\BrowserSkill\0.1.11\bsk.exe"):
    endpoint = {**BASE_URLS, "modelscope": "https://api-inference.modelscope.cn/v1", "ollama": "https://ollama.com/v1"}[provider]
    database = (Path(data_dir).resolve() / "sumika.sqlite3").as_uri() + "?mode=ro"
    connection = sqlite3.connect(database, uri=True)
    try:
        candidates = [(json.loads(config), reference) for config, reference in connection.execute(
            "SELECT config_json, credential_ref FROM provider_profiles WHERE archived_at IS NULL")
            if json.loads(config).get("active_base_url") == endpoint and reference]
    finally:
        connection.close()
    if len(candidates) != 1:
        raise ValueError("one active official credential binding required")
    config, reference = candidates[0]
    vault = WindowsCredentialStore(credential_namespace_for_data_dir(data_dir))
    secrets = vault.read(reference)
    key = (secrets or {}).get("api_key")
    if not key:
        raise ValueError("existing API credential required")
    runtime = OpenAICompatibleProvider(base_url=endpoint, api_key=key)
    report = {"provider": provider, "observed_at": datetime.now(timezone.utc).isoformat(), "model_calls": 0}
    if provider in BASE_URLS:
        report["account"] = read_account(provider, runtime)
    if provider == "moark" and browser_id:
        if browser_id == "sumika-native":
            raise ValueError("native receipts require the host receipt_reader callback")
        report["receipt_evidence"] = AccountPortalReader(BrowserSkillClient(bsk)).read_receipts(provider, browser_id)
        report["receipt_count"] = len(report["receipt_evidence"].get("receipts", []))
        packages = set(report["account"]["package_fingerprints"])
        report["matching_package_receipts"] = sum(row["package_fingerprint"] in packages for row in report["receipt_evidence"].get("receipts", []))
    elif provider == "modelscope":
        report["api_funding"] = read_modelscope_funding(runtime)
    elif provider == "ollama" and browser_id:
        if browser_id == "sumika-native":
            raise ValueError("native portals require the host native_reader callback")
        report["portal"] = AccountPortalReader(BrowserSkillClient(bsk)).read(provider, browser_id)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", required=True, choices=("deepseek", "moark", "modelscope", "ollama"))
    parser.add_argument("--data-dir", type=Path, default=Path("D:/Code/Sumika/.sumika-desktop"))
    parser.add_argument("--browser-id")
    parser.add_argument("--bsk", default=r"D:\Tools\BrowserSkill\0.1.11\bsk.exe")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if args.output and args.output.exists():
        parser.error("output already exists; refusing to overwrite")
    try:
        report = read_evidence(args.provider, args.data_dir, args.browser_id, args.bsk)
    except Exception as error:
        report = {"provider": args.provider, "state": "needs-review", "error_type": type(error).__name__, "model_calls": 0}
    serialized = json.dumps(report, ensure_ascii=False, allow_nan=False, indent=2) + "\n"
    if args.output:
        with args.output.open("x", encoding="utf-8") as destination:
            destination.write(serialized)
    summary = {key: value for key, value in report.items() if key != "receipt_evidence"}
    print(json.dumps(summary, ensure_ascii=False, allow_nan=False))
    return 1 if report.get("state") == "needs-review" else 0


if __name__ == "__main__":
    raise SystemExit(main())
