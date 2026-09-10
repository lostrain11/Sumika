"""Host-neutral contracts and validation for long-term memory adapters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping


MEMORY_CONTRACT_VERSION = 1
MEMORY_BASE_CAPABILITIES = frozenset({"list", "add", "delete"})
MEMORY_EXTENSION_CAPABILITIES = frozenset(
    {
        "scoped_delete",
        "update",
        "semantic_search",
        "export",
        "import",
        "context_sources",
        "migration",
    }
)
MEMORY_CAPABILITIES = MEMORY_BASE_CAPABILITIES | MEMORY_EXTENSION_CAPABILITIES
MEMORY_RECORD_STATUSES = frozenset({"active", "superseded", "deleted"})


class MemoryContractError(ValueError):
    """Raised when an adapter violates the memory contract."""


@dataclass(frozen=True, slots=True)
class MemoryScope:
    """Stable assistant identity, with character_id retained as a legacy alias."""

    assistant_id: str

    @property
    def character_id(self) -> str:
        return self.assistant_id

    @classmethod
    def from_ids(
        cls,
        *,
        assistant_id: str | None = None,
        character_id: str | None = None,
    ) -> MemoryScope:
        normalized_assistant = _optional_identifier(assistant_id, "assistant_id")
        normalized_character = _optional_identifier(character_id, "character_id")
        if normalized_assistant and normalized_character and normalized_assistant != normalized_character:
            raise MemoryContractError("assistant_id must equal legacy character_id")
        resolved = normalized_assistant or normalized_character
        if not resolved:
            raise MemoryContractError("assistant_id must not be empty")
        return cls(resolved)


def describe_capabilities(provider: Any) -> dict[str, Any]:
    version = getattr(provider, "contract_version", MEMORY_CONTRACT_VERSION)
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise MemoryContractError("Memory provider contract_version must be a positive integer")
    capabilities = validate_capabilities(getattr(provider, "capabilities", MEMORY_BASE_CAPABILITIES))
    return {"contract_version": version, "capabilities": sorted(capabilities)}


def validate_capabilities(capabilities: Iterable[str]) -> frozenset[str]:
    if isinstance(capabilities, str):
        raise MemoryContractError("Memory provider capabilities must be a collection")
    try:
        values = frozenset(capabilities)
    except TypeError as exc:
        raise MemoryContractError("Memory provider capabilities must be a collection") from exc
    if not all(isinstance(value, str) for value in values):
        raise MemoryContractError("Memory provider capabilities must be strings")
    unknown = values - MEMORY_CAPABILITIES
    if unknown:
        raise MemoryContractError(f"Unsupported memory capability: {sorted(unknown)[0]}")
    missing = MEMORY_BASE_CAPABILITIES - values
    if missing:
        raise MemoryContractError(f"Memory provider is missing capability: {sorted(missing)[0]}")
    return values


def require_capability(provider: Any, capability: str) -> None:
    if capability not in validate_capabilities(getattr(provider, "capabilities", MEMORY_BASE_CAPABILITIES)):
        raise MemoryContractError(f"Memory provider does not support capability: {capability}")


def validate_memory_record(
    record: Mapping[str, Any],
    *,
    scope: MemoryScope,
    expected_memory_id: str | None = None,
    require_active: bool = True,
    allow_legacy_fields: bool = False,
) -> dict[str, Any]:
    if not isinstance(record, Mapping):
        raise MemoryContractError("Memory provider returned an invalid record")
    value = dict(record)
    memory_id = _required_identifier(value.get("id"), "memory id")
    if expected_memory_id is not None and memory_id != expected_memory_id:
        raise MemoryContractError("Memory provider returned an unexpected memory id")
    record_assistant_id = _optional_identifier(value.get("assistant_id"), "record assistant_id")
    record_character_id = _optional_identifier(value.get("character_id"), "record character_id")
    observed_scope = record_assistant_id or record_character_id
    if not observed_scope or observed_scope != scope.assistant_id:
        raise MemoryContractError("Memory provider returned a record outside the requested assistant scope")
    if record_assistant_id and record_character_id and record_assistant_id != record_character_id:
        raise MemoryContractError("Memory provider returned inconsistent record ownership")
    _required_text(value.get("category"), "record category", maximum=64)
    _required_text(value.get("content"), "record content", maximum=20_000)
    _required_text(value.get("source"), "record source", maximum=128)
    metadata = value.get("metadata", {})
    if not isinstance(metadata, dict):
        raise MemoryContractError("Memory provider returned invalid record metadata")
    _required_text(value.get("created_at"), "record created_at", maximum=128)
    _required_text(value.get("updated_at"), "record updated_at", maximum=128)
    revision = value.get("revision")
    if revision is None and allow_legacy_fields:
        revision = 1
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        raise MemoryContractError("Memory provider returned invalid record revision")
    status = value.get("status")
    if status is None and allow_legacy_fields:
        status = "active"
    if status not in MEMORY_RECORD_STATUSES:
        raise MemoryContractError("Memory provider returned invalid record status")
    if require_active and status != "active":
        raise MemoryContractError("Memory provider returned an inactive record")
    value["id"] = memory_id
    value["assistant_id"] = scope.assistant_id
    value["character_id"] = scope.character_id
    value["metadata"] = dict(metadata)
    value["revision"] = revision
    value["status"] = status
    value["is_active"] = status == "active"
    return value


def validate_memory_records(
    records: Any,
    *,
    scope: MemoryScope,
    allow_legacy_fields: bool = False,
) -> list[dict[str, Any]]:
    if not isinstance(records, list):
        raise MemoryContractError("Memory provider returned an invalid record list")
    return [validate_memory_record(record, scope=scope, allow_legacy_fields=allow_legacy_fields) for record in records]


def validate_delete_result(result: Any, *, scope: MemoryScope, memory_id: str) -> bool:
    if not isinstance(result, Mapping):
        raise MemoryContractError("Memory provider must return a scoped delete result")
    if result.get("deleted") is not True:
        return False
    if result.get("memory_id") != memory_id:
        raise MemoryContractError("Memory provider returned an unexpected deleted memory id")
    result_scope = _optional_identifier(result.get("assistant_id"), "delete result assistant_id")
    if result_scope != scope.assistant_id:
        raise MemoryContractError("Memory provider did not confirm delete scope")
    if result.get("status") != "deleted":
        raise MemoryContractError("Memory provider returned an invalid delete status")
    return True


def safe_provider_error() -> str:
    return "Memory provider failed"


def _optional_identifier(value: Any, name: str) -> str | None:
    if value is None:
        return None
    return _required_identifier(value, name)


def _required_identifier(value: Any, name: str) -> str:
    return _required_text(value, name, maximum=256)


def _required_text(value: Any, name: str, *, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > maximum:
        raise MemoryContractError(f"{name} must be a non-empty short string")
    return value.strip()


__all__ = [
    "MEMORY_BASE_CAPABILITIES",
    "MEMORY_CAPABILITIES",
    "MEMORY_CONTRACT_VERSION",
    "MEMORY_EXTENSION_CAPABILITIES",
    "MemoryContractError",
    "MemoryScope",
    "describe_capabilities",
    "require_capability",
    "safe_provider_error",
    "validate_capabilities",
    "validate_delete_result",
    "validate_memory_record",
    "validate_memory_records",
]
