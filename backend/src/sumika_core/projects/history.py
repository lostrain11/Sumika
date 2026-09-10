"""Pure turn-based pagination over host-owned conversation messages."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Iterable, Mapping


class ConversationPageError(ValueError):
    """Raised when host messages or a pagination cursor are invalid."""


def paginate_turns(
    messages: Iterable[Mapping[str, Any]],
    *,
    before: str | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """Return chronological turns before a stable message ID cursor.

    The initial page contains the latest three turns. A cursor page contains
    ten turns unless the caller supplies another positive limit.
    """

    page_size = (3 if before is None else 10) if limit is None else limit
    if type(page_size) is not int or page_size <= 0 or page_size > 100:
        raise ConversationPageError("limit must be between 1 and 100")
    if before is not None and (not isinstance(before, str) or not before.strip()):
        raise ConversationPageError("before must be a stable message ID")

    turns: list[dict[str, Any]] = []
    current_turn: dict[str, Any] | None = None
    seen_ids: set[str] = set()
    message_to_turn: dict[str, int] = {}

    for raw_message in messages:
        message = _validated_message(raw_message)
        message_id = message["id"]
        if message_id in seen_ids:
            continue
        seen_ids.add(message_id)
        if message["role"] == "user":
            current_turn = {"id": message_id, "messages": [message]}
            turns.append(current_turn)
        elif current_turn is None:
            continue
        else:
            current_turn["messages"].append(message)
        message_to_turn[message_id] = len(turns) - 1

    if before is None:
        eligible = turns
    else:
        boundary = message_to_turn.get(before)
        if boundary is None:
            raise ConversationPageError("unknown before cursor")
        eligible = turns[:boundary]

    selected = eligible[-page_size:]
    has_more = len(eligible) > len(selected)
    next_before = selected[0]["id"] if selected and has_more else None
    return {
        "turns": deepcopy(selected),
        "next_before": next_before,
        "has_more": has_more,
    }


def _validated_message(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise ConversationPageError("message must be an object")
    required = {"id", "role", "content", "created_at"}
    if set(payload) != required:
        raise ConversationPageError("message fields must be id, role, content, created_at")
    message_id = payload["id"]
    role = payload["role"]
    created_at = payload["created_at"]
    if not isinstance(message_id, str) or not message_id.strip() or len(message_id) > 512:
        raise ConversationPageError("invalid message id")
    if not isinstance(role, str) or not role.strip() or len(role) > 64:
        raise ConversationPageError("invalid message role")
    if not isinstance(created_at, str) or not created_at.strip() or len(created_at) > 64:
        raise ConversationPageError("invalid message created_at")
    return {
        "id": message_id,
        "role": role,
        "content": deepcopy(payload["content"]),
        "created_at": created_at,
    }


__all__ = ["ConversationPageError", "paginate_turns"]
