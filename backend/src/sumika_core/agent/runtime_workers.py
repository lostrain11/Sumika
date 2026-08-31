"""Concrete runtime-neutral workers used by :class:`DynamicRouteSupervisor`.

The supervisor owns admission, budgets and lifecycle.  Workers in this module
only translate a validated dispatch into one bounded operation on an existing
runtime.  They intentionally use duck-typed runtime boundaries so a future
Harness can replace DSH or ZCode without importing either adapter here.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any, Mapping

from ..protocol.models import ChatRequest, Message
from .supervisor import (
    DynamicSubtaskDispatch,
    ExternalHarnessWorker,
    NativeChildAgentWorker,
    ProviderWorker,
    RuntimeRouteDescriptor,
    WebWorker,
)


def _safe_workspace(dispatch: DynamicSubtaskDispatch, route: RuntimeRouteDescriptor, fallback: str | None = None) -> str:
    """Return an explicit workspace path without accepting arbitrary content."""

    candidates: list[Any] = []
    if isinstance(dispatch.metadata, Mapping):
        candidates.extend((dispatch.metadata.get("workspace_path"), dispatch.metadata.get("cwd")))
    if isinstance(route.metadata, Mapping):
        candidates.extend((route.metadata.get("workspace_path"), route.metadata.get("cwd")))
    candidates.append(fallback)
    for value in candidates:
        if not isinstance(value, str) or not value.strip():
            continue
        try:
            path = Path(value).expanduser().resolve()
        except (OSError, RuntimeError, ValueError):
            continue
        if path.exists() and path.is_dir():
            return str(path)
    return str(Path.cwd())


def _context_text(context: Any, limit: int = 8_000) -> str:
    if context in (None, "", {}, [], ()):
        return ""
    try:
        value = json.dumps(context, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    except (TypeError, ValueError):
        value = str(context)
    return value[:limit]


class ProviderProfileWorker(ProviderWorker):
    """Execute a short text request through a saved Provider profile."""

    def __init__(self, provider_profiles: Any, profile_id: str, *, worker_id: str | None = None, timeout_ms: int = 120_000) -> None:
        super().__init__(worker_id=worker_id or f"provider-profile-{profile_id}", timeout_ms=timeout_ms, runtime_id="provider")
        self.provider_profiles = provider_profiles
        self.profile_id = str(profile_id)

    def descriptor(self) -> dict[str, Any]:
        value = super().descriptor()
        value.update({"profile_id": self.profile_id, "executor": "provider-profile"})
        return value

    def execute(self, dispatch: DynamicSubtaskDispatch, route: RuntimeRouteDescriptor, cancel_event: threading.Event) -> Any:
        if cancel_event.is_set():
            return {"status": "cancelled", "error_code": "cancelled", "runtime_id": "provider"}
        profile_id = route.provider_profile_id or self.profile_id
        if not profile_id:
            return {"status": "failed", "error_code": "profile-not-configured", "runtime_id": "provider"}
        try:
            profile = self.provider_profiles.get(profile_id)
            if not isinstance(profile, dict) or profile.get("archived_at"):
                return {"status": "failed", "error_code": "profile-not-found", "runtime_id": "provider"}
            if str(profile.get("status") or "").lower() != "available":
                return {"status": "failed", "error_code": "profile-not-ready", "runtime_id": "provider"}
            provider = self.provider_profiles.runtime(profile_id)
            content = dispatch.question
            context = _context_text(dispatch.context_refs)
            if context:
                content = f"{content}\n\nContext (sanitized):\n{context}"
            request = ChatRequest(
                session_id=dispatch.parent_session_id,
                messages=[Message(role="user", content=content)],
                provider_id=str(profile.get("adapter_id") or "openai-compatible"),
                max_tokens=1024,
            )
            chunks: list[str] = []
            for chunk in provider.stream(request):
                if cancel_event.is_set():
                    # The request has already crossed the provider boundary;
                    # do not advertise it as retryable.
                    return {"status": "cancelled", "error_code": "cancelled", "possibly_sent": True, "runtime_id": "provider"}
                if isinstance(chunk, str):
                    chunks.append(chunk)
            answer = "".join(chunks).strip()
            if not answer:
                return {"status": "failed", "error_code": "empty-result", "possibly_sent": True, "runtime_id": "provider"}
            try:
                self.provider_profiles.mark_used(profile_id)
            except Exception:
                # Usage metadata must not turn a successful provider answer
                # into a false failure.
                pass
            return {"status": "completed", "answer": answer, "runtime_id": "provider", "untrusted_external": False}
        except Exception as error:
            return {
                "status": "failed",
                "error_code": type(error).__name__.lower().replace("_", "-")[:120] or "provider-error",
                "possibly_sent": True,
                "runtime_id": "provider",
            }


class LegacyWebWorker(WebWorker):
    """Bridge one dispatch to the existing, policy-checked web coordinator."""

    def __init__(self, coordinator: Any, *, worker_id: str = "web-coordinator", timeout_ms: int = 300_000) -> None:
        super().__init__(worker_id=worker_id, timeout_ms=timeout_ms, runtime_id="browserskill")
        self.coordinator = coordinator

    def execute(self, dispatch: DynamicSubtaskDispatch, route: RuntimeRouteDescriptor, cancel_event: threading.Event) -> Any:
        if cancel_event.is_set():
            return {"status": "cancelled", "error_code": "cancelled", "runtime_id": "browserskill"}
        method = getattr(self.coordinator, "execute_runtime_dispatch", None)
        if callable(method):
            return method(dispatch, route, cancel_event)
        # Older coordinators can still be used through their public dispatch
        # method.  The nested result is compacted by DynamicSubtaskResult.
        # The runtime-neutral catalog uses ``web:<profile>`` identifiers,
        # while the legacy coordinator keeps its original
        # ``web-chat:<profile>`` spelling.  Translate only at this adapter
        # boundary so callers and future workers remain harness-neutral.
        coordinator_route_id = dispatch.route_id
        if coordinator_route_id.startswith("web:"):
            profile_id = route.provider_profile_id or coordinator_route_id.removeprefix("web:")
            coordinator_route_id = f"web-chat:{profile_id}"
        result = self.coordinator.dispatch(
            {
                "dispatch_id": dispatch.dispatch_id,
                "parent_session_id": dispatch.parent_session_id,
                "parent_turn_id": dispatch.parent_turn_id,
                "route_id": coordinator_route_id,
                "question": dispatch.question,
                "context_refs": dispatch.context_refs,
                "consultation_id": dispatch.consultation_id,
                "role": dispatch.role,
            },
            route_id=coordinator_route_id,
            wait=True,
        )
        if cancel_event.is_set():
            return {"status": "cancelled", "error_code": "cancelled", "runtime_id": "browserskill"}
        nested = result.get("result") if isinstance(result, dict) else None
        if isinstance(nested, Mapping):
            return {**dict(nested), "runtime_id": "browserskill"}
        return {"status": "failed", "error_code": "web-worker-invalid-result", "runtime_id": "browserskill"}


class NativeRuntimeWorker(NativeChildAgentWorker):
    """Run a bounded child request through a Harness's public session API."""

    def __init__(self, runtime: Any, *, worker_id: str = "native-child-agent", timeout_ms: int = 120_000) -> None:
        super().__init__(executor=None, worker_id=worker_id, timeout_ms=timeout_ms, runtime_id=str(getattr(runtime, "runtime_id", "unknown")))
        self.runtime = runtime

    def execute(self, dispatch: DynamicSubtaskDispatch, route: RuntimeRouteDescriptor, cancel_event: threading.Event) -> Any:
        if cancel_event.is_set():
            return {"status": "cancelled", "error_code": "cancelled", "runtime_id": self.runtime_id}
        started = time.monotonic()
        child_id: str | None = None
        try:
            metadata = dispatch.metadata if isinstance(dispatch.metadata, Mapping) else {}
            child_id = str(metadata.get("child_session_id") or metadata.get("childSessionId") or "").strip() or None
            if child_id and callable(getattr(self.runtime, "prompt_subagent", None)):
                receipt = self.runtime.prompt_subagent({
                    "parent_session_id": dispatch.parent_session_id,
                    "child_session_id": child_id,
                    "text": dispatch.question,
                })
            else:
                create = getattr(self.runtime, "create_session", None)
                prompt = getattr(self.runtime, "prompt", None)
                if not callable(create) or not callable(prompt):
                    return {"status": "failed", "error_code": "subagent-not-supported", "runtime_id": self.runtime_id}
                workspace = _safe_workspace(dispatch, route)
                created = create({"cwd": workspace, "workspace": {"type": "local", "cwd": workspace}, "mode": "execute", "title": "Sumika child task"})
                child_id = str((created or {}).get("sessionId") or (created or {}).get("session_id") or "").strip() or None
                if not child_id:
                    return {"status": "failed", "error_code": "child-session-not-created", "runtime_id": self.runtime_id}
                model_ref = _model_ref(route)
                selector = getattr(self.runtime, "select_model", None)
                if model_ref and callable(selector):
                    selector({"sessionId": child_id, "model": model_ref})
                receipt = prompt({"sessionId": child_id, "session_id": child_id, "text": dispatch.question, "mode": "execute"})
            if cancel_event.is_set():
                cancel = getattr(self.runtime, "cancel", None)
                if callable(cancel) and child_id:
                    try:
                        cancel({"sessionId": child_id, "session_id": child_id})
                    except Exception:
                        pass
                return {"status": "cancelled", "error_code": "cancelled", "possibly_sent": True, "runtime_id": self.runtime_id}
            answer = _extract_runtime_answer(self.runtime, child_id, receipt)
            if answer:
                return {"status": "completed", "answer": answer, "runtime_id": self.runtime_id, "structured_result": {"child_session_id": child_id}}
            # A child may complete asynchronously.  Keep the receipt visible
            # as structured metadata rather than inventing a textual answer.
            return {"status": "unknown", "error_code": "child-result-pending", "possibly_sent": True, "runtime_id": self.runtime_id, "structured_result": {"child_session_id": child_id}}
        except Exception as error:
            return {"status": "failed", "error_code": type(error).__name__.lower().replace("_", "-")[:120], "possibly_sent": bool(child_id), "runtime_id": self.runtime_id}
        finally:
            del started


class ZCodeExternalHarnessWorker(ExternalHarnessWorker):
    """Use a ZCode ``AgentRuntime`` as an isolated child Harness.

    The worker talks only to the adapter's public methods.  Authentication and
    subscription accounting remain inside the ZCode client process; this
    class never opens a credentials file or forwards a token.
    """

    def __init__(self, runtime: Any, *, worker_id: str = "zcode-external-harness", timeout_ms: int = 300_000, workspace: str | None = None) -> None:
        super().__init__(executor=None, worker_id=worker_id, timeout_ms=timeout_ms, runtime_id="zcode")
        self.runtime = runtime
        self.workspace = workspace

    def execute(self, dispatch: DynamicSubtaskDispatch, route: RuntimeRouteDescriptor, cancel_event: threading.Event) -> Any:
        if cancel_event.is_set():
            return {"status": "cancelled", "error_code": "cancelled", "runtime_id": "zcode"}
        workspace = _safe_workspace(dispatch, route, self.workspace)
        create = getattr(self.runtime, "create_session", None)
        prompt = getattr(self.runtime, "prompt", None)
        if not callable(create) or not callable(prompt):
            return {"status": "failed", "error_code": "zcode-runtime-not-supported", "runtime_id": "zcode"}
        session_id: str | None = None
        sent = False
        listener_remove = None
        events: list[Any] = []
        try:
            session_params: dict[str, Any] = {
                "cwd": workspace,
                "workspace": {"type": "local", "cwd": workspace},
                "mode": "execute",
                "title": "Sumika external worker",
            }
            created = create(session_params)
            if isinstance(created, Mapping):
                session_id = str(created.get("sessionId") or created.get("session_id") or created.get("id") or "").strip() or None
            if not session_id:
                return {"status": "failed", "error_code": "zcode-session-not-created", "runtime_id": "zcode"}
            # ZCodeAgentRuntime exposes an optional listener hook.  Generic
            # runtimes may omit it; snapshot/history polling below remains the
            # portable fallback.
            add_listener = getattr(self.runtime, "add_event_listener", None)
            if callable(add_listener):
                listener_remove = add_listener(lambda event: events.append(event) if len(events) < 128 else None)
            model_ref = _model_ref(route)
            if model_ref:
                selector = getattr(self.runtime, "select_model", None)
                if callable(selector):
                    selector({"sessionId": session_id, "model": model_ref})
            if cancel_event.is_set():
                return {"status": "cancelled", "error_code": "cancelled", "runtime_id": "zcode"}
            send_result = prompt({"sessionId": session_id, "text": dispatch.question, "mode": "execute"})
            sent = True
            if cancel_event.is_set():
                _cancel_runtime(self.runtime, session_id)
                return {"status": "cancelled", "error_code": "cancelled", "possibly_sent": True, "runtime_id": "zcode"}
            answer = _extract_runtime_answer(self.runtime, session_id, send_result)
            # A synchronous app-server may emit the answer only in a listener;
            # include it in the same extraction path without exposing raw
            # protocol frames.
            if not answer:
                answer = _extract_runtime_answer(self.runtime, session_id, events)
            if not answer:
                # app-server responses may acknowledge the send before the
                # final event reaches the listener.  Give the owned process a
                # short bounded drain window; never retry or resend content.
                deadline = time.monotonic() + 0.35
                while time.monotonic() < deadline and not cancel_event.is_set():
                    time.sleep(0.02)
                    answer = _extract_runtime_answer(self.runtime, session_id, events)
                    if answer:
                        break
            if answer:
                return {
                    "status": "completed",
                    "answer": answer,
                    "runtime_id": "zcode",
                    "structured_result": {"session_id": session_id, "transport": "app-server"},
                }
            # A completed turn with no assistant body is still a real outcome,
            # but must not be replaced by fake text.
            completed = _has_completed_event(events)
            if completed:
                return {
                    "status": "completed",
                    "answer": None,
                    "runtime_id": "zcode",
                    "structured_result": {"session_id": session_id, "transport": "app-server", "answer_available": False},
                }
            return {
                "status": "unknown",
                "error_code": "zcode-result-pending",
                "possibly_sent": True,
                "runtime_id": "zcode",
                "structured_result": {"session_id": session_id, "transport": "app-server"},
            }
        except Exception as error:
            return {
                "status": "failed",
                "error_code": type(error).__name__.lower().replace("_", "-")[:120] or "zcode-worker-error",
                "possibly_sent": sent,
                "runtime_id": "zcode",
            }
        finally:
            if callable(listener_remove):
                try:
                    listener_remove()
                except Exception:
                    pass
            # Closing is best-effort: pinned and third-party ZCode builds may
            # not expose session/close, while the adapter still owns process
            # lifecycle at Core shutdown.
            if session_id and not cancel_event.is_set():
                closer = getattr(self.runtime, "close_session", None)
                if callable(closer):
                    try:
                        closer({"sessionId": session_id})
                    except Exception:
                        pass


def _model_ref(route: RuntimeRouteDescriptor) -> dict[str, str] | None:
    metadata = route.metadata if isinstance(route.metadata, Mapping) else {}
    raw = metadata.get("model_entry")
    if isinstance(raw, Mapping):
        provider = str(raw.get("provider_id") or raw.get("providerId") or "").strip()
        model = str(raw.get("model_id") or raw.get("modelId") or "").strip()
        if provider and model:
            return {"providerId": provider, "modelId": model}
    raw = metadata.get("model_ref")
    if isinstance(raw, Mapping):
        provider = str(raw.get("providerId") or raw.get("provider_id") or "").strip()
        model = str(raw.get("modelId") or raw.get("model_id") or "").strip()
        if provider and model:
            return {"providerId": provider, "modelId": model}
    return None


def _cancel_runtime(runtime: Any, session_id: str) -> None:
    cancel = getattr(runtime, "cancel", None)
    if callable(cancel):
        try:
            cancel({"sessionId": session_id})
        except Exception:
            pass


def _has_completed_event(value: Any) -> bool:
    if isinstance(value, Mapping):
        marker = str(value.get("type") or value.get("event_type") or value.get("status") or "").lower()
        if marker in {"turn.completed", "turn/end", "completed", "done", "success"}:
            return True
        return any(_has_completed_event(item) for item in value.values())
    if isinstance(value, list):
        return any(_has_completed_event(item) for item in value)
    return False


def _extract_runtime_answer(runtime: Any, session_id: str | None, receipt: Any) -> str | None:
    """Read only assistant text from a compact snapshot/history projection."""

    def walk(value: Any) -> list[str]:
        found: list[str] = []
        if isinstance(value, Mapping):
            role = str(value.get("role") or value.get("author") or "").lower()
            text = value.get("content") if isinstance(value.get("content"), str) else value.get("text")
            if role in {"assistant", "agent", "model"} and isinstance(text, str) and text.strip():
                found.append(text.strip())
            # ZCode's modern stream labels assistant deltas by event type
            # rather than embedding a role.  Only accept explicit output
            # event names, never arbitrary tool/result fields.
            marker = str(value.get("type") or value.get("event_type") or value.get("method") or "").lower()
            delta = value.get("delta")
            if marker in {"part.delta", "output.text", "message.delta", "assistant.delta"} and isinstance(delta, str) and delta.strip():
                found.append(delta.strip())
            for key in ("messages", "items", "events", "timeline", "parts", "result"):
                if key in value:
                    found.extend(walk(value[key]))
        elif isinstance(value, list):
            for item in value:
                found.extend(walk(item))
        return found

    values: list[str] = []
    values.extend(walk(receipt))
    if session_id:
        for method_name, params in (("snapshot", {"sessionId": session_id, "include_history": True, "maxMessages": 8}), ("history", {"sessionId": session_id, "maxMessages": 8})):
            method = getattr(runtime, method_name, None)
            if callable(method):
                try:
                    values.extend(walk(method(params)))
                except Exception:
                    continue
    return values[-1] if values else None


__all__ = [
    "ProviderProfileWorker",
    "LegacyWebWorker",
    "NativeRuntimeWorker",
    "ZCodeExternalHarnessWorker",
]
