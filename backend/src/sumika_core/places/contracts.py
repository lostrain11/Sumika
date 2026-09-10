"""Versioned, runtime-neutral contracts for place membership and companion views."""

from __future__ import annotations

import re
from dataclasses import dataclass, fields
from typing import Any, ClassVar


PLACES_SCHEMA_VERSION = "sumika.places/v1"
_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,159}")
_VIEW_MODES = ("compact", "panorama", "fullscreen", "transparent")
_ACTION_KINDS = ("keep", "rebind", "create", "hide")


class PlaceContractError(ValueError):
    """A bounded validation error that does not echo caller-controlled values."""


def _identifier(value: Any, field_name: str) -> None:
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise PlaceContractError(f"invalid {field_name}")


def _identifiers(value: Any, field_name: str, *, allow_empty: bool = False) -> None:
    if not isinstance(value, tuple) or len(value) > 64 or (not allow_empty and not value):
        raise PlaceContractError(f"invalid {field_name}")
    for item in value:
        _identifier(item, field_name)
    if len(set(value)) != len(value):
        raise PlaceContractError(f"duplicate {field_name}")


def _choice(value: Any, field_name: str, choices: tuple[str, ...]) -> None:
    if not isinstance(value, str) or value not in choices:
        raise PlaceContractError(f"invalid {field_name}")


class PlaceValue:
    __slots__ = ()
    kind: ClassVar[str]

    def to_dict(self) -> dict[str, Any]:
        def encode(value: Any) -> Any:
            if isinstance(value, PlaceValue):
                return value.to_dict()
            if isinstance(value, tuple):
                return [encode(item) for item in value]
            return value

        return {
            "schema_version": PLACES_SCHEMA_VERSION,
            "kind": self.kind,
            **{field.name: encode(getattr(self, field.name)) for field in fields(self)},
        }


@dataclass(frozen=True, slots=True)
class Place(PlaceValue):
    kind: ClassVar[str] = "place"
    world_id: str

    def __post_init__(self) -> None:
        _identifier(self.world_id, "world_id")


@dataclass(frozen=True, slots=True)
class Room(PlaceValue):
    kind: ClassVar[str] = "room"
    world_id: str
    room_id: str

    def __post_init__(self) -> None:
        _identifier(self.world_id, "world_id")
        _identifier(self.room_id, "room_id")


@dataclass(frozen=True, slots=True)
class AssistantLocation(PlaceValue):
    """The latest accepted location event for one assistant."""

    kind: ClassVar[str] = "assistant-location"
    assistant_id: str
    character_id: str
    world_id: str
    room_id: str
    activity_point_id: str | None
    revision: int
    event_id: str

    def __post_init__(self) -> None:
        for field_name in ("assistant_id", "character_id", "world_id", "room_id", "event_id"):
            _identifier(getattr(self, field_name), field_name)
        if self.assistant_id != self.character_id:
            raise PlaceContractError("assistant_id must equal character_id")
        if self.activity_point_id is not None:
            _identifier(self.activity_point_id, "activity_point_id")
        if type(self.revision) is not int or self.revision < 0:
            raise PlaceContractError("invalid revision")


@dataclass(frozen=True, slots=True)
class PlaceState(PlaceValue):
    """A caller-owned event deduplication snapshot; it has no storage dependency."""

    kind: ClassVar[str] = "place-state"
    locations: tuple[AssistantLocation, ...] = ()
    processed_event_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.locations, tuple) or len(self.locations) > 64:
            raise PlaceContractError("invalid locations")
        if any(not isinstance(location, AssistantLocation) for location in self.locations):
            raise PlaceContractError("invalid locations")
        assistant_ids = tuple(location.assistant_id for location in self.locations)
        if len(set(assistant_ids)) != len(assistant_ids):
            raise PlaceContractError("duplicate assistant locations")
        _identifiers(self.processed_event_ids, "processed_event_ids", allow_empty=True)
        if len(self.processed_event_ids) > 256:
            raise PlaceContractError("too many processed events")


@dataclass(frozen=True, slots=True)
class WindowGeometry(PlaceValue):
    kind: ClassVar[str] = "window-geometry"
    x: int
    y: int
    width: int
    height: int

    def __post_init__(self) -> None:
        if any(type(value) is not int for value in (self.x, self.y, self.width, self.height)):
            raise PlaceContractError("invalid window geometry")
        if not 1 <= self.width <= 32768 or not 1 <= self.height <= 32768:
            raise PlaceContractError("invalid window geometry")


@dataclass(frozen=True, slots=True)
class WindowPreference(PlaceValue):
    kind: ClassVar[str] = "window-preference"
    geometry: WindowGeometry | None = None
    display_id: str | None = None
    fullscreen: bool = False

    def __post_init__(self) -> None:
        if self.geometry is not None and not isinstance(self.geometry, WindowGeometry):
            raise PlaceContractError("invalid geometry")
        if self.display_id is not None:
            _identifier(self.display_id, "display_id")
        if type(self.fullscreen) is not bool:
            raise PlaceContractError("fullscreen must be boolean")


@dataclass(frozen=True, slots=True)
class ViewBinding(PlaceValue):
    kind: ClassVar[str] = "view-binding"
    view_id: str
    world_id: str
    room_id: str
    assistant_ids: tuple[str, ...]
    preference: WindowPreference = WindowPreference()
    mode: str = "compact"
    is_interactive: bool = False
    created_order: int = 0

    def __post_init__(self) -> None:
        for field_name in ("view_id", "world_id", "room_id"):
            _identifier(getattr(self, field_name), field_name)
        _identifiers(self.assistant_ids, "assistant_ids")
        if not isinstance(self.preference, WindowPreference):
            raise PlaceContractError("invalid window preference")
        _choice(self.mode, "mode", _VIEW_MODES)
        if type(self.is_interactive) is not bool:
            raise PlaceContractError("is_interactive must be boolean")
        if type(self.created_order) is not int or self.created_order < 0:
            raise PlaceContractError("invalid created_order")


@dataclass(frozen=True, slots=True)
class RoomGroup(PlaceValue):
    kind: ClassVar[str] = "room-group"
    world_id: str
    room_id: str
    assistant_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        _identifier(self.world_id, "world_id")
        _identifier(self.room_id, "room_id")
        _identifiers(self.assistant_ids, "assistant_ids")


@dataclass(frozen=True, slots=True)
class ViewAction(PlaceValue):
    kind: ClassVar[str] = "view-action"
    action_id: str
    action_kind: str
    view_id: str
    world_id: str
    room_id: str
    assistant_ids: tuple[str, ...]
    preference: WindowPreference
    requires_successful_action_ids: tuple[str, ...] = ()
    failure_disposition: str | None = None

    def __post_init__(self) -> None:
        for field_name in ("action_id", "view_id", "world_id", "room_id"):
            _identifier(getattr(self, field_name), field_name)
        _choice(self.action_kind, "action_kind", _ACTION_KINDS)
        _identifiers(self.assistant_ids, "assistant_ids", allow_empty=True)
        if not isinstance(self.preference, WindowPreference):
            raise PlaceContractError("invalid window preference")
        _identifiers(self.requires_successful_action_ids, "requires_successful_action_ids", allow_empty=True)
        if self.action_kind == "hide":
            if not self.requires_successful_action_ids or self.failure_disposition != "keep-visible":
                raise PlaceContractError("hide requires successful handoff")
        elif self.failure_disposition is not None or self.requires_successful_action_ids:
            raise PlaceContractError("invalid action transition")


@dataclass(frozen=True, slots=True)
class ViewPlan(PlaceValue):
    kind: ClassVar[str] = "view-plan"
    groups: tuple[RoomGroup, ...]
    actions: tuple[ViewAction, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.groups, tuple) or not isinstance(self.actions, tuple):
            raise PlaceContractError("invalid view plan")
        if any(not isinstance(group, RoomGroup) for group in self.groups):
            raise PlaceContractError("invalid view plan groups")
        if any(not isinstance(action, ViewAction) for action in self.actions):
            raise PlaceContractError("invalid view plan actions")
        group_keys = tuple((group.world_id, group.room_id) for group in self.groups)
        if len(set(group_keys)) != len(group_keys):
            raise PlaceContractError("duplicate room groups")
        action_ids = tuple(action.action_id for action in self.actions)
        if len(set(action_ids)) != len(action_ids):
            raise PlaceContractError("duplicate action ids")
        for action in self.actions:
            if action.action_kind == "hide" and not set(action.requires_successful_action_ids).issubset(action_ids):
                raise PlaceContractError("unknown handoff action")


@dataclass(frozen=True, slots=True)
class EventApplication(PlaceValue):
    kind: ClassVar[str] = "event-application"
    disposition: str
    state: PlaceState

    def __post_init__(self) -> None:
        _choice(self.disposition, "disposition", ("applied", "ignored-duplicate", "ignored-stale"))
        if not isinstance(self.state, PlaceState):
            raise PlaceContractError("invalid place state")
