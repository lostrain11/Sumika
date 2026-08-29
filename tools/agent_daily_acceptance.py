"""Run a bounded, repeatable acceptance pass for the Sumika Agent workflow.

The runtime pass uses a temporary Git repository and the checked-in protocol
fixtures.  It never targets the Sumika checkout, copies credentials, or emits
subprocess output.  A DSH profile must be supplied explicitly because the
smoke needs to create a temporary route and session in that profile.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
_WORKSPACE_MARKER = '{"format":1,"purpose":"dsh-workspace-recovery-smoke"}\n'
_WORKSPACE_FILE = "sumika-smoke.txt"
_WORKSPACE_BASELINE = "SUMIKA_WORKSPACE_BASELINE\n"
_SKILL_NAME = "sumika-smoke"
_SKILL_MARKER = "SUMIKA_SKILL_INSTRUCTIONS_OK"

sys.path.insert(0, str(Path(__file__).resolve().parent))
from agent_preflight import PreflightError, _request_json, _safe_base_url, run_preflight  # noqa: E402
from dsh_profile import ProfileBindingError, verify_profile_binding  # noqa: E402


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _profile_path(value: str) -> Path:
    raw = str(value or "").strip()
    if not raw:
        raise ValueError("--profile-dir or SUMIKA_AGENT_PROFILE_DIR is required for --runtime-smoke")
    profile = Path(os.path.expandvars(raw)).expanduser().resolve()
    user_home = Path.home().resolve()
    if profile == user_home or user_home in profile.parents:
        raise ValueError("refusing to mutate a DSH profile under the user home")
    return profile


def _command(
    argv: list[str],
    *,
    cwd: Path = ROOT,
    timeout: float = 120.0,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    started = time.monotonic()
    try:
        completed = subprocess.run(
            argv,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=max(1.0, timeout),
            check=False,
            env=dict(os.environ) if env is None else dict(env),
        )
    except FileNotFoundError:
        return {"status": "unavailable", "error": "executable-not-found", "duration_ms": _duration(started)}
    except subprocess.TimeoutExpired:
        return {"status": "failed", "error": "timeout", "duration_ms": _duration(started)}
    return {
        "status": "passed" if completed.returncode == 0 else "failed",
        "exit_code": int(completed.returncode),
        "duration_ms": _duration(started),
    }


def _duration(started: float) -> int:
    return max(0, int((time.monotonic() - started) * 1000))


def _safe_metric_label(value: Any, maximum: int = 120) -> str | None:
    candidate = str(value or "").strip()
    if not candidate or len(candidate) > maximum:
        return None
    return candidate if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]*", candidate) else None


def _real_session_id(value: str) -> str:
    candidate = str(value or "").strip()
    if (
        not candidate
        or len(candidate) > 240
        or any(ord(char) < 32 or ord(char) == 127 for char in candidate)
    ):
        raise ValueError("--real-session must be a non-empty runtime session id")
    return candidate


def _prepare_workspace(root: Path, *, include_skill: bool = False) -> None:
    root.mkdir(parents=True, exist_ok=False)
    (root / ".sumika-workspace-smoke.json").write_text(_WORKSPACE_MARKER, encoding="utf-8")
    (root / _WORKSPACE_FILE).write_text(_WORKSPACE_BASELINE, encoding="utf-8")
    if include_skill:
        skill_dir = root / ".agents" / "skills" / _SKILL_NAME
        skill_dir.mkdir(parents=True, exist_ok=False)
        (skill_dir / "SKILL.md").write_text(
            "---\n"
            f"name: {_SKILL_NAME}\n"
            "description: A deterministic skill fixture for Sumika protocol acceptance.\n"
            "---\n\n"
            f"{_SKILL_MARKER}\n",
            encoding="utf-8",
        )
    for args in (
        ("git", "init", "-q"),
        ("git", "config", "user.email", "sumika-daily-smoke@example.invalid"),
        ("git", "config", "user.name", "Sumika daily smoke"),
        ("git", "add", "."),
        ("git", "commit", "-qm", "daily smoke baseline"),
    ):
        result = _command(list(args), cwd=root, timeout=30)
        if result["status"] != "passed":
            raise RuntimeError(f"Git fixture setup failed: {result.get('error') or result.get('exit_code')}")


def _error_class(stderr: str) -> str:
    """Extract a stable exception class without retaining its message."""

    text = str(stderr or "")
    matches = re.findall(r"(?:^|\n)(?:[A-Za-z_][\w.]*\.)?([A-Za-z_][\w]*(?:Error|Exception|Exit))(?:$|:)", text)
    return matches[-1] if matches else ("subprocess-error" if text.strip() else "unknown-error")


def _failure_code(stdout: str, stderr: str) -> str:
    """Map process output to a fixed, content-independent diagnostic code."""

    text = f"{stdout}\n{stderr}".lower()
    if "endpoint/profile check failed" in text:
        for code in ("profile-mismatch", "profile-ambiguous", "profile-not-found", "profile-not-readable", "profile-preset-root-invalid", "endpoint-unavailable", "endpoint-http-error", "endpoint-invalid", "endpoint-not-loopback"):
            if code in text:
                return code
        return "profile-check-failed"
    if "user agent preset composition is unavailable" in text or "preset composition" in text:
        return "preset-composition-unavailable"
    if "mcp" in text and ("failed" in text or "unavailable" in text or "error" in text):
        return "mcp-failure"
    if "workspace" in text and ("failed" in text or "error" in text or "restore" in text):
        return "workspace-failure"
    if "timeout" in text or "timed out" in text:
        return "runtime-timeout"
    if "connection refused" in text or "endpoint unavailable" in text or "dsh runtime unavailable" in text:
        return "endpoint-unavailable"
    return "subprocess-failure"


def _failure_phase(code: str) -> str:
    if code.startswith("profile-") or code.startswith("endpoint-") or code == "preset-composition-unavailable":
        return "profile-check"
    if code == "mcp-failure":
        return "mcp"
    if code == "workspace-failure":
        return "workspace"
    return "runtime"


def _project_process_failure(stdout: str, stderr: str, *, phase: str = "runtime") -> dict[str, Any]:
    """Project a failed child process without retaining its output."""

    projection = _project_smoke(stdout, stderr)
    if projection.get("status") != "failed":
        return projection
    code = _failure_code(stdout, stderr)
    projection["error_code"] = code
    projection["phase"] = phase if phase != "runtime" else _failure_phase(code)
    return projection


def _project_smoke(stdout: str, stderr: str = "") -> dict[str, Any]:
    """Keep only bounded, content-independent smoke evidence."""

    try:
        value = json.loads(stdout.strip())
    except (TypeError, json.JSONDecodeError):
        return {"status": "failed", "error": _error_class(stderr)}
    if not isinstance(value, dict):
        return {"status": "failed", "error": _error_class(stderr)}
    projection: dict[str, Any] = {
        "status": "passed" if value.get("ok") is True else "failed",
        "plan_prompt_accepted": bool(value.get("plan_prompt_accepted")),
        "plan_review_answered": bool(value.get("plan_review_answered")),
        "execute_started": bool(value.get("execute_started")),
        "prompt_accepted": bool(value.get("prompt_accepted")),
        "question_answered": bool(value.get("question_answered")),
        "approval_answered": bool(value.get("approval_answered")),
        "marker_received": bool(value.get("marker_received")),
        "stream_requested": bool(value.get("stream_requested")),
        "route_cleanup": str(value.get("route_cleanup") or "unknown"),
    }
    recovery = value.get("workspace_recovery")
    if isinstance(recovery, dict):
        projection["workspace_recovery"] = {
            "restored": bool(recovery.get("restored")),
            "restore_preview_token_used": bool(recovery.get("restore_preview_token_used")),
            "changed_file_count": int(recovery.get("changed_file_count") or 0),
        }
    mcp = value.get("mcp")
    if isinstance(mcp, dict):
        projection["mcp"] = {
            "configuration_applied": bool(mcp.get("configuration_applied")),
            "mountable": bool(mcp.get("mountable")),
            "validation_session_archived": bool(mcp.get("validation_session_archived")),
            "tool_result_seen_by_model": bool(mcp.get("tool_result_seen_by_model")),
        }
    capabilities = value.get("skills_subagents")
    if isinstance(capabilities, dict):
        projection["skills_subagents"] = {
            "skill_discovered": bool(capabilities.get("skill_discovered")),
            "skill_loaded": bool(capabilities.get("skill_loaded")),
            "subagent_created": bool(capabilities.get("subagent_created")),
            "subagent_history_read": bool(capabilities.get("subagent_history_read")),
            "child_count": int(capabilities.get("child_count") or 0),
        }
    return projection


def _browser_command_projection(stdout: str, stderr: str = "", *, phase: str) -> dict[str, Any]:
    """Project BrowserSkill smoke output without retaining page or tool data."""

    try:
        value = json.loads(stdout.strip())
    except (TypeError, json.JSONDecodeError):
        projection = _project_process_failure(stdout, stderr, phase=phase)
        projection["phase"] = phase
        return projection
    if not isinstance(value, dict):
        return {"status": "failed", "error": "invalid-report", "phase": phase}
    if value.get("ok") is not True:
        code = str(value.get("error") or "browser-smoke-failed").strip().lower()
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", code):
            code = "browser-smoke-failed"
        return {"status": "failed", "error_code": code, "phase": phase}
    result: dict[str, Any] = {
        "status": "passed",
        "runtime_ready": bool(value.get("runtime_ready")),
        "browser_tools_completed": max(0, min(64, int(value.get("browser_tools_completed") or 0))),
        "marker_received": bool(value.get("marker_received")),
        "final_state": str(value.get("final_state") or "unknown")[:40],
    }
    for key in ("navigation_approval_count", "approval_count"):
        if key in value:
            result[key] = max(0, min(64, int(value.get(key) or 0)))
    if "local_write_confirmed" in value:
        result["local_write_confirmed"] = bool(value.get("local_write_confirmed"))
    return result


def _project_real_session_evidence(value: Any) -> dict[str, Any]:
    """Apply a second whitelist to Core's content-independent evidence."""

    if not isinstance(value, dict):
        return {"status": "failed", "error_code": "invalid-evidence"}
    source_status = str(value.get("status") or "failed")
    status = source_status if source_status in {"passed", "needs-action", "failed"} else "failed"
    plan = value.get("plan_review") if isinstance(value.get("plan_review"), dict) else {}
    execution = value.get("execution") if isinstance(value.get("execution"), dict) else {}
    workspace = value.get("workspace") if isinstance(value.get("workspace"), dict) else {}
    timing = value.get("timing") if isinstance(value.get("timing"), dict) else {}
    turn_state = str(execution.get("turn_state") or "unknown")
    if turn_state not in {"completed", "failed", "cancelled", "interrupted", "unknown"}:
        turn_state = "unknown"

    def bounded_integer(raw: Any, maximum: int) -> int:
        try:
            return max(0, min(maximum, int(raw or 0)))
        except (TypeError, ValueError):
            return 0

    def bounded_timing(raw: Any) -> int | None:
        if raw is None:
            return None
        try:
            return max(0, min(86_400_000, int(raw)))
        except (TypeError, ValueError):
            return None

    result: dict[str, Any] = {
        "status": status,
        "plan_review": {
            "requested": bool(plan.get("requested")),
            "approved": bool(plan.get("approved")),
            "checkpoint_created": bool(plan.get("checkpoint_created")),
            "checkpoint_before_approval": bool(plan.get("checkpoint_before_approval")),
        },
        "execution": {
            "turn_state": turn_state,
            "tool_call_count": bounded_integer(execution.get("tool_call_count"), 64),
            "tool_result_count": bounded_integer(execution.get("tool_result_count"), 64),
            "write_tool_seen": bool(execution.get("write_tool_seen")),
        },
        "workspace": {
            "diff_observed": bool(workspace.get("diff_observed")),
            "changed_file_count": bounded_integer(workspace.get("changed_file_count"), 10000),
            "restore_previewed": bool(workspace.get("restore_previewed")),
            "restored": bool(workspace.get("restored")),
            "archive_count": bounded_integer(workspace.get("archive_count"), 10000),
        },
        "timing": {
            "approval_to_completion_ms": bounded_timing(timing.get("approval_to_completion_ms")),
            "approval_to_restore_ms": bounded_timing(timing.get("approval_to_restore_ms")),
        },
        "evidence_window_events": bounded_integer(value.get("evidence_window_events"), 1000),
    }
    runtime_id = _safe_metric_label(value.get("runtime_id"), 64)
    if runtime_id:
        result["runtime_id"] = runtime_id
    required = (
        result["plan_review"]["requested"],
        result["plan_review"]["approved"],
        result["plan_review"]["checkpoint_created"],
        result["plan_review"]["checkpoint_before_approval"],
        result["execution"]["turn_state"] == "completed",
        result["execution"]["tool_result_count"] > 0,
        result["execution"]["write_tool_seen"],
        result["workspace"]["diff_observed"],
        result["workspace"]["changed_file_count"] > 0,
        result["workspace"]["restore_previewed"],
        result["workspace"]["restored"],
    )
    if result["status"] == "passed" and not all(required):
        result["status"] = "failed"
        result["error_code"] = "incomplete-evidence"
    return result


def run_real_session_evidence(*, core_url: str, session_id: str, timeout: float) -> dict[str, Any]:
    base_url = _safe_base_url(core_url)
    runtime_session_id = _real_session_id(session_id)
    request = {
        "jsonrpc": "2.0",
        "id": "sumika-real-session-evidence",
        "method": "agent.acceptance.evidence",
        "params": {"sessionId": runtime_session_id},
    }
    try:
        response = _request_json(base_url, "/rpc", method="POST", payload=request, timeout=timeout)
    except PreflightError:
        return {"status": "failed", "error_code": "core-unavailable"}
    if not isinstance(response, dict) or response.get("error") is not None:
        return {"status": "failed", "error_code": "rpc-error"}
    return _project_real_session_evidence(response.get("result"))


def run_browser_smoke(
    *,
    endpoint: str,
    profile_dir: str,
    core_endpoint: str,
    timeout: float,
    include_write: bool = False,
) -> dict[str, Any]:
    """Run the local-only BrowserSkill protocol smoke against an explicit DSH profile."""

    # The smoke scripts validate the profile before mutating temporary DSH
    # routes.  Requiring an explicit profile keeps a daily check from guessing
    # which user's DSH_HOME should be changed.
    profile = _profile_path(profile_dir)
    try:
        profile_binding = verify_profile_binding(endpoint, profile, timeout=min(5.0, max(0.2, timeout)))
    except ProfileBindingError as error:
        return {
            "status": "failed",
            "error_code": error.code,
            "phase": "profile-check",
            "duration_ms": 0,
        }
    scripts = [("read", ROOT / "tools" / "smoke_dsh_browser.py")]
    if include_write:
        scripts.append(("write", ROOT / "tools" / "smoke_dsh_browser_write.py"))
    checks: list[dict[str, Any]] = []
    smoke_env = dict(os.environ)
    smoke_env["BSK_AUTO_UPDATE"] = "off"
    for name, script in scripts:
        command = [
            sys.executable,
            str(script),
            "--endpoint",
            str(endpoint),
            "--profile-dir",
            str(profile),
            "--core-endpoint",
            str(core_endpoint),
            "--timeout",
            str(max(1.0, timeout)),
        ]
        started = time.monotonic()
        try:
            completed = subprocess.run(
                command,
                cwd=str(ROOT),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=max(5.0, timeout + 15.0),
                check=False,
                env=smoke_env,
            )
        except FileNotFoundError:
            checks.append({"id": name, "status": "unavailable", "error": "python-not-found"})
            continue
        except subprocess.TimeoutExpired:
            checks.append({"id": name, "status": "failed", "error": "timeout", "phase": f"browser-{name}"})
            continue
        item = _browser_command_projection(completed.stdout, completed.stderr, phase=f"browser-{name}")
        item["id"] = name
        item["duration_ms"] = _duration(started)
        if completed.returncode != 0:
            item["status"] = "failed"
            item.setdefault("exit_code", int(completed.returncode))
        checks.append(item)
        if item["status"] != "passed":
            break
    statuses = {str(item.get("status")) for item in checks}
    status = "failed" if "failed" in statuses else ("unavailable" if "unavailable" in statuses else "passed")
    return {"status": status, "profile_binding": profile_binding, "checks": checks}


def _core_rpc_endpoint(value: str) -> str:
    """Turn a Core base URL or explicit ``/rpc`` URL into one RPC endpoint."""

    raw = str(value or "").strip().rstrip("/")
    if raw.endswith("/rpc"):
        return raw
    return raw + "/rpc"


def run_runtime_smoke(
    *,
    endpoint: str,
    profile_dir: str,
    timeout: float,
    mcp: bool = False,
    skills_subagents: bool = False,
) -> dict[str, Any]:
    profile = _profile_path(profile_dir)
    profile_started = time.monotonic()
    try:
        profile_binding = verify_profile_binding(endpoint, profile, timeout=min(5.0, max(0.2, timeout)))
    except ProfileBindingError as error:
        return {
            "status": "failed",
            "error": error.code,
            "error_code": error.code,
            "phase": "profile-check",
            "duration_ms": _duration(profile_started),
        }
    with tempfile.TemporaryDirectory(prefix="sumika-agent-daily-") as temporary:
        temporary_root = Path(temporary)
        workspace = temporary_root / "workspace"
        store = temporary_root / "store"
        _prepare_workspace(workspace, include_skill=skills_subagents)
        command = [
            sys.executable,
            str(ROOT / "tools" / "smoke_dsh_round.py"),
            "--endpoint",
            str(endpoint),
            "--profile-dir",
            str(profile),
            "--cwd",
            str(workspace),
            "--workspace-recovery",
            "--workspace-store",
            str(store),
            "--plan-execute",
            "--timeout",
            str(max(1.0, timeout)),
            "--skip-profile-check",
        ]
        if mcp:
            command.append("--mcp")
        if skills_subagents:
            command.append("--skills-subagents")
        started = time.monotonic()
        try:
            completed = subprocess.run(
                command,
                cwd=str(ROOT),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=max(5.0, timeout + 30.0),
                check=False,
                env=dict(os.environ),
            )
        except FileNotFoundError:
            return {"status": "unavailable", "error": "python-not-found", "duration_ms": _duration(started)}
        except subprocess.TimeoutExpired:
            return {"status": "failed", "error": "runtime-smoke-timeout", "duration_ms": _duration(started)}
        projection = _project_process_failure(completed.stdout, completed.stderr)
        projection["duration_ms"] = _duration(started)
        projection["profile_binding"] = profile_binding
        if completed.returncode != 0:
            projection["status"] = "failed"
            projection["exit_code"] = int(completed.returncode)
        return projection


def _preflight_report(core_url: str, timeout: float) -> dict[str, Any]:
    report = run_preflight(core_url, timeout=timeout)
    checks = [
        {"id": str(item.get("id") or "unknown"), "status": str(item.get("status") or "unknown")}
        for item in report.get("checks") or []
        if isinstance(item, dict)
    ]
    result: dict[str, Any] = {"status": str(report.get("overall") or "unavailable"), "checks": checks}
    runtime = next((item for item in report.get("checks") or [] if isinstance(item, dict) and item.get("id") == "agent-runtime"), {})
    provider = next((item for item in report.get("checks") or [] if isinstance(item, dict) and item.get("id") == "provider"), {})
    runtime_id = _safe_metric_label(runtime.get("runtime_id"), 64)
    runtime_version = _safe_metric_label(runtime.get("version"), 64)
    model = _safe_metric_label(provider.get("model"), 120)
    if runtime_id or runtime_version:
        result["runtime"] = {key: value for key, value in {"id": runtime_id, "version": runtime_version}.items() if value}
    if model:
        result["provider"] = {"model": model}
    return result


def _full_checks(timeout: float) -> dict[str, Any]:
    commands = [
        [sys.executable, "-m", "unittest", "discover", "-s", "backend/tests"],
        ["node", "--check", "frontend/main.js"],
        ["npm.cmd" if os.name == "nt" else "npm", "--prefix", "frontend", "run", "build"],
        ["cargo", "check", "--manifest-path", "src-tauri/Cargo.toml"],
    ]
    # ``unittest discover`` imports production modules directly.  A caller
    # may start this script from a clean shell with no repository-specific
    # environment, so make the source tree explicit for every child process.
    check_env = dict(os.environ)
    backend_source = str(ROOT / "backend" / "src")
    existing_pythonpath = str(check_env.get("PYTHONPATH") or "").strip()
    check_env["PYTHONPATH"] = os.pathsep.join(
        item for item in (backend_source, existing_pythonpath) if item
    )
    results: list[dict[str, Any]] = []
    for command in commands:
        result = _command(command, timeout=timeout, env=check_env)
        results.append({"command": Path(command[0]).name, **result})
        if result["status"] != "passed":
            break
    return {
        "status": "passed" if results and all(item["status"] == "passed" for item in results) else "failed",
        "checks": results,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--core-url", default=os.environ.get("SUMIKA_CORE_URL", "http://127.0.0.1:8771"))
    parser.add_argument("--endpoint", default=os.environ.get("SUMIKA_AGENT_ENDPOINT", "http://127.0.0.1:3080"))
    parser.add_argument("--profile-dir", default=os.environ.get("SUMIKA_AGENT_PROFILE_DIR", ""))
    parser.add_argument("--timeout", type=float, default=90.0)
    parser.add_argument("--runtime-smoke", action="store_true", help="run the isolated real DSH Plan/Execute smoke")
    parser.add_argument(
        "--real-session",
        default="",
        help="collect read-only bounded acceptance evidence for an existing real-provider session",
    )
    parser.add_argument("--mcp", action="store_true", help="include the isolated MCP stdio fixture in runtime smoke")
    parser.add_argument(
        "--skills-subagents",
        action="store_true",
        help="include the isolated Skills discovery/load and Subagents delegation smoke",
    )
    parser.add_argument("--full-tests", action="store_true", help="run Python, Node, frontend build, and Rust checks")
    parser.add_argument(
        "--browser-smoke",
        action="store_true",
        help="run the local-only BrowserSkill read smoke against an explicit DSH profile",
    )
    parser.add_argument(
        "--browser-write-smoke",
        action="store_true",
        help="also run the approval-gated local form write smoke",
    )
    parser.add_argument("--skip-preflight", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--report-dir",
        default=os.environ.get("SUMIKA_AGENT_REPORT_DIR", ""),
        help="write a bounded JSON report under the project directory",
    )
    return parser


def _report_directory(value: str) -> Path | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    directory = Path(os.path.expandvars(raw)).expanduser().resolve()
    allowed = (ROOT, ROOT / ".sumika-desktop")
    if not any(directory == base or base in directory.parents for base in allowed):
        raise ValueError("--report-dir must be inside the Sumika project or .sumika-desktop")
    return directory


def _write_report(report: dict[str, Any], directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = directory / f"agent-daily-{stamp}.json"
    suffix = 1
    while target.exists():
        target = directory / f"agent-daily-{stamp}-{suffix}.json"
        suffix += 1
    target.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return target


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if not 1.0 <= args.timeout <= 600:
        print("timeout must be between 1 and 600 seconds", file=sys.stderr)
        return 3
    try:
        report_directory = _report_directory(args.report_dir)
    except ValueError as error:
        print(f"invalid report directory: {error}", file=sys.stderr)
        return 3
    report: dict[str, Any] = {"schema_version": "sumika.agent-daily.v1", "started_at": _now(), "phases": {}}
    if not args.skip_preflight:
        try:
            report["phases"]["preflight"] = _preflight_report(args.core_url, min(args.timeout, 30.0))
        except Exception as error:
            report["phases"]["preflight"] = {"status": "failed", "error": type(error).__name__}
    if args.runtime_smoke:
        try:
            report["phases"]["runtime"] = run_runtime_smoke(
                endpoint=args.endpoint,
                profile_dir=args.profile_dir,
                timeout=args.timeout,
                mcp=args.mcp,
                skills_subagents=args.skills_subagents,
            )
        except (ValueError, RuntimeError) as error:
            report["phases"]["runtime"] = {"status": "failed", "error": type(error).__name__}
    if args.real_session:
        try:
            report["phases"]["real_provider"] = run_real_session_evidence(
                core_url=args.core_url,
                session_id=args.real_session,
                timeout=min(args.timeout, 30.0),
            )
        except ValueError as error:
            report["phases"]["real_provider"] = {"status": "failed", "error": type(error).__name__}
    if args.browser_smoke or args.browser_write_smoke:
        try:
            report["phases"]["browser"] = run_browser_smoke(
                endpoint=args.endpoint,
                profile_dir=args.profile_dir,
                core_endpoint=_core_rpc_endpoint(args.core_url),
                timeout=min(args.timeout, 180.0),
                include_write=args.browser_write_smoke,
            )
        except (ValueError, RuntimeError) as error:
            report["phases"]["browser"] = {"status": "failed", "error": type(error).__name__}
    if args.full_tests:
        report["phases"]["regression"] = _full_checks(args.timeout)
    report["finished_at"] = _now()
    statuses = [str(item.get("status")) for item in report["phases"].values() if isinstance(item, dict)]
    if any(status == "failed" for status in statuses):
        report["overall"] = "failed"
        exit_code = 1
    elif any(status in {"needs-action", "unavailable"} for status in statuses):
        report["overall"] = "needs-action"
        exit_code = 2
    else:
        report["overall"] = "passed"
        exit_code = 0
    report_path: Path | None = None
    if report_directory is not None:
        try:
            report["report_written"] = True
            report_path = _write_report(report, report_directory)
        except OSError as error:
            report["report_written"] = False
            report["report_write_error"] = type(error).__name__
            if report["overall"] == "passed":
                report["overall"] = "failed"
                exit_code = 1
    if args.json:
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    else:
        print(f"Sumika Agent daily acceptance: {report['overall']}")
        for name, phase in report["phases"].items():
            print(f"- {name}: {phase.get('status', 'unknown')}")
        if report_path is not None:
            print(f"report: {report_path}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
