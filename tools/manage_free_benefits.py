"""Operate the same bounded benefit workflows as the client, without a model."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))
sys.path.insert(0, str(ROOT / "packages" / "quality-routing" / "src"))

from sumika_core.benefits import BenefitsService
from sumika_core.browser.runtime import BrowserSkillClient
from sumika_core.integrations.modelscope_benefits import ModelScopeBenefitsReader


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("status", "refresh", "checkin", "configure", "run-due"))
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--enable-discovery", action="store_true")
    parser.add_argument("--enable-checkin", action="store_true")
    parser.add_argument("--disable", action="store_true")
    parser.add_argument("--browser")
    parser.add_argument("--bsk")
    parser.add_argument("--report", type=Path)
    arguments = parser.parse_args()
    if arguments.report and arguments.report.exists():
        parser.error("report already exists; choose a new report path")
    changes = arguments.enable_discovery or arguments.enable_checkin or arguments.disable or arguments.browser is not None
    if changes and arguments.action != "configure":
        parser.error("configuration flags require the configure action")
    if arguments.disable and (arguments.enable_discovery or arguments.enable_checkin):
        parser.error("cannot enable and disable in the same action")
    database = arguments.data_dir.resolve() / "sumika.sqlite3"
    if not database.is_file():
        parser.error("select an existing Sumika data directory")
    executable = arguments.bsk or os.getenv("SUMIKA_BSK_EXECUTABLE") or shutil.which("bsk")
    if not executable:
        known = Path("D:/Tools/BrowserSkill/0.1.11/bsk.exe")
        executable = str(known) if known.is_file() else None
    storage = sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)
    storage.row_factory = sqlite3.Row
    def read_profile(profile_id):
        row = storage.execute("SELECT * FROM provider_profiles WHERE id=?", (profile_id,)).fetchone()
        if row is None:
            return None
        profile = dict(row)
        profile["config"] = json.loads(profile.pop("config_json"))
        return profile
    service = BenefitsService(arguments.data_dir.resolve(), profile_reader=read_profile,
        browser_reader=ModelScopeBenefitsReader(BrowserSkillClient(executable=executable)))
    try:
        if arguments.action == "configure":
            params = {}
            if arguments.enable_discovery:
                params["enabled"] = True
            if arguments.enable_checkin:
                params.update(enabled=True, checkin_enabled=True)
            if arguments.disable:
                params.update(enabled=False, checkin_enabled=False)
            if arguments.browser is not None:
                params["browser_instance_id"] = arguments.browser
            service.configure(params)
        elif arguments.action == "checkin":
            service._check_binding()
            service.run_once(kind="checkin", manual=True)
        elif arguments.action == "refresh":
            service.run_once(kind="refresh", manual=True)
        elif arguments.action == "run-due":
            service.run_once()
        result = service.status()
        encoded = json.dumps(result, ensure_ascii=False, indent=2)
        if arguments.report:
            arguments.report.parent.mkdir(parents=True, exist_ok=True)
            with arguments.report.open("x", encoding="utf-8") as stream:
                stream.write(encoded + "\n")
        summary = {"schema": result["schema"], "enabled": result["enabled"], "checkin_enabled": result["checkin_enabled"],
            "sources": [{key: item.get(key) for key in ("id", "status", "item_count", "error")} for item in result["sources"]],
            "offers": len(result["offers"]), "checkin": result["checkin"], "model_calls": 0}
        print(json.dumps(summary, ensure_ascii=True, indent=2))
        return 0
    finally:
        service.close()
        storage.close()


if __name__ == "__main__":
    raise SystemExit(main())
