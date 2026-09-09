"""Pure, allowlisted adapters from existing character and module snapshots."""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from .contracts import Assistant, Capability, DomainContractError, MemoryNamespace


def assistant_from_character(record: Mapping[str, Any]) -> Assistant:
    if not isinstance(record, Mapping):
        raise DomainContractError("invalid character record")
    character_id = record.get("id")
    config = record.get("config", {})
    if not isinstance(config, Mapping):
        raise DomainContractError("invalid character config")
    return Assistant(
        assistant_id=character_id,
        character_id=character_id,
        display_name=record.get("name"),
        memory=MemoryNamespace(namespace_id=character_id, owner_assistant_id=character_id),
        legacy_avatar_id=None if config.get("avatar_model_id") == "" else config.get("avatar_model_id"),
    )


def assistants_from_characters(records: Iterable[Mapping[str, Any]]) -> tuple[Assistant, ...]:
    assistants: list[Assistant] = []
    identifiers: set[str] = set()
    for record in records:
        assistant = assistant_from_character(record)
        if assistant.assistant_id in identifiers:
            raise DomainContractError("duplicate character identifier")
        if len(assistants) >= 64:
            raise DomainContractError("too many assistants")
        identifiers.add(assistant.assistant_id)
        assistants.append(assistant)
    return tuple(assistants)


def capability_from_module(record: Mapping[str, Any]) -> Capability:
    if not isinstance(record, Mapping):
        raise DomainContractError("invalid module record")
    enabled = record.get("enabled", False)
    if type(enabled) is not bool:
        raise DomainContractError("enabled must be boolean")
    implementation_id = record.get("implementation_id")
    if implementation_id == "none":
        implementation_id = None
    status = record.get("status", "unknown")
    if not enabled:
        state = "disabled"
    elif not implementation_id:
        state = "unconfigured"
    elif status in ("ready", "available", "healthy", "running"):
        state = "ready"
    elif status in ("disabled", "unconfigured", "unavailable", "error"):
        state = status
    else:
        state = "unknown"
    permissions = record.get("permissions", [])
    if not isinstance(permissions, (list, tuple)):
        raise DomainContractError("invalid module permissions")
    return Capability(
        capability_id=record.get("capability"),
        module_id=record.get("id"),
        implementation_id=implementation_id,
        enabled=enabled,
        state=state,
        required_permissions=tuple(permissions),
    )
