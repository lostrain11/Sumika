"""Validated product state projections, not execution or authorization tokens."""

from __future__ import annotations

import re
from dataclasses import dataclass, fields
from typing import Any, ClassVar


DOMAIN_SCHEMA_VERSION = "sumika.domain/v1"
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,159}")


class DomainContractError(ValueError):
    """A bounded validation error that does not echo input values."""


def identifier(value: Any, field_name: str) -> None:
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise DomainContractError(f"invalid {field_name}")


def _text(value: Any, field_name: str) -> None:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > 160
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise DomainContractError(f"invalid {field_name}")


def _choice(value: Any, field_name: str, choices: tuple[str, ...]) -> None:
    if not isinstance(value, str) or value not in choices:
        raise DomainContractError(f"invalid {field_name}")


def _identifiers(value: Any, field_name: str) -> None:
    if not isinstance(value, tuple) or len(value) > 64:
        raise DomainContractError(f"invalid {field_name}")
    for item in value:
        identifier(item, field_name)
    if len(set(value)) != len(value):
        raise DomainContractError(f"duplicate {field_name}")


class DomainValue:
    __slots__ = ()
    kind: ClassVar[str]

    def to_dict(self) -> dict[str, Any]:
        def encode(value: Any) -> Any:
            if isinstance(value, DomainValue):
                return value.to_dict()
            if isinstance(value, tuple):
                return [encode(item) for item in value]
            return value

        return {
            "schema_version": DOMAIN_SCHEMA_VERSION,
            "kind": self.kind,
            **{item.name: encode(getattr(self, item.name)) for item in fields(self)},
        }


@dataclass(frozen=True, slots=True)
class ResourceRef(DomainValue):
    kind: ClassVar[str] = "resource"
    package_id: str
    version: str
    asset_id: str
    resource_kind: str

    def __post_init__(self) -> None:
        for field_name in ("package_id", "version", "asset_id"):
            identifier(getattr(self, field_name), field_name)
        _choice(self.resource_kind, "resource_kind", ("character", "avatar", "voice", "scene"))
        if self.version in ("unknown", "latest"):
            raise DomainContractError("resource version must be explicit")


@dataclass(frozen=True, slots=True)
class MemoryNamespace(DomainValue):
    kind: ClassVar[str] = "memory-namespace"
    namespace_id: str
    owner_assistant_id: str
    shared_with: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        identifier(self.namespace_id, "namespace_id")
        identifier(self.owner_assistant_id, "owner_assistant_id")
        _identifiers(self.shared_with, "shared_with")
        if self.owner_assistant_id in self.shared_with:
            raise DomainContractError("shared_with must exclude the owner")


@dataclass(frozen=True, slots=True)
class Assistant(DomainValue):
    kind: ClassVar[str] = "assistant"
    assistant_id: str
    character_id: str
    display_name: str
    memory: MemoryNamespace
    avatar: ResourceRef | None = None
    voice: ResourceRef | None = None
    legacy_avatar_id: str | None = None
    agent_preset_id: str | None = None

    def __post_init__(self) -> None:
        identifier(self.assistant_id, "assistant_id")
        identifier(self.character_id, "character_id")
        _text(self.display_name, "display_name")
        if not isinstance(self.memory, MemoryNamespace) or self.memory.owner_assistant_id != self.assistant_id:
            raise DomainContractError("memory owner must match assistant")
        for field_name in ("avatar", "voice"):
            resource = getattr(self, field_name)
            if resource is not None and (
                not isinstance(resource, ResourceRef) or resource.resource_kind != field_name
            ):
                raise DomainContractError(f"invalid {field_name} resource")
        for field_name in ("legacy_avatar_id", "agent_preset_id"):
            if getattr(self, field_name) is not None:
                identifier(getattr(self, field_name), field_name)


@dataclass(frozen=True, slots=True)
class Scene(DomainValue):
    kind: ClassVar[str] = "scene"
    scene_id: str
    assistant_ids: tuple[str, ...] = ()
    mode: str = "workbench"
    active_assistant_id: str | None = None
    drawer: str | None = None
    background: ResourceRef | None = None
    pause_when_closed: bool = True
    resume_budget_seconds: int = 0

    def __post_init__(self) -> None:
        identifier(self.scene_id, "scene_id")
        _identifiers(self.assistant_ids, "assistant_ids")
        _choice(self.mode, "mode", ("pet", "workbench", "home"))
        if self.active_assistant_id is not None:
            identifier(self.active_assistant_id, "active_assistant_id")
            if self.active_assistant_id not in self.assistant_ids:
                raise DomainContractError("active assistant must belong to scene")
        if self.drawer is not None:
            _choice(self.drawer, "drawer", ("workbench", "characters", "modules", "settings"))
            if self.mode == "pet":
                raise DomainContractError("pet mode cannot contain a drawer")
        if self.background is not None and (
            not isinstance(self.background, ResourceRef) or self.background.resource_kind != "scene"
        ):
            raise DomainContractError("invalid scene resource")
        if self.pause_when_closed is not True:
            raise DomainContractError("world must pause when closed")
        if type(self.resume_budget_seconds) is not int or not 0 <= self.resume_budget_seconds <= 300:
            raise DomainContractError("resume budget must be between 0 and 300 seconds")


@dataclass(frozen=True, slots=True)
class Capability(DomainValue):
    kind: ClassVar[str] = "capability"
    capability_id: str
    module_id: str
    implementation_id: str | None = None
    enabled: bool = False
    state: str = "unknown"
    required_permissions: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        identifier(self.capability_id, "capability_id")
        identifier(self.module_id, "module_id")
        if self.implementation_id is not None:
            identifier(self.implementation_id, "implementation_id")
        if type(self.enabled) is not bool:
            raise DomainContractError("enabled must be boolean")
        _choice(self.state, "state", ("disabled", "unconfigured", "ready", "unavailable", "error", "unknown"))
        _identifiers(self.required_permissions, "required_permissions")
        if self.state == "ready" and (not self.enabled or self.implementation_id in (None, "none")):
            raise DomainContractError("ready capability needs an enabled implementation")

    @property
    def visible(self) -> bool:
        return self.enabled and self.implementation_id not in (None, "none") and self.state not in (
            "disabled", "unconfigured"
        )


@dataclass(frozen=True, slots=True)
class Permission(DomainValue):
    kind: ClassVar[str] = "permission"
    subject_id: str
    capability_id: str
    resource_id: str
    state: str = "unknown"
    scope: str = "once"
    evidence_id: str | None = None

    def __post_init__(self) -> None:
        for field_name in ("subject_id", "capability_id", "resource_id"):
            identifier(getattr(self, field_name), field_name)
        _choice(self.state, "state", ("unknown", "needs-approval", "granted", "denied", "revoked", "expired"))
        _choice(self.scope, "scope", ("once", "session"))
        if self.evidence_id is not None:
            identifier(self.evidence_id, "evidence_id")
        if self.state == "granted" and self.evidence_id is None:
            raise DomainContractError("granted permission requires evidence")


@dataclass(frozen=True, slots=True)
class Device(DomainValue):
    kind: ClassVar[str] = "device"
    device_id: str
    device_kind: str
    state: str = "unconfigured"
    transport: str = "lan"
    read_only: bool = True
    remote_enabled: bool = False

    def __post_init__(self) -> None:
        identifier(self.device_id, "device_id")
        _choice(self.device_kind, "device_kind", ("camera", "sensor"))
        _choice(self.state, "state", ("unconfigured", "discovered", "registered", "unavailable", "revoked"))
        if self.transport != "lan" or self.read_only is not True or self.remote_enabled is not False:
            raise DomainContractError("v1 devices are LAN read-only with remote access disabled")


_CONTRACTS = {
    contract.kind: contract
    for contract in (ResourceRef, MemoryNamespace, Assistant, Scene, Capability, Permission, Device)
}
_TUPLE_FIELDS = {
    "memory-namespace": ("shared_with",),
    "scene": ("assistant_ids",),
    "capability": ("required_permissions",),
}
_OBJECT_FIELDS = {"assistant": ("memory", "avatar", "voice"), "scene": ("background",)}


def contract_from_dict(payload: Any) -> DomainValue:
    if not isinstance(payload, dict) or payload.get("schema_version") != DOMAIN_SCHEMA_VERSION:
        raise DomainContractError("unsupported domain schema")
    kind = payload.get("kind")
    if not isinstance(kind, str) or kind not in _CONTRACTS:
        raise DomainContractError("unknown domain kind")
    contract = _CONTRACTS[kind]
    names = {item.name for item in fields(contract)}
    if set(payload) - names - {"schema_version", "kind"}:
        raise DomainContractError("unknown domain fields")
    values = {name: payload[name] for name in names if name in payload}
    for name in _TUPLE_FIELDS.get(kind, ()):
        if name in values:
            if not isinstance(values[name], list) or len(values[name]) > 64:
                raise DomainContractError("invalid domain collection")
            values[name] = tuple(values[name])
    for name in _OBJECT_FIELDS.get(kind, ()):
        if values.get(name) is not None:
            expected = "memory-namespace" if name == "memory" else "resource"
            nested = values[name]
            if not isinstance(nested, dict) or nested.get("kind") != expected:
                raise DomainContractError("invalid nested domain kind")
            values[name] = contract_from_dict(nested)
    try:
        return contract(**values)
    except TypeError as error:
        raise DomainContractError("missing or invalid domain fields") from error
