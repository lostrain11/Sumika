"""Concrete runtime-neutral workers used by :class:`DynamicRouteSupervisor`.

The supervisor owns admission, budgets and lifecycle.  Workers in this module
only translate a validated dispatch into one bounded operation on an existing
runtime.  They intentionally use duck-typed runtime boundaries so a future
Harness can replace DSH or ZCode without importing either adapter here.
"""

from __future__ import annotations

import json
import inspect
import threading
import time
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable, Mapping

from ..model_policy import ModelCatalogEntry
from ..protocol.models import ChatRequest, Message
from .supervisor import (
    DesktopAppWorker,
    DynamicSubtaskDispatch,
    ExternalHarnessWorker,
    NativeChildAgentWorker,
    ProviderWorker,
    RuntimeRouteDescriptor,
    WebWorker,
    _call_with_supported_signature,
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


def _safe_route_fragment(value: Any, fallback: str = "model") -> str:
    text = str(value or "").strip().lower()
    if not text:
        return fallback
    result = "".join(char if char.isalnum() or char in "._:-" else "-" for char in text)
    return result[:120] or fallback


def _result_status(value: Any) -> str:
    if not isinstance(value, Mapping):
        return "completed" if isinstance(value, str) and value.strip() else "unknown"
    raw = value.get("status") or value.get("state") or value.get("phase")
    return str(raw or "").strip().lower().replace("_", "-")


def _result_answer(value: Any) -> str | None:
    if isinstance(value, str):
        return value.strip() or None
    if not isinstance(value, Mapping):
        return None
    for key in ("answer", "text", "content", "output", "message"):
        item = value.get(key)
        if isinstance(item, str) and item.strip():
            return item.strip()
    for key in ("result", "response", "data"):
        nested = value.get(key)
        answer = _result_answer(nested)
        if answer:
            return answer
    return None


def _normalize_external_result(value: Any, *, runtime_id: str, session_id: str | None = None) -> dict[str, Any]:
    """Keep a generic Harness result small and free of protocol internals."""

    status = _result_status(value)
    answer = _result_answer(value)
    if status in {"ok", "success", "done", "complete", "completed"} or answer:
        status = "completed"
    elif status in {"cancel", "cancelled", "canceled", "stopped", "interrupted"}:
        status = "cancelled"
    elif status in {"failed", "failure", "error", "denied"}:
        status = "failed"
    else:
        status = "unknown"
    result: dict[str, Any] = {
        "status": status,
        "runtime_id": runtime_id,
    }
    if answer:
        result["answer"] = answer
    if isinstance(value, Mapping):
        error_code = value.get("error_code") or value.get("errorCode") or value.get("code")
        if error_code not in (None, ""):
            result["error_code"] = str(error_code).strip()[:120]
        turn_id = value.get("turn_id") or value.get("turnId")
        if turn_id not in (None, ""):
            result["turn_id"] = str(turn_id).strip()[:240]
        structured = value.get("structured_result") or value.get("structuredResult")
        if isinstance(structured, Mapping):
            result["structured_result"] = dict(list(structured.items())[:32])
        if value.get("possibly_sent") is True:
            result["possibly_sent"] = True
    if session_id:
        result.setdefault("structured_result", {})
        if isinstance(result["structured_result"], Mapping):
            result["structured_result"] = {**dict(result["structured_result"]), "session_id": session_id}
    return result


def _call_harness_method(method: Callable[..., Any], params: Mapping[str, Any], *, timeout: float | None = None) -> Any:
    """Call one supported adapter signature exactly once.

    A retry-on-``TypeError`` strategy is unsafe here: a client can raise a
    ``TypeError`` *after* accepting a prompt, and trying the next signature
    would send the same request twice.  Bind candidate signatures before
    invoking the method so an exception from the method itself crosses the
    boundary unchanged and is handled as a single transport attempt.
    """

    payload = dict(params)
    if timeout is not None:
        payload.setdefault("timeout", timeout)
    try:
        signature = inspect.signature(method)
    except (TypeError, ValueError):
        # Opaque callables are uncommon, but a single mapping call preserves
        # the historical adapter contract without speculative retries.
        return method(payload)

    parameters = tuple(signature.parameters.values())
    positional = tuple(
        item
        for item in parameters
        if item.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
    )
    keyword_only = tuple(item for item in parameters if item.kind == inspect.Parameter.KEYWORD_ONLY)
    accepts_kwargs = any(item.kind == inspect.Parameter.VAR_KEYWORD for item in parameters)
    mapping_names = {"params", "param", "request", "payload", "options", "value", "data", "message"}

    candidates: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
    if len(positional) == 1 and positional[0].name in mapping_names:
        candidates.append(((payload,), {}))

    if accepts_kwargs:
        candidates.append(((), payload))
    else:
        accepted_names = {
            item.name
            for item in parameters
            if item.kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
        }
        filtered = {key: value for key, value in payload.items() if key in accepted_names}
        candidates.append(((), filtered))

    candidates.append(((payload,), {}))
    candidates.append(((), {}))
    for args, kwargs in candidates:
        try:
            signature.bind(*args, **kwargs)
        except TypeError:
            continue
        return method(*args, **kwargs)
    raise TypeError("unsupported external Harness method signature")


class ExternalHarnessClientWorker(ExternalHarnessWorker):
    """Generic Worker for a public, user-supplied Harness client.

    The client is intentionally opaque.  A provider-specific adapter can
    implement ``execute_dispatch`` for full control, or expose the common
    session methods below.  This class is the reusable integration point for
    future Harnesses; it does not know ZCode, DSH, Electron, or credentials.
    """

    def __init__(
        self,
        client: Any,
        *,
        source_id: str | None = None,
        worker_id: str | None = None,
        timeout_ms: int = 300_000,
        close_sessions: bool = True,
    ) -> None:
        runtime_id = str(source_id or getattr(client, "runtime_id", "external") or "external").strip().lower()
        super().__init__(executor=None, worker_id=worker_id or f"external-{_safe_route_fragment(runtime_id)}", timeout_ms=timeout_ms, runtime_id=runtime_id)
        self.client = client
        self.close_sessions = bool(close_sessions)

    def descriptor(self) -> dict[str, Any]:
        value = super().descriptor()
        value.update({"executor": "external-harness-client", "source_id": self.runtime_id})
        return value

    @staticmethod
    def _session_id(value: Any) -> str | None:
        if not isinstance(value, Mapping):
            return None
        for key in ("session_id", "sessionId", "id"):
            item = value.get(key)
            if item not in (None, ""):
                return str(item).strip()[:240] or None
        nested = value.get("session")
        return ExternalHarnessClientWorker._session_id(nested)

    def execute(self, dispatch: DynamicSubtaskDispatch, route: RuntimeRouteDescriptor, cancel_event: threading.Event) -> Any:
        if cancel_event.is_set():
            return {"status": "cancelled", "error_code": "cancelled", "runtime_id": self.runtime_id}

        direct = getattr(self.client, "execute_dispatch", None) or getattr(self.client, "dispatch_subtask", None)
        if callable(direct):
            try:
                # Resolve the adapter signature before invoking it.  Retrying
                # a TypeError here could duplicate an already accepted
                # external request.
                value = _call_with_supported_signature(direct, dispatch, route, cancel_event)
                return _normalize_external_result(value, runtime_id=self.runtime_id)
            except Exception as error:
                return {
                    "status": "failed",
                    "error_code": type(error).__name__.lower().replace("_", "-")[:120] or "external-harness-error",
                    "possibly_sent": True,
                    "runtime_id": self.runtime_id,
                }

        create = getattr(self.client, "create_session", None)
        send = getattr(self.client, "prompt", None) or getattr(self.client, "send", None)
        if not callable(create) or not callable(send):
            return {"status": "failed", "error_code": "external-harness-not-supported", "runtime_id": self.runtime_id}

        session_id: str | None = None
        sent = False
        send_started = False
        try:
            workspace = _safe_workspace(dispatch, route)
            created = _call_harness_method(
                create,
                {
                    "cwd": workspace,
                    "workspace": {"type": "local", "cwd": workspace},
                    "mode": "execute",
                    "title": "Sumika external worker",
                },
            )
            session_id = self._session_id(created)
            if not session_id:
                return {"status": "failed", "error_code": "external-session-not-created", "runtime_id": self.runtime_id}
            if cancel_event.is_set():
                return {"status": "cancelled", "error_code": "cancelled", "runtime_id": self.runtime_id}

            model_ref = _model_ref(route)
            selector = getattr(self.client, "select_model", None)
            if model_ref and callable(selector):
                _call_harness_method(selector, {"sessionId": session_id, "session_id": session_id, "model": model_ref})
            request: dict[str, Any] = {
                "sessionId": session_id,
                "session_id": session_id,
                "text": dispatch.question,
                "content": dispatch.question,
                "mode": "execute",
            }
            if model_ref:
                request["model"] = model_ref
            # Mark the transport boundary before invocation.  If the client
            # raises while processing the call, the request may already have
            # reached the remote Harness and must not be retried blindly.
            send_started = True
            receipt = _call_harness_method(send, request)
            sent = True
            if cancel_event.is_set():
                cancel = getattr(self.client, "cancel", None)
                if callable(cancel):
                    try:
                        _call_harness_method(cancel, {"sessionId": session_id, "session_id": session_id})
                    except Exception:
                        pass
                return {"status": "cancelled", "error_code": "cancelled", "possibly_sent": True, "runtime_id": self.runtime_id}

            immediate = _normalize_external_result(receipt, runtime_id=self.runtime_id, session_id=session_id)
            if immediate["status"] in {"completed", "failed", "cancelled"}:
                return immediate

            waiter = (
                getattr(self.client, "wait_for_turn", None)
                or getattr(self.client, "wait", None)
                or getattr(self.client, "snapshot", None)
                or getattr(self.client, "history", None)
            )
            if callable(waiter):
                waited = _call_harness_method(
                    waiter,
                    {"sessionId": session_id, "session_id": session_id, "turnId": immediate.get("turn_id")},
                    timeout=max(0.001, self.timeout_ms / 1000.0),
                )
                return _normalize_external_result(waited, runtime_id=self.runtime_id, session_id=session_id)
            return {"status": "unknown", "error_code": "external-result-pending", "possibly_sent": sent, "runtime_id": self.runtime_id, "structured_result": {"session_id": session_id}}
        except Exception as error:
            return {
                "status": "failed",
                "error_code": type(error).__name__.lower().replace("_", "-")[:120] or "external-harness-error",
                "possibly_sent": bool(sent or send_started),
                "runtime_id": self.runtime_id,
                "structured_result": {"session_id": session_id} if session_id else None,
            }
        finally:
            if session_id and self.close_sessions:
                closer = getattr(self.client, "close_session", None)
                if callable(closer):
                    try:
                        _call_harness_method(closer, {"sessionId": session_id, "session_id": session_id})
                    except Exception:
                        pass

    def close(self) -> None:
        closer = getattr(self.client, "close", None)
        if callable(closer):
            try:
                closer()
            except Exception:
                pass


def _call_with_client_signature(method: Callable[..., Any], dispatch: DynamicSubtaskDispatch, route: RuntimeRouteDescriptor, cancel_event: threading.Event) -> Any:
    """Backward-compatible alias with single-invocation signature binding."""

    return _call_with_supported_signature(method, dispatch, route, cancel_event)


class ExternalHarnessRouteSource:
    """Expose a generic Harness client to ModelPolicy and the Supervisor."""

    def __init__(
        self,
        client: Any,
        *,
        source_id: str | None = None,
        worker: Any = None,
        worker_factory: Callable[[Any], Any] | None = None,
        quota_consent: str | bool = "unknown",
        cost_class: str = "unknown",
        processing_location: str = "cloud",
    ) -> None:
        self.client = client
        self.source_id = _safe_route_fragment(source_id or getattr(client, "runtime_id", "external"), "external")
        self.worker_id = f"external-{self.source_id}"
        if isinstance(quota_consent, bool):
            self.quota_consent = "granted" if quota_consent else "unknown"
        else:
            normalized_consent = str(quota_consent or "unknown").strip().lower()
            self.quota_consent = normalized_consent if normalized_consent in {"unknown", "granted", "authorized", "approved"} else "unknown"
        normalized_cost = str(cost_class or "unknown").strip().lower()
        self.cost_class = normalized_cost if normalized_cost in {"free-limited", "local", "paid-low", "paid-high", "unknown"} else "unknown"
        normalized_location = str(processing_location or "cloud").strip().lower()
        self.processing_location = normalized_location[:40] or "cloud"
        self._worker = worker
        if self._worker is None and callable(worker_factory):
            self._worker = worker_factory(client)
        self._cache: list[ModelCatalogEntry] = []

    def worker(self) -> Any:
        if self._worker is None:
            self._worker = ExternalHarnessClientWorker(
                self.client,
                source_id=self.source_id,
                worker_id=self.worker_id,
            )
        return self._worker

    def model_entries(self, *, refresh: bool = False, session_id: str | None = None) -> list[ModelCatalogEntry]:
        if not refresh and self._cache:
            return list(self._cache)
        if not refresh:
            return []
        health_fn = getattr(self.client, "health", None) or getattr(self.client, "status", None)
        health: Mapping[str, Any] = {}
        if callable(health_fn):
            try:
                value = _call_harness_method(health_fn, {})
            except Exception:
                # Keep a bounded unavailable projection when health probing
                # fails; a later explicit refresh can recover it.  Do not
                # discard the model identity or claim it is routable.
                value = None
            if isinstance(value, Mapping):
                health = value
        health_ok = bool(health.get("ok") is True or health.get("ready") is True or str(health.get("state") or "").lower() in {"ready", "available", "healthy"})
        models_fn = getattr(self.client, "runtime_models", None) or getattr(self.client, "model_catalog", None) or getattr(self.client, "models", None)
        if not callable(models_fn):
            return self._cached_unavailable("model-catalog-unavailable")
        try:
            value = _call_harness_method(models_fn, {"session_id": session_id} if session_id else {})
        except Exception:
            return self._cached_unavailable("model-catalog-unavailable")
        rows = self._rows(value)
        quota = self._quota()
        quota_state = str(quota.get("state") or "unknown").lower()
        if quota_state not in {"available", "low", "exhausted", "expired", "needs-auth", "blocked", "unknown", "not-applicable"}:
            quota_state = "unknown"
        result: list[ModelCatalogEntry] = []
        for row in rows[:512]:
            provider = str(row.get("provider_id") or row.get("providerId") or row.get("provider") or self.source_id).strip()
            model_id = str(row.get("model_id") or row.get("modelId") or row.get("id") or "").strip()
            if not model_id:
                continue
            capabilities = row.get("capabilities")
            if isinstance(capabilities, str):
                capabilities = [capabilities]
            if not isinstance(capabilities, (list, tuple, set)):
                capabilities = ["chat", "code"]
            capabilities = [str(item).strip() for item in capabilities if str(item).strip()]
            for flag, capability in (("supportsTools", "tools"), ("supportsImages", "vision"), ("supportsStructuredOutput", "structured-output")):
                if row.get(flag) is True and capability not in capabilities:
                    capabilities.append(capability)
            route_id = str(row.get("route_id") or row.get("routeId") or f"harness:{self.source_id}:{_safe_route_fragment(provider)}:{_safe_route_fragment(model_id)}")
            routable = bool(health_ok and quota_state not in {"exhausted", "expired", "blocked", "needs-auth"})
            metadata = dict(row.get("metadata") or {}) if isinstance(row.get("metadata"), Mapping) else {}
            metadata.update({
                "external_source_id": self.source_id,
                "external_harness": True,
                "routable": routable,
                "quota_consent": self.quota_consent,
            })
            result.append(
                ModelCatalogEntry(
                    route_id=route_id,
                    provider_id=provider,
                    model_id=model_id,
                    display_name=str(row.get("display_name") or row.get("displayName") or row.get("label") or row.get("name") or model_id),
                    harness_id=self.source_id,
                    capabilities=tuple(capabilities),
                    quality_tier=str(row.get("quality_tier") or row.get("qualityTier") or "unknown"),
                    cost_class=str(row.get("cost_class") or row.get("costClass") or self.cost_class),
                    processing_location=str(row.get("processing_location") or row.get("processingLocation") or self.processing_location),
                    auth_state="authorized" if health_ok else "unknown",
                    quota_state=quota_state,
                    health_state="healthy" if health_ok else "unavailable",
                    source_kind="external-harness",
                    transport=str(row.get("transport") or "stdio"),
                    metadata=metadata,
                )
            )
        self._cache = result
        return list(result)

    def _cached_unavailable(self, reason: str) -> list[ModelCatalogEntry]:
        """Retain discovered identities while making a failed refresh fail closed."""

        if not self._cache:
            return []
        degraded: list[ModelCatalogEntry] = []
        for entry in self._cache:
            metadata = dict(entry.metadata)
            metadata.update(
                {
                    "routable": False,
                    "catalog_state": "unavailable",
                    "catalog_error": reason[:80],
                }
            )
            degraded.append(replace(entry, health_state="unavailable", metadata=metadata))
        self._cache = degraded
        return list(degraded)

    entries = model_entries

    @staticmethod
    def _rows(value: Any) -> list[dict[str, Any]]:
        if isinstance(value, Mapping):
            rows = value.get("entries") or value.get("models") or value.get("routes") or value.get("items")
            if isinstance(rows, list):
                return [dict(item) for item in rows if isinstance(item, Mapping)]
            groups = value.get("groups")
            flattened: list[dict[str, Any]] = []
            if isinstance(groups, list):
                for group in groups[:128]:
                    if not isinstance(group, Mapping) or not isinstance(group.get("models"), list):
                        continue
                    for model in group["models"][:128]:
                        if isinstance(model, Mapping):
                            flattened.append({"provider_id": group.get("id") or group.get("providerId"), "provider_name": group.get("name"), **dict(model)})
            return flattened
        if isinstance(value, (list, tuple)):
            return [dict(item) for item in value if isinstance(item, Mapping)]
        return []

    def _quota(self) -> Mapping[str, Any]:
        method = getattr(self.client, "quota_status", None)
        if not callable(method):
            return {"state": "unknown", "source": "not-exposed"}
        try:
            value = _call_harness_method(method, {})
        except Exception:
            return {"state": "unknown", "source": "error"}
        return value if isinstance(value, Mapping) else {"state": "unknown", "source": "invalid"}

    def quota_status(self, params: Any = None) -> dict[str, Any]:
        del params
        return dict(self._quota())


class ProviderProfileWorker(ProviderWorker):
    """Execute a short text request through a saved Provider profile."""

    def __init__(self, provider_profiles: Any, profile_id: str, *, pricing: Any = None, worker_id: str | None = None, timeout_ms: int = 120_000) -> None:
        super().__init__(worker_id=worker_id or f"provider-profile-{profile_id}", timeout_ms=timeout_ms, runtime_id="provider")
        self.provider_profiles = provider_profiles
        self.profile_id = str(profile_id)
        self.pricing = pricing

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
            model_id = None
            if isinstance(route.metadata, Mapping):
                model_config = route.metadata.get("model_config")
                model_entry = route.metadata.get("model_entry")
                if isinstance(model_config, Mapping):
                    model_id = str(model_config.get("id") or "").strip() or None
                if not model_id and isinstance(model_entry, Mapping):
                    model_id = str(model_entry.get("model_id") or model_entry.get("modelId") or "").strip() or None
            provider = self.provider_profiles.runtime(profile_id, model_id=model_id)
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
            usage = dict(getattr(provider, "last_usage", {}) or {})
            budget_impact: dict[str, Any] = {"usage": usage} if usage else {}
            if usage and self.pricing is not None and callable(getattr(self.pricing, "receipt", None)):
                try:
                    receipt = self.pricing.receipt(
                        {
                            "route_id": route.route_id,
                            "provider_profile_id": profile_id,
                            "model_id": model_id or str(profile.get("config", {}).get("model") or ""),
                            "metadata": dict(route.metadata or {}),
                        },
                        usage,
                    )
                    budget_impact["charge_receipt"] = receipt.to_dict() if hasattr(receipt, "to_dict") else receipt
                except Exception:
                    # A pricing adapter cannot invalidate a successful model
                    # response. The bounded usage receipt remains available.
                    pass
            return {
                "status": "completed",
                "answer": answer,
                "runtime_id": "provider",
                "untrusted_external": False,
                "budget_impact": budget_impact,
            }
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
        turn_id: str | None = None
        sent = False
        prompt_started = False
        listener_remove = None
        events: list[Any] = []
        event_signal = threading.Event()
        event_lock = threading.RLock()
        terminal: dict[str, Any] = {"kind": None, "marker": None, "error_code": None}
        answer_parts: list[str] = []

        def consume(value: Any) -> None:
            """Consume only events belonging to this session/turn."""

            nonlocal turn_id
            for item in _iter_event_objects(value):
                if not isinstance(item, Mapping):
                    continue
                item_session = _event_session_id(item)
                if session_id and item_session and item_session != session_id:
                    continue
                marker = _event_marker(item)
                item_turn = _event_turn_id(item)
                with event_lock:
                    if marker in {"turn.started", "turn.start", "turn.started.event"} and item_turn:
                        if turn_id is None:
                            turn_id = item_turn
                    if turn_id and item_turn and item_turn != turn_id:
                        continue
                    events.append(dict(item))
                    text = _event_output_text(item, marker)
                    if text:
                        _append_stream_text(answer_parts, text)
                    kind = _terminal_kind(marker, item)
                    if kind:
                        terminal["kind"] = kind
                        terminal["marker"] = marker
                        code = item.get("error_code") or item.get("errorCode")
                        terminal["error_code"] = str(code).strip()[:120] if code else None
                        event_signal.set()

        def listener(event: Any) -> None:
            consume(event)

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
            add_listener = getattr(self.runtime, "add_event_listener", None)
            if callable(add_listener):
                listener_remove = add_listener(listener)
            model_ref = _model_ref(route)
            if model_ref:
                selector = getattr(self.runtime, "select_model", None)
                if callable(selector):
                    selector({"sessionId": session_id, "model": model_ref})
            if cancel_event.is_set():
                return {"status": "cancelled", "error_code": "cancelled", "runtime_id": "zcode"}
            prompt_started = True
            try:
                send_result = prompt({"sessionId": session_id, "text": dispatch.question, "mode": "execute"})
                sent = bool(not isinstance(send_result, Mapping) or send_result.get("accepted", True))
                if isinstance(send_result, Mapping):
                    turn_id = str(send_result.get("turnId") or send_result.get("turn_id") or "").strip() or turn_id
                consume(send_result)
            except Exception:
                # The prompt may have crossed the process boundary before the
                # transport reported an error; treat it as non-replayable.
                sent = True
                raise
            if not sent:
                return {"status": "failed", "error_code": "zcode-send-rejected", "runtime_id": "zcode"}
            if cancel_event.is_set():
                _cancel_runtime(self.runtime, session_id)
                return {"status": "cancelled", "error_code": "cancelled", "possibly_sent": True, "runtime_id": "zcode"}

            # Wait for a correlated terminal event.  The app-server receipt is
            # only an acceptance acknowledgement and can never complete this
            # worker by itself.
            deadline = time.monotonic() + max(0.5, min(self.timeout_ms / 1000.0, 300.0))
            while time.monotonic() < deadline:
                if cancel_event.is_set():
                    _cancel_runtime(self.runtime, session_id)
                    return {"status": "cancelled", "error_code": "cancelled", "possibly_sent": True, "runtime_id": "zcode"}
                with event_lock:
                    kind = terminal.get("kind")
                if kind:
                    break
                # Runtimes without an event-listener hook can still expose a
                # bounded snapshot/history projection.  It is polled only for
                # this session and never causes a second send.
                if not callable(add_listener):
                    for method_name, params in (("snapshot", {"sessionId": session_id, "include_history": True}), ("history", {"sessionId": session_id})):
                        method = getattr(self.runtime, method_name, None)
                        if callable(method):
                            try:
                                consume(method(params))
                            except Exception:
                                pass
                            with event_lock:
                                if terminal.get("kind"):
                                    break
                event_signal.wait(timeout=0.05)
                event_signal.clear()
            with event_lock:
                kind = terminal.get("kind")
                marker = terminal.get("marker")
                error_code = terminal.get("error_code")
                answer = "".join(answer_parts).strip() or None
                captured_events = list(events)
            if kind == "failed":
                return {
                    "status": "failed",
                    "error_code": error_code or "zcode-turn-failed",
                    "possibly_sent": True,
                    "runtime_id": "zcode",
                    "structured_result": {"session_id": session_id, "turn_id": turn_id, "terminal_event": marker, "transport": "app-server"},
                }
            if kind == "cancelled":
                return {"status": "cancelled", "error_code": "cancelled", "possibly_sent": True, "runtime_id": "zcode", "structured_result": {"session_id": session_id, "turn_id": turn_id, "terminal_event": marker, "transport": "app-server"}}
            if kind == "completed":
                if not answer:
                    answer = _extract_runtime_answer(self.runtime, session_id, captured_events)
                return {
                    "status": "completed",
                    "answer": answer,
                    "runtime_id": "zcode",
                    "structured_result": {"session_id": session_id, "turn_id": turn_id, "terminal_event": marker, "transport": "app-server", "answer_available": bool(answer)},
                }
            return {
                "status": "unknown",
                "error_code": "zcode-result-pending",
                "possibly_sent": True,
                "runtime_id": "zcode",
                "structured_result": {"session_id": session_id, "turn_id": turn_id, "transport": "app-server"},
            }
        except Exception as error:
            return {
                "status": "failed",
                "error_code": type(error).__name__.lower().replace("_", "-")[:120] or "zcode-worker-error",
                "possibly_sent": bool(sent or prompt_started),
                "runtime_id": "zcode",
            }
        finally:
            if callable(listener_remove):
                try:
                    listener_remove()
                except Exception:
                    pass
            if session_id:
                closer = getattr(self.runtime, "close_session", None)
                if callable(closer):
                    try:
                        closer({"sessionId": session_id})
                    except Exception:
                        pass


class DesktopAutomationWorker(DesktopAppWorker):
    """Run one bounded action through the Core desktop automation contract.

    The worker deliberately does not know about Electron, UIA, or a specific
    application.  A route descriptor selects the approved application and its
    transport; ``DesktopAutomationRuntime`` remains the sole owner of leases,
    approvals, redaction, and the adapter lifecycle.
    """

    def __init__(
        self,
        runtime: Any,
        *,
        worker_id: str = "desktop-automation",
        timeout_ms: int = 120_000,
    ) -> None:
        super().__init__(executor=None, worker_id=worker_id, timeout_ms=timeout_ms, runtime_id="desktop")
        self.runtime = runtime
        self._lock = threading.RLock()
        self._sessions: dict[tuple[str, str], str] = {}
        self._owned_sessions: set[str] = set()

    def descriptor(self) -> dict[str, Any]:
        value = super().descriptor()
        value.update({"executor": "desktop-automation", "runtime": "desktop"})
        return value

    @staticmethod
    def _metadata(value: Any) -> dict[str, Any]:
        return dict(value) if isinstance(value, Mapping) else {}

    @staticmethod
    def _route_app_id(route: RuntimeRouteDescriptor) -> str:
        metadata = route.metadata if isinstance(route.metadata, Mapping) else {}
        return str(metadata.get("app_id") or metadata.get("appId") or "").strip()

    @staticmethod
    def _status(value: Any) -> str:
        if not isinstance(value, Mapping):
            return "unknown"
        return str(value.get("status") or value.get("state") or "").strip().lower()

    def _remember(self, key: tuple[str, str], session_id: str) -> None:
        with self._lock:
            self._sessions[key] = session_id
            self._owned_sessions.add(session_id)

    def _forget(self, key: tuple[str, str], session_id: str | None = None) -> None:
        with self._lock:
            current = self._sessions.get(key)
            if session_id is None or current == session_id:
                self._sessions.pop(key, None)
            if session_id:
                self._owned_sessions.discard(session_id)

    def _session_for(self, key: tuple[str, str]) -> str | None:
        with self._lock:
            return self._sessions.get(key)

    def _open(
        self,
        app_id: str,
        profile_id: str | None,
        options: Mapping[str, Any],
    ) -> tuple[str | None, bool, dict[str, Any] | None, str | None]:
        opener = getattr(self.runtime, "open_session", None)
        if not callable(opener):
            return None, False, None, "desktop-runtime-not-supported"
        try:
            value = opener(
                app_id,
                profile_id=profile_id,
                owner="agent",
                options=dict(options),
            )
        except Exception as error:
            return None, False, None, type(error).__name__.lower().replace("_", "-")[:120]
        session = value.get("session") if isinstance(value, Mapping) else None
        session_id = ""
        if isinstance(session, Mapping):
            session_id = str(session.get("session_id") or session.get("sessionId") or "").strip()
        if not session_id and isinstance(value, Mapping):
            session_id = str(value.get("session_id") or value.get("sessionId") or "").strip()
        if not session_id:
            return None, False, None, "desktop-session-not-created"
        return session_id, True, dict(value) if isinstance(value, Mapping) else {"session_id": session_id}, None

    def execute(
        self,
        dispatch: DynamicSubtaskDispatch,
        route: RuntimeRouteDescriptor,
        cancel_event: threading.Event,
    ) -> Any:
        if cancel_event.is_set():
            return {"status": "cancelled", "error_code": "cancelled", "runtime_id": "desktop"}
        app_id = self._route_app_id(route)
        if not app_id:
            return {"status": "failed", "error_code": "desktop-app-not-bound", "runtime_id": "desktop"}

        metadata = self._metadata(dispatch.metadata)
        key = (dispatch.parent_session_id, route.route_id)
        explicit_session = str(metadata.get("session_id") or metadata.get("sessionId") or "").strip() or None
        session_id = explicit_session or self._session_for(key)
        created_here = False
        action = str(metadata.get("action") or "send").strip().lower().replace("-", "_")
        # The route's declared transport is authoritative.  A dispatch may
        # pass other open options, but it cannot silently switch to a fallback
        # transport after admission.
        options = metadata.get("options") if isinstance(metadata.get("options"), Mapping) else {}
        open_options = dict(options)
        if route.transport not in {"unknown", ""}:
            open_options["transport"] = route.transport
        profile_id = str(metadata.get("profile_id") or metadata.get("profileId") or "").strip() or None

        try:
            if not session_id:
                session_id, created_here, opened, error_code = self._open(app_id, profile_id, open_options)
                if error_code:
                    return {"status": "failed", "error_code": error_code, "runtime_id": "desktop"}
                if not session_id:
                    return {"status": "failed", "error_code": "desktop-session-not-created", "runtime_id": "desktop"}
                self._remember(key, session_id)
            if cancel_event.is_set():
                return {"status": "cancelled", "error_code": "cancelled", "runtime_id": "desktop"}

            if action in {"observe", "read", "snapshot", "inspect", "health", "status"}:
                observer = getattr(self.runtime, "observe", None)
                if not callable(observer):
                    return {"status": "failed", "error_code": "desktop-observe-not-supported", "runtime_id": "desktop"}
                value = observer(session_id, metadata.get("args") if isinstance(metadata.get("args"), Mapping) else {})
            elif action in {"close", "close_session"}:
                closer = getattr(self.runtime, "close_session", None)
                if not callable(closer):
                    return {"status": "failed", "error_code": "desktop-close-not-supported", "runtime_id": "desktop"}
                value = closer(session_id)
                self._forget(key, session_id)
                created_here = False
            else:
                actor = getattr(self.runtime, "act", None)
                if not callable(actor):
                    return {"status": "failed", "error_code": "desktop-action-not-supported", "runtime_id": "desktop"}
                args = metadata.get("args") if isinstance(metadata.get("args"), Mapping) else {}
                request: dict[str, Any] = {
                    "session_id": session_id,
                    "action": action,
                    "target": metadata.get("target"),
                    "value": metadata.get("value"),
                    "args": dict(args),
                    "idempotency_key": metadata.get("idempotency_key") or metadata.get("idempotencyKey"),
                    # Route confirmation is the only approval bit trusted by
                    # this worker.  The runtime still performs its own exact
                    # action/argument approval matching.
                    "approved": bool(dispatch.confirmed),
                    "approval_id": metadata.get("approval_id") or metadata.get("approvalId"),
                }
                value = actor(request)

            if cancel_event.is_set():
                # Once an action crossed the adapter boundary, callers must
                # treat its outcome as uncertain and never replay it.
                return {
                    "status": "unknown" if action not in {"observe", "read", "snapshot", "inspect", "health", "status"} else "cancelled",
                    "error_code": "possibly-sent" if action not in {"observe", "read", "snapshot", "inspect", "health", "status"} else "cancelled",
                    "possibly_sent": action not in {"observe", "read", "snapshot", "inspect", "health", "status"},
                    "runtime_id": "desktop",
                    "structured_result": {"desktop_session_id": session_id, "action": action},
                }

            status = self._status(value)
            if status in {"waiting-approval", "waiting-human", "needs-confirmation"} or (isinstance(value, Mapping) and value.get("requires_human")):
                return {
                    "status": "waiting-human",
                    "error_code": str((value or {}).get("error_code") or "approval-required") if isinstance(value, Mapping) else "approval-required",
                    "runtime_id": "desktop",
                    "structured_result": {"desktop_session_id": session_id, "action": action, "result": value},
                }
            if status in {"unknown", "possibly-sent", "accepted", "running"} or (isinstance(value, Mapping) and value.get("possibly_sent") is True):
                return {
                    "status": "unknown",
                    "error_code": str((value or {}).get("error_code") or "possibly-sent") if isinstance(value, Mapping) else "possibly-sent",
                    "possibly_sent": action not in {"observe", "read", "snapshot", "inspect", "health", "status"},
                    "runtime_id": "desktop",
                    "structured_result": {"desktop_session_id": session_id, "action": action, "result": value},
                }
            if status in {"failed", "error", "denied"} or (isinstance(value, Mapping) and value.get("ok") is False):
                return {
                    "status": "failed" if status != "denied" else "waiting-human",
                    "error_code": str((value or {}).get("error_code") or ("action-denied" if status == "denied" else "desktop-action-failed")) if isinstance(value, Mapping) else "desktop-action-failed",
                    "runtime_id": "desktop",
                    "structured_result": {"desktop_session_id": session_id, "action": action, "result": value},
                }
            return {
                "status": "completed",
                "runtime_id": "desktop",
                "structured_result": {"desktop_session_id": session_id, "action": action, "result": value},
            }
        except Exception as error:
            # The runtime may have sent a control action before raising.  Do
            # not mark this result retryable or expose the exception text.
            return {
                "status": "failed",
                "error_code": type(error).__name__.lower().replace("_", "-")[:120] or "desktop-worker-error",
                "possibly_sent": action not in {"observe", "read", "snapshot", "inspect", "health", "status"},
                "runtime_id": "desktop",
                "structured_result": {"desktop_session_id": session_id, "action": action} if session_id else None,
            }
        finally:
            if not bool(metadata.get("keep_session", True)) and session_id and created_here:
                closer = getattr(self.runtime, "close_session", None)
                if callable(closer):
                    try:
                        closer(session_id)
                    except Exception:
                        pass
                self._forget(key, session_id)

    def close(self) -> None:
        closer = getattr(self.runtime, "close_session", None)
        with self._lock:
            sessions = list(self._owned_sessions)
            self._owned_sessions.clear()
            self._sessions.clear()
        if callable(closer):
            for session_id in sessions:
                try:
                    closer(session_id)
                except Exception:
                    pass


def _iter_event_objects(value: Any, *, depth: int = 0) -> list[Any]:
    """Flatten common app-server envelopes without executing their fields."""

    if depth > 6:
        return []
    if isinstance(value, Mapping):
        result: list[Any] = [value]
        # These are protocol envelope/container names used by DSH, ZCode and
        # the legacy JSON-RPC fixtures.  Keep the list explicit: recursively
        # walking arbitrary user fields could make a piece of content look
        # like a lifecycle event.
        for key in (
            "event",
            "params",
            "extensions",
            "events",
            "items",
            "messages",
            "parts",
            "timeline",
            "result",
            "payload",
            "data",
            "turn",
            "item",
            "message",
            "part",
            "reason",
        ):
            nested = value.get(key)
            if nested is not None:
                result.extend(_iter_event_objects(nested, depth=depth + 1))
        return result
    if isinstance(value, (list, tuple)):
        result: list[Any] = []
        for item in value[:128]:
            result.extend(_iter_event_objects(item, depth=depth + 1))
        return result
    return []


def _event_marker(event: Mapping[str, Any]) -> str:
    extensions = event.get("extensions") if isinstance(event.get("extensions"), Mapping) else {}
    extension_event = extensions.get("event") if isinstance(extensions.get("event"), Mapping) else {}
    extension_turn = extensions.get("turn") if isinstance(extensions.get("turn"), Mapping) else {}
    turn = event.get("turn") if isinstance(event.get("turn"), Mapping) else {}
    data = event.get("data") if isinstance(event.get("data"), Mapping) else {}
    data_turn = data.get("turn") if isinstance(data.get("turn"), Mapping) else {}
    values = (
        extensions.get("method"),
        extensions.get("event_type"),
        extension_event.get("type"),
        extension_event.get("event_type"),
        extension_event.get("method"),
        extension_turn.get("type"),
        extension_turn.get("event_type"),
        extension_turn.get("state") and f"turn.{extension_turn.get('state')}",
        turn.get("type"),
        turn.get("event_type"),
        turn.get("state") and f"turn.{turn.get('state')}",
        data_turn.get("type"),
        data_turn.get("event_type"),
        data_turn.get("state") and f"turn.{data_turn.get('state')}",
        event.get("type"),
        event.get("event_type"),
        event.get("method"),
        event.get("event"),
        event.get("name"),
        event.get("status") if event.get("status") in {"completed", "failed", "cancelled", "canceled", "stopped", "running"} else None,
    )
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip().lower().replace("/", ".")
    return "event"


def _event_session_id(event: Mapping[str, Any]) -> str | None:
    extensions = event.get("extensions") if isinstance(event.get("extensions"), Mapping) else {}
    nested = _event_nested_maps(event)
    value = event.get("session_id") or event.get("sessionId") or event.get("thread_id") or event.get("threadId") or extensions.get("session_id") or extensions.get("sessionId")
    if value in (None, ""):
        for item in nested:
            value = item.get("session_id") or item.get("sessionId") or item.get("thread_id") or item.get("threadId")
            if value not in (None, ""):
                break
    return str(value).strip() if value not in (None, "") else None


def _event_turn_id(event: Mapping[str, Any]) -> str | None:
    extensions = event.get("extensions") if isinstance(event.get("extensions"), Mapping) else {}
    value = event.get("turn_id") or event.get("turnId") or extensions.get("turn_id") or extensions.get("turnId")
    if value in (None, ""):
        for item in _event_nested_maps(event):
            value = item.get("turn_id") or item.get("turnId")
            if value not in (None, ""):
                break
    return str(value).strip() if value not in (None, "") else None


def _event_nested_maps(event: Mapping[str, Any], *, depth: int = 0) -> list[Mapping[str, Any]]:
    """Return only known lifecycle sub-objects for correlation/state lookup."""

    if depth > 4:
        return []
    result: list[Mapping[str, Any]] = []
    for key in ("event", "params", "extensions", "turn", "data", "payload", "reason"):
        value = event.get(key)
        if isinstance(value, Mapping):
            result.append(value)
            result.extend(_event_nested_maps(value, depth=depth + 1))
    return result


def _event_output_text(event: Mapping[str, Any], marker: str) -> str | None:
    if not any(token in marker for token in ("part.delta", "output.text", "message.delta", "assistant.delta", "output", "assistant")):
        return None
    for key in ("delta", "text", "content", "value"):
        value = event.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None


def _append_stream_text(parts: list[str], text: str) -> None:
    value = text.strip()
    if not value:
        return
    current = "".join(parts)
    if not current:
        parts.append(value)
    elif value.startswith(current):
        parts[:] = [value]
    elif current.endswith(value) or value in current:
        return
    else:
        parts.append(value)


def _terminal_kind(marker: str, event: Mapping[str, Any]) -> str | None:
    # Explicit turn state/reason wins over a generic envelope marker such as
    # ``turn/end``.  Some ZCode builds report ``turn/end`` with
    # ``extensions.turn.state=error``.
    state_values: list[str] = []
    for item in [event, *_event_nested_maps(event)]:
        for key in ("state", "status", "kind"):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                state_values.append(value.strip().lower().replace("_", "."))
    for state in state_values:
        if state in {"failed", "error", "failure", "errored"} or state.endswith(".failed") or state.endswith(".error"):
            return "failed"
        if state in {"cancelled", "canceled", "stopped", "interrupted", "aborted"} or state.endswith(".cancelled") or state.endswith(".canceled"):
            return "cancelled"
        if state in {"completed", "complete", "done", "success", "succeeded"} or state.endswith(".completed"):
            return "completed"
    value = marker.lower().replace("_", ".")
    if any(token in value for token in ("turn.failed", "turn.error", "turn.failure", "error")):
        return "failed"
    if any(token in value for token in ("turn.cancelled", "turn.canceled", "turn.stopped", "turn.interrupted", "turn.cancel")):
        return "cancelled"
    if any(token in value for token in ("turn.completed", "turn.complete", "turn.end", "turn.ended")):
        return "completed"
    status = str(event.get("status") or event.get("state") or "").lower()
    if status in {"failed", "error"}:
        return "failed"
    if status in {"cancelled", "canceled", "stopped", "interrupted"}:
        return "cancelled"
    if status in {"completed", "done", "success"} and "turn" in value:
        return "completed"
    return None


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
    "DesktopAutomationWorker",
]
