"""Run a bounded BrowserSkill write smoke against a local-only test page.

The page and model route are created in-process.  The smoke proves that the
official DSH BrowserSkill plugin, Sumika's policy companion, and a non-sensitive
DOM write can complete together without touching an external site or account.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
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


MARKER = "SUMIKA_DSH_BROWSER_WRITE_OK"
SCRIPT = (
    {"name": "skill", "arguments": {"name": "browser-skill"}},
    {"name": "browser_session_start", "arguments": {"noFocus": True}},
    {
        "name": "browser_navigate",
        "arguments": {"url": "__SUMIKA_LOCAL_PAGE_URL__", "waitUntil": "domcontentloaded"},
    },
    {"name": "browser_snapshot", "arguments": {"maxDepth": 8, "maxTokens": 1600}},
    {
        "name": "browser_fill",
        "arguments": {"target": "#display-name", "value": "sumika-test"},
    },
    {
        "name": "browser_press",
        "arguments": {"target": "#display-name", "key": "Enter"},
    },
    {"name": "browser_snapshot", "arguments": {"maxDepth": 8, "maxTokens": 1600}},
    {"name": "browser_session_stop", "arguments": {}},
)


class _LocalPage(BaseHTTPRequestHandler):
    submitted_values: list[str] = []

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler contract
        if self.path.rstrip("/") not in {"", "/", "/done"}:
            self.send_error(404)
            return
        done = self.path.rstrip("/") == "/done"
        body = (
            "<!doctype html><html><body>"
            "<h1>Sumika browser smoke</h1>"
            + ("<p id='result'>submitted</p>" if done else "")
            + "<form method='post' action='/done'>"
            "<label for='display-name'>Display name</label>"
            "<input id='display-name' name='display_name' autocomplete='off'>"
            "<button type='submit'>Submit</button></form>"
            "</body></html>"
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler contract
        if self.path.rstrip("/") != "/done":
            self.send_error(404)
            return
        try:
            length = max(0, min(int(self.headers.get("Content-Length", "0")), 4096))
            payload = self.rfile.read(length).decode("utf-8", errors="replace")
        except (TypeError, ValueError):
            payload = ""
        # Keep only the deterministic test field; never retain arbitrary page data.
        value = ""
        for part in payload.split("&"):
            if part.startswith("display_name="):
                value = part.split("=", 1)[1].replace("+", " ")
                break
        self.submitted_values.append(value)
        self.send_response(303)
        self.send_header("Location", "/done")
        self.send_header("Content-Length", "0")
        self.send_header("Connection", "close")
        self.end_headers()

    def log_message(self, format: str, *args: Any) -> None:
        del format, args


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", default=os.environ.get("SUMIKA_AGENT_ENDPOINT", "http://127.0.0.1:3080"))
    parser.add_argument("--profile-dir", default=os.environ.get("SUMIKA_AGENT_PROFILE_DIR", ""))
    parser.add_argument("--core-endpoint", default=os.environ.get("SUMIKA_CORE_ENDPOINT", "http://127.0.0.1:8771/rpc"))
    parser.add_argument("--timeout", type=float, default=90.0)
    return parser


def _profile_path(value: str) -> Path:
    raw = str(value or "").strip()
    if not raw:
        raise SystemExit("--profile-dir or SUMIKA_AGENT_PROFILE_DIR is required")
    profile = Path(os.path.expandvars(raw)).expanduser().resolve()
    user_home = Path.home().resolve()
    if profile == user_home or user_home in profile.parents:
        raise SystemExit("refusing to mutate a DSH profile under the user home")
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


def _script_for_page(page_url: str) -> list[dict[str, Any]]:
    """Return a fresh deterministic tool script bound to the ephemeral page."""

    script: list[dict[str, Any]] = []
    for item in SCRIPT:
        arguments = dict(item.get("arguments") or {})
        if arguments.get("url") == "__SUMIKA_LOCAL_PAGE_URL__":
            arguments["url"] = page_url
        script.append({"name": str(item["name"]), "arguments": arguments})
    return script


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
    page = ThreadingHTTPServer(("127.0.0.1", 0), _LocalPage)
    page.daemon_threads = True
    page_thread = threading.Thread(target=page.serve_forever, name="sumika-browser-write-page", daemon=True)
    page_thread.start()
    host, port = page.server_address[:2]
    page_url = f"http://{host}:{port}/"
    script = _script_for_page(page_url)
    profile_id = f"dsh-browser-write-{uuid4().hex[:12]}"
    route_id = _dsh_route_id(profile_id)
    runtime = DSHAgentRuntime(ROOT / ".sumika-smoke-unused", env=env)
    events: list[dict[str, Any]] = []
    runtime.set_event_sink(events.append)
    runtime.start_event_bridge()
    previous: dict[str, str | None] = {}
    session_id = ""
    cleanup_error: str | None = None
    snapshot: dict[str, Any] = {}
    approvals = 0
    try:
        health = runtime.health()
        if not health.get("ok"):
            raise RuntimeError("DSH health check failed")
        previous = _default_model(runtime)
        with OpenAICompatibleStub(
            model="sumika-dsh-browser-write",
            response_text=MARKER,
            scripted_tool_calls=script,
        ) as stub:
            runtime.sync_provider_profile(
                {
                    "id": profile_id,
                    "name": "Sumika local BrowserSkill write smoke",
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
            goal = f"Use the browser Skill on {page_url}, fill the display name with sumika-test, submit it, then stop the browser session."
            runtime.prompt({"sessionId": session_id, "text": goal, "mode": "execute"})
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
                snapshot = runtime.snapshot({"sessionId": session_id, "maxMessages": 24})
                messages = snapshot.get("messages") if isinstance(snapshot.get("messages"), list) else []
                marker_received = any(MARKER in str(item.get("content") or "") for item in messages if isinstance(item, dict))
                if marker_received and snapshot.get("state") in {"idle", "completed"}:
                    break
                time.sleep(0.2)
            else:
                raise RuntimeError("DSH browser write smoke timed out")
            if approvals < 1:
                raise RuntimeError("BrowserSkill write smoke observed no DSH approval request")
            expected = [str(item["name"]) for item in script]
            if stub.completed_tool_calls != expected:
                raise RuntimeError(f"unexpected BrowserSkill tool sequence: {stub.completed_tool_calls}")
            if _LocalPage.submitted_values != ["sumika-test"]:
                raise RuntimeError("local form was not submitted with the expected value")
            print(
                json.dumps(
                    {
                        "ok": True,
                        "runtime_ready": True,
                        "browser_tools_completed": len(expected) - 1,
                        "approval_count": approvals,
                        "local_write_confirmed": True,
                        "marker_received": True,
                        "final_state": snapshot.get("state"),
                    },
                    ensure_ascii=False,
                )
            )
    except Exception as error:
        print(json.dumps({"ok": False, "error": type(error).__name__}, ensure_ascii=False))
        return 1
    finally:
        try:
            _remove_route(runtime, route_id, previous)
        except Exception:
            cleanup_error = "route-cleanup"
        runtime.close()
        page.shutdown()
        page.server_close()
        page_thread.join(timeout=2.0)
    if cleanup_error:
        print(json.dumps({"ok": False, "error": cleanup_error}, ensure_ascii=False))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
