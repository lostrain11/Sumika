"""Plain-file project records, portable across models and Harnesses."""
import hashlib
import json
from pathlib import Path


def read_records(root: Path):
    base = root / "docs/project"
    return {name: json.loads((base / f"{name}.json").read_text(encoding="utf-8-sig"))
            for name in ("requirements", "plan", "progress", "decisions", "handoff")}


def validate(root: Path):
    data = read_records(root)
    for name, value in data.items():
        if value.get("schema_version") != 1:
            raise ValueError(f"{name}: invalid schema version")
    entries = data["requirements"]["entries"]
    if not entries:
        raise ValueError("requirements must contain original user text")
    ids = [item["id"] for item in entries]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate requirement ids")
    for item in entries:
        if not item["original"] or not item["source"] or item["status"] not in ("active", "superseded", "deferred"):
            raise ValueError("requirement missing original, source or valid status")
        if hashlib.sha256(item["original"].encode()).hexdigest() != item["sha256"]:
            raise ValueError(f"original text changed: {item['id']}")
        if item["source"].startswith("docs/project/approved-plan.md:"):
            line = int(item["source"].rsplit(":", 1)[1])
            source = (root / "docs/project/approved-plan.md").read_text(encoding="utf-8").splitlines()[line - 1]
            if source.removeprefix("- ") != item["original"]:
                raise ValueError("original and source disagree")
        if item.get("supersedes") and item["supersedes"] not in ids:
            raise ValueError("unknown superseded requirement")
    phases = data["plan"]["phases"]
    phase_ids = [p["id"] for p in phases]
    if phase_ids != [f"P{i}" for i in range(8)]:
        raise ValueError("plan must preserve phases P0-P7")
    for p in phases:
        if not p.get("acceptance") or not p.get("tasks") or not p.get("requirements"):
            raise ValueError(f"phase missing acceptance, tasks or provenance: {p['id']}")
        if not set(p["requirements"]) <= set(ids):
            raise ValueError("phase refers to unknown requirement")
        if p["status"] == "complete" and not p.get("evidence"):
            raise ValueError("complete phase requires evidence")
        for evidence in p.get("evidence", []):
            path = (root / evidence).resolve()
            if not path.is_relative_to(root.resolve()) or not path.is_file():
                raise ValueError("missing or external evidence file")
    if data["progress"]["current_phase"] != data["handoff"]["current_phase"]:
        raise ValueError("progress and handoff disagree")
    if data["handoff"]["current_phase"] not in phase_ids:
        raise ValueError("unknown handoff phase")
    if not data["handoff"]["next_action"] or not data["handoff"]["remaining"]:
        raise ValueError("missing next action or remaining work")
    return data


def handoff(root: Path) -> str:
    data = validate(root)
    current = data["handoff"]
    text = ["# Sumika 接手上下文", data["plan"]["goal"],
            "当前阶段: " + current["current_phase"], "## 已完成"]
    text.extend("- " + item for item in current["completed"])
    text.append("## 剩余与限制")
    text.extend("- " + item for item in current["remaining"] + current["constraints"])
    text += ["## 下一步", current["next_action"], "## 需求原文索引"]
    text.extend(f"- {item['id']} [{item['status']}]: {item['original']}" for item in data["requirements"]["entries"])
    return "\n".join(text) + "\n"
