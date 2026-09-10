"""Pure place and view-planning contracts for future Sumika hosts."""

from .contracts import (
    PLACES_SCHEMA_VERSION,
    AssistantLocation,
    EventApplication,
    Place,
    PlaceContractError,
    PlaceState,
    Room,
    RoomGroup,
    ViewAction,
    ViewBinding,
    ViewPlan,
    WindowGeometry,
    WindowPreference,
)
from .grouping import apply_location_event, group_locations, plan_views

__all__ = [
    "PLACES_SCHEMA_VERSION",
    "AssistantLocation",
    "EventApplication",
    "Place",
    "PlaceContractError",
    "PlaceState",
    "Room",
    "RoomGroup",
    "ViewAction",
    "ViewBinding",
    "ViewPlan",
    "WindowGeometry",
    "WindowPreference",
    "apply_location_event",
    "group_locations",
    "plan_views",
]
