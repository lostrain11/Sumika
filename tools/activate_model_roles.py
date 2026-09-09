"""Import reviewed role evaluations and activate existing profiles without model calls."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "backend/src"), str(ROOT / "packages/quality-routing/src")]

from sumika_core.provider_profiles import provider_execution_revision
from sumika_core.quality.selection import FixedEvaluationSample, SelectionCohort, SelectionEvidenceStore
from sumika_core.storage import Storage


IDENTITIES_KEY = "model-policy/evaluated-model-identities/v1"
SETTINGS_KEY = "quality-routing/settings/v1"
CASES = {"leader": {"dag", "review", "replan"}, "role": {"facts", "uncertainty", "boundary"}}


def validate_report(report, profile, *, reviewed=False, now=None, bounded=False):
    timestamp = time.time() if now is None else now
    purpose = report.get("purpose")
    model = report.get("model_id")
    cases = {"bounded": {"fact-extraction", "negation-and-numbers", "instruction-following"}} if bounded else CASES
    if (report.get("schema") != "sumika-role-evaluation/v1" or purpose not in cases
            or report.get("profile_id") != profile["id"] or report.get("qualified") is not True
            or report.get("model_calls") != 3 or (purpose == "role" and not reviewed)):
        raise ValueError("successful reviewed role report required")
    if model not in {row["id"] for row in profile["config"]["models"]} or profile.get("archived_at"):
        raise ValueError("current registered model required")
    if report.get("execution_revision") != provider_execution_revision(profile, model):
        raise ValueError("evaluation execution binding changed")
    version = report.get("model_version")
    if not isinstance(version, str) or not re.fullmatch(r"[A-Za-z0-9._:-]{1,160}", version):
        raise ValueError("explicit evaluated version required")
    samples = report.get("samples")
    if not isinstance(samples, list) or len(samples) != 3 or {row.get("id") for row in samples} != cases[purpose]:
        raise ValueError("three distinct fixed cases required")
    for row in samples:
        observed = row.get("observed_at")
        if (row.get("passed") is not True or row.get("finish_reason") != "stop"
                or type(observed) not in {int, float} or not timestamp - 86400 <= observed <= timestamp
                or not re.fullmatch(r"[a-f0-9]{64}", str(row.get("response_digest", "")))
                or any(type(row.get("usage", {}).get(key)) is not int or row["usage"][key] < 0
                       for key in ("input_tokens", "output_tokens"))):
            raise ValueError("fresh complete evaluated samples required")
    return "profile:" + profile["id"] + ":" + model


def activate(storage, reports, *, leader_id, reviewed=False, assistant_id="sumika"):
    if not storage.get_character(assistant_id):
        raise ValueError("existing assistant required")
    entries = []
    for report in reports:
        profile = storage.get_provider_profile(report.get("profile_id"))
        if not profile:
            raise ValueError("existing provider required")
        candidate_id = validate_report(report, profile, reviewed=reviewed)
        entries.append((candidate_id, report))
    if leader_id not in {candidate_id for candidate_id, report in entries if report["purpose"] == "leader"}:
        raise ValueError("preferred leader must have current leader evidence")
    if not any(report["purpose"] == "role" for _, report in entries):
        raise ValueError("role evidence required")
    evidence = SelectionEvidenceStore(storage)
    for purpose in CASES:
        evidence.register_cohort(assistant_id, SelectionCohort(purpose, "role-activation-" + purpose, "v1", "1"))
    identities = json.loads(storage.get_meta(IDENTITIES_KEY) or "{}")
    for candidate_id, report in entries:
        digest = hashlib.sha256(json.dumps(report, sort_keys=True).encode()).hexdigest()
        profile = storage.get_provider_profile(report["profile_id"])
        config = profile["config"]
        for row in config["models"]:
            if row["id"] == report["model_id"]:
                row.update(health_state="healthy", last_tested_at=report["checked_at"])
        storage.update_provider_profile_config(profile["id"], config)
        storage.update_provider_profile_state(profile["id"], status="available")
        if provider_execution_revision(storage.get_provider_profile(profile["id"]), report["model_id"]) != report["execution_revision"]:
            raise ValueError("health metadata changed execution unexpectedly")
        identities[candidate_id] = {"model_version": report["model_version"], "execution_revision": report["execution_revision"],
                                   "report_digest": digest, "version_basis": "evaluated-provider-release-or-alias"}
        for sample in report["samples"]:
            evidence.record_sample(assistant_id, FixedEvaluationSample(digest[:32] + ":" + sample["id"], candidate_id,
                report["model_version"], report["purpose"], "role-activation-" + report["purpose"], "v1", "1", True,
                sample["observed_at"], sample["observed_at"] + 7 * 86400))
    storage.set_meta(IDENTITIES_KEY, json.dumps(identities, sort_keys=True))
    raw = json.loads(storage.get_meta(SETTINGS_KEY) or "{}")
    settings = raw.setdefault("assistants", {}).setdefault(assistant_id, {})
    settings.update(leader_candidate_id=leader_id, role_candidate_id=None, selection_mode={"leader": "auto", "role": "auto"},
                    candidate_pool=sorted(set(settings.get("candidate_pool", [])) | {candidate_id for candidate_id, _ in entries}))
    storage.set_meta(SETTINGS_KEY, json.dumps(raw, sort_keys=True))
    return {"assistant_id": assistant_id, "preferred_leader": leader_id, "selection_mode": settings["selection_mode"],
            "candidate_pool": settings["candidate_pool"], "model_calls": 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path, action="append", required=True)
    parser.add_argument("--preferred-leader", required=True)
    parser.add_argument("--reviewed", action="store_true")
    arguments = parser.parse_args()
    reports = [json.loads(path.read_text(encoding="utf-8")) for path in arguments.report]
    database = arguments.data_dir / "sumika.sqlite3"
    if not database.is_file():
        raise ValueError("existing data directory required")
    storage = Storage(database)
    try:
        print(json.dumps(activate(storage, reports, leader_id=arguments.preferred_leader, reviewed=arguments.reviewed)))
    finally:
        storage.close()


if __name__ == "__main__":
    main()
