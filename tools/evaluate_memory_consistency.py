"""Multi-turn memory consistency: what the model actually sees after an update.

Single-shot retrieval metrics do not catch the failure that matters most in a
relationship: the user changes their mind and the old fact keeps coming back.
This walks a scripted conversation through RoleSession and inspects the injected
context, not just the database.
"""
import argparse
import json
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from extensions.roles.roles import import_card
from extensions.roles.service import RoleSession

CARD = {"spec": "chara_card_v2", "data": {
    "name": "验收角色", "description": "用于记忆一致性评测", "mes_example": "示例",
    "character_book": {"entries": []}}}


def _session(root, provider="embedded", cache=None, user_id="user", role_id="acceptance"):
    card = root / "card.json"
    card.write_text(json.dumps(CARD, ensure_ascii=False), encoding="utf8")
    role_dir = root / "store" / f"{user_id}-{role_id}"
    if not (role_dir / "role.json").is_file():
        role_dir = import_card(card, root / "store", f"{user_id}-{role_id}")
    return RoleSession(role_dir, str(root / "memory.db"), user_id=user_id, project_id="p",
                       work_model="work", role_model="role", card_context_enabled=True,
                       memory_provider=provider,
                       embedding_cache=(cache or root / "embeddings") if provider == "semantic" else None)


def injected(session, question):
    """Text of the memory blocks the model would see for this question."""
    result = session.request("context", {"user_content": question, "mode": "role"})
    blocks = result["context"]["blocks"]
    return " ".join(json.dumps(block, ensure_ascii=False) for block in blocks
                    if block["source"] == "memory_context")


def run(root, provider="embedded", cache=None):
    started = time.perf_counter()
    cases = []

    def check(name, passed, detail):
        cases.append({"case": name, "passed": bool(passed), "detail": detail})

    session = _session(root, provider, cache)
    try:
        first = session.request("remember", {"text": "用户喜欢喝乌龙茶。", "fact_key": "user.drink"})
        seen = injected(session, "我喜欢喝什么？")
        check("first_turn_recall", "乌龙茶" in seen, seen[:120])
        literal = injected(session, "乌龙茶")
        check("literal_match_recall", "乌龙茶" in literal, literal[:120])

        session.request("remember", {"text": "用户改喝白水了。", "fact_key": "user.drink"})
        seen = injected(session, "我现在喝什么？")
        check("update_is_recalled", "白水" in seen, seen[:120])
        check("stale_value_not_injected", "乌龙茶" not in seen, seen[:120])

        unrelated = injected(session, "我昨天看的动画是第几集？")
        check("no_mis_recall_on_unrelated_topic",
              "乌龙茶" not in unrelated and "白水" not in unrelated, unrelated[:120])

        session.request("remember", {"text": "用户喜欢晚上九点看动画。", "fact_key": "user.anime"})
        seen = injected(session, "我什么时候看动画？")
        check("second_fact_coexists", "九点" in seen and "白水" not in seen, seen[:120])

        other = session.memory.search("白水", user_id="user", role_id="other-role", project_id="p")
        check("cross_role_scope_is_clean", not other, str(other))

        relations = session.request("relate", {"subject": "用户", "predicate": "饮用",
                                              "object": "白水"})
        listed = session.request("relations_all", {})
        check("relation_recorded", any(item["object"] == "白水" for item in listed),
              json.dumps(listed, ensure_ascii=False)[:120])
        check("relation_source_present", all(item.get("source") for item in listed),
              json.dumps(listed, ensure_ascii=False)[:120])
        active = session.request("search", {"query": "白水"})
        if active:
            session.request("forget", {"id": active[0]["id"]})
        check("forget_stops_recall", not session.request("search", {"query": "白水"}),
              "forgotten row must not be searchable")
    finally:
        session.close()

    reopened = _session(root, provider, cache)
    try:
        drink = injected(reopened, "我现在喝什么？")
        check("restart_keeps_update", "乌龙茶" not in drink, drink[:120])
        anime = injected(reopened, "我什么时候看动画？")
        check("restart_keeps_other_fact", "九点" in anime, anime[:120])
        check("restart_does_not_mix_facts", "九点" not in drink and "白水" not in anime,
              f"drink={drink[:60]} anime={anime[:60]}")
    finally:
        reopened.close()

    return {"schema_version": 1, "created_at": datetime.now(timezone.utc).isoformat(),
            "provider": provider, "turns": len(cases), "cases": cases,
            "passed": sum(1 for case in cases if case["passed"]), "total": len(cases),
            "all_passed": all(case["passed"] for case in cases),
            "elapsed_seconds": round(time.perf_counter() - started, 2),
            "boundary": "scripted local regression; not an AML benchmark and not a quality certification"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("docs/project/memory-consistency-evidence.json"))
    parser.add_argument("--provider", default="embedded", choices=("embedded", "semantic"))
    parser.add_argument("--cache", type=Path, default=Path(".sumika-next/embedding-models"),
                        help="Embedding cache for the semantic provider (reused across runs)")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="sumika-memory-consistency-") as folder:
        report = run(Path(folder), provider=args.provider, cache=args.cache.resolve())
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf8")
    for case in report["cases"]:
        print(("PASS " if case["passed"] else "FAIL ") + case["case"])
    print(f"{report['passed']}/{report['total']} passed in {report['elapsed_seconds']}s")


if __name__ == "__main__":
    main()
