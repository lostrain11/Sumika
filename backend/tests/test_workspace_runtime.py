import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sumika_core.workspace import WorkspaceError, WorkspaceRuntime


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


class WorkspaceRuntimeTests(unittest.TestCase):
    def _repository(self, directory: str) -> Path:
        root = Path(directory) / "repo"
        root.mkdir()
        _git(root, "init", "-q")
        _git(root, "config", "user.email", "sumika-tests@example.invalid")
        _git(root, "config", "user.name", "Sumika tests")
        (root / "tracked.txt").write_text("before\n", encoding="utf-8")
        (root / "removed.txt").write_text("restore me\n", encoding="utf-8")
        _git(root, "add", ".")
        _git(root, "commit", "-qm", "fixture")
        return root

    def test_memory_checkpoint_restores_and_keeps_internal_blobs_private(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self._repository(directory)
            runtime = WorkspaceRuntime()
            created = runtime.create_checkpoint(root, name="before edit")
            checkpoint = created["checkpoint"]

            (root / "tracked.txt").write_text("after\n", encoding="utf-8")
            (root / "removed.txt").unlink()
            (root / "new.txt").write_text("new\n", encoding="utf-8")
            preview = runtime.restore_preview(checkpoint["id"], path=root)
            self.assertEqual(preview["restore"]["write_count"], 2)
            self.assertEqual(preview["restore"]["archive_count"], 2)
            self.assertNotIn("current_files", preview)
            self.assertNotIn("checkpoint_files", preview)
            self.assertNotIn("_memory_blobs", str(preview))

            restored = runtime.restore(
                checkpoint["id"],
                path=root,
                approved=True,
                confirm_checkpoint=checkpoint["id"],
                preview_token=preview["restore"]["preview_token"],
            )
            self.assertTrue(restored["restored"])
            self.assertEqual((root / "tracked.txt").read_text(encoding="utf-8"), "before\n")
            self.assertEqual((root / "removed.txt").read_text(encoding="utf-8"), "restore me\n")
            self.assertFalse((root / "new.txt").exists())
            self.assertTrue(restored["archive"]["entries"])

    def test_disk_checkpoint_survives_runtime_reopen(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self._repository(directory)
            data = Path(directory) / "sumika-data"
            first = WorkspaceRuntime(data)
            checkpoint = first.create_checkpoint(root)["checkpoint"]
            (root / "tracked.txt").write_text("changed\n", encoding="utf-8")

            second = WorkspaceRuntime(data)
            listed = second.list_checkpoints(root)["checkpoints"]
            self.assertEqual(listed[0]["id"], checkpoint["id"])
            diff = second.diff_checkpoint(checkpoint["id"], path=root)
            self.assertTrue(diff["changed"])
            self.assertNotIn("current_files", diff)
            restored = second.restore(
                checkpoint["id"],
                path=root,
                approved=True,
                confirm_checkpoint=checkpoint["id"],
            )
            self.assertTrue(restored["restored"])
            self.assertEqual((root / "tracked.txt").read_text(encoding="utf-8"), "before\n")

    def test_preview_counts_deleted_untracked_checkpoint_file_as_a_write(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self._repository(directory)
            scratch = root / "scratch.txt"
            scratch.write_text("keep me\n", encoding="utf-8")
            runtime = WorkspaceRuntime()
            checkpoint = runtime.create_checkpoint(root)["checkpoint"]

            scratch.unlink()
            preview = runtime.restore_preview(checkpoint["id"], path=root)

            self.assertEqual(preview["counts"]["removed"], 1)
            self.assertEqual(preview["restore"]["write_count"], 1)
            self.assertEqual(preview["restore"]["write_paths"], ["scratch.txt"])

            restored = runtime.restore(
                checkpoint["id"],
                path=root,
                approved=True,
                confirm_checkpoint=checkpoint["id"],
                preview_token=preview["restore"]["preview_token"],
            )
            self.assertTrue(restored["restored"])
            self.assertEqual(scratch.read_text(encoding="utf-8"), "keep me\n")

    def test_summary_limit_does_not_limit_restore_scope(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self._repository(directory)
            targets = [root / f"tracked-{index}.txt" for index in range(3)]
            for index, target in enumerate(targets):
                target.write_text(f"before {index}\n", encoding="utf-8")
            _git(root, "add", ".")
            _git(root, "commit", "-qm", "more fixtures")
            runtime = WorkspaceRuntime()
            checkpoint = runtime.create_checkpoint(root)["checkpoint"]
            for index, target in enumerate(targets):
                target.write_text(f"after {index}\n", encoding="utf-8")

            with patch("sumika_core.workspace.runtime._MAX_DIFF_FILES", 2):
                preview = runtime.restore_preview(checkpoint["id"], path=root)
                self.assertEqual(preview["counts"]["changed_total"], 3)
                self.assertEqual(len(preview["files"]), 2)
                self.assertTrue(preview["files_truncated"])
                self.assertEqual(preview["restore"]["archive_count"], 3)
                self.assertEqual(preview["restore"]["write_count"], 3)
                restored = runtime.restore(
                    checkpoint["id"],
                    path=root,
                    approved=True,
                    confirm_checkpoint=checkpoint["id"],
                    preview_token=preview["restore"]["preview_token"],
                )

            self.assertTrue(restored["restored"])
            for index, target in enumerate(targets):
                self.assertEqual(target.read_text(encoding="utf-8"), f"before {index}\n")

    def test_restore_rejects_stale_preview_and_missing_or_invalid_blob(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self._repository(directory)
            runtime = WorkspaceRuntime()
            checkpoint = runtime.create_checkpoint(root)["checkpoint"]
            (root / "tracked.txt").write_text("changed\n", encoding="utf-8")
            preview = runtime.restore_preview(checkpoint["id"], path=root)
            (root / "tracked.txt").write_text("changed again\n", encoding="utf-8")
            with self.assertRaisesRegex(WorkspaceError, "changed after"):
                runtime.restore(
                    checkpoint["id"],
                    path=root,
                    approved=True,
                    confirm_checkpoint=checkpoint["id"],
                    preview_token=preview["restore"]["preview_token"],
                )

            manifest = runtime._memory_manifests[checkpoint["id"]]
            file_entry = manifest["files"]["tracked.txt"]
            manifest["_memory_blobs"].pop(file_entry["blob"])
            with self.assertRaisesRegex(WorkspaceError, "blob is unavailable"):
                runtime.restore(
                    checkpoint["id"],
                    path=root,
                    approved=True,
                    confirm_checkpoint=checkpoint["id"],
                )

    def test_worktree_preview_and_approved_create_use_source_head_only(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self._repository(directory)
            (root / "tracked.txt").write_text("source-only change\n", encoding="utf-8")
            destination = Path(directory) / "linked-worktree"
            runtime = WorkspaceRuntime()

            preview = runtime.preview_worktree(root, destination, "codex/workspace-test")

            self.assertTrue(preview["source"]["dirty"])
            self.assertFalse(preview["includes_uncommitted_changes"])
            self.assertEqual(preview["worktree"]["kind"], "linked")
            created = runtime.create_worktree(
                root,
                destination,
                "codex/workspace-test",
                approved=True,
                confirm_branch=preview["worktree"]["branch"],
                confirm_destination=preview["worktree"]["path"],
                preview_token=preview["preview_token"],
            )

            self.assertTrue(created["created"])
            self.assertEqual(created["worktree"]["kind"], "linked")
            self.assertEqual(created["worktree"]["branch"], "codex/workspace-test")
            self.assertEqual((destination / "tracked.txt").read_text(encoding="utf-8"), "before\n")

    def test_worktree_create_rejects_wrong_confirmation_and_existing_destination(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self._repository(directory)
            destination = Path(directory) / "linked-worktree"
            runtime = WorkspaceRuntime()
            preview = runtime.preview_worktree(root, destination, "codex/workspace-test")

            with self.assertRaisesRegex(WorkspaceError, "exact branch and destination"):
                runtime.create_worktree(
                    root,
                    destination,
                    "codex/workspace-test",
                    approved=True,
                    confirm_branch="codex/wrong",
                    confirm_destination=preview["worktree"]["path"],
                    preview_token=preview["preview_token"],
                )

            destination.mkdir()
            with self.assertRaisesRegex(WorkspaceError, "already exists"):
                runtime.preview_worktree(root, destination, "codex/workspace-test")

    def test_commit_preview_and_approved_commit_include_exact_changed_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self._repository(directory)
            runtime = WorkspaceRuntime()
            checkpoint = runtime.create_checkpoint(root, name="clean baseline")["checkpoint"]
            (root / "tracked.txt").write_text("after\n", encoding="utf-8")
            (root / "new.txt").write_text("new file\n", encoding="utf-8")

            preview = runtime.preview_commit(checkpoint["id"], path=root, message="Implement guarded commit")

            self.assertEqual({item["path"] for item in preview["files"]}, {"new.txt", "tracked.txt"})
            self.assertIn("after", preview["patch"])
            self.assertIn("new file", preview["patch"])
            self.assertFalse(preview["patch_truncated"])
            self.assertEqual(preview["patch_omitted_files"], [])
            committed = runtime.commit(
                checkpoint["id"],
                path=root,
                message="Implement guarded commit",
                approved=True,
                confirm_branch=preview["workspace"]["branch"],
                preview_token=preview["preview_token"],
            )

            self.assertFalse(committed["pushed"])
            self.assertEqual(set(committed["files"]), {"new.txt", "tracked.txt"})
            self.assertEqual(_git(root, "status", "--porcelain"), "")
            self.assertEqual(_git(root, "log", "-1", "--pretty=%s").strip(), "Implement guarded commit")

    def test_guarded_commit_supports_a_rename_as_two_exact_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self._repository(directory)
            runtime = WorkspaceRuntime()
            checkpoint = runtime.create_checkpoint(root)["checkpoint"]
            _git(root, "mv", "tracked.txt", "renamed.txt")
            preview = runtime.preview_commit(checkpoint["id"], path=root, message="Rename tracked file")

            self.assertEqual({item["path"] for item in preview["files"]}, {"tracked.txt", "renamed.txt"})
            committed = runtime.commit(
                checkpoint["id"],
                path=root,
                message="Rename tracked file",
                approved=True,
                confirm_branch=preview["workspace"]["branch"],
                preview_token=preview["preview_token"],
            )

            self.assertEqual(set(committed["files"]), {"tracked.txt", "renamed.txt"})
            self.assertFalse((root / "tracked.txt").exists())
            self.assertTrue((root / "renamed.txt").is_file())

    def test_commit_rejects_dirty_checkpoint_and_stale_preview(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self._repository(directory)
            runtime = WorkspaceRuntime()
            (root / "tracked.txt").write_text("dirty baseline\n", encoding="utf-8")
            dirty_checkpoint = runtime.create_checkpoint(root)["checkpoint"]
            with self.assertRaisesRegex(WorkspaceError, "clean workspace"):
                runtime.preview_commit(dirty_checkpoint["id"], path=root, message="Must fail")

            (root / "tracked.txt").write_text("before\n", encoding="utf-8")
            checkpoint = runtime.create_checkpoint(root)["checkpoint"]
            before_head = _git(root, "rev-parse", "HEAD").strip()
            (root / "tracked.txt").write_text("first change\n", encoding="utf-8")
            preview = runtime.preview_commit(checkpoint["id"], path=root, message="Stale preview")
            (root / "tracked.txt").write_text("second change\n", encoding="utf-8")

            with self.assertRaisesRegex(WorkspaceError, "changed after"):
                runtime.commit(
                    checkpoint["id"],
                    path=root,
                    message="Stale preview",
                    approved=True,
                    confirm_branch=preview["workspace"]["branch"],
                    preview_token=preview["preview_token"],
                )
            self.assertEqual(_git(root, "rev-parse", "HEAD").strip(), before_head)

    def test_commit_preview_rejects_staged_path_outside_content_diff(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self._repository(directory)
            runtime = WorkspaceRuntime()
            checkpoint = runtime.create_checkpoint(root)["checkpoint"]
            (root / "tracked.txt").write_text("after\n", encoding="utf-8")
            _git(root, "rm", "--cached", "removed.txt")

            with self.assertRaisesRegex(WorkspaceError, "staged paths outside"):
                runtime.preview_commit(checkpoint["id"], path=root, message="Must fail")

    def test_commit_preview_rejects_changes_outside_supported_path_set(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self._repository(directory)
            runtime = WorkspaceRuntime()
            checkpoint = runtime.create_checkpoint(root)["checkpoint"]
            (root / "tracked.txt").write_text("after\n", encoding="utf-8")
            git_status = runtime._git_status

            def status_with_excluded_path(status_root):
                status = git_status(status_root)
                status["dirty"] = True
                status["total_file_count"] += 1
                status["excluded_file_count"] = 1
                return status

            with patch.object(runtime, "_git_status", side_effect=status_with_excluded_path):
                with self.assertRaisesRegex(WorkspaceError, "outside the supported"):
                    runtime.preview_commit(checkpoint["id"], path=root, message="Must fail")

    def test_status_summary_limit_never_hides_a_dirty_workspace(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self._repository(directory)
            (root / "tracked.txt").write_text("changed\n", encoding="utf-8")
            (root / "removed.txt").write_text("changed too\n", encoding="utf-8")

            with patch("sumika_core.workspace.runtime._MAX_STATUS_FILES", 1):
                workspace = WorkspaceRuntime().inspect(root)["workspace"]

            self.assertTrue(workspace["dirty"])
            self.assertEqual(workspace["file_count"], 2)
            self.assertEqual(workspace["total_file_count"], 2)
            self.assertEqual(len(workspace["files"]), 1)
            self.assertTrue(workspace["files_truncated"])

    def test_all_unmerged_porcelain_codes_are_conflicts(self):
        for status in ("DD", "AU", "UD", "UA", "DU", "AA", "UU"):
            with self.subTest(status=status):
                self.assertEqual(WorkspaceRuntime._status_label(status), "conflict")

    def test_paths_inside_deprecated_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self._repository(directory)
            deprecated = root / "deprecated" / "old"
            deprecated.mkdir(parents=True)
            with self.assertRaisesRegex(WorkspaceError, "outside deprecated"):
                WorkspaceRuntime().inspect(deprecated)


if __name__ == "__main__":
    unittest.main()
