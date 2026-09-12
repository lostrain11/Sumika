from __future__ import annotations

import hashlib
import json
from typing import Any, Callable

from quality_routing import RoutingError
from quality_routing.contracts import bounded_text, identifier
from quality_routing.harness import RuntimeBinding
from quality_routing.privacy import looks_like_secret_text


ADMISSION_FIELDS = {"approved", "routingApproved", "routing_approved", "work_request_id", "client_request_id", "revision",
                    "parent_work_request_id", "parent_revision", "parent_step_id"}


def external_payload_digest(params: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps({key: value for key, value in params.items() if key not in ADMISSION_FIELDS},
                                    sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def validate_step_payload(value: Any) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).lower().replace("_", "").replace("-", "") in {
                "apikey", "apisecret", "password", "secret", "token", "accesstoken", "refreshtoken", "authorization", "cookie", "credentials",
            }:
                raise RoutingError("external plans must reference host credentials, not contain them")
            validate_step_payload(item)
    elif isinstance(value, list):
        for item in value:
            validate_step_payload(item)
    elif looks_like_secret_text(value):
        raise RoutingError("secret-like content cannot be stored in an external plan")


class LegacyWorkAdmission:
    dispatch_sources = {
        "agent.session.prompt": "agent",
        "agent.session.retry": "agent",
        "agent.subagent.prompt": "agent",
        "sumika.route.dispatch": "route",
        "sumika.route.retry": "route",
        "sumika.route.replan": "route",
        "sumika.route.arm": "route",
        "sumika.consultation.start": "consultation",
        "browser.web_chat.message.start": "web",
        "browser.web_chat.send": "web",
    }

    def __init__(self, work, *, profiles: Callable, routes: Callable, agent_offer: Callable,
                 route_status: Callable | None = None, runtime_binding: Callable | None = None) -> None:
        self.work = work
        self.profiles = profiles
        self.routes = routes
        self.agent_offer = agent_offer
        self.route_status = route_status
        self.runtime_binding = runtime_binding
        self._armed: dict[tuple[str, str], dict[str, Any]] = {}

    def handles(self, method: str, params: dict[str, Any]) -> bool:
        if method == "agent.session.update_queue":
            action = params.get("action") or params.get("kind")
            return (action.get("kind") if isinstance(action, dict) else action) in {"edit", "steer"}
        if method == "sumika.route.replan" and params.get("dispatch_selected", params.get("dispatchSelected")) is False:
            return False
        return method in self.dispatch_sources

    def prepare_steps(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        proposed = params.get("external_steps", [])
        if not isinstance(proposed, list) or len(proposed) > 32:
            raise RoutingError("external steps must be a list of at most 32 explicit steps")
        steps = []
        for item in proposed:
            if not isinstance(item, dict) or not {"id", "purpose", "method", "params"}.issubset(item):
                raise RoutingError("external steps require id, purpose, method and params")
            validate_step_payload(item)
            identifier(item["id"])
            bounded_text(item["purpose"])
            method = item["method"]
            supplied = item["params"]
            if method not in self.dispatch_sources or method.endswith((".arm", ".retry", ".replan")):
                raise RoutingError("this external step requires its own preflight")
            if not isinstance(supplied, dict) or ADMISSION_FIELDS.intersection(supplied) or "external_steps" in supplied:
                raise RoutingError("external step cannot contain approval or parent references")
            expected = {"assistant_id": params.get("assistant_id", "sumika"),
                        "core_session_id": params.get("core_session_id", "default"), "project_id": params.get("project_id")}
            if any(key in supplied and supplied[key] != value for key, value in expected.items()):
                raise RoutingError("external step is outside parent scope")
            payload = {**supplied, **expected}
            offer = self.offer(method, payload)
            steps.append({"id": item["id"], "purpose": item["purpose"], "method": method,
                          "params": payload, "payload_digest": external_payload_digest(payload),
                          "binding_digest": hashlib.sha256(json.dumps(offer, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest(),
                          "candidate_id": offer["candidate_id"], "high_cny": offer.get("high_cny") if offer.get("limit_enforced") is True else None,
                          "free": offer.get("free") is True, "reason": offer.get("reason", "")})
        if len({item["id"] for item in steps}) != len(steps):
            raise RoutingError("external step IDs must be unique")
        return steps

    def offer(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        source = self.dispatch_sources.get(method, "agent")
        if method == "sumika.route.arm" and isinstance(params.get("request"), dict):
            params = params["request"]
        if method == "sumika.route.retry" and self.route_status:
            upstream = params.get("dispatch_id") or params.get("dispatchId")
            receipt = self.route_status(str(upstream)) if upstream else {}
            previous = receipt.get("dispatch") or {}
            if not receipt.get("retryable") or receipt.get("possibly_sent") is True:
                raise RoutingError("only explicitly unsent failures can be retried")
            params = {**previous, **params}
        if source == "agent":
            supplied = dict(self.agent_offer(params))
            binding = self.runtime_binding() if self.runtime_binding else None
            session_id = str(params.get("sessionId") or params.get("session_id") or params.get("childSessionId") or "default")
            execution_key = "agent:" + session_id
            if binding is not None:
                if not isinstance(binding, RuntimeBinding):
                    raise RoutingError("invalid host runtime binding")
                execution_key = "agent:" + hashlib.sha256(json.dumps(
                    [binding.harness_id, binding.instance_id, session_id], ensure_ascii=False,
                ).encode()).hexdigest()
            return {
                "source": source, "method": method, "candidate_id": supplied.get("candidate_id", "agent:configured"),
                "identity": supplied.get("identity", ["agent", "unpriced"]),
                "high_cny": supplied.get("high_cny"), "limit_enforced": supplied.get("limit_enforced") is True,
                "free": supplied.get("free") is True, "funding": supplied.get("funding", "unknown"),
                "complexity": "complex",
                "runtime_binding": binding.to_dict() if binding else None,
                "execution_key": execution_key,
                "reason": supplied.get("reason") or "宿主无法承诺硬上限；此入口暂不能自动派发，费用未知",
            }
        profiles = {str(row["id"]): row for row in self.profiles()}
        route_ids = params.get("route_ids") or params.get("routeIds") or []
        constraints = params.get("route_constraints") or params.get("routeConstraints") or {}
        if source == "consultation" and isinstance(constraints, dict):
            route_ids = constraints.get("route_ids") or constraints.get("routeIds") or route_ids
        requested_profile_ids = params.get("profile_ids") or params.get("profileIds") or []
        if source == "web":
            profile_id = str(params.get("profile_id") or "")
            if profile_id not in profiles:
                raise RoutingError("web-chat profile was not found")
            selected = [profiles[profile_id]]
            identities = [self._profile_identity(selected[0])]
        else:
            route_id = params.get("route_id") or params.get("routeId")
            if route_id:
                route_ids = [str(route_id)]
            if requested_profile_ids:
                selected = [profiles[profile_id] for profile_id in requested_profile_ids if profile_id in profiles]
                if len(selected) != len(requested_profile_ids):
                    raise RoutingError("consultation profile was not found")
                identities = [self._profile_identity(profile) for profile in selected]
            elif route_ids and all(str(route_id).startswith("web-chat:") for route_id in route_ids):
                selected = [profiles[str(route_id).removeprefix("web-chat:")] for route_id in route_ids
                            if str(route_id).removeprefix("web-chat:") in profiles]
                identities = [self._profile_identity(profile) for profile in selected]
                if len(selected) != len(route_ids):
                    raise RoutingError("web-chat route was not found")
            else:
                routes = sorted((route for route in self.routes() if (
                    route.route_id in route_ids if route_ids else source == "consultation" and route.kind in {"web", "web-worker"}
                )), key=lambda route: route.route_id)
                selected = [profiles[route.provider_profile_id] for route in routes if route.provider_profile_id in profiles]
                identities = [{"route_id": route.route_id, "executor": route.executor, "kind": route.kind,
                               "provider_profile_id": route.provider_profile_id} for route in routes]
                identities.extend(self._profile_identity(profile) for profile in selected)
                if not routes or len(selected) != len(routes) or (route_ids and len(routes) != len(route_ids)):
                    selected = []
        free = bool(selected) and all(profile.get("budget_policy") in {"free-only", "no-paid"} for profile in selected)
        digest = hashlib.sha256(json.dumps(identities, sort_keys=True, default=str).encode()).hexdigest()
        return {
            "source": source, "method": method, "candidate_id": f"{source}:{digest[:32]}", "identity": identities,
            "trigger_binding": (self.runtime_binding().to_dict() if method == "sumika.route.arm"
                                and self.runtime_binding and self.runtime_binding() is not None else None),
            "high_cny": "0" if free else None, "limit_enforced": free, "free": free,
            "funding": "free-policy" if free else "unknown", "complexity": "simple" if source == "web" else "complex",
            "execution_key": ",".join(sorted("web-profile:" + str(profile["id"]) for profile in selected)),
            "reason": "仅允许既有 free-only 网页策略，不代表官方免费价格证据" if free
                      else "此网页或执行宿主缺少可靠费用上界；需要预算确认，暂不派发",
        }

    @staticmethod
    def _profile_identity(profile: dict[str, Any]) -> dict[str, Any]:
        return {key: profile.get(key) for key in (
            "id", "adapter_id", "adapter_version", "browser_profile_id", "browser_instance",
            "chat_url", "budget_policy", "config", "archived_at", "auto_chat_enabled", "allowed_actions"
        )}

    def dispatch(self, method: str, params: dict[str, Any], execute: Callable) -> dict[str, Any]:
        if method.startswith("browser.web_chat.") and (
            not isinstance(params.get("text"), str) or not params["text"].strip()
        ):
            raise RoutingError("web-chat text must be a non-empty string")
        def current_offer():
            offer = self.offer(method, params)
            if params.get("external_steps"):
                if params.get("parent_work_request_id") or method.endswith((".arm", ".retry", ".replan")):
                    raise RoutingError("nested or deferred delegation requires a separate plan")
                offer["external_steps"] = self.prepare_steps(params)
            return offer

        offer = current_offer()
        result = self.work.external_dispatch(params, offer, execute,
                                             refresh_offer=current_offer)
        if method == "sumika.route.arm" and result.get("armed"):
            key = (str(result.get("parent_session_id") or ""), str(result.get("parent_turn_id") or ""))
            with self.work._lock:
                self._armed[key] = {"params": dict(params), "work_request_id": result["work_request_id"],
                                    "owner": result["work_request"]["assistant_id"]}
        return result

    def advance_boundary(self, event: dict[str, Any], execute: Callable,
                         *, source_binding: RuntimeBinding | None = None) -> Any:
        if not isinstance(source_binding, RuntimeBinding) or source_binding.launch_id is None:
            return {"accepted": False, "reason": "runtime-identity-unverified"}
        key = (str(event.get("session_id") or event.get("parent_session_id") or ""),
               str(event.get("turn_id") or event.get("parent_turn_id") or ""))
        with self.work._lock:
            armed = self._armed.get(key) or self._armed.get((key[0], ""))
            if not armed:
                return {"accepted": False, "reason": "no-authorized-arm"}
            value = self.work.get(armed["work_request_id"], armed["owner"])
            try:
                original = RuntimeBinding.from_dict(value["external"].get("trigger_binding"))
            except RoutingError:
                return {"accepted": False, "reason": "runtime-identity-unverified"}
            if not original.matches_attempt(source_binding):
                return {"accepted": False, "reason": "runtime-binding-changed"}
            if value["status"] != "executing":
                return {"accepted": False, "status": value["status"], "reason": "armed work is not executable"}
            current = self.offer("sumika.route.arm", armed["params"])
            digest = hashlib.sha256(json.dumps(current, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()
            if digest != value["external"]["binding_digest"]:
                self.work.external_observe(value["request_id"], armed["owner"], {
                    "status": "failed", "accepted": False, "possibly_sent": False,
                    "reason": "route or price changed before deferred dispatch",
                })
                return {"accepted": False, "status": "awaiting-confirmation", "reason": "route changed; preflight required"}
        result = execute(True)
        if isinstance(result, dict) and isinstance(result.get("dispatch"), dict):
            self.work.external_observe(value["request_id"], armed["owner"], result["dispatch"])
            with self.work._lock:
                self._armed.pop(key, None)
                self._armed.pop((key[0], ""), None)
        return result

    def observe(self, method: str, params: dict[str, Any], result: Any) -> Any:
        sources = {"browser.web_chat.message.status": "web", "browser.web_chat.message.wait": "web",
                   "browser.web_chat.message.cancel": "web", "sumika.route.status": "route",
                   "sumika.consultation.status": "consultation"}
        if method not in sources or not isinstance(result, dict):
            return result
        upstream_id = (params.get("attempt_id") or params.get("attemptId") or params.get("dispatch_id")
                       or params.get("dispatchId") or params.get("consultation_id") or params.get("consultationId"))
        owner = params.get("assistant_id", "sumika")
        for value in self.work.repository.list_records(self.work.namespace, owner):
            external = value.get("external") or {}
            if upstream_id and external.get("source") == sources[method] and external.get("upstream_id") == upstream_id:
                return self.work.external_observe(value["request_id"], owner, result)
        return result

    def observe_agent_event(self, event: dict[str, Any], boundary: str | None,
                            *, source_binding: RuntimeBinding | None = None) -> None:
        if boundary not in {"turn.completed", "turn.failed", "turn.cancelled"}:
            return
        if not isinstance(source_binding, RuntimeBinding) or source_binding.launch_id is None:
            return
        turn_id, session_id = event.get("turn_id"), event.get("session_id")
        if not turn_id or not session_id:
            return
        for owner in tuple(self.work._owner_ids):
            for value in self.work.repository.list_records(self.work.namespace, owner):
                external = value.get("external") or {}
                if (external.get("source") == "agent" and external.get("session_id") == session_id
                        and external.get("upstream_id") == turn_id):
                    try:
                        recorded = RuntimeBinding.from_dict(external.get("runtime_binding"))
                        attempt = value.get("attempts", {}).get(f'{value["request_id"]}:external:1', {})
                        dispatched = RuntimeBinding.from_dict(attempt.get("runtime_binding"))
                    except RoutingError:
                        continue
                    if not recorded.matches_attempt(source_binding) or not dispatched.matches_attempt(source_binding):
                        continue
                    self.work.external_observe(value["request_id"], owner, {
                        "status": "completed" if boundary == "turn.completed" else "submission-unknown",
                        "turn_id": turn_id, "possibly_sent": True,
                    })

    def observe_route_event(self, event: dict[str, Any]) -> None:
        upstream = event.get("consultation_id") or event.get("dispatch_id")
        source = "consultation" if event.get("consultation_id") else "route"
        if not upstream or event.get("status") not in {"completed", "failed", "partial", "cancelled", "unknown"}:
            return
        for owner in tuple(self.work._owner_ids):
            for value in self.work.repository.list_records(self.work.namespace, owner):
                external = value.get("external") or {}
                if external.get("source") == source and external.get("upstream_id") == upstream:
                    result = dict(event)
                    if event["status"] not in {"completed", "partial"}:
                        result.update(status="submission-unknown", possibly_sent=True)
                    self.work.external_observe(value["request_id"], owner, result)

    def cancel_external(self, value: dict[str, Any], execute: Callable) -> dict[str, Any]:
        external = value.get("external") or {}
        if not value.get("cancel_requested") or value.get("cancel_dispatched"):
            return value
        own_attempt = value.get("attempts", {}).get(f'{value["request_id"]}:external:1', {})
        if own_attempt.get("status") != "reserved":
            return value
        source, upstream = external.get("source"), external.get("upstream_id")
        if source == "agent" and external.get("session_id"):
            method, params = "agent.session.cancel", {"sessionId": external["session_id"]}
        elif source == "web" and upstream:
            method, params = "browser.web_chat.message.cancel", {"attempt_id": upstream}
        elif source in {"route", "consultation"} and upstream:
            method, params = "sumika.route.cancel", {"consultation_id" if source == "consultation" else "dispatch_id": upstream}
        else:
            return value
        with self.work._lock:
            current = self.work.get(value["request_id"], value["assistant_id"])
            if current.get("cancel_dispatched"):
                return current
            current["cancel_dispatched"] = True
            self.work._save(current)
        execute(method, params)
        return self.work.get(value["request_id"], value["assistant_id"])
