"""A small, runtime-neutral Git workspace safety boundary.

The Agent harness owns sessions and tool execution.  This module owns the
durable file checkpoint needed before an Agent changes a real repository.  It
intentionally exposes summaries and hashes rather than file contents.
"""

from __future__ import annotations

import base64
import binascii
import difflib
import hashlib
import json
import os
import re
import shutil
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any
from uuid import uuid4


WORKSPACE_CHECKPOINT_FORMAT_VERSION = 1
_MAX_NAME_LENGTH = 200
_MAX_PATH_LENGTH = 4096
_MAX_FILE_BYTES = 16 * 1024 * 1024
_MAX_TOTAL_BYTES = 512 * 1024 * 1024
_MAX_STATUS_FILES = 256
_MAX_DIFF_FILES = 512
_MAX_COMMIT_FILES = 200
_MAX_COMMIT_PATH_CHARS = 24000
_MAX_COMMIT_MESSAGE_LENGTH = 4000
_MAX_PATCH_BYTES = 256 * 1024
_MAX_PATCH_FILE_BYTES = 128 * 1024


class WorkspaceError(ValueError):
    """A user-actionable workspace or recovery failure."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


class WorkspaceRuntime:
    """Inspect Git workspaces and create recoverable file checkpoints."""

    def __init__(self, data_dir: str | Path | None = None, *, logger: Any = None) -> None:
        self.logger = logger
        self._lock = threading.RLock()
        self._memory = data_dir is None
        self._memory_manifests: dict[str, dict[str, Any]] = {}
        if self._memory:
            self._store_root: Path | None = None
        else:
            self._store_root = Path(data_dir).expanduser().resolve() / "workspace-checkpoints"
            self._store_root.mkdir(parents=True, exist_ok=True)

    def inspect(self, path: str | Path) -> dict[str, Any]:
        started = time.monotonic()
        root, workspace = self._resolve_workspace(path)
        status = self._git_status(root)
        checkpoints = self.list_checkpoints(str(root))["checkpoints"]
        result = {"workspace": {**workspace, **status}, "checkpoint_count": len(checkpoints)}
        self._log("workspace inspect", workspace, started, files=len(status["files"]))
        return result

    def list_checkpoints(self, path: str | Path | None = None) -> dict[str, Any]:
        workspace_id: str | None = None
        if path is not None:
            root, workspace = self._resolve_workspace(path)
            del root
            workspace_id = workspace["id"]
        manifests = self._load_manifests()
        rows = [self._checkpoint_summary(item) for item in manifests if workspace_id is None or item.get("workspace_id") == workspace_id]
        rows.sort(key=lambda item: (str(item.get("created_at") or ""), str(item.get("id") or "")), reverse=True)
        return {"checkpoints": rows[:256]}

    def create_checkpoint(self, path: str | Path, *, name: str = "Agent checkpoint") -> dict[str, Any]:
        started = time.monotonic()
        root, workspace = self._resolve_workspace(path)
        clean_name = self._checkpoint_name(name)
        manifest = self._capture_manifest(root, workspace, clean_name)
        self._save_manifest(manifest)
        summary = self._checkpoint_summary(manifest)
        self._log("workspace checkpoint created", workspace, started, checkpoint_id=manifest["id"], files=summary["file_count"])
        return {"checkpoint": summary}

    def diff_checkpoint(self, checkpoint_id: str, *, path: str | Path | None = None) -> dict[str, Any]:
        started = time.monotonic()
        manifest = self._get_manifest(checkpoint_id)
        root, workspace = self._resolve_manifest_workspace(manifest, path)
        result = self._diff_manifest(manifest, root, workspace)
        self._log("workspace checkpoint diff", workspace, started, checkpoint_id=checkpoint_id, changed=result["counts"]["changed_total"])
        return self._public_diff(result)

    def restore_preview(self, checkpoint_id: str, *, path: str | Path | None = None) -> dict[str, Any]:
        manifest = self._get_manifest(checkpoint_id)
        root, workspace = self._resolve_manifest_workspace(manifest, path)
        result = self._diff_manifest(manifest, root, workspace)
        current = result["current_files"]
        desired = result["checkpoint_files"]
        changed_paths = result["changed_paths"]
        archive = [
            rel
            for rel in changed_paths
            if current.get(rel, {}).get("state") == "present"
        ]
        writes = [
            rel
            for rel in changed_paths
            if desired.get(rel, {}).get("state") == "present"
        ]
        result["restore"] = {
            "archive_count": len(archive),
            "write_count": len(writes),
            "archive_paths": archive[:_MAX_DIFF_FILES],
            "write_paths": writes[:_MAX_DIFF_FILES],
            "preview_token": result["preview_token"],
        }
        return self._public_diff(result)

    def restore(
        self,
        checkpoint_id: str,
        *,
        approved: bool = False,
        confirm_checkpoint: str | None = None,
        preview_token: str | None = None,
        path: str | Path | None = None,
    ) -> dict[str, Any]:
        if approved is not True or confirm_checkpoint != checkpoint_id:
            raise WorkspaceError("restoring a workspace checkpoint requires approval and an exact checkpoint id confirmation")
        started = time.monotonic()
        manifest = self._get_manifest(checkpoint_id)
        root, workspace = self._resolve_manifest_workspace(manifest, path)
        current_diff = self._diff_manifest(manifest, root, workspace)
        if preview_token is not None and preview_token != current_diff["preview_token"]:
            raise WorkspaceError("workspace changed after the restore preview; inspect and confirm again")
        self._verify_manifest_blobs(root, manifest)
        pre_restore = self._capture_manifest(root, workspace, f"恢复前 · {manifest['name']}")
        self._save_manifest(pre_restore)
        archive_root = self._archive_root(root)
        archive_entries: list[dict[str, str]] = []
        try:
            archive_entries = self._archive_current_changes(root, manifest, current_diff, archive_root)
            self._apply_manifest(root, manifest, set(current_diff["changed_paths"]))
        except Exception as error:
            # The pre-restore checkpoint is durable even if a later write fails.
            self._log("workspace restore failed", workspace, started, checkpoint_id=checkpoint_id, error_type=type(error).__name__)
            raise WorkspaceError(f"workspace restore failed; pre-restore checkpoint is {pre_restore['id']}") from error
        result = {
            "checkpoint": self._checkpoint_summary(manifest),
            "pre_restore_checkpoint": self._checkpoint_summary(pre_restore),
            "diff": self._public_diff(current_diff),
            "archive": {"root": str(archive_root), "entries": archive_entries},
            "restored": True,
        }
        self._log("workspace restored", workspace, started, checkpoint_id=checkpoint_id, archived=len(archive_entries))
        return result

    def preview_worktree(
        self,
        source_path: str | Path,
        destination_path: str | Path,
        branch: str,
    ) -> dict[str, Any]:
        """Preview creation of one linked worktree without changing Git state."""

        started = time.monotonic()
        source_root, source = self._resolve_workspace(source_path)
        clean_branch = self._branch_name(source_root, branch)
        destination = self._new_worktree_destination(source_root, destination_path)
        if source["head"] == "(unborn)":
            raise WorkspaceError("a worktree requires an existing source commit")
        if self._git_optional(source_root, "show-ref", "--verify", f"refs/heads/{clean_branch}"):
            raise WorkspaceError("worktree branch already exists")
        status = self._git_status(source_root)
        token_payload = {
            "source_workspace_id": source["id"],
            "source_head": source["head"],
            "branch": clean_branch,
            "destination": os.path.normcase(str(destination)),
        }
        preview_token = hashlib.sha256(
            json.dumps(token_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        worktree = {
            "id": self._workspace_id(destination),
            "title": destination.name,
            "path": str(destination),
            "branch": clean_branch,
            "head": source["head"],
            "kind": "linked",
        }
        self._log("workspace worktree previewed", source, started, branch=clean_branch, source_dirty=status["dirty"])
        return {
            "source": {**source, **status},
            "worktree": worktree,
            "preview_token": preview_token,
            "requires_approval": True,
            "includes_uncommitted_changes": False,
        }

    def create_worktree(
        self,
        source_path: str | Path,
        destination_path: str | Path,
        branch: str,
        *,
        approved: bool = False,
        confirm_branch: str | None = None,
        confirm_destination: str | None = None,
        preview_token: str | None = None,
    ) -> dict[str, Any]:
        """Create one new branch and linked worktree after an exact preview."""

        if approved is not True:
            raise WorkspaceError("worktree creation requires explicit approval")
        if not isinstance(preview_token, str) or re.fullmatch(r"[0-9a-f]{64}", preview_token) is None:
            raise WorkspaceError("worktree creation requires a valid preview token")
        started = time.monotonic()
        preview = self.preview_worktree(source_path, destination_path, branch)
        if (
            confirm_branch != preview["worktree"]["branch"]
            or confirm_destination != preview["worktree"]["path"]
        ):
            raise WorkspaceError("worktree creation requires exact branch and destination confirmation")
        if preview["preview_token"] != preview_token:
            raise WorkspaceError("source repository changed after the worktree preview; inspect and confirm again")
        source_root = Path(str(preview["source"]["path"]))
        destination = Path(str(preview["worktree"]["path"]))
        clean_branch = str(preview["worktree"]["branch"])
        try:
            self._git_bytes_with_timeout(
                source_root,
                120,
                "worktree",
                "add",
                "-b",
                clean_branch,
                str(destination),
                str(preview["source"]["head"]),
            )
        except WorkspaceError as error:
            self._log("workspace worktree create failed", preview["source"], started, branch=clean_branch, error_type=type(error).__name__)
            raise WorkspaceError(
                "Git worktree creation failed; Sumika did not remove any branch or destination left by Git"
            ) from error
        inspected = self.inspect(destination)["workspace"]
        if inspected.get("branch") != clean_branch or inspected.get("kind") != "linked":
            raise WorkspaceError("Git created a worktree that did not match the approved branch")
        self._log("workspace worktree created", inspected, started, branch=clean_branch, source_workspace_id=preview["source"]["id"])
        return {"source": preview["source"], "worktree": inspected, "created": True}

    def preview_commit(
        self,
        checkpoint_id: str,
        *,
        path: str | Path,
        message: str,
    ) -> dict[str, Any]:
        """Preview an exact local commit relative to a clean checkpoint."""

        started = time.monotonic()
        clean_message = self._commit_message(message)
        manifest = self._get_manifest(checkpoint_id)
        root, workspace = self._resolve_manifest_workspace(manifest, path)
        baseline = manifest.get("git") if isinstance(manifest.get("git"), dict) else {}
        if baseline.get("baseline_clean") is not True:
            raise WorkspaceError("Git commit requires a checkpoint captured from a clean workspace")
        if workspace["branch"] == "(detached)" or workspace["branch"] != baseline.get("branch"):
            raise WorkspaceError("workspace branch changed after the checkpoint")
        if workspace["head"] != baseline.get("head"):
            raise WorkspaceError("workspace HEAD changed after the checkpoint")
        diff = self._diff_manifest(manifest, root, workspace)
        changed_paths = list(diff["changed_paths"])
        if not changed_paths:
            raise WorkspaceError("workspace has no changes to commit")
        if len(changed_paths) > _MAX_COMMIT_FILES or sum(len(item) for item in changed_paths) > _MAX_COMMIT_PATH_CHARS:
            raise WorkspaceError("workspace has too many changed paths for one guarded commit")
        status = diff["workspace"]
        if int(status.get("excluded_file_count") or 0) or int(status.get("unsupported_file_count") or 0):
            raise WorkspaceError("workspace contains changes outside the supported commit path set")
        if int((status.get("status_counts") or {}).get("conflict", 0)):
            raise WorkspaceError("workspace has unresolved Git conflicts")
        staged_paths = set(self._git_path_list(root, "diff", "--cached", "--name-only", "--no-renames"))
        unexpected_staged = sorted(staged_paths.difference(changed_paths))
        if unexpected_staged:
            raise WorkspaceError("Git index contains staged paths outside this checkpoint diff")
        identity_name = self._git_optional(root, "config", "user.name")
        identity_email = self._git_optional(root, "config", "user.email")
        if not identity_name or not identity_email:
            raise WorkspaceError("Git user.name and user.email must be configured before committing")
        patch, patch_truncated, patch_omitted = self._checkpoint_patch(
            manifest,
            root,
            changed_paths,
            diff["current_files"],
        )
        message_sha256 = hashlib.sha256(clean_message.encode("utf-8")).hexdigest()
        token_payload = {
            "checkpoint": checkpoint_id,
            "workspace_preview": diff["preview_token"],
            "head": workspace["head"],
            "branch": workspace["branch"],
            "message_sha256": message_sha256,
        }
        commit_token = hashlib.sha256(
            json.dumps(token_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        self._log("workspace commit previewed", workspace, started, checkpoint_id=checkpoint_id, files=len(changed_paths))
        return {
            "checkpoint": self._checkpoint_summary(manifest),
            "workspace": status,
            "changed": True,
            "counts": diff["counts"],
            "files": diff["files"],
            "files_truncated": diff["files_truncated"],
            "patch": patch,
            "patch_truncated": patch_truncated,
            "patch_omitted_files": patch_omitted,
            "message_summary": clean_message.splitlines()[0],
            "message_sha256": message_sha256,
            "preview_token": commit_token,
            "requires_approval": True,
            "hooks": "disabled",
            "signing": "disabled",
        }

    def commit(
        self,
        checkpoint_id: str,
        *,
        path: str | Path,
        message: str,
        approved: bool = False,
        confirm_branch: str | None = None,
        preview_token: str | None = None,
    ) -> dict[str, Any]:
        """Create one local commit for the exact paths in a fresh preview."""

        if approved is not True:
            raise WorkspaceError("Git commit requires explicit approval")
        if not isinstance(preview_token, str) or re.fullmatch(r"[0-9a-f]{64}", preview_token) is None:
            raise WorkspaceError("Git commit requires a valid preview token")
        started = time.monotonic()
        preview = self.preview_commit(checkpoint_id, path=path, message=message)
        branch = str(preview["workspace"]["branch"])
        if confirm_branch != branch:
            raise WorkspaceError("Git commit requires exact branch confirmation")
        if preview["preview_token"] != preview_token:
            raise WorkspaceError("workspace changed after the commit preview; inspect and confirm again")
        root = Path(str(preview["workspace"]["path"]))
        changed_paths = [str(item["path"]) for item in preview["files"]]
        if preview.get("files_truncated") or not changed_paths:
            raise WorkspaceError("commit preview did not contain the complete changed path set")
        try:
            staged_before = set(
                self._git_path_list(root, "diff", "--cached", "--name-only", "--no-renames")
            )
            present_paths: list[str] = []
            missing_paths: list[str] = []
            for rel in changed_paths:
                target = self._checked_child(root, rel)
                if target.exists():
                    present_paths.append(rel)
                elif rel not in staged_before:
                    missing_paths.append(rel)
            if present_paths:
                self._git_bytes_with_timeout(root, 120, "add", "--all", "--", *present_paths)
            if missing_paths:
                self._git_bytes_with_timeout(root, 120, "add", "--update", "--", *missing_paths)
            staged_paths = set(self._git_path_list(root, "diff", "--cached", "--name-only", "--no-renames"))
            if staged_paths != set(changed_paths):
                raise WorkspaceError("Git index does not match the approved commit paths")
            before_head = str(preview["workspace"]["head"])
            self._git_with_input(
                root,
                ("commit", "--no-verify", "--no-gpg-sign", "--file=-"),
                self._commit_message(message) + "\n",
                timeout=120,
            )
            after_head = self._git(root, "rev-parse", "HEAD").strip()
            if not after_head or after_head == before_head:
                raise WorkspaceError("Git did not create a new commit")
            committed_paths = self._git_path_list(
                root,
                "diff-tree",
                "--no-commit-id",
                "--name-only",
                "--no-renames",
                "-r",
                after_head,
            )
            if set(committed_paths) != set(changed_paths):
                raise WorkspaceError("created commit does not match the approved preview")
        except WorkspaceError as error:
            self._log("workspace commit failed", preview["workspace"], started, checkpoint_id=checkpoint_id, error_type=type(error).__name__)
            raise
        inspected = self.inspect(root)["workspace"]
        self._log("workspace committed", inspected, started, checkpoint_id=checkpoint_id, commit=after_head[:12], files=len(committed_paths))
        return {
            "workspace": inspected,
            "checkpoint": preview["checkpoint"],
            "commit": after_head,
            "branch": branch,
            "file_count": len(committed_paths),
            "files": committed_paths,
            "hooks": "disabled",
            "signing": "disabled",
            "pushed": False,
        }

    # ---- workspace and Git inspection ---------------------------------

    def _resolve_workspace(self, path: str | Path) -> tuple[Path, dict[str, Any]]:
        if isinstance(path, Path):
            raw = str(path)
        elif isinstance(path, str):
            raw = path.strip()
        else:
            raise WorkspaceError("workspace path must be text")
        if not raw or len(raw) > _MAX_PATH_LENGTH or any(ord(char) < 32 for char in raw):
            raise WorkspaceError("workspace path must be a non-empty absolute path without control characters")
        candidate = Path(raw).expanduser()
        if not candidate.is_absolute():
            raise WorkspaceError("workspace path must be absolute")
        try:
            candidate = candidate.resolve(strict=True)
        except OSError as error:
            raise WorkspaceError("workspace path is not accessible") from error
        if not candidate.is_dir() or self._inside_deprecated(candidate):
            raise WorkspaceError("workspace path must be an accessible Git directory outside deprecated/")
        git_root_text = self._git(candidate, "rev-parse", "--show-toplevel").strip()
        if not git_root_text:
            raise WorkspaceError("workspace is not a Git repository")
        try:
            root = Path(git_root_text).resolve(strict=True)
        except OSError as error:
            raise WorkspaceError("Git repository root is not accessible") from error
        if not root.is_dir() or self._inside_deprecated(root):
            raise WorkspaceError("Git repository root is not a supported workspace")
        workspace_id = self._workspace_id(root)
        branch = self._git_optional(root, "symbolic-ref", "--short", "-q", "HEAD") or "(detached)"
        head = self._git_optional(root, "rev-parse", "HEAD") or "(unborn)"
        workspace = {
            "id": workspace_id,
            "title": root.name or str(root),
            "path": str(root),
            "branch": branch,
            "head": head,
            "kind": self._worktree_kind(root),
        }
        return root, workspace

    def _resolve_manifest_workspace(self, manifest: dict[str, Any], path: str | Path | None) -> tuple[Path, dict[str, Any]]:
        stored_path = manifest.get("workspace_path")
        target = path if path is not None else stored_path
        if not isinstance(target, (str, Path)) or not str(target):
            raise WorkspaceError("checkpoint does not contain a valid workspace path")
        root, workspace = self._resolve_workspace(target)
        if workspace["id"] != manifest.get("workspace_id"):
            raise WorkspaceError("checkpoint belongs to a different workspace")
        return root, workspace

    def _git_status(self, root: Path) -> dict[str, Any]:
        raw = self._git_bytes(root, "status", "--porcelain=v1", "--untracked-files=all", "-z")
        files: list[dict[str, str]] = []
        counts: dict[str, int] = {}
        total_file_count = 0
        supported_file_count = 0
        excluded_file_count = 0
        unsupported_file_count = 0
        records = raw.split(b"\0")
        index = 0
        while index < len(records):
            record = records[index]
            index += 1
            if not record:
                continue
            total_file_count += 1
            if len(record) < 3:
                unsupported_file_count += 1
                continue
            status = record[:2].decode("ascii", errors="replace")
            rel = os.fsdecode(record[3:])
            related_paths = [rel]
            if "R" in status or "C" in status:
                if index >= len(records) or not records[index]:
                    unsupported_file_count += 1
                    continue
                related_paths.append(os.fsdecode(records[index]))
                index += 1
            if any(not self._safe_relative(item) for item in related_paths):
                unsupported_file_count += 1
                continue
            if any(self._excluded_relative(item) for item in related_paths):
                excluded_file_count += 1
                continue
            label = self._status_label(status)
            counts[label] = counts.get(label, 0) + 1
            supported_file_count += 1
            if len(files) < _MAX_STATUS_FILES:
                files.append({"path": rel.replace("\\", "/"), "status": label})
        return {
            "dirty": total_file_count > 0,
            "status_counts": counts,
            "files": files,
            "file_count": supported_file_count,
            "total_file_count": total_file_count,
            "excluded_file_count": excluded_file_count,
            "unsupported_file_count": unsupported_file_count,
            "files_truncated": supported_file_count > len(files),
        }

    @staticmethod
    def _status_label(status: str) -> str:
        if "?" in status:
            return "untracked"
        if status in {"DD", "AU", "UD", "UA", "DU", "AA", "UU"}:
            return "conflict"
        if "D" in status:
            return "deleted"
        if "A" in status:
            return "added"
        if "R" in status:
            return "renamed"
        if "M" in status:
            return "modified"
        return "changed"

    # ---- checkpoint capture and diff ----------------------------------

    def _capture_manifest(self, root: Path, workspace: dict[str, Any], name: str) -> dict[str, Any]:
        tracked = self._git_path_list(root, "ls-files")
        untracked = self._git_path_list(root, "ls-files", "--others", "--exclude-standard")
        paths = sorted({path for path in tracked + untracked if self._safe_relative(path) and not self._excluded_relative(path)})
        files: dict[str, dict[str, Any]] = {}
        total_bytes = 0
        for rel in paths:
            target = self._checked_child(root, rel)
            if target.is_symlink():
                raise WorkspaceError(f"checkpoint cannot capture symlink path: {rel}")
            if target.exists():
                if not target.is_file():
                    continue
                size = target.stat().st_size
                if size > _MAX_FILE_BYTES:
                    raise WorkspaceError(f"file is too large for a checkpoint: {rel}")
                total_bytes += size
                if total_bytes > _MAX_TOTAL_BYTES:
                    raise WorkspaceError("workspace exceeds the checkpoint size limit")
                digest = self._sha256_file(target)
                files[rel.replace("\\", "/")] = {
                    "state": "present",
                    "sha256": digest,
                    "size": size,
                    "mode": target.stat().st_mode & 0o777,
                    "blob": digest,
                }
            elif rel in tracked:
                files[rel.replace("\\", "/")] = {"state": "absent", "sha256": None, "size": 0, "mode": None, "blob": None}
        status = self._git_status(root)
        manifest = {
            "format_version": WORKSPACE_CHECKPOINT_FORMAT_VERSION,
            "id": f"wschk-{uuid4().hex[:20]}",
            "name": name,
            "workspace_id": workspace["id"],
            "workspace_path": workspace["path"],
            "created_at": _utc_now(),
            "git": {
                "head": workspace["head"],
                "branch": workspace["branch"],
                "baseline_clean": not status["dirty"],
            },
            "files": files,
            "total_bytes": total_bytes,
        }
        return manifest

    def _diff_manifest(self, manifest: dict[str, Any], root: Path, workspace: dict[str, Any]) -> dict[str, Any]:
        current = self._capture_manifest(root, workspace, "__current__")
        desired_files = manifest.get("files") if isinstance(manifest.get("files"), dict) else {}
        current_files = current.get("files") if isinstance(current.get("files"), dict) else {}
        rows: list[dict[str, Any]] = []
        changed_paths: list[str] = []
        added = removed = changed = 0
        for rel in sorted(set(desired_files) | set(current_files)):
            before = desired_files.get(rel)
            after = current_files.get(rel)
            if before is None and after is not None:
                status = "added"
                added += 1
            elif before is not None and after is None:
                status = "removed"
                removed += 1
            elif before != after:
                status = "changed"
                changed += 1
            else:
                continue
            changed_paths.append(rel)
            if len(rows) < _MAX_DIFF_FILES:
                rows.append({
                    "path": rel,
                    "status": status,
                    "before": self._file_summary(before),
                    "after": self._file_summary(after),
                })
        token_payload = {"checkpoint": manifest.get("id"), "files": current_files}
        preview_token = hashlib.sha256(json.dumps(token_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
        return {
            "checkpoint": self._checkpoint_summary(manifest),
            "workspace": {**workspace, **self._git_status(root)},
            "changed": bool(added or removed or changed),
            "counts": {"added": added, "removed": removed, "changed": changed, "changed_total": added + removed + changed},
            "files": rows,
            "files_truncated": len(changed_paths) > len(rows),
            "preview_token": preview_token,
            "changed_paths": changed_paths,
            "current_files": current_files,
            "checkpoint_files": desired_files,
        }

    @staticmethod
    def _file_summary(value: dict[str, Any] | None) -> dict[str, Any] | None:
        if value is None:
            return None
        return {key: value.get(key) for key in ("state", "size", "sha256", "mode")}

    @staticmethod
    def _public_diff(value: dict[str, Any]) -> dict[str, Any]:
        return {
            key: item
            for key, item in value.items()
            if key not in {"changed_paths", "current_files", "checkpoint_files"}
        }

    def _checkpoint_patch(
        self,
        manifest: dict[str, Any],
        root: Path,
        changed_paths: list[str],
        current_files: dict[str, Any],
    ) -> tuple[str, bool, list[str]]:
        checkpoint_files = manifest.get("files") if isinstance(manifest.get("files"), dict) else {}
        checkpoint_dir = None if self._memory else self._store_root / str(manifest["id"]) / "blobs"  # type: ignore[operator]
        sections: list[str] = []
        total_bytes = 0
        truncated = False
        omitted: list[str] = []
        for rel in changed_paths:
            before_entry = checkpoint_files.get(rel)
            after_entry = current_files.get(rel)
            before = b""
            after = b""
            if isinstance(before_entry, dict) and before_entry.get("state") == "present":
                before = self._blob_bytes(manifest, before_entry, checkpoint_dir)
            if isinstance(after_entry, dict) and after_entry.get("state") == "present":
                target = self._checked_child(root, rel)
                if target.is_symlink() or not target.is_file():
                    raise WorkspaceError(f"workspace changed while commit patch was being generated: {rel}")
                after = target.read_bytes()
                if hashlib.sha256(after).hexdigest() != after_entry.get("sha256"):
                    raise WorkspaceError(f"workspace changed while commit patch was being generated: {rel}")
            if (
                len(before) > _MAX_PATCH_FILE_BYTES
                or len(after) > _MAX_PATCH_FILE_BYTES
                or b"\0" in before
                or b"\0" in after
            ):
                omitted.append(rel)
                continue
            try:
                before_text = before.decode("utf-8")
                after_text = after.decode("utf-8")
            except UnicodeDecodeError:
                omitted.append(rel)
                continue
            before_name = (
                f"a/{rel}"
                if isinstance(before_entry, dict) and before_entry.get("state") == "present"
                else "/dev/null"
            )
            after_name = (
                f"b/{rel}"
                if isinstance(after_entry, dict) and after_entry.get("state") == "present"
                else "/dev/null"
            )
            diff_lines = list(
                difflib.unified_diff(
                    before_text.splitlines(keepends=True),
                    after_text.splitlines(keepends=True),
                    fromfile=before_name,
                    tofile=after_name,
                )
            )
            rendered: list[str] = [f"diff --git a/{rel} b/{rel}\n"]
            for line in diff_lines:
                rendered.append(line)
                if not line.endswith(("\n", "\r")):
                    rendered.append("\n\\ No newline at end of file\n")
            section = "".join(rendered)
            encoded = section.encode("utf-8")
            remaining = _MAX_PATCH_BYTES - total_bytes
            if len(encoded) <= remaining:
                sections.append(section)
                total_bytes += len(encoded)
                continue
            if remaining > 0:
                sections.append(encoded[:remaining].decode("utf-8", errors="ignore"))
            truncated = True
            break
        return "".join(sections), truncated, omitted

    def _checkpoint_summary(self, manifest: dict[str, Any]) -> dict[str, Any]:
        files = manifest.get("files") if isinstance(manifest.get("files"), dict) else {}
        present = [item for item in files.values() if isinstance(item, dict) and item.get("state") == "present"]
        return {
            "id": manifest.get("id"),
            "name": manifest.get("name"),
            "created_at": manifest.get("created_at"),
            "workspace_id": manifest.get("workspace_id"),
            "head": (manifest.get("git") or {}).get("head"),
            "branch": (manifest.get("git") or {}).get("branch"),
            "baseline_clean": (manifest.get("git") or {}).get("baseline_clean") is True,
            "file_count": len(present),
            "total_bytes": sum(int(item.get("size") or 0) for item in present),
        }

    # ---- durable manifest/blob storage --------------------------------

    def _save_manifest(self, manifest: dict[str, Any]) -> None:
        with self._lock:
            if self._memory:
                # Keep an encoded private copy for the in-memory test/runtime
                # mode; a manifest containing only hashes cannot be restored.
                stored = json.loads(json.dumps(manifest))
                blobs: dict[str, str] = {}
                root = Path(str(manifest["workspace_path"]))
                for rel, item in (manifest.get("files") or {}).items():
                    if not isinstance(item, dict) or item.get("state") != "present":
                        continue
                    source = self._checked_child(root, rel)
                    if source.is_symlink() or not source.is_file():
                        raise WorkspaceError(f"workspace changed while checkpoint was being captured: {rel}")
                    blob = source.read_bytes()
                    if hashlib.sha256(blob).hexdigest() != item.get("sha256"):
                        raise WorkspaceError(f"workspace changed while checkpoint was being captured: {rel}")
                    blobs[str(item["blob"])] = base64.b64encode(blob).decode("ascii")
                stored["_memory_blobs"] = blobs
                self._memory_manifests[str(manifest["id"])] = stored
                return
            assert self._store_root is not None
            checkpoint_dir = self._store_root / str(manifest["id"])
            blob_dir = checkpoint_dir / "blobs"
            blob_dir.mkdir(parents=True, exist_ok=False)
            root = Path(str(manifest["workspace_path"]))
            for rel, item in (manifest.get("files") or {}).items():
                if not isinstance(item, dict) or item.get("state") != "present":
                    continue
                source = self._checked_child(root, rel)
                if not source.is_file() or source.is_symlink():
                    raise WorkspaceError(f"workspace changed while checkpoint was being captured: {rel}")
                destination = blob_dir / str(item["blob"])
                shutil.copyfile(source, destination)
                if self._sha256_file(destination) != item.get("sha256"):
                    raise WorkspaceError(f"workspace changed while checkpoint was being captured: {rel}")
            self._atomic_json(checkpoint_dir / "manifest.json", manifest)

    def _load_manifests(self) -> list[dict[str, Any]]:
        with self._lock:
            if self._memory:
                return [json.loads(json.dumps(item)) for item in self._memory_manifests.values()]
            assert self._store_root is not None
            result: list[dict[str, Any]] = []
            for manifest_path in self._store_root.glob("wschk-*/manifest.json"):
                try:
                    value = json.loads(manifest_path.read_text(encoding="utf-8"))
                    self._validate_manifest(value)
                except (OSError, ValueError, TypeError, json.JSONDecodeError):
                    if self.logger:
                        self.logger.warning("workspace checkpoint ignored invalid manifest")
                    continue
                result.append(value)
            return result

    def _get_manifest(self, checkpoint_id: str) -> dict[str, Any]:
        if not isinstance(checkpoint_id, str) or not re.fullmatch(r"wschk-[0-9a-f]{20}", checkpoint_id):
            raise WorkspaceError("invalid workspace checkpoint id")
        for item in self._load_manifests():
            if item.get("id") == checkpoint_id:
                return item
        raise WorkspaceError(f"unknown workspace checkpoint: {checkpoint_id}")

    @staticmethod
    def _validate_manifest(value: Any) -> None:
        if not isinstance(value, dict) or value.get("format_version") != WORKSPACE_CHECKPOINT_FORMAT_VERSION:
            raise ValueError("unsupported workspace checkpoint format")
        if not isinstance(value.get("id"), str) or not re.fullmatch(r"wschk-[0-9a-f]{20}", value["id"]):
            raise ValueError("invalid workspace checkpoint id")
        if not isinstance(value.get("workspace_id"), str) or not isinstance(value.get("workspace_path"), str):
            raise ValueError("invalid workspace checkpoint workspace")
        if not isinstance(value.get("files"), dict):
            raise ValueError("invalid workspace checkpoint files")
        for rel, item in value["files"].items():
            if not WorkspaceRuntime._safe_relative(rel) or WorkspaceRuntime._excluded_relative(rel):
                raise ValueError("invalid workspace checkpoint path")
            if not isinstance(item, dict) or item.get("state") not in {"present", "absent"}:
                raise ValueError("invalid workspace checkpoint file")
            if item.get("state") == "present":
                digest = item.get("sha256")
                if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest) or item.get("blob") != digest:
                    raise ValueError("invalid workspace checkpoint digest")

    @staticmethod
    def _atomic_json(path: Path, value: dict[str, Any]) -> None:
        temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        temporary.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")
        os.replace(temporary, path)

    # ---- restore and archive ------------------------------------------

    def _archive_root(self, root: Path) -> Path:
        deprecated = root / "deprecated"
        if deprecated.is_symlink():
            raise WorkspaceError("workspace deprecated directory cannot be a symlink")
        base = deprecated / _timestamp()
        candidate = base
        suffix = 1
        while candidate.exists():
            candidate = base.with_name(f"{base.name}-{suffix}")
            suffix += 1
        archive_root = candidate / "workspace-restore"
        archive_root.mkdir(parents=True, exist_ok=False)
        return archive_root

    def _archive_current_changes(
        self,
        root: Path,
        manifest: dict[str, Any],
        diff: dict[str, Any],
        archive_root: Path,
    ) -> list[dict[str, str]]:
        desired = manifest.get("files") if isinstance(manifest.get("files"), dict) else {}
        current = diff.get("current_files") if isinstance(diff.get("current_files"), dict) else {}
        entries: list[dict[str, str]] = []
        for rel, item in current.items():
            if not isinstance(item, dict) or item.get("state") != "present":
                continue
            if desired.get(rel) == item:
                continue
            source = self._checked_child(root, rel)
            if not source.exists() or source.is_symlink() or not source.is_file():
                continue
            destination = self._archive_destination(archive_root, rel)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(destination))
            entries.append({"original_path": rel, "archive_path": str(destination.relative_to(root)).replace("\\", "/")})
        return entries

    @staticmethod
    def _archive_destination(archive_root: Path, rel: str) -> Path:
        destination = archive_root.joinpath(*PurePosixPath(rel).parts)
        if not destination.exists():
            return destination
        stem = destination.stem
        suffix = destination.suffix
        index = 1
        while True:
            candidate = destination.with_name(f"{stem}-{index}{suffix}")
            if not candidate.exists():
                return candidate
            index += 1

    def _apply_manifest(self, root: Path, manifest: dict[str, Any], changed_paths: set[str]) -> None:
        files = manifest.get("files") if isinstance(manifest.get("files"), dict) else {}
        checkpoint_dir = None if self._memory else self._store_root / str(manifest["id"]) / "blobs"  # type: ignore[operator]
        for rel, item in files.items():
            if not isinstance(item, dict) or rel not in changed_paths:
                continue
            target = self._checked_child(root, rel)
            if item.get("state") == "absent":
                if target.exists() or target.is_symlink():
                    raise WorkspaceError(f"restore could not clear archived path: {rel}")
                continue
            if target.is_symlink():
                raise WorkspaceError(f"restore cannot replace a symlink path: {rel}")
            blob = self._blob_bytes(manifest, item, checkpoint_dir)
            if hashlib.sha256(blob).hexdigest() != item.get("sha256"):
                raise WorkspaceError(f"checkpoint blob failed integrity check: {rel}")
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_name(f".{target.name}.{uuid4().hex}.sumika-restore")
            temporary.write_bytes(blob)
            os.replace(temporary, target)
            mode = item.get("mode")
            if isinstance(mode, int):
                try:
                    target.chmod(mode)
                except OSError:
                    pass

    def _verify_manifest_blobs(self, root: Path, manifest: dict[str, Any]) -> None:
        files = manifest.get("files") if isinstance(manifest.get("files"), dict) else {}
        checkpoint_dir = None if self._memory else self._store_root / str(manifest["id"]) / "blobs"  # type: ignore[operator]
        for rel, item in files.items():
            if not isinstance(item, dict) or item.get("state") != "present":
                continue
            target = self._checked_child(root, rel)
            if target.is_symlink() or (target.exists() and not target.is_file()):
                raise WorkspaceError(f"restore target is not a regular file path: {rel}")
            blob = self._blob_bytes(manifest, item, checkpoint_dir)
            if hashlib.sha256(blob).hexdigest() != item.get("sha256"):
                raise WorkspaceError(f"checkpoint blob failed integrity check: {rel}")

    def _blob_bytes(self, manifest: dict[str, Any], item: dict[str, Any], checkpoint_dir: Path | None) -> bytes:
        digest = str(item.get("blob") or "")
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise WorkspaceError("checkpoint blob reference is invalid")
        if self._memory:
            # Memory mode stores a compact private copy alongside the manifest.
            blobs = manifest.get("_memory_blobs") if isinstance(manifest.get("_memory_blobs"), dict) else {}
            encoded = blobs.get(digest)
            if not isinstance(encoded, str):
                raise WorkspaceError("checkpoint blob is unavailable")
            try:
                return base64.b64decode(encoded.encode("ascii"), validate=True)
            except (ValueError, binascii.Error) as error:
                raise WorkspaceError("checkpoint blob is invalid") from error
        if checkpoint_dir is None:
            raise WorkspaceError("checkpoint blob directory is unavailable")
        try:
            if checkpoint_dir.is_symlink() or not checkpoint_dir.is_dir():
                raise WorkspaceError("checkpoint blob directory is invalid")
            source = checkpoint_dir / digest
            if source.is_symlink():
                raise WorkspaceError("checkpoint blob path is invalid")
            candidate = source.resolve(strict=True)
            if candidate.parent != checkpoint_dir.resolve(strict=True):
                raise WorkspaceError("checkpoint blob path is invalid")
            return candidate.read_bytes()
        except OSError as error:
            raise WorkspaceError("checkpoint blob is unavailable") from error

    # ---- low-level helpers --------------------------------------------

    def _git(self, root: Path, *args: str) -> str:
        return self._git_bytes(root, *args).decode("utf-8", errors="replace")

    def _git_optional(self, root: Path, *args: str) -> str:
        try:
            return self._git(root, *args).strip()
        except WorkspaceError:
            return ""

    def _git_bytes(self, root: Path, *args: str) -> bytes:
        return self._git_bytes_with_timeout(root, 10, *args)

    def _git_bytes_with_timeout(self, root: Path, timeout: int, *args: str) -> bytes:
        try:
            completed = subprocess.run(
                ["git", "-C", str(root), *args],
                capture_output=True,
                timeout=timeout,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise WorkspaceError("Git is unavailable or did not respond") from error
        if completed.returncode != 0:
            detail = completed.stderr.decode("utf-8", errors="replace").strip()
            raise WorkspaceError(detail[:240] or "Git command failed")
        return completed.stdout

    @staticmethod
    def _git_with_input(root: Path, args: tuple[str, ...], value: str, *, timeout: int) -> bytes:
        try:
            completed = subprocess.run(
                ["git", "-C", str(root), *args],
                input=value.encode("utf-8"),
                capture_output=True,
                timeout=timeout,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise WorkspaceError("Git is unavailable or did not respond") from error
        if completed.returncode != 0:
            detail = completed.stderr.decode("utf-8", errors="replace").strip()
            raise WorkspaceError(detail[:240] or "Git command failed")
        return completed.stdout

    def _git_path_list(self, root: Path, *args: str) -> list[str]:
        raw = self._git_bytes(root, *args, "-z")
        return [os.fsdecode(item) for item in raw.split(b"\0") if item]

    def _worktree_kind(self, root: Path) -> str:
        def absolute_git_path(value: str) -> Path:
            path = Path(value)
            return (path if path.is_absolute() else root / path).resolve(strict=False)

        git_dir = absolute_git_path(self._git(root, "rev-parse", "--git-dir").strip())
        common_dir = absolute_git_path(self._git(root, "rev-parse", "--git-common-dir").strip())
        return "primary" if os.path.normcase(str(git_dir)) == os.path.normcase(str(common_dir)) else "linked"

    @staticmethod
    def _workspace_id(root: Path) -> str:
        return "ws-" + hashlib.sha256(os.path.normcase(str(root)).encode("utf-8")).hexdigest()[:24]

    @staticmethod
    def _sha256_file(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _checkpoint_name(value: Any) -> str:
        if not isinstance(value, str) or not value.strip():
            return "Agent checkpoint"
        name = value.strip()
        if len(name) > _MAX_NAME_LENGTH or any(ord(char) < 32 or ord(char) == 127 for char in name):
            raise WorkspaceError("checkpoint name is too long or contains control characters")
        return name

    @staticmethod
    def _commit_message(value: Any) -> str:
        if not isinstance(value, str):
            raise WorkspaceError("commit message must be text")
        message = value.replace("\r\n", "\n").replace("\r", "\n").strip()
        if not message:
            raise WorkspaceError("commit message must not be empty")
        if len(message) > _MAX_COMMIT_MESSAGE_LENGTH or any(
            (ord(char) < 32 and char not in {"\n", "\t"}) or ord(char) == 127
            for char in message
        ):
            raise WorkspaceError("commit message is too long or contains unsupported control characters")
        return message

    def _branch_name(self, root: Path, value: Any) -> str:
        if not isinstance(value, str):
            raise WorkspaceError("worktree branch must be text")
        branch = value.strip()
        if not branch or len(branch) > 240 or any(ord(char) < 32 or ord(char) == 127 for char in branch):
            raise WorkspaceError("worktree branch is invalid")
        try:
            self._git_bytes(root, "check-ref-format", "--branch", branch)
        except WorkspaceError as error:
            raise WorkspaceError("worktree branch is not a valid Git branch name") from error
        return branch

    def _new_worktree_destination(self, root: Path, value: Any) -> Path:
        if isinstance(value, Path):
            raw = str(value)
        elif isinstance(value, str):
            raw = value.strip()
        else:
            raise WorkspaceError("worktree destination must be text")
        if not raw or len(raw) > _MAX_PATH_LENGTH or any(ord(char) < 32 or ord(char) == 127 for char in raw):
            raise WorkspaceError("worktree destination must be a non-empty absolute path without control characters")
        candidate = Path(raw).expanduser()
        if not candidate.is_absolute():
            raise WorkspaceError("worktree destination must be absolute")
        if candidate.exists() or candidate.is_symlink():
            raise WorkspaceError("worktree destination already exists")
        try:
            parent = candidate.parent.resolve(strict=True)
        except OSError as error:
            raise WorkspaceError("worktree destination parent is not accessible") from error
        if not parent.is_dir() or parent.is_symlink():
            raise WorkspaceError("worktree destination parent must be a regular directory")
        destination = parent / candidate.name
        if self._inside_deprecated(destination):
            raise WorkspaceError("worktree destination must be outside deprecated/")
        destination_text = os.path.normcase(str(destination))
        worktree_roots: list[Path] = [root]
        for line in self._git(root, "worktree", "list", "--porcelain").splitlines():
            if line.startswith("worktree "):
                worktree_roots.append(Path(line[len("worktree ") :]).resolve(strict=False))
        for worktree_root in worktree_roots:
            worktree_text = os.path.normcase(str(worktree_root.resolve(strict=False)))
            try:
                if os.path.commonpath((worktree_text, destination_text)) == worktree_text:
                    raise WorkspaceError("worktree destination must be outside every existing worktree")
            except ValueError:
                continue
            if destination_text == worktree_text:
                raise WorkspaceError("worktree destination is already registered")
        return destination

    @staticmethod
    def _safe_relative(value: str) -> bool:
        if not isinstance(value, str) or not value or len(value) > _MAX_PATH_LENGTH:
            return False
        if any(ord(char) < 32 or ord(char) == 127 for char in value):
            return False
        path = PurePosixPath(value.replace("\\", "/"))
        return not path.is_absolute() and ".." not in path.parts and not any(part in {"", "."} for part in path.parts)

    @staticmethod
    def _excluded_relative(value: str) -> bool:
        parts = PurePosixPath(value.replace("\\", "/")).parts
        return bool(parts) and parts[0].lower() == "deprecated"

    @staticmethod
    def _inside_deprecated(path: Path) -> bool:
        return any(part.lower() == "deprecated" for part in path.parts)

    def _checked_child(self, root: Path, rel: str) -> Path:
        if not self._safe_relative(rel) or self._excluded_relative(rel):
            raise WorkspaceError("workspace path is outside the supported file set")
        candidate = root.joinpath(*PurePosixPath(rel.replace("\\", "/")).parts)
        try:
            parent = candidate.parent.resolve(strict=False)
            if os.path.commonpath((str(root), str(parent))) != str(root):
                raise WorkspaceError("workspace path escapes the repository")
            current = root
            for part in PurePosixPath(rel.replace("\\", "/")).parts[:-1]:
                current = current / part
                if current.is_symlink():
                    raise WorkspaceError("workspace path contains a symlink")
        except ValueError as error:
            raise WorkspaceError("workspace path is invalid") from error
        return candidate

    def _log(self, message: str, workspace: dict[str, Any], started: float, **fields: Any) -> None:
        if not self.logger:
            return
        safe = {"workspace_id": workspace.get("id"), "duration_ms": round((time.monotonic() - started) * 1000), **fields}
        self.logger.info("%s %s", message, " ".join(f"{key}={value}" for key, value in safe.items()))


__all__ = ["WorkspaceError", "WorkspaceRuntime", "WORKSPACE_CHECKPOINT_FORMAT_VERSION"]
