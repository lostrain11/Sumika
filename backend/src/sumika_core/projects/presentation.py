from __future__ import annotations

from typing import Any


class ConversationPresentation:
    namespace = "conversation-presentation/v1"

    def __init__(self, repository) -> None:
        self.repository = repository

    def project(self, session: dict[str, Any]) -> dict[str, Any]:
        owner = session.get("character_id")
        value = self.repository.get_record(self.namespace, session["id"], owner) if owner else None
        return {**session, **{key: value[key] for key in ("purpose", "pinned", "archived") if value and key in value}}

    def update(self, session: dict[str, Any], owner: str, changes: dict[str, Any]) -> dict[str, Any]:
        if session.get("character_id") != owner:
            raise ValueError("conversation is outside this assistant scope")
        if set(changes) - {"purpose", "pinned", "archived"}:
            raise ValueError("unsupported conversation preference")
        if "purpose" in changes and changes["purpose"] not in {"chat", "work", "unclassified"}:
            raise ValueError("invalid conversation purpose")
        if any(type(changes[key]) is not bool for key in ("pinned", "archived") if key in changes):
            raise ValueError("conversation flags must be boolean")
        previous = self.repository.get_record(self.namespace, session["id"], owner) or {}
        self.repository.save_record(self.namespace, session["id"], owner, {**previous, **changes})
        return self.project(session)
