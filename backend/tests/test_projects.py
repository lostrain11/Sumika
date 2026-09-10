import copy
import unittest
from datetime import datetime, timezone

from sumika_core.projects import (
    ConversationAccessError,
    ProjectContractError,
    ProjectNotFoundError,
    ProjectService,
)


class FakeRepository:
    def __init__(self):
        self.records = {}
        self.deleted = []

    def save_record(self, namespace, record_id, assistant_id, payload):
        self.records[(namespace, record_id)] = copy.deepcopy(payload)
        return copy.deepcopy(payload)

    def get_record(self, namespace, record_id, assistant_id):
        return copy.deepcopy(self.records.get((namespace, record_id)))

    def list_records(self, namespace, assistant_id):
        return [
            copy.deepcopy(payload)
            for (record_namespace, _), payload in self.records.items()
            if record_namespace == namespace
        ]

    def delete_record(self, namespace, record_id, assistant_id):
        self.deleted.append((namespace, record_id, assistant_id))
        return self.records.pop((namespace, record_id), None) is not None


class FakeSource:
    def __init__(self, records):
        self.records = {record["source_id"]: copy.deepcopy(record) for record in records}
        self.list_calls = []
        self.get_calls = []

    def list_conversations(self, assistant_id):
        self.list_calls.append(assistant_id)
        return [copy.deepcopy(record) for record in self.records.values()]

    def get_conversation(self, source_id, assistant_id):
        self.get_calls.append((source_id, assistant_id))
        return copy.deepcopy(self.records.get(source_id))


class ProjectServiceTests(unittest.TestCase):
    def setUp(self):
        self.repository = FakeRepository()
        self.source = FakeSource([
            {
                "source_id": "conversation-one",
                "assistant_id": "assistant-one",
                "title": "First conversation",
                "summary": "A shallow summary",
                "updated_at": "2026-09-09T01:00:00Z",
                "messages": [{"content": "external history"}],
            },
            {
                "source_id": "conversation-two",
                "assistant_id": "assistant-one",
                "title": "Second conversation",
                "summary": "Another shallow summary",
                "updated_at": "2026-09-09T02:00:00Z",
                "messages": [{"content": "second external history"}],
            },
            {
                "source_id": "conversation-other",
                "assistant_id": "assistant-two",
                "title": "Private conversation",
                "summary": "Must not cross assistants",
                "updated_at": "2026-09-09T03:00:00Z",
                "messages": [{"content": "private external history"}],
            },
        ])
        ticks = iter(range(20))
        self.service = ProjectService(
            self.repository,
            {"core": self.source},
            clock=lambda: datetime(2026, 9, 9, 0, next(ticks), tzinfo=timezone.utc),
            id_factory=lambda: "project-generated",
        )

    def test_project_records_are_scoped_even_when_repository_leaks(self):
        first = self.service.create_project(
            "assistant-one",
            project_id="project-one",
            name="One",
            category="programming",
        )
        self.service.create_project(
            "assistant-two",
            project_id="project-two",
            name="Two",
            category="life",
        )

        self.assertEqual([item["id"] for item in self.service.list_projects("assistant-one")], ["project-one"])
        self.assertEqual(first["assistant_id"], "assistant-one")
        with self.assertRaises(ProjectNotFoundError):
            self.service.get_project("project-two", "assistant-one")
        with self.assertRaises(ProjectNotFoundError):
            self.service.update_project("project-one", "assistant-two", name="Stolen")

    def test_user_rename_is_not_overwritten_by_generated_metadata(self):
        self.service.create_project("assistant-one", project_id="project-one")
        renamed = self.service.update_project("project-one", "assistant-one", name="User title")
        suggested = self.service.apply_metadata(
            "project-one",
            "assistant-one",
            name="Generated title",
            category="research",
            summary="Generated summary",
        )

        self.assertEqual(renamed["manual_fields"], ["name"])
        self.assertEqual(suggested["name"], "User title")
        self.assertEqual(suggested["category"], "research")
        self.assertEqual(suggested["summary"], "Generated summary")
        self.assertEqual(suggested["manual_fields"], ["name"])

    def test_explicit_empty_creation_fields_are_not_replaced_by_defaults(self):
        for field_name in ("project_id", "name", "category"):
            with self.subTest(field=field_name), self.assertRaises(ProjectContractError):
                self.service.create_project("assistant-one", **{field_name: ""})

    def test_shallow_reads_do_not_query_sources_or_copy_history(self):
        self.service.create_project("assistant-one", project_id="project-one", name="One")
        self.service.attach_conversation(
            "project-one",
            "assistant-one",
            source="core",
            source_id="conversation-one",
        )
        self.source.list_calls.clear()
        self.source.get_calls.clear()

        listed = self.service.list_projects("assistant-one")
        fetched = self.service.get_project("project-one", "assistant-one")

        self.assertEqual(self.source.list_calls, [])
        self.assertEqual(self.source.get_calls, [])
        self.assertEqual(listed[0]["conversations"], [{"source": "core", "source_id": "conversation-one"}])
        self.assertNotIn("messages", repr(self.repository.records))
        self.assertEqual(fetched["directory"], None)

    def test_details_are_explicit_and_limited_to_attached_project_refs(self):
        self.service.create_project("assistant-one", project_id="project-one", name="One")
        self.service.create_project("assistant-one", project_id="project-two", name="Two")
        self.service.attach_conversation(
            "project-one", "assistant-one", source="core", source_id="conversation-one"
        )
        self.source.get_calls.clear()

        details = self.service.get_project_details("project-one", "assistant-one")

        self.assertEqual(self.source.get_calls, [("conversation-one", "assistant-one")])
        self.assertEqual(details["conversations"][0]["detail"]["messages"][0]["content"], "external history")
        with self.assertRaises(ConversationAccessError):
            self.service.get_project_details(
                "project-two",
                "assistant-one",
                references=[{"source": "core", "source_id": "conversation-one"}],
            )

    def test_source_ownership_is_checked_for_attach_details_and_unclassified(self):
        self.service.create_project("assistant-one", project_id="project-one", name="One")
        with self.assertRaises(ConversationAccessError):
            self.service.attach_conversation(
                "project-one",
                "assistant-one",
                source="core",
                source_id="conversation-other",
            )

        self.service.attach_conversation(
            "project-one", "assistant-one", source="core", source_id="conversation-one"
        )
        unclassified = self.service.list_unclassified_conversations("assistant-one")
        self.assertEqual([item["source_id"] for item in unclassified], ["conversation-two"])
        self.assertNotIn("messages", unclassified[0])

        self.source.records["conversation-one"]["assistant_id"] = "assistant-two"
        with self.assertRaises(ConversationAccessError):
            self.service.get_project_details("project-one", "assistant-one")

    def test_archive_search_and_directory_binding_are_metadata_only(self):
        created = self.service.create_project(
            "assistant-one",
            project_id="project-one",
            name="Local compiler",
            category="programming",
            summary="Track compiler work",
            directory="D:\\Code\\not-read-by-project-core",
        )
        self.assertEqual(created["directory"], "D:\\Code\\not-read-by-project-core")
        results = self.service.search("assistant-one", "compiler")
        self.assertEqual([item["id"] for item in results["projects"]], ["project-one"])
        self.service.archive_project("project-one", "assistant-one")
        self.assertEqual(self.service.list_projects("assistant-one"), [])
        self.assertEqual(
            [item["id"] for item in self.service.list_projects("assistant-one", archived=True)],
            ["project-one"],
        )
        self.assertEqual(self.repository.deleted, [])


if __name__ == "__main__":
    unittest.main()
