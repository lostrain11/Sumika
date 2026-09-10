import ast
import json
import unittest
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

from sumika_core.places import (
    PLACES_SCHEMA_VERSION,
    AssistantLocation,
    PlaceContractError,
    PlaceState,
    ViewBinding,
    WindowGeometry,
    WindowPreference,
    apply_location_event,
    group_locations,
    plan_views,
)


def location(assistant_id, world_id, room_id, activity_point_id, revision, event_id):
    return AssistantLocation(assistant_id, assistant_id, world_id, room_id, activity_point_id, revision, event_id)


class PlaceContractTests(unittest.TestCase):
    def test_places_use_an_independent_versioned_contract(self):
        sample = location("one", "home-a", "bedroom", "desk", 1, "event-one")
        payload = json.loads(json.dumps(sample.to_dict()))
        self.assertEqual(payload["schema_version"], "sumika.places/v1")
        self.assertEqual(PLACES_SCHEMA_VERSION, "sumika.places/v1")
        self.assertNotEqual(PLACES_SCHEMA_VERSION, "sumika.domain/v1")
        self.assertEqual(payload["assistant_id"], payload["character_id"])
        with self.assertRaises(PlaceContractError):
            replace(sample, character_id="other")
        with self.assertRaises(FrozenInstanceError):
            sample.room_id = "other"

    def test_location_event_rejects_stale_and_is_idempotent(self):
        first = location("one", "home-a", "bedroom", "desk", 2, "event-two")
        applied = apply_location_event(PlaceState(), first)
        self.assertEqual(applied.disposition, "applied")
        duplicate = apply_location_event(applied.state, first)
        self.assertEqual(duplicate.disposition, "ignored-duplicate")
        self.assertEqual(duplicate.state, applied.state)
        stale = apply_location_event(applied.state, location("one", "home-a", "living", "sofa", 1, "event-one"))
        self.assertEqual(stale.disposition, "ignored-stale")
        self.assertEqual(stale.state.locations[0].room_id, "bedroom")
        self.assertEqual(
            apply_location_event(stale.state, location("one", "home-a", "living", "sofa", 1, "event-one")).disposition,
            "ignored-duplicate",
        )


class PlaceGroupingTests(unittest.TestCase):
    def test_bedrooms_living_room_and_separation_generate_transition_plan(self):
        one_bedroom = location("one", "home-a", "bedroom-one", "desk", 1, "one-bed")
        two_bedroom = location("two", "home-a", "bedroom-two", "bed", 1, "two-bed")
        bindings = (
            ViewBinding("one-window", "home-a", "bedroom-one", ("one",), created_order=2),
            ViewBinding("two-window", "home-a", "bedroom-two", ("two",), is_interactive=True, created_order=1),
        )
        initial = plan_views((one_bedroom, two_bedroom), bindings)
        self.assertEqual([action.action_kind for action in initial.actions], ["keep", "keep"])

        living = plan_views((
            replace(one_bedroom, room_id="living", activity_point_id="sofa", revision=2, event_id="one-living"),
            replace(two_bedroom, room_id="living", activity_point_id="window", revision=2, event_id="two-living"),
        ), bindings)
        self.assertEqual([action.action_kind for action in living.actions], ["rebind", "hide"])
        self.assertEqual(living.actions[0].view_id, "two-window")
        self.assertEqual(living.actions[0].assistant_ids, ("one", "two"))
        self.assertEqual(living.actions[1].requires_successful_action_ids, ("place-action-1",))
        self.assertEqual(living.actions[1].failure_disposition, "keep-visible")

        separated = plan_views((one_bedroom, two_bedroom), (ViewBinding(
            "living-window", "home-a", "living", ("one", "two"), created_order=0,
        ),))
        self.assertEqual([action.action_kind for action in separated.actions], ["rebind", "create"])
        self.assertEqual([action.assistant_ids for action in separated.actions], [("one",), ("two",)])

    def test_activity_points_and_display_mode_do_not_change_groups_or_members(self):
        locations = (
            location("one", "home-a", "living", "sofa", 1, "one"),
            location("two", "home-a", "living", "window", 1, "two"),
        )
        self.assertEqual(group_locations(locations)[0].assistant_ids, ("one", "two"))
        binding = ViewBinding("living-window", "home-a", "living", ("one", "two"), mode="compact")
        plan = plan_views(locations, (replace(binding, mode="fullscreen"),))
        self.assertEqual(plan.actions[0].action_kind, "keep")
        self.assertEqual(plan.actions[0].assistant_ids, ("one", "two"))

    def test_same_room_name_in_different_worlds_never_merges(self):
        groups = group_locations((
            location("one", "home-a", "living", "sofa", 1, "one"),
            location("two", "home-b", "living", "sofa", 1, "two"),
        ))
        self.assertEqual([(group.world_id, group.room_id) for group in groups], [("home-a", "living"), ("home-b", "living")])
        self.assertEqual([action.action_kind for action in plan_views(
            (location("one", "home-a", "living", "sofa", 1, "one"), location("two", "home-b", "living", "sofa", 1, "two")), (),
        ).actions], ["create", "create"])
        generated = plan_views((
            location("one", "home-a", "living", "sofa", 1, "one"),
            location("two", "home-b", "living", "sofa", 1, "two"),
        ), (ViewBinding("place-view-1", "home-c", "study", ("three",)),))
        self.assertEqual([action.view_id for action in generated.actions[:2]], ["place-view-2", "place-view-3"])

    def test_carrier_priority_and_window_preferences_are_preserved(self):
        preference = WindowPreference(WindowGeometry(20, 30, 640, 480), "display-two", True)
        target_preference = WindowPreference(WindowGeometry(50, 60, 800, 600), "display-one", False)
        bindings = (
            ViewBinding("oldest", "home-a", "bedroom", ("one",), preference, created_order=1),
            ViewBinding("interactive", "home-a", "study", ("two",), created_order=9, is_interactive=True),
            ViewBinding("target", "home-a", "living", ("three",), target_preference, created_order=12),
        )
        target = (
            location("one", "home-a", "living", "sofa", 2, "one"),
            location("two", "home-a", "living", "chair", 2, "two"),
            location("three", "home-a", "living", "window", 2, "three"),
        )
        plan = plan_views(target, bindings)
        self.assertEqual(plan.actions[0].view_id, "target")
        self.assertEqual(plan.actions[0].action_kind, "rebind")
        self.assertEqual(plan.actions[0].preference, target_preference)
        self.assertEqual([action.view_id for action in plan.actions[1:]], ["oldest", "interactive"])
        self.assertTrue(all(action.failure_disposition == "keep-visible" for action in plan.actions[1:]))

        without_target = plan_views(target[:2], bindings[:2])
        self.assertEqual(without_target.actions[0].view_id, "interactive")
        self.assertEqual(without_target.actions[0].preference, WindowPreference())

        oldest = plan_views(target[:2], (replace(bindings[0], is_interactive=False), replace(
            bindings[1], is_interactive=False,
        )))
        self.assertEqual(oldest.actions[0].view_id, "oldest")
        self.assertEqual(oldest.actions[0].preference, preference)

    def test_source_is_pure_and_does_not_import_runtime_adapters(self):
        package = Path(__file__).parents[1] / "src" / "sumika_core" / "places"
        forbidden = {"tauri", "storage", "app", "sumika_core.storage"}
        allowed = {"__future__", "dataclasses", "typing", "re", "contracts", "grouping"}
        for source in package.glob("*.py"):
            tree = ast.parse(source.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        self.assertNotIn(alias.name.split(".")[0], forbidden)
                elif isinstance(node, ast.ImportFrom) and node.module is not None:
                    self.assertNotIn(node.module.split(".")[0], forbidden)
                    self.assertIn(node.module, allowed)


if __name__ == "__main__":
    unittest.main()
