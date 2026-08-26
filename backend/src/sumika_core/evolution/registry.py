"""Read-only Evolution Knowledge Registry.

Registry entries are references and evaluation metadata, never role memories
and never an install/upgrade instruction.  Formal activation remains a user
approval boundary.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class EvolutionRegistry:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def list(self) -> list[dict[str, Any]]:
        if not self.path.is_file():
            return []
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        return list(value.get("entries", [])) if isinstance(value, dict) and isinstance(value.get("entries"), list) else []

    def check(self) -> dict[str, Any]:
        entries = self.list()
        return {"ok": self.path.is_file() and bool(entries), "entry_count": len(entries), "path": str(self.path), "mode": "read-only-curated", "requires_user_approval": True}
