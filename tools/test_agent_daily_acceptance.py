import unittest
import os
from pathlib import Path
from unittest.mock import patch

try:
    import agent_daily_acceptance as acceptance
except ModuleNotFoundError:
    from tools import agent_daily_acceptance as acceptance


class AgentDailyAcceptanceTests(unittest.TestCase):
    def test_tool_status_projection_excludes_plan_exit_lifecycle_item(self):
        tool_script = [
            {"name": "exit_plan_mode"},
            {"name": "read"},
            {"name": "pwsh"},
        ]
        statuses = [
            {"name": "read", "status": "completed"},
            {"name": "pwsh", "status": "completed"},
        ]
        from tools import smoke_dsh_round

        self.assertIsNone(smoke_dsh_round._tool_status_error(tool_script, statuses))
        self.assertIsNotNone(
            smoke_dsh_round._tool_status_error(tool_script, [{"name": "read", "status": "failed"}])
        )

    def test_smoke_projection_keeps_only_bounded_evidence(self):
        report = acceptance._project_smoke(
            '{"ok":true,"session_id":"private-session","plan_prompt_accepted":true,'
            '"plan_review_answered":true,"execute_started":true,"prompt_accepted":true,'
            '"question_answered":true,"approval_answered":true,"marker_received":true,'
            '"stream_requested":true,"route_cleanup":"ok",'
            '"workspace_recovery":{"restored":true,"restore_preview_token_used":true,'
            '"changed_file_count":1},"prompt":"do not copy me",'
            '"workspace":{"path":"C:\\\\private"}}'
        )
        self.assertEqual(report["status"], "passed")
        self.assertTrue(report["workspace_recovery"]["restored"])
        self.assertNotIn("private-session", str(report))
        self.assertNotIn("do not copy me", str(report))
        self.assertNotIn("private", str(report))

    def test_smoke_projection_reports_only_error_class_for_traceback(self):
        report = acceptance._project_smoke("", "Traceback\nValueError: private detail\n")
        self.assertEqual(report, {"status": "failed", "error": "ValueError"})

    def test_smoke_projection_rejects_non_json(self):
        self.assertEqual(
            acceptance._project_smoke("runtime traceback with a secret"),
            {"status": "failed", "error": "unknown-error"},
        )

    def test_profile_path_rejects_user_home(self):
        with self.assertRaises(ValueError):
            acceptance._profile_path(str(Path.home()))

    def test_profile_path_accepts_explicit_non_home_directory(self):
        candidate = acceptance.ROOT / ".sumika-test-profile-placeholder"
        self.assertEqual(acceptance._profile_path(str(candidate)), candidate.resolve())

    def test_smoke_projection_includes_bounded_skills_and_subagents_evidence(self):
        report = acceptance._project_smoke(
            '{"ok":true,"skills_subagents":{'
            '"skill_discovered":true,"skill_loaded":true,"subagent_created":true,'
            '"subagent_history_read":true,"child_count":1,"child_id":"private-child"}}'
        )
        self.assertEqual(
            report["skills_subagents"],
            {
                "skill_discovered": True,
                "skill_loaded": True,
                "subagent_created": True,
                "subagent_history_read": True,
                "child_count": 1,
            },
        )
        self.assertNotIn("private-child", str(report))

    def test_full_checks_passes_backend_source_on_pythonpath(self):
        calls = []

        def fake_command(argv, *, timeout, env=None, **_kwargs):
            calls.append((argv, timeout, env))
            return {"status": "passed", "duration_ms": 1}

        with patch.object(acceptance, "_command", side_effect=fake_command), patch.dict(
            os.environ, {"PYTHONPATH": "D:\\existing-source"}, clear=False
        ):
            report = acceptance._full_checks(5.0)

        self.assertEqual(report["status"], "passed")
        self.assertEqual(len(calls), 4)
        expected = str(acceptance.ROOT / "backend" / "src")
        for _, _, env in calls:
            self.assertIsNotNone(env)
            self.assertTrue(str(env["PYTHONPATH"]).startswith(expected + os.pathsep))
            self.assertIn("D:\\existing-source", str(env["PYTHONPATH"]))

    def test_parser_exposes_skills_subagents_switch(self):
        args = acceptance._parser().parse_args(["--runtime-smoke", "--skills-subagents"])
        self.assertTrue(args.skills_subagents)

    def test_parser_exposes_real_session_evidence_switch(self):
        args = acceptance._parser().parse_args(["--real-session", "session-1"])
        self.assertEqual(args.real_session, "session-1")

    def test_real_session_projection_keeps_only_bounded_metrics(self):
        report = acceptance._project_real_session_evidence(
            {
                "status": "passed",
                "runtime_id": "dsh",
                "session_id": "private-session",
                "checkpoint_id": "private-checkpoint",
                "plan_review": {
                    "requested": True,
                    "approved": True,
                    "checkpoint_created": True,
                    "checkpoint_before_approval": True,
                    "detail": "private plan",
                },
                "execution": {
                    "turn_state": "completed",
                    "tool_call_count": 2,
                    "tool_result_count": 2,
                    "write_tool_seen": True,
                    "output": "private output",
                },
                "workspace": {
                    "diff_observed": True,
                    "changed_file_count": 1,
                    "restore_previewed": True,
                    "restored": True,
                    "archive_count": 1,
                    "path": "D:\\private",
                },
                "timing": {"approval_to_completion_ms": 100, "approval_to_restore_ms": 200},
                "evidence_window_events": 42,
            }
        )
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["runtime_id"], "dsh")
        self.assertEqual(report["workspace"]["changed_file_count"], 1)
        self.assertEqual(report["timing"]["approval_to_restore_ms"], 200)
        serialized = str(report)
        for forbidden in ("private-session", "private-checkpoint", "private plan", "private output", "D:\\private"):
            self.assertNotIn(forbidden, serialized)

    def test_real_session_projection_rejects_false_pass(self):
        report = acceptance._project_real_session_evidence(
            {"status": "passed", "plan_review": {"approved": True}}
        )
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["error_code"], "incomplete-evidence")

    def test_real_session_projection_rejects_pass_without_a_completed_write(self):
        report = acceptance._project_real_session_evidence(
            {
                "status": "passed",
                "plan_review": {
                    "requested": True,
                    "approved": True,
                    "checkpoint_created": True,
                    "checkpoint_before_approval": True,
                },
                "execution": {
                    "turn_state": "completed",
                    "tool_call_count": 1,
                    "tool_result_count": 1,
                    "write_tool_seen": False,
                },
                "workspace": {
                    "diff_observed": True,
                    "changed_file_count": 0,
                    "restore_previewed": True,
                    "restored": True,
                },
            }
        )

        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["error_code"], "incomplete-evidence")

    def test_real_session_evidence_uses_read_only_core_rpc(self):
        captured = {}

        def request(base_url, path, **kwargs):
            captured.update({"base_url": base_url, "path": path, **kwargs})
            return {
                "jsonrpc": "2.0",
                "result": {
                    "status": "needs-action",
                    "plan_review": {},
                    "execution": {},
                    "workspace": {},
                    "timing": {},
                },
            }

        with patch.object(acceptance, "_request_json", side_effect=request):
            report = acceptance.run_real_session_evidence(
                core_url="http://127.0.0.1:8771",
                session_id="session-private",
                timeout=5.0,
            )

        self.assertEqual(report["status"], "needs-action")
        self.assertEqual(captured["path"], "/rpc")
        self.assertEqual(captured["method"], "POST")
        self.assertEqual(captured["payload"]["method"], "agent.acceptance.evidence")
        self.assertEqual(captured["payload"]["params"], {"sessionId": "session-private"})
        self.assertNotIn("session-private", str(report))

    def test_preflight_projection_keeps_safe_runtime_and_model_labels(self):
        source = {
            "overall": "ready",
            "checks": [
                {"id": "agent-runtime", "status": "ready", "runtime_id": "dsh", "version": "0.1.1-rc.2"},
                {"id": "provider", "status": "ready", "model": "glm-4.5-air", "profile_id": "private profile"},
            ],
        }
        with patch.object(acceptance, "run_preflight", return_value=source):
            report = acceptance._preflight_report("http://127.0.0.1:8771", 5.0)

        self.assertEqual(report["runtime"], {"id": "dsh", "version": "0.1.1-rc.2"})
        self.assertEqual(report["provider"], {"model": "glm-4.5-air"})
        self.assertNotIn("private profile", str(report))

    def test_parser_exposes_browser_smoke_switches(self):
        args = acceptance._parser().parse_args(["--browser-smoke", "--browser-write-smoke"])
        self.assertTrue(args.browser_smoke)
        self.assertTrue(args.browser_write_smoke)

    def test_browser_projection_keeps_only_safe_counts(self):
        report = acceptance._browser_command_projection(
            '{"ok":true,"runtime_ready":true,"browser_tools_completed":7,'
            '"approval_count":3,"local_write_confirmed":true,"marker_received":true,'
            '"final_state":"completed","page":"private","value":"secret"}',
            phase="browser-write",
        )
        self.assertEqual(
            report,
            {
                "status": "passed",
                "runtime_ready": True,
                "browser_tools_completed": 7,
                "marker_received": True,
                "final_state": "completed",
                "approval_count": 3,
                "local_write_confirmed": True,
            },
        )
        self.assertNotIn("private", str(report))
        self.assertNotIn("secret", str(report))

    def test_browser_projection_keeps_a_safe_failure_code(self):
        report = acceptance._browser_command_projection(
            '{"ok":false,"error":"profile-mismatch","detail":"private path"}',
            phase="browser-read",
        )
        self.assertEqual(report, {"status": "failed", "error_code": "profile-mismatch", "phase": "browser-read"})
        self.assertNotIn("private", str(report))

    def test_core_rpc_endpoint_does_not_duplicate_rpc_suffix(self):
        self.assertEqual(acceptance._core_rpc_endpoint("http://127.0.0.1:8770"), "http://127.0.0.1:8770/rpc")
        self.assertEqual(acceptance._core_rpc_endpoint("http://127.0.0.1:8770/rpc"), "http://127.0.0.1:8770/rpc")

    def test_browser_smoke_fails_before_subprocess_on_profile_mismatch(self):
        with patch.object(
            acceptance,
            "verify_profile_binding",
            side_effect=acceptance.ProfileBindingError("profile-mismatch"),
        ), patch.object(acceptance.subprocess, "run") as run:
            report = acceptance.run_browser_smoke(
                endpoint="http://127.0.0.1:3095",
                profile_dir=str(acceptance.ROOT / ".sumika-test-profile-placeholder"),
                core_endpoint="http://127.0.0.1:8770/rpc",
                timeout=5.0,
            )
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["error_code"], "profile-mismatch")
        self.assertEqual(report["phase"], "profile-check")
        run.assert_not_called()

    def test_process_failure_projection_exposes_safe_code_and_phase(self):
        report = acceptance._project_process_failure(
            "",
            "Traceback\nAgentRuntimeError: user Agent preset composition is unavailable\n",
        )
        self.assertEqual(report["error_code"], "preset-composition-unavailable")
        self.assertEqual(report["phase"], "profile-check")
        self.assertNotIn("composition is unavailable", str(report))

    def test_report_directory_rejects_paths_outside_project(self):
        with self.assertRaises(ValueError):
            acceptance._report_directory(str(Path.cwd().anchor))


if __name__ == "__main__":
    unittest.main()
