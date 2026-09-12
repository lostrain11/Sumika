from __future__ import annotations

import json
import hashlib
import threading
import time
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from typing import Any
from uuid import uuid4

from quality_routing import Node, Quote, RoutingError, Scope
from quality_routing.contracts import amount
from quality_routing.harness import ExternalSessionRef, RuntimeBinding
from quality_routing.development_journal import append_event, recovery_state
from quality_routing.workflow import ExternalQuote, WorkRequest, admission_state, authorize, check_authorization, check_delegation, classify_request, delegation_digest, work_artifact
from ..development.contracts import DevelopmentExecutor, LEGACY_EXECUTOR_ID
from ..providers.guard import RequestNotSent
from .legacy_admission import external_payload_digest


class WorkService:
    namespace = "work-requests/v1"

    def __init__(self, repository, quality, *, owner_ids=(), record_received=None, development_factory=None,
                 skill_library=None, skill_data_root=None, development_executor: DevelopmentExecutor | None = None) -> None:
        self.repository = repository
        self.quality = quality
        self.record_received = record_received
        if development_executor is not None and development_factory is not None:
            raise ValueError("configure one development executor, not two execution paths")
        if development_factory is not None:
            from ..development.executor import ApiDevelopmentExecutor
            development_executor = ApiDevelopmentExecutor(development_factory)
        self.development_executor = development_executor
        self.skill_library = skill_library
        self.skill_data_root = skill_data_root
        self._lock = threading.RLock()
        self._pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="sumika-work")
        self._closed = False
        self._owner_ids = set(owner_ids)
        for owner in self._owner_ids:
            for value in repository.list_records(self.namespace, owner):
                if value.get("status") in {"planning", "executing", "cancel-requested"} and not value.get("task_id"):
                    value["status"] = "submission-unknown" if any(attempt["status"] == "reserved" for attempt in value.get("attempts", {}).values()) else "interrupted"
                    if value.get("development"):
                        self._development_recovery(value)
                    for attempt in value.get("attempts", {}).values():
                        if attempt["status"] == "reserved":
                            attempt["submission_unknown"] = True
                    self._save(value)

    def _request(self, value: dict[str, Any]) -> WorkRequest:
        return WorkRequest(**{key: item for key, item in value["request"].items() if key != "schema_version"})

    def _save(self, value: dict[str, Any]) -> dict[str, Any]:
        return self.repository.save_record(self.namespace, value["request_id"], value["assistant_id"], value)

    @staticmethod
    def _development_unresolved(value):
        if not value.get("development"):
            return False
        try:
            return recovery_state(value.get("development_journal", []))["state"] == "submission-unknown"
        except (RoutingError, KeyError, TypeError):
            return True

    @staticmethod
    def _development_recovery(value):
        try:
            recovery = recovery_state(value.get("development_journal", []))
        except (RoutingError, KeyError, TypeError):
            recovery = {"state": "submission-unknown", "reason": "journal-invalid", "automatic_replay": False}
        value["development_recovery"] = recovery
        if recovery["state"] == "submission-unknown":
            value["status"] = "submission-unknown"
        value["status_detail"] = "开发执行已停止；请检查操作记录和源码副本，不会自动重发或重新运行工具。"

    def get(self, request_id: str, assistant_id: str) -> dict[str, Any]:
        value = self.repository.get_record(self.namespace, request_id, assistant_id)
        if value is None:
            raise RoutingError("work request not found in this assistant scope")
        if value.get("task_id"):
            request = self._request(value)
            task = self.quality.status(value["task_id"], Scope(assistant_id, request.session_id))
            value.update(task=task, status=task["status"], artifacts=task.get("artifacts", []), commentary=task.get("commentary"))
        return value

    def list(self, assistant_id: str) -> list[dict[str, Any]]:
        return [self.get(row["request_id"], assistant_id) for row in self.repository.list_records(self.namespace, assistant_id)]

    def inspect_development(self, params):
        with self._lock:
            value = self.get(params["request_id"], params.get("assistant_id", "sumika"))
            if not value.get("development") or not self.development_executor:
                raise RoutingError("development inspection is unavailable")
            self._check_development(value)
            if value["status"] in {"planning", "executing", "verifying"}:
                raise RoutingError("wait for development execution to stop before inspecting")
            prepared = value.get("development_workspace")
            if not prepared:
                raise RoutingError("no completed development workspace preparation was recorded")
            inspection = self.development_executor.inspect(value["development"], prepared)
            result = value.get("development_result") or {}
            evidence_current = (result.get("status") == "completed"
                                and result.get("workspace_digest") == inspection["workspace_digest"])
            return {"request_id": value["request_id"], "revision": value["revision"],
                    "assistant_id": value["assistant_id"], "status": value["status"],
                    "recovery": recovery_state(value.get("development_journal", [])),
                    "test_evidence_current": evidence_current, "independently_verified": False,
                    **inspection}

    def preflight(self, params: dict[str, Any]) -> dict[str, Any]:
        if params.get("external_steps"):
            raise RoutingError("external step plans must enter through their Agent/Web host, not the API text planner")
        scope = self.quality._scope(params)
        request = WorkRequest(str(params.get("request_id") or uuid4().hex), scope.owner_id, scope.session_id,
                              params.get("goal"), params.get("revision", 1), params.get("source", "workbench"),
                              params.get("project_id"), params.get("original_message_id"))
        if request.project_id and self.repository.get_record("projects/v1", request.project_id, request.assistant_id) is None:
            raise RoutingError("project is outside this assistant scope")
        development = None
        if params.get("development") is not None:
            if not self.development_executor or not request.project_id or not isinstance(params["development"], dict):
                raise RoutingError("development requires a configured workspace and project")
            project = self.repository.get_record("projects/v1", request.project_id, request.assistant_id)
            development = self.development_executor.preflight(project.get("directory"), params["development"])
        with self._lock:
            previous = self.repository.get_record(self.namespace, request.request_id, scope.owner_id)
            if previous:
                if self._request(previous).fingerprint == request.fingerprint and previous.get("development") == development:
                    return self.get(request.request_id, scope.owner_id)
                raise RoutingError("existing request cannot be overwritten; submit a new request version")
            selection = self.quality.select_bindings(scope.owner_id)
            classification = classify_request(request.goal)
            if development:
                classification = {"complexity": "complex", "reason": "在源码副本中读写文件并运行明确授权的测试"}
            settings = self.quality.settings(scope.owner_id)
            allowed = list(dict.fromkeys(item for item in [*settings["candidate_pool"], selection["leader_candidate_id"], selection["role_candidate_id"]] if item))
            candidates = [item for item in self.quality.engine.candidates() if item.candidate_id in allowed and item.available and item.authorized]
            candidates = [item for item in candidates if item.channel == "api" and item.quote(16000, 4096).effective_cost_cny is not None]
            if settings.get("budget_preferences", {}).get("preference") == "free-only":
                candidates = [item for item in candidates if item.quote(16000, 4096).free]
            allowed = [item.candidate_id for item in candidates]
            selected = None
            if classification["complexity"] == "simple":
                qualified = [item for item in candidates if any(proof.baseline_id == "bounded-text-v1" and proof.expires_at > time.time() for proof in item.quality)]
                priced = [(item.quote(8000, 2048), item) for item in qualified]
                priced = [(quote, item) for quote, item in priced if quote.available and quote.effective_cost_cny is not None]
                if priced:
                    selected = min(priced, key=lambda pair: (not pair[0].free, pair[0].effective_cost_cny, pair[1].candidate_id))[1]
            else:
                leader_id = selection["leader_candidate_id"] or selection.get("bindings", {}).get("leader", {}).get("recommended_candidate_id")
                if leader_id and leader_id not in allowed:
                    recommended = next((item for item in self.quality.engine.candidates() if item.candidate_id == leader_id and item.available and item.authorized
                                        and item.channel == "api" and item.quote(16000, 4096).effective_cost_cny is not None), None)
                    if recommended and (settings.get("budget_preferences", {}).get("preference") != "free-only" or recommended.quote(16000, 4096).free):
                        allowed.append(leader_id)
                        candidates.append(recommended)
                selected = next((item for item in candidates if item.candidate_id == leader_id), None)
            input_tokens, output_tokens, calls = (16000, 4096, 4) if classification["complexity"] == "simple" else (64000, 16000, 80)
            if development:
                input_tokens, output_tokens, calls = development["max_input_tokens"], development["max_output_tokens"], development["max_calls"]
                allowed = [selected.candidate_id] if selected else []
            route_quote = selected.quote(input_tokens * calls, output_tokens * calls) if selected else None
            high = route_quote.effective_cost_cny if route_quote else None
            if high is not None and selected.fixed_cash is not None:
                high *= calls
            quote = Quote(high / 4 if high is not None else None, high / 2 if high is not None else None, high, calls, (input_tokens + output_tokens) * calls)
            state = admission_state(classification["complexity"], quote, funding=route_quote.funding_kind if route_quote else "unknown", executable=bool(selected and route_quote.available))
            value = {"schema_version": "sumika.work/v1", "id": request.request_id, "request_id": request.request_id,
                     "assistant_id": scope.owner_id, "request": request.to_dict(), "goal": request.goal,
                     "revision": request.revision, "status": state, "classification": classification,
                     "quote": {"low_cny": str(quote.low_cny) if quote.low_cny is not None else None,
                               "typical_cny": str(quote.typical_cny) if quote.typical_cny is not None else None,
                               "high_cny": str(quote.high_cny) if quote.high_cny is not None else None,
                               "max_calls": calls, "max_tokens": quote.max_tokens},
                     "funding": route_quote.to_dict() if route_quote else None,
                     "candidate_id": selected.candidate_id if selected else None, "allowed_candidate_ids": allowed,
                     "authorization_max_cny": settings.get("budget_preferences", {}).get("max_cny") or (str(high) if high is not None else None),
                     "candidate_identities": {item.candidate_id: list(item.identity()) for item in candidates},
                     "selection": selection, "authorization": None, "attempts": {}, "artifacts": [], "commentary": None,
                     "assumptions": ["估算包含规划、验证及范围内修复；发送前复检额度", "不包含工作区写入或无法限制费用的外部Harness"]}
            if state == "ready":
                value["authorization"] = authorize(request, quote, candidate_ids=tuple(allowed), max_cny="0")
            if development:
                value["development"] = development
                value["development_executor_id"] = self.development_executor.executor_id
                value["skills"] = self.skill_library.snapshot(scope.owner_id) if self.skill_library else []
                value["development_events"] = []
                value["assumptions"] = ["在独立源码副本修改；不自动合入、提交、发布或安装依赖", "测试是本机进程，源码副本不构成操作系统沙箱；测试代码具备当前用户权限",
                                        "源码发送给所选API；跳过运行数据、私有资源、非UTF-8和超过256KiB文件；上下文超限停止"]
            saved = self._save(value)
            if self.record_received:
                self.record_received(request)
            return saved

    def confirm(self, params: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            value = self.get(params["request_id"], params.get("assistant_id", "sumika"))
            if value["revision"] != params.get("revision"):
                raise RoutingError("approval is stale")
            if value.get("parent_authorization"):
                raise RoutingError("confirm the parent plan, not an individual delegated step")
            if value["status"] not in {"awaiting-confirmation", "ready"}:
                raise RoutingError("request is not awaiting confirmation")
            if value.get("external") and value["external"].get("limit_enforced") is not True:
                raise RoutingError(value.get("status_detail") or "host cannot enforce a spending limit")
            quote = ExternalQuote(**value["quote"]) if value.get("external") else Quote(**value["quote"])
            value["authorization"] = authorize(self._request(value), quote, candidate_ids=tuple(value["allowed_candidate_ids"]), max_cny=params.get("max_cny"))
            if value.get("external_steps"):
                value["authorization"]["delegation_digest"] = delegation_digest(value["external_steps"])
            if value.get("development"):
                self._check_development_executor(value)
                value["authorization"]["development_digest"] = delegation_digest([value["development"]])
                value["authorization"]["skills_digest"] = delegation_digest(value.get("skills", []))
                value["authorization"]["development_executor_id"] = value.get("development_executor_id", LEGACY_EXECUTOR_ID)
            value["status"] = "ready"
            return self._save(value)

    def revise(self, params: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            previous = self.get(params["request_id"], params.get("assistant_id", "sumika"))
            if any(attempt["status"] == "reserved" for attempt in previous["attempts"].values()):
                raise RoutingError("resolve in-flight or unknown attempts before revising")
            if self._development_unresolved(previous):
                raise RoutingError("resolve unknown development operations before revising")
            if previous["status"] in {"planning", "executing", "running", "verifying"}:
                raise RoutingError("pause or cancel current execution before revising")
            request = self._request(previous)
            next_revision = request.revision + 1
            stable_id = previous.get("stable_request_id", request.request_id)
            revised = self.preflight({**request.to_dict(), "request_id": f"{stable_id}:v{next_revision}",
                                      "revision": next_revision, "goal": params.get("goal", request.goal),
                                      **({"development": previous["development"]} if previous.get("development") else {})})
            revised.update(stable_request_id=stable_id, previous_request_id=request.request_id,
                           previous_task_id=previous.get("task_id"))
            return self._save(revised)

    def role_preflight(self, request, candidate) -> dict[str, Any]:
        messages = [{"role": item.role, "content": item.content} for item in request.messages]
        digest = hashlib.sha256(json.dumps({"messages": messages, "tools": request.tools, "candidate": candidate.identity(),
                                            "max_tokens": request.max_tokens, "session_id": request.session_id},
                                           sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()
        work_request = WorkRequest("role-" + digest, request.character_id, request.session_id,
                                   next(item.content for item in reversed(request.messages) if item.role == "user"), source="role")
        input_tokens = len(json.dumps(messages, ensure_ascii=False).encode()) + len(json.dumps(request.tools).encode()) + 1024
        with self._lock:
            previous = self.repository.get_record(self.namespace, work_request.request_id, work_request.assistant_id)
            if previous:
                return previous
            route_quote = candidate.quote(input_tokens, request.max_tokens)
            cost = route_quote.effective_cost_cny
            quote = Quote(cost, cost, cost, 1, input_tokens + request.max_tokens)
            state = admission_state("simple", quote, funding=route_quote.funding_kind, executable=route_quote.available)
            value = {"schema_version": "sumika.work/v1", "id": work_request.request_id, "request_id": work_request.request_id,
                     "request": work_request.to_dict(), "assistant_id": request.character_id, "goal": work_request.goal,
                     "revision": 1, "status": state, "classification": {"complexity": "simple", "reason": "当前角色交流请求"},
                     "candidate_id": candidate.candidate_id, "allowed_candidate_ids": [candidate.candidate_id],
                     "candidate_identities": {candidate.candidate_id: list(candidate.identity())},
                     "quote": {"low_cny": str(cost) if cost is not None else None, "typical_cny": str(cost) if cost is not None else None,
                               "high_cny": str(cost) if cost is not None else None, "max_calls": 1, "max_tokens": quote.max_tokens},
                     "funding": route_quote.to_dict(), "input_tokens": input_tokens, "authorization": None, "attempts": {},
                     "artifacts": [], "commentary": None}
            if state == "ready":
                value["authorization"] = authorize(work_request, quote, candidate_ids=(candidate.candidate_id,), max_cny="0")
            return self._save(value)

    def external_preflight(self, params: dict[str, Any], offer: dict[str, Any]) -> dict[str, Any]:
        scope = self.quality._scope({"assistant_id": params.get("assistant_id", "sumika"),
                                     "session_id": params.get("core_session_id", "default")})
        source = offer["source"]
        payload_digest = external_payload_digest(params)
        binding_digest = hashlib.sha256(json.dumps(offer, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()
        client_id = params.get("work_request_id") or params.get("client_request_id")
        parent_reference = None
        if params.get("parent_work_request_id"):
            parent_reference = {"request_id": params["parent_work_request_id"], "revision": params.get("parent_revision"),
                                "step_id": params.get("parent_step_id")}
            client_id = "child-" + hashlib.sha256(json.dumps(parent_reference, sort_keys=True).encode()).hexdigest()
        request_id = str(client_id or f"{source}-{payload_digest}")
        goal = str(params.get("text") or params.get("goal") or params.get("question") or "继续已指定的外部任务")
        request = WorkRequest(request_id, scope.owner_id, scope.session_id, goal,
                              params.get("revision", 1), source, params.get("project_id"))
        with self._lock:
            if request.project_id and self.repository.get_record("projects/v1", request.project_id, request.assistant_id) is None:
                raise RoutingError("project is outside this assistant scope")
            self._owner_ids.add(scope.owner_id)
            previous = self.repository.get_record(self.namespace, request_id, scope.owner_id)
            if previous:
                external = previous.get("external", {})
                if self._request(previous).fingerprint != request.fingerprint or external.get("payload_digest") != payload_digest:
                    raise RoutingError("external request changed; create a new request version")
                if external.get("binding_digest") != binding_digest and previous["status"] in {"ready", "awaiting-confirmation"}:
                    raise RoutingError("external route changed; a new preflight is required")
                return previous
            execution_key = offer.get("execution_key")
            if execution_key:
                requested_keys = set(execution_key.split(","))
                for active in self.repository.list_records(self.namespace, scope.owner_id):
                    active_keys = set(str((active.get("external") or {}).get("execution_key") or "").split(","))
                    if requested_keys.intersection(active_keys) and any(
                        attempt.get("status") == "reserved" for attempt in active.get("attempts", {}).values()
                    ):
                        return active
            supported = offer.get("limit_enforced") is True
            high = offer.get("high_cny") if supported else None
            own_high = high
            steps = offer.get("external_steps", [])
            if steps:
                high = (str(amount(high) + sum((amount(step["high_cny"]) for step in steps), Decimal(0)))
                        if high is not None and all(step["high_cny"] is not None for step in steps) else None)
            quote = ExternalQuote(high, high, high)
            free = supported and offer.get("free") is True and quote.high_cny == 0 and all(step["free"] for step in steps)
            complexity = offer.get("complexity", "complex")
            ready = free and complexity == "simple" and not steps
            candidate_id = str(offer["candidate_id"])
            value = {
                "schema_version": "sumika.work/v1", "id": request_id, "request_id": request_id,
                "assistant_id": scope.owner_id, "request": request.to_dict(), "goal": goal,
                "revision": request.revision, "status": "ready" if ready else "awaiting-confirmation",
                "classification": {"complexity": complexity, "reason": offer.get("reason", "外部执行入口")},
                "quote": {"low_cny": str(quote.low_cny) if high is not None else None,
                          "typical_cny": str(quote.typical_cny) if high is not None else None,
                          "high_cny": str(quote.high_cny) if high is not None else None,
                          "max_calls": None, "max_tokens": None},
                "funding": {"funding_kind": offer.get("funding", "unknown"), "free": free},
                "candidate_id": candidate_id, "allowed_candidate_ids": list(dict.fromkeys([candidate_id, *(step["candidate_id"] for step in steps)])),
                "authorization": authorize(request, quote, candidate_ids=(candidate_id,), max_cny="0") if ready else None,
                "attempts": {}, "artifacts": [], "commentary": None,
                "status_detail": offer.get("reason", ""),
                "external": {"source": source, "payload_digest": payload_digest, "binding_digest": binding_digest,
                             "limit_enforced": supported, "identity": offer.get("identity"),
                             "runtime_binding": deepcopy(offer.get("runtime_binding")),
                             "trigger_binding": deepcopy(offer.get("trigger_binding")),
                             "upstream_id": None, "execution_key": offer.get("execution_key"),
                             "method": offer.get("method"),
                             "own_high_cny": own_high,
                             "session_id": params.get("sessionId") or params.get("session_id") or params.get("childSessionId")},
            }
            if steps:
                value["external_steps"] = steps
                value["funding"]["funding_kind"] = "free-policy" if free else "mixed-or-unknown"
                value["classification"] = {"complexity": "complex", "reason": "包括需要确认范围的外部子步骤"}
            if parent_reference:
                if steps:
                    raise RoutingError("nested delegation is not supported")
                value["parent_authorization"] = parent_reference
                parent = self.get(parent_reference["request_id"], scope.owner_id)
                check_delegation(parent, value)
                value["authorization"] = authorize(request, quote, candidate_ids=(candidate_id,), max_cny=high)
                value["authorization"]["budget_owner_request_id"] = parent["request_id"]
                value["status"] = "ready"
            if source == "agent" and offer.get("runtime_binding") is not None and value["external"]["session_id"]:
                binding = RuntimeBinding.from_dict(offer["runtime_binding"])
                value["external"]["session_ref"] = ExternalSessionRef(
                    binding.harness_id, binding.instance_id, value["external"]["session_id"],
                ).to_dict()
            saved = self._save(value)
            if self.record_received:
                self.record_received(request)
            return saved

    def external_response(self, value: dict[str, Any]) -> dict[str, Any]:
        result = dict(value.get("source_result") or {})
        if not result:
            result.update(accepted=False, ok=False, status=value["status"])
        result.update(work_request_id=value["request_id"], work_request=value)
        if value.get("external_steps"):
            result["status"] = value["status"]
        if value["status"] == "awaiting-confirmation":
            result.update(accepted=False, ok=False, status="awaiting-confirmation", requires_approval=True,
                          reason=value.get("status_detail") or "需要确认此请求的目标和费用")
        if value["status"] == "submission-unknown":
            result.update(accepted=False, ok=False, status="submission-unknown", possibly_sent=True,
                          requires_human=True, reason="提交状态未知；请读取状态或人工接管，不会自动重发")
        return result

    def external_dispatch(self, params: dict[str, Any], offer: dict[str, Any], execute,
                          *, refresh_offer) -> dict[str, Any]:
        value = self.external_preflight(params, offer)
        with self._lock:
            value = self.get(value["request_id"], value["assistant_id"])
            if self._closed:
                raise RoutingError("work service is closed")
            if value["status"] != "ready":
                return self.external_response(value)
            keys = set(str(value["external"].get("execution_key") or "").split(",")) - {""}
            for owner in self._owner_ids:
                for active in self.repository.list_records(self.namespace, owner):
                    if owner == value["assistant_id"] and active["request_id"] == value["request_id"]:
                        continue
                    active_keys = set(str((active.get("external") or {}).get("execution_key") or "").split(",")) - {""}
                    if keys.intersection(active_keys) and any(item.get("status") == "reserved" for item in active.get("attempts", {}).values()):
                        raise RoutingError("external execution resource has an unresolved request")
            current_offer = refresh_offer()
            current_digest = hashlib.sha256(json.dumps(current_offer, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()
            if current_digest != value["external"]["binding_digest"]:
                raise RoutingError("external route or price changed before dispatch")
            if current_offer.get("runtime_binding") is not None:
                binding = RuntimeBinding.from_dict(current_offer["runtime_binding"])
                if not binding.matches_attempt(binding):
                    raise RoutingError("runtime launch identity is unverified")
            if current_offer.get("limit_enforced") is not True:
                raise RoutingError("host cannot enforce a spending limit")
            upper = amount(value["external"].get("own_high_cny", value["quote"]["high_cny"]))
            check_authorization(self._request(value), value["authorization"], value["candidate_id"], upper)
            attempt_id = f'{value["request_id"]}:external:1'
            if value["attempts"]:
                return self.external_response(value)
            parent = None
            if value.get("parent_authorization"):
                parent = self.get(value["parent_authorization"]["request_id"], value["assistant_id"])
                check_delegation(parent, value)
                parent_previous = deepcopy(parent)
                parent["authorization"]["reserved_cny"] = str(amount(parent["authorization"]["reserved_cny"]) + upper)
                parent["attempts"][attempt_id] = {"status": "reserved", "upper_cny": str(upper),
                                                   "child_request_id": value["request_id"], "step_id": value["parent_authorization"]["step_id"]}
            previous = deepcopy(value)
            value["authorization"]["reserved_cny"] = str(upper)
            value["attempts"][attempt_id] = {"status": "reserved", "upper_cny": str(upper),
                                             "runtime_binding": deepcopy(value["external"].get("runtime_binding"))}
            value["status"] = "executing"
            if parent is not None:
                self.repository.save_record_group(self.namespace, value["assistant_id"], [(parent_previous, parent), (previous, value)])
            else:
                self._save(value)
        try:
            result = execute()
        except RequestNotSent:
            self.external_observe(value["request_id"], value["assistant_id"],
                                  {"status": "failed", "accepted": False, "possibly_sent": False})
            raise
        except Exception:
            self.external_observe(value["request_id"], value["assistant_id"], {"status": "submission-unknown", "possibly_sent": True})
            raise
        if not isinstance(result, dict):
            result = {"status": "unknown", "possibly_sent": True}
        return self.external_observe(value["request_id"], value["assistant_id"], result)

    def external_observe(self, request_id: str, assistant_id: str, result: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            value = self.repository.get_record(self.namespace, request_id, assistant_id)
            if not value or not value.get("external") or not value["attempts"]:
                raise RoutingError("external request not found in this assistant scope")
            previous = deepcopy(value)
            attempt_id = f'{request_id}:external:1'
            attempt = value["attempts"][attempt_id]
            if attempt["status"] == "not-sent":
                return self.external_response(value)
            detail = result.get("result") if isinstance(result.get("result"), dict) else {}
            dispatch = result.get("dispatch") if isinstance(result.get("dispatch"), dict) else {}
            status = result.get("status") or detail.get("status") or dispatch.get("status")
            possibly_sent = result.get("possibly_sent") is True or detail.get("possibly_sent") is True
            complete = status in {"completed", "done", "succeeded", "partial"} or (
                result.get("ok") is True and not result.get("accepted") and not result.get("pending")
            )
            if attempt["status"] == "completed":
                text = result.get("text") or result.get("answer") or detail.get("answer")
                if complete and isinstance(text, str) and text.strip() and not value["artifacts"]:
                    artifact = work_artifact(request_id, assistant_id, text, source=value["external"]["source"])
                    artifact["verification"] = "source-completed"
                    value["artifacts"] = [artifact]
                    self._save(value)
                return self.external_response(value)
            not_sent = result.get("accepted") is False and result.get("possibly_sent") is False and status not in {
                "unknown", "possibly-sent", "submission-unknown"
            }
            value["external"]["upstream_id"] = (result.get("attempt_id") or result.get("dispatch_id") or result.get("turn_id")
                                                or result.get("consultation_id") or dispatch.get("dispatch_id")
                                                or (result.get("id") if value["external"]["source"] == "agent" else None)
                                                or value["external"].get("upstream_id"))
            value["source_result"] = {key: item for key, item in result.items() if key not in {
                "work_request", "work_request_id", "messages", "history"
            }}
            if complete or not_sent:
                upper = amount(attempt["upper_cny"])
                attempt["status"] = "completed" if complete else "not-sent"
                value["authorization"]["reserved_cny"] = str(amount(value["authorization"]["reserved_cny"]) - upper)
                value["authorization"]["spent_cny"] = str(amount(value["authorization"]["spent_cny"]) + (upper if complete else Decimal(0)))
                value["authorization"]["usage_basis"] = "conservative-upper-bound-not-bill"
                value["status"] = "completed" if complete else "failed"
                text = result.get("text") or result.get("answer") or detail.get("answer")
                if complete and isinstance(text, str) and text.strip() and not value["artifacts"]:
                    artifact = work_artifact(request_id, assistant_id, text, source=value["external"]["source"])
                    artifact["verification"] = "source-completed"
                    value["artifacts"] = [artifact]
            elif status in {"unknown", "possibly-sent", "submission-unknown"} or (
                possibly_sent and status not in {"accepted", "running", "pending", "executing"}
            ):
                value["status"] = "submission-unknown"
            else:
                value["status"] = "cancel-requested" if value.get("cancel_requested") else "executing"
            attempt["submission_unknown"] = value["status"] == "submission-unknown"
            if value.get("external_steps"):
                self._external_plan_state(value)
            if value.get("parent_authorization"):
                parent = self.repository.get_record(self.namespace, value["parent_authorization"]["request_id"], assistant_id)
                parent_previous = deepcopy(parent)
                parent_attempt = parent["attempts"][attempt_id]
                if parent_attempt["status"] != "reserved":
                    raise RoutingError("parent and child reservation states differ")
                if complete or not_sent:
                    parent_attempt["status"] = attempt["status"]
                    upper = amount(attempt["upper_cny"])
                    parent["authorization"]["reserved_cny"] = str(amount(parent["authorization"]["reserved_cny"]) - upper)
                    parent["authorization"]["spent_cny"] = str(amount(parent["authorization"]["spent_cny"]) + (upper if complete else Decimal(0)))
                    parent["authorization"]["usage_basis"] = "conservative-upper-bound-not-bill"
                parent_attempt["submission_unknown"] = value["status"] == "submission-unknown"
                self._external_plan_state(parent)
                self.repository.save_record_group(self.namespace, assistant_id, [(parent_previous, parent), (previous, value)])
            else:
                self._save(value)
            return self.external_response(value)

    @staticmethod
    def _external_plan_state(value: dict[str, Any]) -> None:
        attempts = value["attempts"]
        unresolved = any(item["status"] == "reserved" for item in attempts.values())
        if value.get("cancel_requested"):
            value["status"] = "cancel-requested" if unresolved else "cancelled"
        elif any(item.get("submission_unknown") and item["status"] == "reserved" for item in attempts.values()):
            value["status"] = "submission-unknown"
        elif any(item["status"] == "not-sent" for item in attempts.values()):
            value["status"] = "failed"
        elif unresolved or len(attempts) < len(value["external_steps"]) + 1:
            value["status"] = "executing"
        else:
            value["status"] = "completed"

    def submit(self, params: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            value = self.get(params["request_id"], params.get("assistant_id", "sumika"))
            if value["status"] != "ready":
                return value
            if value.get("external"):
                raise RoutingError("resume the authorized request through its original Agent/Web entry")
            if value["request"]["source"] == "role":
                raise RoutingError("resume this authorized request through chat.send")
            if self._closed:
                raise RoutingError("work service is closed")
            previous = deepcopy(value)
            value["status"] = "planning" if value["classification"]["complexity"] == "complex" else "executing"
            if value.get("development"):
                try:
                    self.repository.save_record_group(self.namespace, value["assistant_id"], [(previous, value)])
                except ValueError:
                    return self.get(value["request_id"], value["assistant_id"])
            else:
                self._save(value)
            self._pool.submit(self._run, value)
            return value

    def _run(self, value: dict[str, Any]) -> None:
        try:
            if value.get("development"):
                self._run_development(value)
                return
            request = self._request(value)
            params = {"assistant_id": request.assistant_id, "session_id": request.session_id, "goal": request.goal,
                      "allowed_candidate_ids": value["allowed_candidate_ids"], "external_allowed": True}
            if value["classification"]["complexity"] == "simple":
                task = self.quality.simple_plan(params, value["candidate_id"], request.request_id)
            else:
                task = self.quality.plan(params, work_request_id=request.request_id)
            with self._lock:
                current = self.repository.get_record(self.namespace, request.request_id, request.assistant_id)
                current["task_id"] = task["task_id"]
                if current["status"] == "cancelled":
                    self.quality.rpc("quality.task.cancel", {**params, "task_id": task["task_id"]})
                else:
                    current["status"] = task["status"]
                    self._save(current)
                    self.quality.rpc("quality.task.confirm", {**params, "task_id": task["task_id"], "revision": task["revision"]})
                self._save(current)
        except Exception as exc:
            with self._lock:
                current = self.repository.get_record(self.namespace, value["request_id"], value["assistant_id"])
                if current and current["status"] != "cancelled":
                    current["status"] = "submission-unknown" if any(item["status"] == "reserved" for item in current["attempts"].values()) else "failed"
                    if current.get("development"):
                        self._development_recovery(current)
                    current["error"] = "需要检查执行状态；未自动重发" if current["status"] == "submission-unknown" else "工作未完成，请检查候选、预算或执行记录"
                    current["error_type"] = type(exc).__name__
                    self._save(current)

    def _run_development(self, value):
        from quality_routing.development import DevelopmentNotSent

        request = self._request(value)
        scope = Scope(request.assistant_id, request.session_id)
        def cancelled():
            return self._closed or self.get(request.request_id, request.assistant_id)["status"] in {"cancelled", "cancel-requested", "submission-unknown"}

        with self._lock:
            current = self.get(request.request_id, request.assistant_id)
            if cancelled():
                return
            self._check_development(current)
            current["status"] = "executing"
            self._save(current)
        candidate = next((item for item in self.quality.engine.candidates() if item.candidate_id == value["candidate_id"]), None)
        if not candidate or list(candidate.identity()) != value["candidate_identities"].get(candidate.candidate_id):
            raise RoutingError("fixed development candidate unavailable or changed")
        def prepared(item):
            with self._lock:
                current = self.get(request.request_id, request.assistant_id)
                self._check_development(current)
                current["development_workspace"] = item
                self._save(current)

        def event(item, difference):
            with self._lock:
                current = self.get(request.request_id, request.assistant_id)
                current["development_events"].append(item)
                if difference is not None:
                    current["development_diff"] = difference
                self._save(current)

        def journal(item):
            with self._lock:
                current = self.get(request.request_id, request.assistant_id)
                self._check_development(current)
                if item["phase"] == "started" and cancelled():
                    raise RoutingError("development dispatch cancelled")
                previous = deepcopy(current)
                current["development_journal"] = append_event(current.get("development_journal", []), item)
                self.repository.save_record_group(self.namespace, request.assistant_id, [(previous, current)])

        skills = value.get("skills", [])
        def helper(skill_id, helper_id, operation):
            with self._lock:
                current = self.get(request.request_id, request.assistant_id)
                self._check_development(current)
                if cancelled() or self.skill_library is None:
                    raise RoutingError("Skill helper is unavailable")
            return self.skill_library.helper(request.assistant_id, skills, skill_id, helper_id, operation, data_root=self.skill_data_root)

        def invoke(messages, tools):
            with self._lock:
                self._check_development(self.get(request.request_id, request.assistant_id))
                if cancelled():
                    raise DevelopmentNotSent("development dispatch cancelled")
            try:
                return self.quality.invoke_development(candidate, scope, messages, tools, cancelled, request.request_id, value["development"])
            except RequestNotSent as exc:
                raise DevelopmentNotSent("development request was not sent") from exc

        execution = self.development_executor.run(request.goal, spec=value["development"], skills=skills,
            invoke=invoke, helper=helper, cancelled=cancelled, prepared=prepared, journal=journal, event=event)
        if (execution.get("schema_version") != "development-execution/v1"
                or execution.get("executor_id") != self.development_executor.executor_id):
            raise RoutingError("development executor returned an incompatible receipt")
        result = execution["result"]
        with self._lock:
            current = self.get(request.request_id, request.assistant_id)
            if not cancelled():
                current["status"] = result["status"]
            current["development_diff"] = execution["diff"]
            if result["status"] == "submission-unknown":
                self._development_recovery(current)
            current["development_result"] = result
            if result["text"]:
                artifact = work_artifact(request.request_id, request.assistant_id, result["text"], source="development")
                artifact.update(verification="tests-passed" if result["status"] == "completed" else "unverified", verified=False)
                current["artifacts"] = [artifact]
            self._save(current)

    def _check_development_executor(self, value):
        expected = value.get("development_executor_id", LEGACY_EXECUTOR_ID)
        if self.development_executor is None or self.development_executor.executor_id != expected:
            raise RoutingError("confirmed development executor is unavailable; no automatic replacement")
        return expected

    def _check_development(self, value):
        if value.get("development"):
            expected = self._check_development_executor(value)
            authorization = value.get("authorization") or {}
            if authorization.get("development_executor_id", LEGACY_EXECUTOR_ID) != expected:
                raise RoutingError("development executor differs from the confirmed version")
            if authorization.get("development_digest") != delegation_digest([value["development"]]):
                raise RoutingError("development scope differs from the confirmed version")
            if value.get("skills") and authorization.get("skills_digest") != delegation_digest(value["skills"]):
                raise RoutingError("Skill snapshot differs from the confirmed version")
            check_authorization(self._request(value), authorization, value["candidate_id"], 0)

    def reserve(self, request_id: str, scope: Scope, candidate, input_tokens: int, output_tokens: int) -> str:
        with self._lock:
            value = self.repository.get_record(self.namespace, request_id, scope.owner_id)
            if not value or value["status"] in {"cancelled", "cancel-requested", "failed", "submission-unknown"}:
                raise RoutingError("work request is not executable")
            if value.get("development") and (self._closed or value["status"] != "executing"):
                raise RoutingError("development request is not executing")
            request = self._request(value)
            if request.session_id != scope.session_id:
                raise RoutingError("work session mismatch")
            quote = candidate.quote(input_tokens, output_tokens)
            if not quote.available or quote.effective_cost_cny is None:
                raise RoutingError("current price or funding is unknown")
            previous = deepcopy(value) if value.get("development") else None
            authorization = value["authorization"]
            if not authorization:
                raise RoutingError("work requires confirmation")
            self._check_development(value)
            if value.get("candidate_identities", {}).get(candidate.candidate_id) != list(candidate.identity()):
                raise RoutingError("candidate identity changed; request a new preflight")
            if amount(authorization["max_cny"]) == 0 and not quote.free:
                raise RoutingError("free authorization cannot spend purchased resources")
            check_authorization(request, authorization, candidate.candidate_id, quote.effective_cost_cny)
            if len(value["attempts"]) >= value["quote"]["max_calls"]:
                raise RoutingError("authorized call limit exceeded")
            attempt_id = uuid4().hex
            operation_id = None
            if value.get("development"):
                pending = recovery_state(value.get("development_journal", []))["pending_operations"]
                if len(pending) != 1 or pending[0]["kind"] != "model":
                    raise RoutingError("development model call requires a persisted intent")
                operation_id = pending[0]["operation_id"]
                if any(item.get("development_operation_id") == operation_id for item in value["attempts"].values()):
                    raise RoutingError("development model operation already reserved")
            authorization["reserved_cny"] = str(amount(authorization["reserved_cny"]) + quote.effective_cost_cny)
            value["attempts"][attempt_id] = {"status": "reserved", "upper_cny": str(quote.effective_cost_cny)}
            if operation_id:
                value["attempts"][attempt_id]["development_operation_id"] = operation_id
                self.repository.save_record_group(self.namespace, scope.owner_id, [(previous, value)])
            else:
                self._save(value)
            return attempt_id

    def settle(self, request_id: str, scope: Scope, attempt_id: str, outcome, candidate) -> None:
        with self._lock:
            value = self.repository.get_record(self.namespace, request_id, scope.owner_id)
            attempt = value["attempts"][attempt_id]
            if attempt["status"] != "reserved":
                return
            if outcome.possibly_sent and outcome.status != "completed" or outcome.status == "unknown":
                value["status"] = "submission-unknown"
                self._save(value)
                return
            upper = amount(attempt["upper_cny"])
            attempt["status"] = outcome.status
            authorization = value["authorization"]
            authorization["reserved_cny"] = str(amount(authorization["reserved_cny"]) - upper)
            charge = Decimal(0) if outcome.input_tokens == 0 and outcome.output_tokens == 0 else upper
            authorization["spent_cny"] = str(amount(authorization["spent_cny"]) + charge)
            authorization["usage_basis"] = "conservative-upper-bound-not-bill"
            if value["request"]["source"] == "role":
                value["status"] = "completed" if outcome.status == "completed" else "failed"
            self._save(value)

    def cancel(self, params: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            value = self.get(params["request_id"], params.get("assistant_id", "sumika"))
            unresolved = ((value.get("external") or value.get("development")) and any(item.get("status") == "reserved" for item in value["attempts"].values())) or self._development_unresolved(value)
            value["status"] = "cancel-requested" if unresolved else "cancelled"
            if unresolved:
                value["cancel_requested"] = True
                value["status_detail"] = "已请求停止；上游状态和费用尚未确认，保留预留，请读取原入口状态"
            self._save(value)
            if value.get("external_steps"):
                for child in self.repository.list_records(self.namespace, value["assistant_id"]):
                    if ((child.get("parent_authorization") or {}).get("request_id") == value["request_id"]
                            and child["status"] not in {"completed", "failed", "cancelled"}):
                        self.cancel({"request_id": child["request_id"], "assistant_id": value["assistant_id"]})
            if value.get("task_id"):
                self.quality.rpc("quality.task.cancel", {"task_id": value["task_id"], "assistant_id": value["assistant_id"], "session_id": value["request"]["session_id"]})
            return value

    def rpc(self, method: str, params: dict[str, Any]) -> Any:
        if method == "work.task.preflight":
            return self.preflight(params)
        if method == "work.task.submit":
            return self.submit(params)
        if method == "work.task.revise":
            return self.revise(params)
        if method == "work.authorization.confirm":
            return self.confirm(params)
        if method == "work.task.get":
            return self.get(params["request_id"], params.get("assistant_id", "sumika"))
        if method == "work.task.inspect":
            return self.inspect_development(params)
        if method == "work.task.list":
            return {"tasks": self.list(params.get("assistant_id", "sumika"))}
        if method == "work.task.cancel":
            return self.cancel(params)
        raise RoutingError("unknown work method")

    def close(self) -> None:
        self._closed = True
        if hasattr(self.quality, "_closed"):
            self.quality._closed.set()
        self._pool.shutdown(wait=True, cancel_futures=True)
