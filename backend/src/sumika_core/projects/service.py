"""Host-neutral project and conversation index service."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Protocol
from uuid import uuid4

from .models import EDITABLE_FIELDS, ConversationRef, Project, ProjectContractError


PROJECT_NAMESPACE = "projects/v1"
_UNSET = object()
_SOURCE_SUMMARY_FIELDS = (
    "source_id",
    "assistant_id",
    "title",
    "summary",
    "updated_at",
    "status",
    "capabilities",
)


class ProjectRepository(Protocol):
    def save_record(
        self,
        namespace: str,
        record_id: str,
        assistant_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]: ...

    def get_record(
        self,
        namespace: str,
        record_id: str,
        assistant_id: str,
    ) -> dict[str, Any] | None: ...

    def list_records(self, namespace: str, assistant_id: str) -> list[dict[str, Any]]: ...

    def delete_record(self, namespace: str, record_id: str, assistant_id: str) -> bool: ...


class ConversationSource(Protocol):
    def list_conversations(self, assistant_id: str) -> list[dict[str, Any]]: ...

    def get_conversation(self, source_id: str, assistant_id: str) -> dict[str, Any] | None: ...


class ProjectServiceError(ValueError):
    """Base error for project operations."""


class ProjectNotFoundError(ProjectServiceError):
    """Raised when a project is absent from the requested assistant scope."""


class ConversationAccessError(ProjectServiceError):
    """Raised when a source cannot prove conversation ownership or attachment."""


class ProjectService:
    def __init__(
        self,
        repository: ProjectRepository,
        sources: Mapping[str, ConversationSource] | None = None,
        *,
        clock: Callable[[], datetime] | None = None,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._repository = repository
        self._sources = dict(sources or {})
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._id_factory = id_factory or (lambda: f"project-{uuid4().hex}")
        for source in self._sources:
            ConversationRef(source, "validation")

    def create_project(
        self,
        assistant_id: str,
        *,
        project_id: str | None = None,
        name: str | None = None,
        category: str | None = None,
        summary: str | None = None,
        directory: str | None = None,
    ) -> dict[str, Any]:
        manual_fields = tuple(
            field
            for field, value in (
                ("name", name),
                ("category", category),
                ("summary", summary),
                ("directory", directory),
            )
            if value is not None
        )
        project = Project(
            id=self._id_factory() if project_id is None else project_id,
            name="Untitled project" if name is None else name,
            category="custom" if category is None else category,
            summary="" if summary is None else summary,
            assistant_id=assistant_id,
            manual_fields=manual_fields,
            conversations=(),
            directory=directory,
            archived=False,
            updated_at=self._now(),
        )
        if self._load(project.id, assistant_id) is not None:
            raise ProjectServiceError("project already exists")
        return self._save(project).to_dict()

    def list_projects(
        self,
        assistant_id: str,
        *,
        archived: bool | None = False,
        query: str | None = None,
    ) -> list[dict[str, Any]]:
        if archived is not None and type(archived) is not bool:
            raise ProjectServiceError("archived must be boolean or null")
        normalized_query = self._query(query)
        projects: list[Project] = []
        for payload in self._repository.list_records(PROJECT_NAMESPACE, assistant_id):
            project = self._owned_project(payload, assistant_id)
            if project is None or (archived is not None and project.archived != archived):
                continue
            if normalized_query and normalized_query not in self._project_search_text(project):
                continue
            projects.append(project)
        projects.sort(key=lambda item: (item.updated_at, item.id), reverse=True)
        return [project.to_dict() for project in projects]

    def get_project(self, project_id: str, assistant_id: str) -> dict[str, Any]:
        return self._require(project_id, assistant_id).to_dict()

    def update_project(
        self,
        project_id: str,
        assistant_id: str,
        *,
        name: Any = _UNSET,
        category: Any = _UNSET,
        summary: Any = _UNSET,
        directory: Any = _UNSET,
        manual: bool = True,
    ) -> dict[str, Any]:
        if type(manual) is not bool:
            raise ProjectServiceError("manual must be boolean")
        project = self._require(project_id, assistant_id)
        requested = {
            "name": name,
            "category": category,
            "summary": summary,
            "directory": directory,
        }
        changes: dict[str, Any] = {}
        manual_fields = list(project.manual_fields)
        for field_name, value in requested.items():
            if value is _UNSET or (not manual and field_name in project.manual_fields):
                continue
            changes[field_name] = value
            if manual and field_name not in manual_fields:
                manual_fields.append(field_name)
        if not changes:
            return project.to_dict()
        updated = replace(
            project,
            **changes,
            manual_fields=tuple(field for field in EDITABLE_FIELDS if field in manual_fields),
            updated_at=self._now(),
        )
        return self._save(updated).to_dict()

    def apply_metadata(
        self,
        project_id: str,
        assistant_id: str,
        *,
        name: str | None = None,
        category: str | None = None,
        summary: str | None = None,
    ) -> dict[str, Any]:
        """Apply host-provided free metadata without invoking a model."""

        return self.update_project(
            project_id,
            assistant_id,
            name=_UNSET if name is None else name,
            category=_UNSET if category is None else category,
            summary=_UNSET if summary is None else summary,
            manual=False,
        )

    def archive_project(
        self,
        project_id: str,
        assistant_id: str,
        *,
        archived: bool = True,
    ) -> dict[str, Any]:
        if type(archived) is not bool:
            raise ProjectServiceError("archived must be boolean")
        project = self._require(project_id, assistant_id)
        if project.archived == archived:
            return project.to_dict()
        return self._save(replace(project, archived=archived, updated_at=self._now())).to_dict()

    def attach_conversation(
        self,
        project_id: str,
        assistant_id: str,
        *,
        source: str,
        source_id: str,
    ) -> dict[str, Any]:
        project = self._require(project_id, assistant_id)
        reference = ConversationRef(source, source_id)
        if reference in project.conversations:
            return project.to_dict()
        self._verify_source_summary(reference, assistant_id)
        updated = replace(
            project,
            conversations=project.conversations + (reference,),
            updated_at=self._now(),
        )
        return self._save(updated).to_dict()

    def detach_conversation(
        self,
        project_id: str,
        assistant_id: str,
        *,
        source: str,
        source_id: str,
    ) -> dict[str, Any]:
        project = self._require(project_id, assistant_id)
        reference = ConversationRef(source, source_id)
        conversations = tuple(item for item in project.conversations if item != reference)
        if conversations == project.conversations:
            return project.to_dict()
        return self._save(
            replace(project, conversations=conversations, updated_at=self._now())
        ).to_dict()

    def get_project_details(
        self,
        project_id: str,
        assistant_id: str,
        *,
        references: list[Mapping[str, Any]] | None = None,
    ) -> dict[str, Any]:
        project = self._require(project_id, assistant_id)
        attached = {(item.source, item.source_id): item for item in project.conversations}
        selected = list(project.conversations)
        if references is not None:
            selected = []
            for payload in references:
                reference = ConversationRef.from_dict(payload)
                key = (reference.source, reference.source_id)
                if key not in attached:
                    raise ConversationAccessError("conversation is not attached to this project")
                selected.append(attached[key])

        details = [self._source_detail(reference, assistant_id) for reference in selected]
        return {"project": project.to_dict(), "conversations": details}

    def list_unclassified_conversations(
        self,
        assistant_id: str,
        *,
        query: str | None = None,
    ) -> list[dict[str, Any]]:
        attached = {
            (reference.source, reference.source_id)
            for project_payload in self.list_projects(assistant_id, archived=None)
            for reference in Project.from_dict(project_payload).conversations
        }
        normalized_query = self._query(query)
        records: list[dict[str, Any]] = []
        for source, adapter in self._sources.items():
            for payload in adapter.list_conversations(assistant_id):
                record = self._source_summary(source, payload, assistant_id)
                if record is None or (source, record["source_id"]) in attached:
                    continue
                if normalized_query and normalized_query not in self._source_search_text(record):
                    continue
                records.append(record)
        records.sort(key=lambda item: (str(item.get("updated_at", "")), item["source"], item["source_id"]), reverse=True)
        return records

    def search(self, assistant_id: str, query: str) -> dict[str, list[dict[str, Any]]]:
        normalized_query = self._query(query)
        if not normalized_query:
            raise ProjectServiceError("query must not be empty")
        return {
            "projects": self.list_projects(assistant_id, archived=None, query=query),
            "conversations": self.list_unclassified_conversations(assistant_id, query=query),
        }

    def _load(self, project_id: str, assistant_id: str) -> Project | None:
        payload = self._repository.get_record(PROJECT_NAMESPACE, project_id, assistant_id)
        return self._owned_project(payload, assistant_id)

    def _require(self, project_id: str, assistant_id: str) -> Project:
        project = self._load(project_id, assistant_id)
        if project is None:
            raise ProjectNotFoundError("project not found in assistant scope")
        return project

    def _save(self, project: Project) -> Project:
        payload = self._repository.save_record(
            PROJECT_NAMESPACE,
            project.id,
            project.assistant_id,
            project.to_dict(),
        )
        saved = self._owned_project(payload, project.assistant_id)
        if saved is None or saved.id != project.id:
            raise ProjectServiceError("repository returned an invalid project")
        return saved

    @staticmethod
    def _owned_project(payload: Any, assistant_id: str) -> Project | None:
        if not isinstance(payload, Mapping) or payload.get("assistant_id") != assistant_id:
            return None
        try:
            return Project.from_dict(payload)
        except ProjectContractError as error:
            raise ProjectServiceError("repository returned an invalid project") from error

    def _verify_source_summary(self, reference: ConversationRef, assistant_id: str) -> None:
        adapter = self._sources.get(reference.source)
        if adapter is None:
            return
        for payload in adapter.list_conversations(assistant_id):
            record = self._source_summary(reference.source, payload, assistant_id)
            if record is not None and record["source_id"] == reference.source_id:
                return
        raise ConversationAccessError("conversation source did not confirm assistant ownership")

    def _source_detail(self, reference: ConversationRef, assistant_id: str) -> dict[str, Any]:
        adapter = self._sources.get(reference.source)
        if adapter is None:
            return {**reference.to_dict(), "status": "unavailable", "detail": None}
        payload = adapter.get_conversation(reference.source_id, assistant_id)
        if payload is None:
            return {**reference.to_dict(), "status": "unavailable", "detail": None}
        if not isinstance(payload, Mapping):
            raise ConversationAccessError("conversation source returned invalid detail")
        if payload.get("assistant_id") != assistant_id or payload.get("source_id") != reference.source_id:
            raise ConversationAccessError("conversation source returned a different owner or record")
        if payload.get("source", reference.source) != reference.source:
            raise ConversationAccessError("conversation source returned a different source")
        return {
            **reference.to_dict(),
            "status": str(payload.get("status", "available")),
            "detail": deepcopy(dict(payload)),
        }

    @staticmethod
    def _source_summary(source: str, payload: Any, assistant_id: str) -> dict[str, Any] | None:
        if not isinstance(payload, Mapping) or payload.get("assistant_id") != assistant_id:
            return None
        if payload.get("source", source) != source:
            return None
        try:
            reference = ConversationRef(source, payload.get("source_id"))
        except ProjectContractError:
            return None
        record = {"source": source, "source_id": reference.source_id, "assistant_id": assistant_id}
        for field_name in _SOURCE_SUMMARY_FIELDS:
            if field_name in ("source_id", "assistant_id") or field_name not in payload:
                continue
            record[field_name] = deepcopy(payload[field_name])
        return record

    @staticmethod
    def _project_search_text(project: Project) -> str:
        return "\n".join((project.name, project.category, project.summary)).casefold()

    @staticmethod
    def _source_search_text(record: Mapping[str, Any]) -> str:
        return "\n".join(str(record.get(field, "")) for field in ("title", "summary")).casefold()

    @staticmethod
    def _query(query: str | None) -> str:
        if query is None:
            return ""
        if not isinstance(query, str) or len(query) > 200:
            raise ProjectServiceError("invalid query")
        return query.strip().casefold()

    def _now(self) -> str:
        value = self._clock()
        if not isinstance(value, datetime):
            raise ProjectServiceError("clock must return datetime")
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


__all__ = [
    "PROJECT_NAMESPACE",
    "ConversationAccessError",
    "ConversationSource",
    "ProjectNotFoundError",
    "ProjectRepository",
    "ProjectService",
    "ProjectServiceError",
]
