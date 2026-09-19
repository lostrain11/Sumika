"""Real acceptance for the role-chat entry: two turns through one explicit provider."""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from extensions.models.settings import load as load_settings
from extensions.roles.card_context import script_ratios
from extensions.roles.chat import RoleChat


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--settings", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--session", default="role-chat-acceptance")
    args = parser.parse_args()
    if args.out.exists():
        parser.error("output exists; use a new evidence filename")
    settings = load_settings(args.settings)
    chat = RoleChat(settings)
    turns = []
    for message in ("今天排练怎么样？我叫小林，喜欢晚上九点看动画。",
                    "记得我昨天看到第几集吗？"):
        result = chat.reply(message, session_id=args.session)
        turns.append({"user": message, **{k: v for k, v in result.items() if k != "text"},
                      "text": result.get("text", ""),
                      "kana_ratio": script_ratios(result.get("text", ""))["kana"]})
    evidence = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "provider": settings["provider"],
        "model": settings["model"],
        "role_tools": 0,
        "key_source": "process_environment",
        "key_recorded": False,
        "turns": turns,
        "checks": {
            "language_policy_source": turns[0].get("language_policy_source"),
            "all_turns_chinese": all(t["kana_ratio"] == 0 for t in turns),
            "usage_reported": all(t.get("usage_status") == "reported" for t in turns),
        },
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf8")
    print(json.dumps({key: value for key, value in evidence["checks"].items()}, ensure_ascii=False, indent=2))
    print(json.dumps([{"kana": t["kana_ratio"], "usage": t.get("usage")} for t in turns], ensure_ascii=False))


if __name__ == "__main__":
    main()
