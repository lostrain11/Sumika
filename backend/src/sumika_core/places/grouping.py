"""Pure grouping and view-transition planning for ``sumika.places/v1``."""

from __future__ import annotations

from dataclasses import replace

from .contracts import (
    AssistantLocation,
    EventApplication,
    PlaceContractError,
    PlaceState,
    RoomGroup,
    ViewAction,
    ViewBinding,
    ViewPlan,
    WindowPreference,
)


def group_locations(locations: tuple[AssistantLocation, ...]) -> tuple[RoomGroup, ...]:
    """Group only by world and room; activity points intentionally have no effect."""
    if not isinstance(locations, tuple) or any(not isinstance(item, AssistantLocation) for item in locations):
        raise PlaceContractError("invalid locations")
    by_room: dict[tuple[str, str], list[str]] = {}
    for location in locations:
        by_room.setdefault((location.world_id, location.room_id), []).append(location.assistant_id)
    return tuple(
        RoomGroup(world_id, room_id, tuple(sorted(assistant_ids)))
        for (world_id, room_id), assistant_ids in sorted(by_room.items())
    )


def apply_location_event(state: PlaceState, update: AssistantLocation) -> EventApplication:
    """Apply a monotonic location event without I/O or an implicit event store."""
    if not isinstance(state, PlaceState) or not isinstance(update, AssistantLocation):
        raise PlaceContractError("invalid location event")
    if update.event_id in state.processed_event_ids:
        return EventApplication("ignored-duplicate", state)

    event_ids = (*state.processed_event_ids, update.event_id)[-256:]
    locations_by_assistant = {location.assistant_id: location for location in state.locations}
    previous = locations_by_assistant.get(update.assistant_id)
    if previous is not None and update.revision <= previous.revision:
        return EventApplication("ignored-stale", replace(state, processed_event_ids=event_ids))
    locations_by_assistant[update.assistant_id] = update
    locations = tuple(sorted(locations_by_assistant.values(), key=lambda location: location.assistant_id))
    return EventApplication("applied", PlaceState(locations, event_ids))


def plan_views(
    locations: tuple[AssistantLocation, ...],
    bindings: tuple[ViewBinding, ...],
) -> ViewPlan:
    """Produce ordered host actions; only a host may execute the returned plan."""
    groups = group_locations(locations)
    _validate_bindings(bindings)
    available = list(bindings)
    allocated_view_ids = {binding.view_id for binding in bindings}
    primary_actions: list[ViewAction] = []
    action_by_group: dict[tuple[str, str], ViewAction] = {}

    for index, group in enumerate(groups, start=1):
        candidate = _select_carrier(group, available)
        action_id = f"place-action-{index}"
        if candidate is None:
            action = ViewAction(
                action_id,
                "create",
                _next_view_id(allocated_view_ids, index),
                group.world_id,
                group.room_id,
                group.assistant_ids,
                WindowPreference(),
            )
        else:
            available.remove(candidate)
            unchanged = (
                candidate.world_id == group.world_id
                and candidate.room_id == group.room_id
                and candidate.assistant_ids == group.assistant_ids
            )
            action = ViewAction(
                action_id,
                "keep" if unchanged else "rebind",
                candidate.view_id,
                group.world_id,
                group.room_id,
                group.assistant_ids,
                candidate.preference,
        )
        allocated_view_ids.add(action.view_id)
        primary_actions.append(action)
        action_by_group[(group.world_id, group.room_id)] = action

    hides: list[ViewAction] = []
    for binding in available:
        handoffs = _handoffs_for(binding, locations, primary_actions, action_by_group)
        hides.append(
            ViewAction(
                f"place-action-{len(primary_actions) + len(hides) + 1}",
                "hide",
                binding.view_id,
                binding.world_id,
                binding.room_id,
                binding.assistant_ids,
                binding.preference,
                handoffs,
                "keep-visible",
            )
        )
    return ViewPlan(groups, tuple((*primary_actions, *hides)))


def _validate_bindings(bindings: tuple[ViewBinding, ...]) -> None:
    if not isinstance(bindings, tuple) or any(not isinstance(binding, ViewBinding) for binding in bindings):
        raise PlaceContractError("invalid view bindings")
    view_ids = tuple(binding.view_id for binding in bindings)
    if len(set(view_ids)) != len(view_ids):
        raise PlaceContractError("duplicate view bindings")


def _select_carrier(group: RoomGroup, bindings: list[ViewBinding]) -> ViewBinding | None:
    group_members = set(group.assistant_ids)
    target = [binding for binding in bindings if (binding.world_id, binding.room_id) == (group.world_id, group.room_id)]
    interactive = [
        binding for binding in bindings
        if binding.is_interactive and group_members.intersection(binding.assistant_ids)
    ]
    participants = [binding for binding in bindings if group_members.intersection(binding.assistant_ids)]
    candidates = target or interactive or participants
    return min(candidates, key=lambda binding: (binding.created_order, binding.view_id)) if candidates else None


def _next_view_id(allocated_view_ids: set[str], starting_index: int) -> str:
    index = starting_index
    while f"place-view-{index}" in allocated_view_ids:
        index += 1
    return f"place-view-{index}"


def _handoffs_for(
    binding: ViewBinding,
    locations: tuple[AssistantLocation, ...],
    primary_actions: list[ViewAction],
    action_by_group: dict[tuple[str, str], ViewAction],
) -> tuple[str, ...]:
    destination_keys = {
        (location.world_id, location.room_id)
        for location in locations
        if location.assistant_id in binding.assistant_ids
    }
    actions = [action_by_group[key] for key in sorted(destination_keys)]
    if not actions:
        actions = primary_actions
    return tuple(action.action_id for action in actions)
