from __future__ import annotations

from typing import Any


class CoreConversations:
    def __init__(self, storage) -> None:
        self.storage = storage

    def list_conversations(self, assistant_id: str) -> list[dict[str, Any]]:
        return [{"source_id": row["id"], "assistant_id": assistant_id, "title": row["title"],
                 "summary": "", "updated_at": row["updated_at"], "available": True}
                for row in self.storage.list_sessions() if row.get("character_id") == assistant_id]

    def get_conversation(self, source_id: str, assistant_id: str) -> dict[str, Any] | None:
        summary = next((row for row in self.list_conversations(assistant_id) if row["source_id"] == source_id), None)
        if summary is None:
            return None
        return {**summary, "messages": [row for row in self.storage.list_messages(source_id)
                                         if row.get("character_id") in {None, assistant_id}]}


class QualityConversations:
    def __init__(self, quality, storage) -> None:
        self.quality = quality
        self.storage = storage

    def list_conversations(self, assistant_id: str) -> list[dict[str, Any]]:
        rows = []
        for payload in self.storage.load_quality_tasks():
            snapshot = payload["snapshot"]
            if snapshot["scope"]["owner_id"] != assistant_id:
                continue
            rows.append({"source_id": snapshot["task_id"], "assistant_id": assistant_id,
                         "title": payload["metadata"].get("goal", "工作任务")[:120], "summary": "",
                         "updated_at": "", "available": True})
        return rows

    def get_conversation(self, source_id: str, assistant_id: str) -> dict[str, Any] | None:
        for payload in self.storage.load_quality_tasks():
            snapshot = payload["snapshot"]
            if snapshot["task_id"] == source_id and snapshot["scope"]["owner_id"] == assistant_id:
                return {"source_id": source_id, "assistant_id": assistant_id, "available": True,
                        "artifacts": payload["metadata"].get("artifacts", []), "status": snapshot.get("status")}
        return None
