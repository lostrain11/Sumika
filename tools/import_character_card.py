"""Import a community character card (SillyTavern V1/V2/V3 JSON, PNG, or CHARX)
into a Sumika data directory as a chat character.

This command is intentionally offline: it reads the card file, converts it with
``sumika_core.character_import``, and writes one character row into the local
SQLite storage.  It never contacts a provider, DSH, or the network.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))

from sumika_core.character_import import CharacterCardError, convert_character_card, parse_card_bytes  # noqa: E402
from sumika_core.server import _validate_character_config, _validate_character_name  # noqa: E402
from sumika_core.storage import Storage  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", required=True, help="path to a .json/.png/.charx character card")
    parser.add_argument(
        "--data-dir",
        default=os.environ.get("SUMIKA_DATA_DIR", str(ROOT / ".sumika")),
        help="Sumika data directory (default: SUMIKA_DATA_DIR or .sumika)",
    )
    parser.add_argument("--name", default=None, help="override the character name from the card")
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="replace the persona of an existing character with the same name",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the converted config without writing to storage",
    )
    args = parser.parse_args()

    card_path = Path(args.file)
    try:
        card = parse_card_bytes(card_path.read_bytes())
        result = convert_character_card(card, character_name=args.name)
        _validate_character_name(result["name"])
        config = _validate_character_config(result["config"])
    except (CharacterCardError, ValueError, TypeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    summary = {
        "name": result["name"],
        "mapped": result["mapped"],
        "warnings": result["warnings"],
        "book_entries": result["book_entries"],
    }
    if args.dry_run:
        print(json.dumps({**summary, "config": config}, ensure_ascii=False, indent=2))
        return 0

    storage = Storage(Path(args.data_dir) / "sumika.db")
    existing = next(
        (row for row in storage.list_characters() if row["name"] == result["name"]),
        None,
    )
    if existing is not None:
        if not args.overwrite:
            print(
                f"error: character already exists: {result['name']} (pass --overwrite to replace)",
                file=sys.stderr,
            )
            return 2
        character = storage.update_character_config(existing["id"], config)
        action = "updated"
    else:
        character = storage.create_character(f"character-{os.urandom(6).hex()}", result["name"], config)
        action = "created"
    print(json.dumps({**summary, "action": action, "character_id": character["id"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
