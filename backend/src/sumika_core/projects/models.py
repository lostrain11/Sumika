"""Validated project records and conversation references."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping


PROJECT_CATEGORIES = (
    "learning",
    "programming",
    "life",
    "health",
    "research",
    "custom",
)
PROJECT_FIELDS = {
    "id",
    "name",
    "category",
    "summary",
    "assistant_id",
    "manual_fields",
    "conversations",
    "directory",
    "archived",
    "updated_at",
}
EDITABLE_FIELDS = ("name", "category", "summary", "directory")


class ProjectContractError(ValueError):
    """Raised when project data does not satisfy the core contract."""


def _short_text(value: Any, field_name: str, *, maximum: int, empty: bool = False) -> str:
    if not isinstance(value, str):
        raise ProjectContractError(f"invalid {field_name}")
    normalized = value.strip()
    if (not empty and not normalized) or len(normalized) > maximum:
        raise ProjectContractError(f"invalid {field_name}")
    if any(ord(character) < 32 or ord(character) == 127 for character in normalized):
        raise ProjectContractError(f"invalid {field_name}")
    return normalized


def _timestamp(value: Any) -> str:
    normalized = _short_text(value, "updated_at", maximum=64)
    try:
        datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    except ValueError as error:
        raise ProjectContractError("invalid updated_at") from error
    return normalized


@dataclass(frozen=True, slots=True)
class ConversationRef:
    source: str
    source_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "source", _short_text(self.source, "source", maximum=80))
        object.__setattr__(self, "source_id", _short_text(self.source_id, "source_id", maximum=512))

    def to_dict(self) -> dict[str, str]:
        return {"source": self.source, "source_id": self.source_id}

    @classmethod
    def from_dict(cls, payload: Any) -> ConversationRef:
        if not isinstance(payload, Mapping) or set(payload) != {"source", "source_id"}:
            raise ProjectContractError("invalid conversation reference")
        return cls(source=payload["source"], source_id=payload["source_id"])


@dataclass(frozen=True, slots=True)
class Project:
    id: str
    name: str
    category: str
    summary: str
    assistant_id: str
    manual_fields: tuple[str, ...]
    conversations: tuple[ConversationRef, ...]
    directory: str | None
    archived: bool
    updated_at: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _short_text(self.id, "id", maximum=160))
        object.__setattr__(self, "name", _short_text(self.name, "name", maximum=160))
        category = _short_text(self.category, "category", maximum=64)
        if category not in PROJECT_CATEGORIES:
            raise ProjectContractError("invalid category")
        object.__setattr__(self, "category", category)
        object.__setattr__(self, "summary", _short_text(self.summary, "summary", maximum=500, empty=True))
        object.__setattr__(
            self,
            "assistant_id",
            _short_text(self.assistant_id, "assistant_id", maximum=160),
        )
        if not isinstance(self.manual_fields, tuple):
            raise ProjectContractError("invalid manual_fields")
        if len(set(self.manual_fields)) != len(self.manual_fields):
            raise ProjectContractError("duplicate manual_fields")
        if any(field not in EDITABLE_FIELDS for field in self.manual_fields):
            raise ProjectContractError("invalid manual_fields")
        if not isinstance(self.conversations, tuple):
            raise ProjectContractError("invalid conversations")
        if any(not isinstance(reference, ConversationRef) for reference in self.conversations):
            raise ProjectContractError("invalid conversations")
        keys = tuple((reference.source, reference.source_id) for reference in self.conversations)
        if len(set(keys)) != len(keys):
            raise ProjectContractError("duplicate conversations")
        if self.directory is not None:
            object.__setattr__(
                self,
                "directory",
                _short_text(self.directory, "directory", maximum=4096),
            )
        if type(self.archived) is not bool:
            raise ProjectContractError("invalid archived")
        object.__setattr__(self, "updated_at", _timestamp(self.updated_at))

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "category": self.category,
            "summary": self.summary,
            "assistant_id": self.assistant_id,
            "manual_fields": list(self.manual_fields),
            "conversations": [reference.to_dict() for reference in self.conversations],
            "directory": self.directory,
            "archived": self.archived,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, payload: Any) -> Project:
        if not isinstance(payload, Mapping) or set(payload) != PROJECT_FIELDS:
            raise ProjectContractError("invalid project record")
        manual_fields = payload["manual_fields"]
        conversations = payload["conversations"]
        if not isinstance(manual_fields, list) or not isinstance(conversations, list):
            raise ProjectContractError("invalid project collections")
        return cls(
            id=payload["id"],
            name=payload["name"],
            category=payload["category"],
            summary=payload["summary"],
            assistant_id=payload["assistant_id"],
            manual_fields=tuple(manual_fields),
            conversations=tuple(ConversationRef.from_dict(item) for item in conversations),
            directory=payload["directory"],
            archived=payload["archived"],
            updated_at=payload["updated_at"],
        )


__all__ = [
    "EDITABLE_FIELDS",
    "PROJECT_CATEGORIES",
    "ConversationRef",
    "Project",
    "ProjectContractError",
]
