"""Run a bounded DSH-to-BrowserSkill protocol smoke.

The smoke uses a temporary OpenAI-compatible model route and an isolated DSH
profile. It verifies that the official BrowserSkill plugin is lazily revealed
after the browser Skill is loaded, that Sumika's policy companion blocks a
first external navigation until approval, and that a real BrowserSkill
session can be observed and stopped. Only boolean/count evidence is printed.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend" / "src"))

from backend.tests.fixtures.openai_compatible import OpenAICompatibleStub  # noqa: E402
from sumika_core.agent.adapters.dsh.runtime import DSHAgentRuntime, _dsh_route_id  # noqa: E402
from sumika_core.agent.contracts import AgentRuntimeError  # noqa: E402
from tools.dsh_profile import ProfileBindingError, verify_profile_binding  # noqa: E402


MARKER = "SUMIKA_DSH_BROWSER_SMOKE_OK"
SCRIPT = (
    {"name": "skill", "arguments": {"name": "browser-skill"}},
    {"name": "browser_session_start", "arguments": {"noFocus": True}},
    {
        "name": "browser_navigate",
        "arguments": {"url": "https://example.com/", "waitUntil": "domcontentloaded"},
    },
    {
        "name": "browser_snapshot",
        "arguments": {"maxDepth": 8, "maxTokens": 1200},
    },
    {"name": "browser_session_stop", "arguments": {}},
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", default=os.environ.get("SUMIKA_AGENT_ENDPOINT", "http://127.0.0.1:3080"))
    parser.add_argument("--profile-dir", default=os.environ.get("SUMIKA_AGENT_PROFILE_DIR", ""))
    parser.add_argument("--core-endpoint", default=os.environ.get("SUMIKA_CORE_ENDPOINT", "http://127.0.0.1:8770/rpc"))
    parser.add_argument("--timeout", type=float, default=45.0)
    return parser


def _profile_path(value: str) -> Path:
    profile = Path(os.path.expandvars(str(value or "").strip())).expanduser().resolve()
    if not str(value or "").strip():
        raise SystemExit("--profile-dir or SUMIKA_AGENT_PROFILE_DIR is required")
    home = Path.home().resolve()
    if profile == home or home in profile.parents:
        raise SystemExit("Refusing to mutate a DSH profile under the user home")
    return profile


def _default_model(runtime: DSHAgentRuntime) -> dict[str, str | None]:
    try:
        descriptor = runtime._settings_namespace("agent-default-model")
    except AgentRuntimeError:
        return {"provider": None, "model": None}
    value = descriptor.get("value") if isinstance(descriptor, dict) else {}
    value = value if isinstance(value, dict) else {}
    return {
        "provider": str(value.get("provider") or "") or None,
        "model": str(value.get("model") or "") or None,
    }


def _restore_default(runtime: DSHAgentRuntime, route_id: str, previous: dict[str, str | None]) -> None:
    try:
        descriptor = runtime._settings_namespace("agent-default-model")
    except AgentRuntimeError:
        return
    value = descriptor.get("value") if isinstance(descriptor, dict) else {}
    if not isinstance(value, dict) or str(value.get("provider") or "") != route_id:
        return
    operations: list[dict[str, Any]] = []
    for key in ("provider", "model"):
        if previous.get(key):
            operations.append({"op": "set", "path": [key], "value": previous[key]})
        else:
            operations.append({"op": "unset", "path": [key]})
    payload: dict[str, Any] = {"ns": "agent-default-model", "ops": operations}
    if isinstance(descriptor.get("revision"), int):
        payload["expectedRevision"] = descriptor["revision"]
    runtime._call("settings.mutate", payload)


def _remove_route(runtime: DSHAgentRuntime, route_id: str, previous: dict[str, str | None]) -> None:
    descriptor = runtime._settings_namespace("llm-pi-ai")
    value = descriptor.get("value") if isinstance(descriptor, dict) else {}
    providers = value.get("providers") if isinstance(value, dict) else {}
    if isinstance(providers, dict) and route_id in providers:
        payload: dict[str, Any] = {
            "ns": "llm-pi-ai",
            "ops": [{"op": "unset", "path": ["providers", route_id]}],
        }
        if isinstance(descriptor.get("revision"), int):
            payload["expectedRevision"] = descriptor["revision"]
        runtime._call("settings.mutate", payload)
    _restore_default(runtime, route_id, previous)


def _tool_statuses(snapshot: dict[str, Any]) -> list[dict[str, str]]:
    return [
        {"name": str(item.get("name") or ""), "status": str(item.get("status") or "")}
        for item in snapshot.get("tools") or []
        if isinstance(item, dict) and item.get("name")
    ]


def main() -> int:
    args = _parser().parse_args()
    profile = _profile_path(args.profile_dir)
    try:
        verify_profile_binding(args.endpoint, profile, timeout=min(5.0, max(0.2, args.timeout)))
    except ProfileBindingError as error:
        print(json.dumps({"ok": False, "error": error.code}, ensure_ascii=False))
        return 1
    env = dict(os.environ)
    env.update(
        {
            "SUMIKA_AGENT_ENDPOINT": str(args.endpoint).rstrip("/"),
            "SUMIKA_AGENT_PROFILE_DIR": str(profile),
            "SUMIKA_AGENT_ENABLED": "1",
            "SUMIKA_CORE_ENDPOINT": str(args.core_endpoint),
        }
    )
    profile_id = f"dsh-browser-smoke-{uuid4().hex[:12]}"
    route_id = _dsh_route_id(profile_id)
    runtime = DSHAgentRuntime(ROOT / ".sumika-smoke-unused", env=env)
    events: list[dict[str, Any]] = []
    runtime.set_event_sink(events.append)
    runtime.start_event_bridge()
    previous: dict[str, str | None] = {}
    session_id = ""
    cleanup_error: str | None = None
    completed_calls: list[str] = []
    approvals = 0
    snapshot: dict[str, Any] = {}
    try:
        health = runtime.health()
        if not health.get("ok"):
            raise RuntimeError("DSH health check failed")
        previous = _default_model(runtime)
        with OpenAICompatibleStub(model="sumika-dsh-browser-smoke", response_text=MARKER, scripted_tool_calls=list(SCRIPT)) as stub:
            runtime.sync_provider_profile(
                {
                    "id": profile_id,
                    "name": "Sumika DSH Browser protocol smoke",
                    "template_id": "openai-compatible",
                    "processing_location": "local",
                    "config": {"active_base_url": stub.base_url, "model": stub.model},
                    "secrets": {},
                }
            )
            created = runtime.create_session({"cwd": str(ROOT)})
            session_id = str(created.get("sessionId") or created.get("id") or "")
            if not session_id:
                raise RuntimeError("DSH session.create did not return a session id")
            runtime.select_model({"sessionId": session_id, "provider": route_id, "model": stub.model})
            runtime.prompt({"sessionId": session_id, "text": "Load the browser Skill, open example.com, observe it, and stop the browser session.", "mode": "execute"})
            deadline = time.monotonic() + max(5.0, args.timeout)
            answered: set[str] = set()
            while time.monotonic() < deadline:
                for interaction in runtime.interactions({"sessionId": session_id}).get("interactions") or []:
                    if not isinstance(interaction, dict):
                        continue
                    interaction_id = str(interaction.get("id") or "")
                    if not interaction_id or interaction_id in answered:
                        continue
                    kind = str(interaction.get("kind") or "")
                    if kind == "approval":
                        runtime.respond_interaction(
                            {
                                "rpcId": interaction_id,
                                "sessionId": session_id,
                                "approvalId": interaction.get("approval_id"),
                                "outcome": "allowed-once",
                            }
                        )
                        approvals += 1
                    elif kind == "question":
                        # The browser flow should not require a user question;
                        # answer a deterministic Continue if the mounted preset
                        # asks one so the smoke remains non-interactive.
                        runtime.respond_interaction(
                            {
                                "rpcId": interaction_id,
                                "sessionId": session_id,
                                "answer": {"answers": [{"id": "continue", "selected": ["Continue"]}]},
                            }
                        )
                    else:
                        raise RuntimeError(f"unsupported DSH interaction: {kind}")
                    answered.add(interaction_id)
                snapshot = runtime.snapshot({"sessionId": session_id, "maxMessages": 16})
                messages = snapshot.get("messages") if isinstance(snapshot.get("messages"), list) else []
                done = any(MARKER in str(item.get("content") or "") for item in messages if isinstance(item, dict))
                if done and snapshot.get("state") in {"idle", "completed"}:
                    break
                time.sleep(0.2)
            else:
                raise RuntimeError("DSH browser smoke timed out")
            if approvals < 1:
                raise RuntimeError("BrowserSkill navigation smoke observed no DSH approval request")
            completed_calls = list(stub.completed_tool_calls)
            statuses = _tool_statuses(snapshot)
            expected = [str(item["name"]) for item in SCRIPT]
            if completed_calls != expected:
                raise RuntimeError(f"unexpected BrowserSkill tool sequence: {completed_calls}")
            browser_names = {item["name"] for item in statuses}
            required = {"browser_session_start", "browser_navigate", "browser_snapshot", "browser_session_stop"}
            if not required.issubset(browser_names):
                raise RuntimeError("browser tools were not present in the final DSH projection")
            if any(item["status"] != "completed" for item in statuses if item["name"] in required):
                raise RuntimeError("a BrowserSkill tool did not complete")
            print(
                json.dumps(
                    {
                        "ok": True,
                        "runtime_ready": True,
                        "browser_skill_loaded": "skill" in completed_calls,
                        "browser_tools_completed": len(required),
                        "navigation_approval_count": approvals,
                        "final_state": snapshot.get("state"),
                        "event_count": len(events),
                        "marker_received": True,
                    },
                    ensure_ascii=False,
                )
            )
    except Exception as error:
        print(json.dumps({"ok": False, "error": type(error).__name__, "detail": str(error)[:400]}, ensure_ascii=False))
        return 1
    finally:
        try:
            if route_id:
                _remove_route(runtime, route_id, previous)
        except Exception as error:
            cleanup_error = type(error).__name__
        runtime.close()
    if cleanup_error:
        print(json.dumps({"ok": False, "error": "cleanup_failed"}, ensure_ascii=False))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
