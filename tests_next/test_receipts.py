import json
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
from io import StringIO
from pathlib import Path
import shutil
import subprocess
import sys
import unittest
import uuid
from unittest.mock import patch

from sumika_next.cli import main
from sumika_next.continuity import handoff, validate
from sumika_next.receipts import (RECEIPTS_DIR, ReceiptError, create_receipt,
                                  read_receipts, recent_receipts)

try:
    from tests_next.scratch import ScratchDirectory
except ImportError:  # ``unittest discover -s tests_next`` imports modules top-level
    from scratch import ScratchDirectory

ROOT = Path(__file__).resolve().parents[1]


def report(**overrides):
    data = {
        "task_id": "P3-receipt-001",
        "session_id": "sumika-demo",
        "summary": "实现显式任务成果记录",
        "changes": ["sumika_next/receipts.py", "sumika_next/continuity.py"],
        "verification": [{"command": "python -B -m unittest", "result": "passed"}],
        "remaining": ["P4 自动捕获尚未接线"],
        "next": "进入 P4 自动捕获接线",
    }
    data.update(overrides)
    return data


class ReceiptCreationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = ScratchDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "docs/project").mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def write_input(self, data, name="report.json"):
        (self.root / name).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return name

    def test_reserved_windows_names_are_rejected_before_writes(self):
        for task_id in ('CON', 'nul.txt', 'LPT1', 'trailing.'):
            self.write_input(report(task_id=task_id))
            with self.subTest(task_id=task_id), self.assertRaises(ReceiptError):
                create_receipt(self.root, 'report.json')
            self.assertFalse((self.root / RECEIPTS_DIR).exists())

    def test_failure_to_open_does_not_delete_any_existing_path(self):
        self.write_input(report())
        with patch('builtins.open', side_effect=PermissionError('denied')), patch.object(Path, 'unlink') as unlink:
            with self.assertRaises(ReceiptError): create_receipt(self.root, 'report.json')
            unlink.assert_not_called()

    def test_valid_report_is_normalized_and_recorded(self):
        self.write_input(report(task_id="  P3-receipt-001  ", session_id="   ",
                                changes=["  a.py  "], remaining=[]))
        path = create_receipt(self.root, "report.json")
        self.assertEqual(path.resolve(), (self.root / RECEIPTS_DIR / "P3-receipt-001.json").resolve())
        record = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(list(record), ["schema_version", "task_id", "session_id", "summary",
                                        "changes", "verification", "remaining", "next",
                                        "provenance", "git_head", "recorded_at"])
        self.assertEqual(record["schema_version"], 1)
        self.assertEqual(record["task_id"], "P3-receipt-001")
        self.assertIsNone(record["session_id"])
        self.assertEqual(record["changes"], ["a.py"])
        self.assertEqual(record["remaining"], [])
        self.assertEqual(record["verification"],
                         [{"command": "python -B -m unittest", "result": "passed"}])
        self.assertEqual(record["provenance"], "operator_report")
        self.assertIsNone(record["git_head"], "a scratch root is not a Git repository")
        recorded = datetime.fromisoformat(record["recorded_at"])
        self.assertEqual(recorded.utcoffset(), timedelta(0))
        self.assertEqual([item["session_id"] for item in read_receipts(self.root)], [None])

    def test_git_head_is_attached_for_a_repository_root(self):
        if shutil.which("git") is None:
            self.skipTest("git is not available")
        subprocess.run(["git", "-C", str(self.root), "init", "-q"], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(self.root), "-c", "user.name=test",
                        "-c", "user.email=test@example.invalid", "commit", "-q",
                        "--allow-empty", "-m", "init"], check=True, capture_output=True)
        self.write_input(report())
        record = json.loads(create_receipt(self.root, "report.json").read_text(encoding="utf-8"))
        self.assertRegex(record["git_head"], r"^[0-9a-f]{40}$")

    def test_task_id_traversal_and_unsafe_names_are_rejected(self):
        for task_id in ("../escape", "..\\escape", "a/b", "a\\b", "/absolute", ".", "..",
                        "C:\\escape", "任务-1", "a b", "-lead"):
            with self.subTest(task_id=task_id):
                with self.assertRaises(ReceiptError):
                    create_receipt(self.root, self.write_input(report(task_id=task_id)))
                self.assertFalse((self.root / RECEIPTS_DIR).exists())
        self.assertFalse((self.root.parent / "escape.json").exists())

    def test_invalid_fields_are_rejected(self):
        cases = {
            "missing next": {key: value for key, value in report().items() if key != "next"},
            "unknown field": report(note="x"),
            "task_id type": report(task_id=7),
            "summary type": report(summary=1),
            "summary blank": report(summary="   "),
            "next blank": report(next=""),
            "session_id type": report(session_id=None),
            "changes type": report(changes="a.py"),
            "changes item type": report(changes=[1]),
            "changes item blank": report(changes=[""]),
            "verification type": report(verification={"command": "x", "result": "passed"}),
            "verification item type": report(verification=["passed"]),
            "verification missing result": report(verification=[{"command": "x"}]),
            "verification extra field": report(verification=[{"command": "x", "result": "passed",
                                                              "note": "y"}]),
            "verification blank command": report(verification=[{"command": "", "result": "passed"}]),
            "verification bad result": report(verification=[{"command": "x", "result": "ok"}]),
            "verification non-string result": report(verification=[{"command": "x", "result": True}]),
            "remaining type": report(remaining="later"),
        }
        for name, data in cases.items():
            with self.subTest(case=name):
                with self.assertRaises(ReceiptError):
                    create_receipt(self.root, self.write_input(data))
                self.assertFalse((self.root / RECEIPTS_DIR).exists())

    def test_non_object_report_is_rejected(self):
        (self.root / "report.json").write_text("[1, 2]", encoding="utf-8")
        with self.assertRaises(ReceiptError):
            create_receipt(self.root, "report.json")
        self.assertFalse((self.root / RECEIPTS_DIR).exists())

    def test_duplicate_task_id_keeps_the_first_record(self):
        self.write_input(report())
        path = create_receipt(self.root, "report.json")
        original = path.read_bytes()
        with self.assertRaises(ReceiptError):
            create_receipt(self.root, self.write_input(report(summary="changed")))
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual([item.name for item in (self.root / RECEIPTS_DIR).iterdir()],
                         ["P3-receipt-001.json"])

    def test_failed_and_not_run_results_are_preserved(self):
        verification = [
            {"command": "python -B -m unittest discover -s tests_next", "result": "passed"},
            {"command": "python -B tools/verify_phase2.py", "result": "failed"},
            {"command": "python -B tools/probe_dsh_next.py", "result": "not_run"},
        ]
        record_path = create_receipt(self.root, self.write_input(report(verification=verification)))
        self.assertEqual(json.loads(record_path.read_text(encoding="utf-8"))["verification"],
                         verification)
        shutil.copytree(ROOT / "docs/project", self.root / "docs/project", dirs_exist_ok=True)
        text = handoff(self.root)
        self.assertIn("最近成果记录", text)
        self.assertIn("operator_report", text)
        for item in verification:
            self.assertIn(f"`{item['command']}` -> {item['result']}", text)

    def test_unencodable_report_is_rejected_without_leaving_a_file(self):
        payload = json.dumps(report(task_id="SUR-2", summary="\ud800"), ensure_ascii=True)
        (self.root / "report.json").write_text(payload, encoding="utf-8")
        with self.assertRaises(ReceiptError):
            create_receipt(self.root, "report.json")
        directory = self.root / RECEIPTS_DIR
        self.assertEqual(list(directory.glob("*")) if directory.exists() else [], [])

    def test_validation_failure_writes_nothing(self):
        with self.assertRaises(ReceiptError):
            create_receipt(self.root, self.write_input(report(verification=[
                {"command": "x", "result": "unsure"}])))
        self.assertFalse((self.root / RECEIPTS_DIR).exists())
        self.assertEqual([path for path in self.root.glob("**/*.tmp*")], [])

    def test_blocked_record_path_writes_nothing(self):
        directory = self.root / RECEIPTS_DIR
        directory.mkdir(parents=True)
        (directory / "P3-receipt-001.json").mkdir()
        with self.assertRaises(ReceiptError):
            create_receipt(self.root, self.write_input(report()))
        self.assertTrue((directory / "P3-receipt-001.json").is_dir())

    def test_blocked_receipts_directory_writes_nothing(self):
        (self.root / RECEIPTS_DIR).write_text("not a directory", encoding="utf-8")
        with self.assertRaises(ReceiptError):
            create_receipt(self.root, self.write_input(report()))

    def test_input_file_rules(self):
        with self.assertRaises(ReceiptError):  # absolute path
            create_receipt(self.root, self.root / "report.json")
        outside = self.root.parent / f"outside-{uuid.uuid4().hex}.json"
        outside.write_text(json.dumps(report()), encoding="utf-8")
        try:
            with self.assertRaises(ReceiptError):  # escapes the project root
                create_receipt(self.root, Path("..") / outside.name)
        finally:
            outside.unlink(missing_ok=True)
        with self.assertRaises(ReceiptError):  # missing file
            create_receipt(self.root, "missing.json")
        (self.root / "nested").mkdir()
        with self.assertRaises(ReceiptError):  # directory, not a file
            create_receipt(self.root, "nested")
        (self.root / "bad.json").write_text("{not json", encoding="utf-8")
        with self.assertRaises(ReceiptError):  # unreadable report
            create_receipt(self.root, "bad.json")
        self.assertFalse((self.root / RECEIPTS_DIR).exists())

    def test_injected_now_is_normalized_to_utc(self):
        for index, moment in enumerate((datetime(2026, 1, 1),
                                        datetime(2026, 1, 1, 8, tzinfo=timezone(timedelta(hours=8))))):
            with self.subTest(now=moment):
                (self.root / "report.json").write_text(
                    json.dumps(report(task_id=f"NOW-{index}")), encoding="utf-8")
                path = create_receipt(self.root, "report.json", now=moment, head=None)
                record = json.loads(path.read_text(encoding="utf-8"))
                self.assertTrue(record["recorded_at"].endswith("+00:00"))
        self.assertEqual(len(read_receipts(self.root)), 2)

    def test_project_root_must_have_docs_project(self):
        other = Path(self.tmp.name) / "not-a-project"
        other.mkdir()
        (other / "report.json").write_text(json.dumps(report()), encoding="utf-8")
        with self.assertRaises(ReceiptError):
            create_receipt(other, "report.json")
        self.assertFalse((other / RECEIPTS_DIR).exists())


class ReceiptHandoffTests(unittest.TestCase):
    def setUp(self):
        self.tmp = ScratchDirectory()
        self.root = Path(self.tmp.name)
        shutil.copytree(ROOT / "docs/project", self.root / "docs/project", ignore=shutil.ignore_patterns('receipts'))
        self.initial_handoff = validate(self.root)['handoff']

    def tearDown(self):
        self.tmp.cleanup()

    def create(self, task_id, recorded_at, **overrides):
        (self.root / "report.json").write_text(
            json.dumps(report(task_id=task_id, **overrides), ensure_ascii=False), encoding="utf-8")
        return create_receipt(self.root, "report.json", now=recorded_at, head=None)

    def test_handoff_without_receipts_stays_compatible(self):
        text = handoff(self.root)
        self.assertNotIn("最近成果记录", text)
        self.assertIn("## 需求原文索引", text)
        self.assertEqual(validate(self.root)["handoff"]["current_phase"], self.initial_handoff['current_phase'])

    def test_handoff_lists_recent_receipts_newest_first_and_limited(self):
        for index in range(4):
            self.create(f"P3-receipt-{index}",
                        datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(hours=index),
                        summary=f"summary-{index}")
        text = handoff(self.root)
        self.assertIn("最近成果记录", text)
        self.assertIn("summary-3", text)
        self.assertIn("summary-1", text)
        self.assertNotIn("summary-0", text)
        self.assertLess(text.index("summary-3"), text.index("summary-2"))

    def test_recent_receipts_are_ordered(self):
        self.create("older", datetime(2026, 1, 2, tzinfo=timezone.utc))
        self.create("newer", datetime(2026, 1, 3, tzinfo=timezone.utc))
        self.assertEqual([record["task_id"] for record in recent_receipts(self.root)],
                         ["newer", "older"])

    def test_corrupt_receipt_files_are_not_silently_ignored(self):
        directory = self.root / RECEIPTS_DIR
        directory.mkdir(parents=True)
        broken = directory / "broken.json"
        broken.write_text("{not json", encoding="utf-8")
        with self.assertRaises(ReceiptError):
            handoff(self.root)
        broken.write_text(json.dumps(report(task_id="other")), encoding="utf-8")
        with self.assertRaises(ReceiptError):
            validate(self.root)
        broken.unlink()
        (directory / "P3-receipt-001.json").write_text(json.dumps(
            {**report(), "schema_version": 2, "provenance": "operator_report",
             "git_head": None, "recorded_at": "2026-01-01T00:00:00+00:00"}), encoding="utf-8")
        with self.assertRaises(ReceiptError):
            read_receipts(self.root)

    def test_blank_session_id_round_trips_through_handoff(self):
        (self.root / "report.json").write_text(json.dumps(report(session_id="   ")),
                                               encoding="utf-8")
        create_receipt(self.root, "report.json",
                       now=datetime(2026, 1, 1, tzinfo=timezone.utc), head=None)
        self.assertEqual([item["session_id"] for item in read_receipts(self.root)], [None])
        text = handoff(self.root)
        self.assertIn("最近成果记录", text)
        self.assertEqual(validate(self.root)["handoff"]["phase_status"], self.initial_handoff['phase_status'])

    def test_receipt_writes_do_not_touch_the_other_project_records(self):
        names = ("requirements.json", "plan.json", "progress.json", "decisions.json",
                 "handoff.json")
        before = {name: (self.root / "docs/project" / name).read_bytes() for name in names}
        self.create("P3-receipt-001", datetime(2026, 1, 1, tzinfo=timezone.utc))
        after = {name: (self.root / "docs/project" / name).read_bytes() for name in names}
        self.assertEqual(before, after)
        self.assertEqual(validate(self.root)["handoff"]["phase_status"], self.initial_handoff['phase_status'])

    def test_receipts_path_must_be_a_directory(self):
        (self.root / RECEIPTS_DIR).write_text("not a directory", encoding="utf-8")
        with self.assertRaises(ReceiptError):
            read_receipts(self.root)
        with self.assertRaises(ReceiptError):
            validate(self.root)

    def test_uppercase_extension_is_read_and_non_records_are_ignored(self):
        directory = self.root / RECEIPTS_DIR
        directory.mkdir(parents=True)
        record = {**report(task_id="UPPER"), "schema_version": 1, "provenance": "operator_report",
                  "git_head": None, "recorded_at": "2026-01-01T00:00:00+00:00"}
        (directory / "UPPER.JSON").write_text(json.dumps(record), encoding="utf-8")
        (directory / ".gitkeep").write_text("", encoding="utf-8")
        (directory / "notes.txt").write_text("not a receipt", encoding="utf-8")
        self.assertEqual([item["task_id"] for item in read_receipts(self.root)], ["UPPER"])
        (directory / "P3-blocked.json").mkdir()
        with self.assertRaises(ReceiptError):
            read_receipts(self.root)

    def test_dangling_receipts_link_fails_loudly(self):
        link = self.root / RECEIPTS_DIR
        try:
            link.symlink_to(self.root / "missing-target", target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("cannot create symlinks in this environment")
        with self.assertRaises(ReceiptError):
            read_receipts(self.root)

    def test_recorded_at_must_be_utc_isoformat(self):
        directory = self.root / RECEIPTS_DIR
        directory.mkdir(parents=True)
        path = directory / "P3-receipt-001.json"
        for value in ("zzz", "2026-01-01T00:00:00", "2026-01-01T00:00:00+08:00"):
            with self.subTest(recorded_at=value):
                path.write_text(json.dumps(
                    {**report(), "schema_version": 1, "provenance": "operator_report",
                     "git_head": None, "recorded_at": value}), encoding="utf-8")
                with self.assertRaises(ReceiptError):
                    read_receipts(self.root)


class ReceiptCliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = ScratchDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "docs/project").mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, *argv):
        out, err = StringIO(), StringIO()
        with patch.object(sys, "argv", ["sumika", *argv]), redirect_stdout(out), redirect_stderr(err):
            try:
                main()
            except SystemExit as exit_code:
                return exit_code.code, out.getvalue(), err.getvalue()
        return 0, out.getvalue(), err.getvalue()

    def test_cli_receipt_writes_and_prints_relative_path(self):
        (self.root / "report.json").write_text(json.dumps(report()), encoding="utf-8")
        code, out, err = self.run_cli("receipt", "--root", str(self.root), "--input", "report.json")
        self.assertEqual((code, err), (0, ""))
        self.assertIn("receipt: docs/project/receipts/P3-receipt-001.json", out)
        self.assertNotIn("sumika-demo", out)
        self.assertTrue((self.root / RECEIPTS_DIR / "P3-receipt-001.json").is_file())

    def test_cli_receipt_requires_input(self):
        code, out, err = self.run_cli("receipt", "--root", str(self.root))
        self.assertEqual(code, 2)
        self.assertIn("requires --input", err)
        self.assertFalse((self.root / RECEIPTS_DIR).exists())

    def test_cli_reports_invalid_report_without_writing(self):
        (self.root / "report.json").write_text(json.dumps(report(task_id="../escape")),
                                               encoding="utf-8")
        code, out, err = self.run_cli("receipt", "--root", str(self.root), "--input", "report.json")
        self.assertEqual(code, 2)
        self.assertIn("task_id", err)
        self.assertNotIn("Traceback", err)
        self.assertFalse((self.root / RECEIPTS_DIR).exists())

    def test_cli_reports_unencodable_text_without_leaving_a_file(self):
        payload = json.dumps(report(task_id="SUR-2", summary="\ud800"), ensure_ascii=True)
        (self.root / "report.json").write_text(payload, encoding="utf-8")
        code, out, err = self.run_cli("receipt", "--root", str(self.root), "--input", "report.json")
        self.assertEqual(code, 2)
        self.assertIn("UTF-8", err)
        self.assertNotIn("Traceback", err)
        directory = self.root / RECEIPTS_DIR
        self.assertEqual(list(directory.glob("*")) if directory.exists() else [], [])

    def test_cli_rejects_input_for_other_commands(self):
        code, out, err = self.run_cli("check", "--root", str(self.root), "--input", "report.json")
        self.assertEqual(code, 2)
        self.assertIn("only valid with 'receipt'", err)
