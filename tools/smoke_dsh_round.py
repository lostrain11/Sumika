"""Run one explicit DSH Agent round against local protocol fixtures."""

from __future__ import annotations

import argparse
from collections import Counter
import json
import os
import sys
import time
from pathlib import Path
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend" / "src"))

from backend.tests.fixtures.openai_compatible import OpenAICompatibleStub  # noqa: E402
from sumika_core.agent.adapters.dsh.runtime import (  # noqa: E402
    DSHAgentRuntime,
    _dsh_route_id,
)
from sumika_core.agent.contracts import AgentRuntimeError  # noqa: E402
from sumika_core.workspace.runtime import WorkspaceRuntime  # noqa: E402
from dsh_profile import ProfileBindingError, verify_profile_binding  # noqa: E402


_WORKSPACE_SMOKE_MARKER = '{"format":1,"purpose":"dsh-workspace-recovery-smoke"}\n'
_WORKSPACE_SMOKE_FILE = "sumika-smoke.txt"
_WORKSPACE_BASELINE = "SUMIKA_WORKSPACE_BASELINE\n"
_WORKSPACE_EDITED = "SUMIKA_WORKSPACE_AGENT_EDIT\n"
_MCP_PROFILE_MARKER_FILE = ".sumika-mcp-smoke-profile.json"
_MCP_PROFILE_MARKER = '{"format":1,"purpose":"dsh-mcp-protocol-smoke"}\n'
_MCP_SERVER_NAME = "sumika_smoke"
_MCP_TOOL_NAME = "mcp__sumika_smoke__echo"
_MCP_RESULT_MARKER = "SUMIKA_MCP_ECHO:roundtrip"
_MCP_SERVER = ROOT / "backend" / "tests" / "fixtures" / "mcp_stdio_server.py"
_SKILL_NAME = "sumika-smoke"
_SKILL_MARKER = "SUMIKA_SKILL_INSTRUCTIONS_OK"


def _tool_status_error(tool_script: list[dict[str, object]], tool_statuses: list[dict[str, str]]) -> str | None:
    """Validate observable tools without treating plan exit as a tool.

    DSH records ``exit_plan_mode`` in the plan lifecycle and omits it from the
    terminal ``tools`` projection. All other scripted calls must appear exactly
    once and finish successfully.
    """

    expected = [
        str(item.get("name") or "")
        for item in tool_script
        if str(item.get("name") or "") != "exit_plan_mode"
    ]
    observed = [str(item.get("name") or "") for item in tool_statuses]
    if Counter(expected) != Counter(observed):
        return f"DSH smoke round observed unexpected tools: {tool_statuses}"
    incomplete = [item for item in tool_statuses if item.get("status") != "completed"]
    if incomplete:
        return f"DSH smoke round contained incomplete or failed tools: {tool_statuses}"
    return None


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", default=os.environ.get("SUMIKA_AGENT_ENDPOINT", "http://127.0.0.1:3080"))
    parser.add_argument("--profile-dir", default=os.environ.get("SUMIKA_AGENT_PROFILE_DIR", ""))
    parser.add_argument("--cwd", default=str(ROOT))
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--workspace-recovery", action="store_true")
    parser.add_argument("--workspace-store", default=os.environ.get("SUMIKA_WORKSPACE_SMOKE_STORE", ""))
    parser.add_argument("--mcp", action="store_true")
    parser.add_argument(
        "--skills-subagents",
        action="store_true",
        help="verify local Skill discovery/loading and one-shot Subagent delegation",
    )
    parser.add_argument(
        "--plan-execute",
        action="store_true",
        help="run a DSH plan review, approve it, then execute the deterministic tool sequence",
    )
    parser.add_argument(
        "--skip-profile-check",
        action="store_true",
        help="skip the read-only endpoint/profile pairing check (only for an already verified process)",
    )
    return parser


def _default_model_snapshot(runtime: DSHAgentRuntime) -> dict[str, str | None]:
    """Capture only the non-sensitive default model fields before a smoke run."""

    try:
        descriptor = runtime._settings_namespace("agent-default-model")
    except AgentRuntimeError:
        # A brand-new isolated DSH profile may not have this optional
        # namespace. The smoke route is still safe; there is simply no
        # default-model side effect to restore.
        return {"provider": None, "model": None}
    value = descriptor.get("value") if isinstance(descriptor, dict) else {}
    if not isinstance(value, dict):
        value = {}
    return {
        "provider": str(value.get("provider") or "") or None,
        "model": str(value.get("model") or "") or None,
    }


def _restore_default_model(
    runtime: DSHAgentRuntime,
    route_id: str,
    previous: dict[str, str | None],
) -> None:
    """Restore the default only when the smoke run still owns that setting."""

    try:
        descriptor = runtime._settings_namespace("agent-default-model")
    except AgentRuntimeError:
        return
    current = descriptor.get("value") if isinstance(descriptor, dict) else {}
    if not isinstance(current, dict) or str(current.get("provider") or "") != route_id:
        return
    operations: list[dict[str, object]] = []
    for key in ("provider", "model"):
        value = previous.get(key)
        if value:
            operations.append({"op": "set", "path": [key], "value": value})
        else:
            operations.append({"op": "unset", "path": [key]})
    payload: dict[str, object] = {"ns": "agent-default-model", "ops": operations}
    revision = descriptor.get("revision")
    if isinstance(revision, int):
        payload["expectedRevision"] = revision
    runtime._call("settings.mutate", payload)


def _set_default_model(runtime: DSHAgentRuntime, route_id: str, model: str) -> None:
    """Point the isolated profile's child-agent inheritance at the stub route."""

    descriptor = runtime._settings_namespace("agent-default-model")
    payload: dict[str, object] = {
        "ns": "agent-default-model",
        "ops": [
            {"op": "set", "path": ["provider"], "value": route_id},
            {"op": "set", "path": ["model"], "value": model},
        ],
    }
    revision = descriptor.get("revision")
    if isinstance(revision, int):
        payload["expectedRevision"] = revision
    runtime._call("settings.mutate", payload)


def _remove_route(
    runtime: DSHAgentRuntime,
    route_id: str,
    *,
    previous_default: dict[str, str | None],
) -> None:
    """Remove only this smoke route and restore its default-model side effect."""

    errors: list[Exception] = []
    try:
        descriptor = runtime._settings_namespace("llm-pi-ai")
        value = descriptor.get("value") if isinstance(descriptor, dict) else {}
        providers = value.get("providers") if isinstance(value, dict) else {}
        if isinstance(providers, dict) and route_id in providers:
            payload: dict[str, object] = {
                "ns": "llm-pi-ai",
                "ops": [{"op": "unset", "path": ["providers", route_id]}],
            }
            revision = descriptor.get("revision")
            if isinstance(revision, int):
                payload["expectedRevision"] = revision
            runtime._call("settings.mutate", payload)
    except Exception as error:
        errors.append(error)
    try:
        _restore_default_model(runtime, route_id, previous_default)
    except Exception as error:
        errors.append(error)
    if errors:
        raise errors[0]


def main() -> int:
    args = _parser().parse_args()
    profile_dir = str(args.profile_dir).strip()
    if not profile_dir:
        raise SystemExit("--profile-dir or SUMIKA_AGENT_PROFILE_DIR is required; use an isolated DSH profile")
    profile_path = Path(profile_dir).resolve()
    global_home = Path.home().resolve()
    if profile_path == global_home or global_home in profile_path.parents:
        raise SystemExit("Refusing to mutate a profile under the user home; pass Sumika's isolated DSH profile")
    profile_binding: dict[str, object] | None = None
    if not args.skip_profile_check:
        try:
            profile_binding = verify_profile_binding(
                args.endpoint,
                profile_path,
                timeout=min(5.0, max(0.2, args.timeout)),
            )
        except ProfileBindingError as error:
            raise SystemExit(f"DSH endpoint/profile check failed: {error.code}") from error
    if args.mcp:
        marker = profile_path / _MCP_PROFILE_MARKER_FILE
        try:
            marker_text = marker.read_text(encoding="utf-8")
        except OSError as error:
            raise SystemExit(
                f"MCP smoke requires {_MCP_PROFILE_MARKER_FILE} in a dedicated isolated profile"
            ) from error
        if marker_text != _MCP_PROFILE_MARKER:
            raise SystemExit("MCP smoke profile marker does not match")
        if not _MCP_SERVER.is_file():
            raise SystemExit("MCP smoke stdio server fixture is unavailable")
    workspace_path = Path(args.cwd).resolve()
    workspace_runtime: WorkspaceRuntime | None = None
    workspace_checkpoint: dict[str, object] | None = None
    workspace_restored = False
    if args.workspace_recovery:
        if workspace_path == ROOT:
            raise SystemExit("Refusing workspace recovery smoke against the Sumika source checkout")
        marker = workspace_path / ".sumika-workspace-smoke.json"
        target = workspace_path / _WORKSPACE_SMOKE_FILE
        try:
            marker_text = marker.read_text(encoding="utf-8")
            baseline_text = target.read_text(encoding="utf-8")
        except OSError as error:
            raise SystemExit("Workspace recovery smoke requires its dedicated marker and baseline file") from error
        if marker_text != _WORKSPACE_SMOKE_MARKER or baseline_text != _WORKSPACE_BASELINE:
            raise SystemExit("Workspace recovery smoke marker or baseline content does not match")
        workspace_store = str(args.workspace_store).strip()
        if not workspace_store:
            raise SystemExit("--workspace-store or SUMIKA_WORKSPACE_SMOKE_STORE is required with --workspace-recovery")
        workspace_runtime = WorkspaceRuntime(Path(workspace_store).resolve())
        workspace_checkpoint = workspace_runtime.create_checkpoint(
            workspace_path,
            name="DSH workspace recovery smoke",
        )["checkpoint"]

    env = dict(os.environ)
    env.update(
        {
            "SUMIKA_AGENT_ENDPOINT": args.endpoint,
            "SUMIKA_AGENT_PROFILE_DIR": str(profile_path),
            "SUMIKA_AGENT_ENABLED": "1",
        }
    )
    expected = "SUMIKA_DSH_SMOKE_OK"
    # DSH mounts each MCP server name process-wide. A fresh name keeps
    # repeated smoke runs independent even when an older isolated preset is
    # intentionally retained as evidence.
    mcp_server_name = f"sumika_smoke_{uuid4().hex[:8]}"
    mcp_tool_name = f"mcp__{mcp_server_name}__echo"
    base_tool_script = [
        {
            "name": "read",
            "arguments": {
                "file_path": _WORKSPACE_SMOKE_FILE if args.workspace_recovery else "README.md",
                "offset": 1,
                "limit": 2,
            },
        },
        {
            "name": "ask_user_question",
            "arguments": {
                "questions": [
                    {
                        "id": "continue-smoke",
                        "header": "Protocol check",
                        "question": "Continue the deterministic Sumika protocol check?",
                        "options": [
                            {"label": "Continue", "description": "Complete the remaining protocol checks."},
                            {"label": "Stop", "description": "Leave the test turn waiting."},
                        ],
                        "multi_select": False,
                    }
                ]
            },
        },
        {
            "name": "pwsh",
                "arguments": {
                    "command": "Get-Location",
                    "description": "Report the current workspace location",
                    "workdir": str(workspace_path),
                "sandbox_permissions": "danger-full-access",
                "justification": "Approve one harmless location query to verify the DSH approval transport.",
            },
        },
    ]
    tool_script = (
        [
            {
                "name": "exit_plan_mode",
                "arguments": {
                    "plan": "# Sumika daily protocol smoke\n\n- Inspect the isolated workspace.\n- Execute the approved deterministic checks.\n- Verify the workspace can be restored."
                },
            }
        ]
        if args.plan_execute
        else []
    )
    if args.skills_subagents:
        tool_script.append(
            {
                "name": "skill",
                "arguments": {"name": _SKILL_NAME},
            }
        )
    if args.mcp:
        tool_script.append(
            {
                "name": mcp_tool_name,
                "arguments": {"text": "roundtrip"},
            }
        )
    tool_script.extend(base_tool_script)
    if args.workspace_recovery:
        tool_script.append(
            {
                "name": "edit",
                "arguments": {
                    "file_path": _WORKSPACE_SMOKE_FILE,
                    "old_string": _WORKSPACE_BASELINE,
                    "new_string": _WORKSPACE_EDITED,
                    "replace_all": False,
                },
            }
        )
    if args.skills_subagents:
        # Use the foreground route so the smoke can immediately inspect the
        # durable child roster and history.  The standard preset still owns
        # the provider and permission policy; this only fixes the request
        # shape sent by the deterministic model fixture.
        tool_script.append(
            {
                "name": "subagent",
                "arguments": {
                    "description": "verify child",
                    "prompt": "Reply with the deterministic child marker only.",
                    "run_in_background": False,
                },
            }
        )
    profile_id = f"dsh-smoke-{uuid4().hex[:12]}"
    route_id = _dsh_route_id(profile_id)
    events: list[dict[str, object]] = []
    runtime = DSHAgentRuntime(ROOT / ".sumika-smoke-unused", env=env)
    runtime.set_event_sink(events.append)
    cleanup_error = None
    summary: dict[str, object] = {}
    agent_preset = "standard"
    mcp_setup: dict[str, object] | None = None
    skills_setup: dict[str, object] | None = None
    previous_default_model: dict[str, str | None] = {}

    try:
        health = runtime.health()
        if not health.get("ok"):
            raise RuntimeError(str(health.get("error") or "DSH health check failed"))
        previous_default_model = _default_model_snapshot(runtime)
        time.sleep(0.25)
        if args.mcp:
            roster = runtime.list_presets({})
            source = next(
                (
                    item
                    for item in roster.get("presets") or []
                    if isinstance(item, dict)
                    and item.get("id") == "standard"
                    and not item.get("broken")
                ),
                None,
            )
            if source is None:
                raise RuntimeError("DSH standard preset is unavailable for MCP smoke")
            agent_preset = f"sumika-mcp-smoke-{uuid4().hex[:10]}"
            runtime.copy_preset(
                {
                    "from": "standard",
                    "agentPreset": agent_preset,
                    "name": "Sumika MCP protocol smoke",
                }
            )
            preview = runtime.preview_mcp_configuration(
                {
                    "agentPreset": agent_preset,
                    "action": "upsert",
                    "configuration": {
                        "server_name": mcp_server_name,
                        "transport": "stdio",
                        "enabled": True,
                        "command": sys.executable,
                        "args": [str(_MCP_SERVER)],
                        "tool_call_timeout_ms": 10000,
                    },
                }
            )
            applied = runtime.apply_mcp_configuration(
                {
                    "agentPreset": agent_preset,
                    "previewToken": preview.get("preview_token"),
                }
            )
            if not applied.get("mountable") or not applied.get("validation_session_archived"):
                raise RuntimeError("MCP smoke preset did not pass mount validation")
            mcp_setup = {
                "agent_preset": agent_preset,
                "configuration_applied": bool(applied.get("applied")),
                "mountable": True,
                "validation_session_archived": True,
            }
        with OpenAICompatibleStub(response_text=expected, scripted_tool_calls=tool_script) as stub:
            binding = runtime.sync_provider_profile(
                {
                    "id": profile_id,
                    "name": "Sumika DSH protocol smoke",
                    "template_id": "openai-compatible",
                    "processing_location": "local",
                    "config": {"active_base_url": stub.base_url, "model": stub.model},
                    "secrets": {},
                }
            )
            if args.skills_subagents:
                # Spawned children inherit the profile default model in the
                # pinned DSH release.  Keep that inheritance inside the
                # isolated smoke route and restore it in ``finally``.
                _set_default_model(runtime, route_id, stub.model)
            created = runtime.create_session(
                {"cwd": str(Path(args.cwd).resolve()), "agentPreset": agent_preset}
            )
            session_id = str(created.get("sessionId") or created.get("id") or "")
            if not session_id:
                raise RuntimeError("DSH session.create did not return a session id")
            runtime.select_model({"sessionId": session_id, "provider": route_id, "model": stub.model})
            if args.skills_subagents:
                skill_catalog = runtime._call("skill.list", {"sessionId": session_id})
                skills = skill_catalog.get("skills") if isinstance(skill_catalog, dict) else None
                discovered = any(
                    isinstance(item, dict)
                    and str(item.get("name") or "") == _SKILL_NAME
                    and item.get("modelInvocable") is True
                    for item in (skills if isinstance(skills, list) else [])
                )
                if not discovered:
                    raise RuntimeError("DSH did not discover the isolated Skill fixture")
                skills_setup = {
                    "skill_discovered": True,
                    "skill_loaded": False,
                    "subagent_created": False,
                    "subagent_history_read": False,
                    "child_count": 0,
                }
            plan_accepted: dict[str, object] | None = None
            accepted: dict[str, object] | None = None
            if args.plan_execute:
                plan_accepted = runtime.prompt(
                    {
                        "sessionId": session_id,
                        "text": "Inspect the isolated workspace and prepare a short plan for the deterministic checks.",
                        "mode": "plan",
                    }
                )
            else:
                accepted = runtime.prompt(
                    {
                        "sessionId": session_id,
                        "text": "Run the deterministic read, question, and approval protocol checks, then reply with the marker.",
                    }
                )

            deadline = time.monotonic() + max(1.0, args.timeout)
            snapshot: dict[str, object] = {}
            answered_interactions: set[str] = set()
            question_answered = False
            approval_answered = False
            plan_review_answered = False
            execute_started = not args.plan_execute
            marker_received = False
            while time.monotonic() < deadline:
                pending = runtime.interactions({"sessionId": session_id})
                for interaction in pending.get("interactions") or []:
                    if not isinstance(interaction, dict) or str(interaction.get("id") or "") in answered_interactions:
                        continue
                    interaction_id = str(interaction["id"])
                    if interaction.get("kind") == "question":
                        if interaction.get("plan_review"):
                            questions = interaction.get("questions")
                            question = questions[0] if isinstance(questions, list) and questions else {}
                            plan_review = interaction.get("plan_review")
                            plan_review = plan_review if isinstance(plan_review, dict) else {}
                            review_id = (
                                str(question.get("id") or "plan-review")
                                if isinstance(question, dict)
                                else "plan-review"
                            )
                            approve = str(plan_review.get("approve") or "Approve")
                            answer = {"answers": [{"id": review_id, "selected": [approve]}]}
                            plan_review_answered = True
                        else:
                            answer = {"answers": [{"id": "continue-smoke", "selected": ["Continue"]}]}
                            question_answered = True
                        runtime.respond_interaction(
                            {
                                "rpcId": interaction_id,
                                "sessionId": session_id,
                                "answer": answer,
                            }
                        )
                    elif interaction.get("kind") == "approval":
                        runtime.respond_interaction(
                            {
                                "rpcId": interaction_id,
                                "sessionId": session_id,
                                "approvalId": interaction.get("approval_id"),
                                "outcome": "allowed-once",
                            }
                        )
                        approval_answered = True
                    else:
                        raise RuntimeError(f"unsupported DSH interaction: {interaction.get('kind')}")
                    answered_interactions.add(interaction_id)
                snapshot = runtime.snapshot({"sessionId": session_id, "maxMessages": 8})
                plan_state = snapshot.get("plan") if isinstance(snapshot.get("plan"), dict) else {}
                if (
                    args.plan_execute
                    and not execute_started
                    and plan_review_answered
                    and snapshot.get("state") in {"completed", "idle"}
                    and plan_state.get("active") is not True
                ):
                    accepted = runtime.prompt(
                        {
                            "sessionId": session_id,
                            "text": "Carry out the approved deterministic checks, then reply with the marker.",
                            "mode": "execute",
                            "leave_plan": True,
                        }
                    )
                    execute_started = True
                messages = snapshot.get("messages") if isinstance(snapshot.get("messages"), list) else []
                marker_received = any(
                    expected in str(item.get("content") or "")
                    for item in messages
                    if isinstance(item, dict)
                )
                if marker_received and snapshot.get("state") in {"completed", "idle"}:
                    break
                time.sleep(0.2)
            else:
                raise RuntimeError("DSH smoke round timed out before the final assistant message and terminal state")

            payloads = [
                request.get("payload")
                for request in stub.requests
                if isinstance(request, dict) and isinstance(request.get("payload"), dict)
            ]
            tool_names = sorted(
                {
                    str(tool.get("function", {}).get("name") or tool.get("name") or "")
                    for payload in payloads
                    for tool in (payload.get("tools") or [])
                    if isinstance(tool, dict)
                }
                - {""}
            )
            summary = {
                "ok": True,
                "runtime_ready": True,
                "route_active": bool(binding.get("active")),
                "session_id": session_id,
                "prompt_accepted": bool(accepted and accepted.get("accepted", True)),
                "plan_prompt_accepted": bool(plan_accepted),
                "plan_review_answered": plan_review_answered,
                "execute_started": execute_started,
                "request_count": len(stub.requests),
                "stream_requested": bool(payloads) and all(bool(payload.get("stream")) for payload in payloads),
                "tool_count": len(tool_names),
                "tool_names": tool_names[:32],
                "scripted_tools_completed": list(stub.completed_tool_calls),
                "question_answered": question_answered,
                "approval_answered": approval_answered,
                "final_state": snapshot.get("state"),
                "event_count": len(events),
                "event_types": sorted({str(item.get("event_type") or "") for item in events if isinstance(item, dict)})[:24],
                "marker_received": marker_received,
            }
            if profile_binding is not None:
                summary["profile_binding"] = profile_binding
            if stub.completed_tool_calls != [item["name"] for item in tool_script]:
                raise RuntimeError(f"DSH did not complete the scripted tool sequence: {stub.completed_tool_calls}")
            if args.mcp:
                mcp_result_seen = any(
                    _MCP_RESULT_MARKER in json.dumps(payload.get("messages") or [], ensure_ascii=False)
                    for payload in payloads
                )
                if mcp_tool_name not in tool_names:
                    raise RuntimeError("DSH model request did not expose the configured MCP tool")
                if not mcp_result_seen:
                    raise RuntimeError("DSH model request did not receive the MCP tool result")
                summary["mcp"] = {
                    **(mcp_setup or {}),
                    "tool_name": mcp_tool_name,
                    "tool_result_seen_by_model": True,
                }
            if args.skills_subagents:
                skill_loaded = any(
                    _SKILL_MARKER in json.dumps(payload.get("messages") or [], ensure_ascii=False)
                    for payload in payloads
                )
                if not skill_loaded:
                    raise RuntimeError("DSH model request did not receive the loaded Skill instructions")
                child_catalog: dict[str, object] = {"entries": []}
                child_history: dict[str, object] | None = None
                child_entry: dict[str, object] | None = None
                child_deadline = time.monotonic() + min(12.0, max(2.0, args.timeout / 3))
                while time.monotonic() < child_deadline:
                    child_catalog = runtime.list_subagents({"parentSessionId": session_id})
                    children = [
                        item
                        for item in child_catalog.get("entries") or []
                        if isinstance(item, dict) and item.get("kind") == "child"
                    ]
                    if children:
                        child_entry = children[-1]
                        try:
                            candidate_history = runtime.subagent_history(
                                {
                                    "parentSessionId": session_id,
                                    "childSessionId": child_entry.get("id"),
                                    "mode": child_entry.get("mode"),
                                    "maxMessages": 8,
                                }
                            )
                        except AgentRuntimeError:
                            candidate_history = None
                        if isinstance(candidate_history, dict):
                            child_history = candidate_history
                            break
                    time.sleep(0.2)
                if child_entry is None:
                    raise RuntimeError("DSH subagent tool did not create a direct child")
                if child_history is None:
                    raise RuntimeError("DSH subagent history was not readable")
                skills_setup = {
                    **(skills_setup or {}),
                    "skill_discovered": True,
                    "skill_loaded": True,
                    "subagent_created": True,
                    "subagent_history_read": isinstance(child_history.get("messages"), list),
                    "child_count": len(
                        [
                            item
                            for item in child_catalog.get("entries") or []
                            if isinstance(item, dict) and item.get("kind") == "child"
                        ]
                    ),
                }
                if not skills_setup["subagent_history_read"]:
                    raise RuntimeError("DSH subagent history returned no projected messages")
                summary["skills_subagents"] = skills_setup
            if not question_answered or not approval_answered:
                raise RuntimeError("DSH smoke round completed without both interaction responses")
            if args.plan_execute and not plan_review_answered:
                raise RuntimeError("DSH plan smoke completed without an approved plan review")
            tool_statuses = [
                {
                    "name": str(item.get("name") or ""),
                    "status": str(item.get("status") or ""),
                }
                for item in snapshot.get("tools") or []
                if isinstance(item, dict)
            ]
            tool_status_error = _tool_status_error(tool_script, tool_statuses)
            if tool_status_error:
                raise RuntimeError(tool_status_error)
            summary["tool_statuses"] = tool_statuses
            if workspace_runtime is not None and workspace_checkpoint is not None:
                checkpoint_id = str(workspace_checkpoint["id"])
                changed = workspace_runtime.diff_checkpoint(checkpoint_id, path=workspace_path)
                changed_paths = [str(item.get("path") or "") for item in changed.get("files") or []]
                if changed.get("counts", {}).get("changed_total") != 1 or changed_paths != [_WORKSPACE_SMOKE_FILE]:
                    raise RuntimeError(f"unexpected workspace smoke diff: {changed.get('counts')} {changed_paths}")
                preview = workspace_runtime.restore_preview(checkpoint_id, path=workspace_path)
                restored = workspace_runtime.restore(
                    checkpoint_id,
                    approved=True,
                    confirm_checkpoint=checkpoint_id,
                    preview_token=str(preview["preview_token"]),
                    path=workspace_path,
                )
                workspace_restored = True
                after = workspace_runtime.diff_checkpoint(checkpoint_id, path=workspace_path)
                if after.get("changed") or (workspace_path / _WORKSPACE_SMOKE_FILE).read_text(encoding="utf-8") != _WORKSPACE_BASELINE:
                    raise RuntimeError("workspace smoke restore did not reproduce the checkpoint")
                summary["workspace_recovery"] = {
                    "checkpoint_id": checkpoint_id,
                    "changed_file_count": changed["counts"]["changed_total"],
                    "restore_preview_token_used": True,
                    "pre_restore_checkpoint_id": restored["pre_restore_checkpoint"]["id"],
                    "archive_entry_count": len(restored["archive"]["entries"]),
                    "restored": True,
                }
    finally:
        if workspace_runtime is not None and workspace_checkpoint is not None and not workspace_restored:
            try:
                checkpoint_id = str(workspace_checkpoint["id"])
                preview = workspace_runtime.restore_preview(checkpoint_id, path=workspace_path)
                if preview.get("changed"):
                    workspace_runtime.restore(
                        checkpoint_id,
                        approved=True,
                        confirm_checkpoint=checkpoint_id,
                        preview_token=str(preview["preview_token"]),
                        path=workspace_path,
                    )
            except Exception:
                pass
        try:
            _remove_route(runtime, route_id, previous_default=previous_default_model)
        except Exception as error:  # cleanup is reported rather than hiding the smoke result
            cleanup_error = type(error).__name__
        runtime.close()

    summary["route_cleanup"] = "ok" if cleanup_error is None else f"failed:{cleanup_error}"
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary.get("ok") and cleanup_error is None else 1


if __name__ == "__main__":
    raise SystemExit(main())
