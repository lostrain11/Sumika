from __future__ import annotations

import fnmatch
import copy
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from decimal import Decimal
from typing import Any, Callable, Iterable
from uuid import uuid4

from .budget import Budget
from .contracts import BudgetRule, Candidate, Node, Outcome, Plan, Quote, RoutingError, Scope, Verification, amount
from .selection import select_candidate
from .planning import handoff_errors, validate_planning


@dataclass(frozen=True)
class Execution:
    task_id: str
    scope: Scope
    revision: int
    attempt_id: str
    node: Node
    candidate: Candidate
    dependency_results: dict[str, str]
    cancelled: threading.Event
    handoff: dict[str, Any] | None = None


@dataclass
class _Task:
    plan: Plan
    budget: Budget
    allowed_ids: frozenset[str]
    external_allowed: bool
    approved: bool = False
    cancelled: bool = False
    states: dict[str, str] = field(default_factory=dict)
    results: dict[str, dict[str, Any]] = field(default_factory=dict)
    attempts: dict[str, int] = field(default_factory=dict)
    reason: str = ""
    reservation_accounts: dict[str, str] = field(default_factory=dict)
    candidate_identities: dict[str, tuple[Any, ...]] = field(default_factory=dict)
    file_grant: frozenset[str] = frozenset()
    quality_baselines: frozenset[str] = frozenset()
    assignments: dict[str, str] = field(default_factory=dict)
    upgrades: set[str] = field(default_factory=set)
    unknown_attempts: set[str] = field(default_factory=set)
    dispatch_paused: bool = False
    planning: dict[str, Any] | None = None
    planning_required: bool = False


class Coordinator:
    def __init__(self, candidates: Iterable[Candidate] = (), *,
                 executor: Callable[[Execution], Outcome] | None = None,
                 verifier: Callable[[Execution, Outcome], Verification] | None = None,
                 permission: Callable[[Execution], bool] | None = None,
                 save: Callable[[str, dict[str, Any]], None] | None = None,
                 event_sink: Callable[[dict[str, Any]], None] | None = None,
                 max_concurrency: int = 3) -> None:
        if type(max_concurrency) is not int or not 1 <= max_concurrency <= 3:
            raise RoutingError("concurrency must be 1 to 3")
        self._candidates = {candidate.candidate_id: candidate for candidate in candidates}
        self._tasks: dict[str, _Task] = {}
        self._executor = executor
        self._verifier = verifier
        self._permission = permission
        self._save = save
        self._events = event_sink
        self._lock = threading.RLock()
        self._pool = ThreadPoolExecutor(max_workers=max_concurrency, thread_name_prefix="quality-routing")
        self._maximum = max_concurrency
        self._active: dict[str, tuple[Execution, Future]] = {}
        self._balances: dict[str, Decimal | None] = {}
        self._closed = False

    def set_candidates(self, candidates: Iterable[Candidate]) -> None:
        with self._lock:
            self._candidates = {candidate.candidate_id: candidate for candidate in candidates}

    def candidates(self) -> tuple[Candidate, ...]:
        with self._lock:
            return tuple(self._candidates.values())

    def set_account_balance(self, account_id: str, balance_cny: Decimal | None) -> None:
        with self._lock:
            self._balances[account_id] = amount(balance_cny) if balance_cny is not None else None

    def submit(self, plan: Plan, quote: Quote, rule: BudgetRule, *, allowed_ids: Iterable[str],
               external_allowed: bool = False, planning: dict[str, Any] | None = None,
               planning_required: bool = False, file_grant: Iterable[str] | None = None) -> dict[str, Any]:
        if type(external_allowed) is not bool:
            raise RoutingError("external authorization must be boolean")
        if type(planning_required) is not bool:
            raise RoutingError("planning requirement must be boolean")
        checked_planning = validate_planning(planning, plan)
        with self._lock:
            if self._closed or plan.task_id in self._tasks or plan.revision != 1:
                raise RoutingError("task already exists, coordinator closed, or invalid initial revision")
            task = _Task(plan, Budget(quote, rule), frozenset(allowed_ids), external_allowed,
                         states={node.node_id: "pending" for node in plan.nodes})
            task.candidate_identities = {key: candidate.identity() for key, candidate in self._candidates.items() if key in task.allowed_ids}
            task.file_grant = frozenset(file_grant if file_grant is not None else
                                        (path for node in plan.nodes for path in node.allowed_files))
            if any(not isinstance(path, str) or not path for path in task.file_grant):
                raise RoutingError("invalid host file grant")
            for node in plan.nodes:
                for path in node.allowed_files:
                    if path not in task.file_grant and (any(char in path for char in "*?[") or
                            not any(fnmatch.fnmatchcase(path, grant) for grant in task.file_grant)):
                        raise RoutingError("plan exceeds approved file scope")
            task.planning = checked_planning
            task.planning_required = planning_required or checked_planning is not None
            task.quality_baselines = frozenset(node.baseline_id for node in plan.nodes)
            self._tasks[plan.task_id] = task
            self._persist(task, "task.created")
            return self.status(plan.task_id, plan.scope)

    def _task(self, task_id: str, scope: Scope) -> _Task:
        task = self._tasks.get(task_id)
        if task is None or task.plan.scope != scope:
            raise RoutingError("task not found in this scope")
        return task

    def approve(self, task_id: str, scope: Scope, revision: int) -> dict[str, Any]:
        with self._lock:
            task = self._task(task_id, scope)
            if revision != task.plan.revision or task.cancelled:
                raise RoutingError("approval is stale")
            task.approved = True
            self._persist(task, "task.approved")
            return self.status(task_id, scope)

    def update_rule(self, task_id: str, scope: Scope, rule: BudgetRule) -> dict[str, Any]:
        with self._lock:
            task = self._task(task_id, scope)
            task.budget.rule = rule
            task.reason = ""
            self._persist(task, "task.budget.updated")
            return self.status(task_id, scope)

    def record_prior_call(self, task_id: str, scope: Scope, attempt_id: str,
                          estimated_cash: Decimal | None, actual_cash: Decimal | None, tokens: int) -> None:
        with self._lock:
            task = self._task(task_id, scope)
            task.budget.record_prior_call(attempt_id, estimated_cash, actual_cash, tokens)
            self._persist(task, "preflight.accounted")

    def revise(self, plan: Plan, *, quote: Quote | None = None, require_confirmation: bool = False,
               invalidate_ids: Iterable[str] = (), planning: dict[str, Any] | None = None) -> dict[str, Any]:
        with self._lock:
            task = self._task(plan.task_id, plan.scope)
            if plan.revision != task.plan.revision + 1 or task.cancelled:
                raise RoutingError("invalid revision")
            if task.unknown_attempts or set(task.states.values()) & {"running", "verifying", "unknown"}:
                raise RoutingError("recover the original attempt before replanning")
            inherited_planning = copy.deepcopy(task.planning) if planning is None else planning
            if planning is None and inherited_planning is not None:
                inherited_planning["handoffs"] = {key: value for key, value in inherited_planning["handoffs"].items()
                                                  if key in {node.node_id for node in plan.nodes}}
            checked_planning = validate_planning(inherited_planning, plan)
            if checked_planning is not None and task.planning is not None and (
                    checked_planning["goal_contract_digest"] != task.planning["goal_contract_digest"]):
                raise RoutingError("planning cannot change the authorized goal contract")
            previous = {node.node_id: node for node in task.plan.nodes}
            previous_dependencies = {dependency for node in task.plan.nodes for dependency in node.dependencies}
            next_dependencies = {dependency for node in plan.nodes for dependency in node.dependencies}
            terminal_baselines = {node.baseline_id for node in task.plan.nodes if node.node_id not in previous_dependencies}
            revised_terminal_baselines = {node.baseline_id for node in plan.nodes if node.node_id not in next_dependencies}
            if not terminal_baselines <= revised_terminal_baselines:
                raise RoutingError("revision cannot replace the approved quality baseline of a terminal")
            for node in plan.nodes:
                if (node.baseline_id not in task.quality_baselines or
                        node.node_id in previous and node.baseline_id != previous[node.node_id].baseline_id):
                    raise RoutingError("revision cannot replace the approved quality baseline")
                for path in node.allowed_files:
                    if path not in task.file_grant and (any(char in path for char in "*?[") or
                                                       not any(fnmatch.fnmatchcase(path, grant) for grant in task.file_grant)):
                        raise RoutingError("revision exceeds approved file scope")
            invalid = {node.node_id for node in plan.nodes if previous.get(node.node_id) != node}
            if checked_planning is not None and task.planning is not None:
                for node in plan.nodes:
                    before = task.planning["handoffs"].get(node.node_id, {})
                    after = checked_planning["handoffs"].get(node.node_id, {})
                    if not isinstance(before, dict) or not isinstance(after, dict) or (
                            {key: value for key, value in before.items() if key != "review"} !=
                            {key: value for key, value in after.items() if key != "review"}):
                        invalid.add(node.node_id)
            invalid.update(invalidate_ids)
            invalid.update(key for key, state in task.states.items() if state != "completed")
            invalid.update(key for key, value in task.states.items() if value in {"running", "verifying"})
            while True:
                expanded = invalid | {node.node_id for node in plan.nodes if set(node.dependencies) & invalid}
                if expanded == invalid:
                    break
                invalid = expanded
            states = {}
            for node in plan.nodes:
                if task.states.get(node.node_id) in {"running", "verifying", "unknown"}:
                    states[node.node_id] = "unknown"
                elif node.node_id not in invalid and task.states.get(node.node_id) == "completed":
                    states[node.node_id] = "completed"
                else:
                    states[node.node_id] = "pending"
            for execution, _future in self._active.values():
                if execution.task_id == plan.task_id:
                    execution.cancelled.set()
            task.results = {key: value for key, value in task.results.items() if states.get(key) == "completed"}
            task.states = states
            task.plan = plan
            task.planning = checked_planning
            task.planning_required = task.planning_required or checked_planning is not None
            task.dispatch_paused = False
            if quote is not None:
                task.budget.quote = quote
            if require_confirmation or quote is not None:
                task.approved = False
                task.candidate_identities = {key: candidate.identity() for key, candidate in self._candidates.items()
                                             if key in task.allowed_ids}
            task.reason = ""
            self._persist(task, "plan.revised")
            return self.status(plan.task_id, plan.scope)

    def mark_unknown(self, task_id: str, scope: Scope, attempt_id: str) -> None:
        with self._lock:
            task = self._task(task_id, scope)
            if attempt_id not in task.budget.reservations:
                raise RoutingError("unknown reservation")
            task.unknown_attempts.add(attempt_id)
            self._persist(task, "attempt.unknown")

    def pause(self, task_id: str, scope: Scope) -> dict[str, Any]:
        with self._lock:
            task = self._task(task_id, scope)
            task.dispatch_paused = True
            self._persist(task, "task.dispatch-paused")
            return self.status(task_id, scope)

    @staticmethod
    def _conflicts(left: Node, right: Node) -> bool:
        for first in left.allowed_files:
            for second in right.allowed_files:
                first_root = first.split("*", 1)[0]
                second_root = second.split("*", 1)[0]
                if first_root.startswith(second_root) or second_root.startswith(first_root):
                    return True
        return False

    def advance(self, task_id: str, scope: Scope) -> dict[str, Any]:
        with self._lock:
            task = self._task(task_id, scope)
            if (self._closed or task.cancelled or not task.approved or task.dispatch_paused or
                    task.unknown_attempts or "unknown" in task.states.values()):
                return self.status(task_id, scope)
            if self._executor is None or self._verifier is None or self._permission is None:
                task.reason = "host-executor-verifier-or-permission-unavailable"
                return self.status(task_id, scope)
            task.reason = ""
            for node in task.plan.nodes:
                if len(self._active) >= self._maximum:
                    break
                if task.states[node.node_id] != "pending" or any(task.states[key] != "completed" for key in node.dependencies):
                    continue
                if handoff_errors(node, task.planning, task.results, required=task.planning_required):
                    task.reason = "handoff-required"
                    continue
                if any(self._conflicts(node, execution.node) for execution, _future in self._active.values()):
                    continue
                try:
                    unchanged = [candidate for candidate in self._candidates.values()
                                 if task.candidate_identities.get(candidate.candidate_id) == candidate.identity()
                                 and (node.node_id not in task.assignments or
                                      task.assignments[node.node_id] == candidate.candidate_id)]
                    candidate = select_candidate(node, unchanged, set(task.allowed_ids), external_allowed=task.external_allowed)
                except RoutingError as error:
                    task.reason = str(error)
                    continue
                account_runs = [execution for execution, _future in self._active.values()
                                if execution.candidate.account_id == candidate.account_id]
                limit = 1 if candidate.channel == "web" else candidate.account_concurrency
                if len(account_runs) >= limit:
                    continue
                estimate = candidate.estimate(node.input_tokens, node.output_tokens)
                balance = self._balances.get(candidate.account_id)
                reserved_costs = [reservation.cash_cny for current in self._tasks.values()
                                  for attempt, reservation in current.budget.reservations.items()
                                  if current.reservation_accounts.get(attempt) == candidate.account_id]
                reservations = sum((cost or Decimal(0) for cost in reserved_costs), Decimal(0))
                if balance is not None and (balance == 0 or estimate is None or None in reserved_costs or reservations + estimate > balance):
                    task.reason = "account-balance-exhausted-or-unpriced"
                    continue
                attempt_id = uuid4().hex
                execution = Execution(task_id, scope, task.plan.revision, attempt_id, node, candidate,
                                      {key: task.results[key]["text"] for key in node.dependencies}, threading.Event(),
                                      copy.deepcopy(task.planning["handoffs"].get(node.node_id)) if task.planning else None)
                if self._permission(execution) is not True:
                    task.reason = "host-permission-denied"
                    continue
                try:
                    warning = task.budget.reserve(attempt_id, estimate, node.input_tokens + node.output_tokens)
                except RoutingError as error:
                    task.reason = str(error)
                    continue
                task.states[node.node_id] = "running"
                task.assignments[node.node_id] = candidate.candidate_id
                task.reservation_accounts[attempt_id] = candidate.account_id
                task.attempts[node.node_id] = task.attempts.get(node.node_id, 0) + 1
                self._persist(task, "node.reserved")
                future = self._pool.submit(self._execute, execution)
                self._active[attempt_id] = (execution, future)
                future.add_done_callback(lambda completed, current=execution: self._finish(current, completed))
                if warning != "within-estimate":
                    task.reason = warning
            self._persist(task, "task.advanced")
            return self.status(task_id, scope)

    def _execute(self, execution: Execution) -> tuple[Outcome, Verification | None]:
        if execution.cancelled.is_set():
            return Outcome("cancelled", cash_cny=Decimal(0), input_tokens=0, output_tokens=0), None
        try:
            result = self._executor(execution)
            if not isinstance(result, Outcome):
                raise RoutingError("invalid host outcome")
        except Exception:
            return Outcome("unknown", possibly_sent=True), None
        if result.status != "completed" or execution.cancelled.is_set():
            return result, None
        for path in result.changed_files:
            if not any(fnmatch.fnmatchcase(path, pattern) for pattern in execution.node.allowed_files):
                return result, Verification(False, reason="file-scope-violation")
        try:
            check = self._verifier(execution, result)
            if not isinstance(check, Verification):
                raise RoutingError("invalid verification")
            return result, check
        except Exception:
            return result, Verification(False, reason="verification-unavailable")

    def _finish(self, execution: Execution, future: Future) -> None:
        try:
            result, check = future.result()
        except Exception:
            result, check = Outcome("unknown", possibly_sent=True), None
        with self._lock:
            task = self._tasks[execution.task_id]
            if result.status != "unknown" and not (result.possibly_sent and result.status != "completed"):
                tokens = (result.input_tokens + result.output_tokens
                          if result.input_tokens is not None and result.output_tokens is not None else None)
                task.budget.settle(execution.attempt_id, result.cash_cny, tokens)
                task.reservation_accounts.pop(execution.attempt_id, None)
                balance = self._balances.get(execution.candidate.account_id)
                if balance is not None:
                    charged = result.cash_cny
                    if charged is None:
                        charged = execution.candidate.estimate(execution.node.input_tokens, execution.node.output_tokens)
                    self._balances[execution.candidate.account_id] = max(Decimal(0), balance - charged) if charged is not None else Decimal(0)
            self._active.pop(execution.attempt_id, None)
            if task.cancelled or task.plan.revision != execution.revision:
                self._persist(task, "result.discarded")
                return
            status = result.status
            if status == "completed" and (check is None or not check.passed):
                status = "needs-replan" if task.attempts.get(execution.node.node_id, 0) >= 2 else "verification-failed"
            if status == "failed" and task.attempts.get(execution.node.node_id, 0) >= 2:
                status = "needs-replan"
            if result.possibly_sent and result.status != "completed":
                status = "unknown"
            task.states[execution.node.node_id] = status
            task.results[execution.node.node_id] = {
                "status": status, "text": result.text, "attempt_id": execution.attempt_id,
                "candidate_id": execution.candidate.candidate_id, "requested_reasoning_effort": execution.candidate.reasoning_effort,
                "applied_reasoning_effort": result.applied_reasoning_effort,
                "input_tokens": result.input_tokens, "output_tokens": result.output_tokens,
                "cash_cny": str(result.cash_cny) if result.cash_cny is not None else None,
                "possibly_sent": result.possibly_sent, "evidence": list(check.evidence if check else ()),
                "reason": check.reason if check else "",
            }
            self._persist(task, "node.finished")

    def retry(self, task_id: str, scope: Scope, node_id: str) -> dict[str, Any]:
        with self._lock:
            task = self._task(task_id, scope)
            if (task.cancelled or task.unknown_attempts or "unknown" in task.states.values() or
                    task.states.get(node_id) not in {"failed", "verification-failed"} or task.attempts.get(node_id, 0) >= 2):
                raise RoutingError("retry requires a known failure and is limited to one repair")
            task.assignments[node_id] = task.results[node_id]["candidate_id"]
            task.states[node_id] = "pending"
            task.reason = ""
            self._persist(task, "node.retry")
            return self.status(task_id, scope)

    def upgrade(self, task_id: str, scope: Scope, node_id: str, candidate_id: str | None = None) -> dict[str, Any]:
        with self._lock:
            task = self._task(task_id, scope)
            if (task.cancelled or task.unknown_attempts or "unknown" in task.states.values() or
                    task.states.get(node_id) != "needs-replan" or node_id in task.upgrades or
                    task.attempts.get(node_id, 0) != 2):
                raise RoutingError("upgrade requires one exhausted repair and is limited to once")
            node = next(node for node in task.plan.nodes if node.node_id == node_id)
            target_id = candidate_id or node.baseline_id
            failed_id = task.results[node_id]["candidate_id"]
            if target_id == failed_id:
                raise RoutingError("upgrade must replace the failed executor")
            target = self._candidates.get(target_id)
            if target is None or task.candidate_identities.get(target_id) != target.identity():
                raise RoutingError("upgrade candidate identity changed")
            select_candidate(node, [target], set(task.allowed_ids), external_allowed=task.external_allowed)
            task.assignments[node_id] = target_id
            task.upgrades.add(node_id)
            task.states[node_id] = "pending"
            task.reason = ""
            self._persist(task, "node.upgrade")
            return self.status(task_id, scope)

    def cancel(self, task_id: str, scope: Scope) -> dict[str, Any]:
        with self._lock:
            task = self._task(task_id, scope)
            task.cancelled = True
            for execution, _future in self._active.values():
                if execution.task_id == task_id:
                    execution.cancelled.set()
            self._persist(task, "task.cancelled")
            return self.status(task_id, scope)

    def reserve_auxiliary(self, task_id: str, scope: Scope, attempt_id: str,
                          cash_cny: Decimal | None, tokens: int, candidate_id: str | None = None) -> None:
        with self._lock:
            task = self._task(task_id, scope)
            if not task.approved or task.cancelled or task.unknown_attempts or "unknown" in task.states.values():
                raise RoutingError("task not authorized")
            candidate = self._candidates.get(candidate_id) if candidate_id else None
            if candidate_id and (candidate is None or candidate_id not in task.allowed_ids or not candidate.authorized
                                 or not candidate.available or candidate.external and not task.external_allowed
                                 or task.candidate_identities.get(candidate_id) != candidate.identity()):
                raise RoutingError("auxiliary candidate not authorized")
            if candidate:
                balance = self._balances.get(candidate.account_id)
                reserved = [reservation.cash_cny for current in self._tasks.values()
                            for attempt, reservation in current.budget.reservations.items()
                            if current.reservation_accounts.get(attempt) == candidate.account_id]
                if balance is not None and (cash_cny is None or None in reserved or
                                           sum(reserved, Decimal(0)) + amount(cash_cny) > balance or balance == 0):
                    raise RoutingError("account-balance-exhausted-or-unpriced")
            task.budget.reserve(attempt_id, cash_cny, tokens)
            if candidate:
                task.reservation_accounts[attempt_id] = candidate.account_id
            self._persist(task, "auxiliary.reserved")

    def settle_auxiliary(self, task_id: str, scope: Scope, attempt_id: str,
                         cash_cny: Decimal | None, tokens: int | None) -> None:
        with self._lock:
            task = self._task(task_id, scope)
            account = task.reservation_accounts.get(attempt_id)
            reserved = task.budget.reservations.get(attempt_id)
            task.budget.settle(attempt_id, cash_cny, tokens)
            if account and reserved:
                balance = self._balances.get(account)
                if balance is not None:
                    charged = amount(cash_cny) if cash_cny is not None else reserved.cash_cny
                    self._balances[account] = max(Decimal(0), balance - charged) if charged is not None else Decimal(0)
                task.reservation_accounts.pop(attempt_id, None)
            self._persist(task, "auxiliary.settled")

    def status(self, task_id: str, scope: Scope) -> dict[str, Any]:
        with self._lock:
            task = self._task(task_id, scope)
            states = set(task.states.values())
            status = ("cancelled" if task.cancelled else "awaiting-confirmation" if not task.approved
                      else "needs-attention" if task.unknown_attempts or "unknown" in states
                      else "running" if "running" in states else "paused" if task.dispatch_paused
                      else "needs-planning" if states == {"completed"} and task.planning is not None and not task.planning["horizon_complete"]
                      else "completed" if states == {"completed"}
                      else "needs-attention" if states & {"unknown", "needs-replan", "verification-failed", "failed"}
                      else "paused" if task.reason else "ready")
            return {"schema": "quality-routing/task/v1", "task_id": task_id, "scope": asdict(scope),
                    "revision": task.plan.revision, "status": status, "reason": task.reason,
                    "plan": task.plan.to_dict(), "states": dict(task.states), "results": dict(task.results),
                    "unknown_attempts": sorted(task.unknown_attempts),
                    "planning": copy.deepcopy(task.planning),
                    "handoff_issues": {node.node_id: list(issues) for node in task.plan.nodes
                                       if task.states[node.node_id] == "pending" and
                                       (issues := handoff_errors(node, task.planning, task.results, required=task.planning_required))},
                    "budget": task.budget.to_dict()}

    def list_tasks(self, scope: Scope) -> list[dict[str, Any]]:
        with self._lock:
            return [self.status(key, scope) for key, task in self._tasks.items() if task.plan.scope == scope]

    def snapshot(self, task_id: str, scope: Scope) -> dict[str, Any]:
        with self._lock:
            task = self._task(task_id, scope)
            return {**self.status(task_id, scope), "allowed_ids": sorted(task.allowed_ids), "external_allowed": task.external_allowed,
                    "approved": task.approved, "cancelled": task.cancelled, "attempts": dict(task.attempts),
                    "reservation_accounts": dict(task.reservation_accounts), "candidate_identities": dict(task.candidate_identities),
                    "file_grant": sorted(task.file_grant), "quality_baselines": sorted(task.quality_baselines),
                    "assignments": dict(task.assignments), "upgrades": sorted(task.upgrades),
                    "dispatch_paused": task.dispatch_paused, "planning_required": task.planning_required}

    def restore(self, value: dict[str, Any]) -> None:
        plan = Plan.from_dict(value["plan"])
        with self._lock:
            if plan.task_id in self._tasks:
                raise RoutingError("task already exists")
            states = {key: "unknown" if state in {"running", "verifying"} else state for key, state in value["states"].items()}
            self._tasks[plan.task_id] = _Task(plan, Budget.restore(value["budget"]), frozenset(value["allowed_ids"]),
                                           value["external_allowed"] is True, False, value["cancelled"] is True,
                                           states, dict(value["results"]), dict(value["attempts"]), "restored-requires-confirmation",
                                           dict(value.get("reservation_accounts", {})),
                                           {key: tuple(identity) for key, identity in value.get("candidate_identities", {}).items()},
                                           frozenset(value.get("file_grant", (path for node in plan.nodes for path in node.allowed_files))),
                                           frozenset(value.get("quality_baselines", (node.baseline_id for node in plan.nodes))),
                                           dict(value.get("assignments", {})), set(value.get("upgrades", [])),
                                           set(value.get("unknown_attempts", [])) | set(value["budget"]["reservations"]),
                                           value.get("dispatch_paused") is True,
                                           validate_planning(value.get("planning"), plan),
                                           value.get("planning_required") is True)

    def wait(self, task_id: str, scope: Scope, timeout: float = 30) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            value = self.advance(task_id, scope)
            if value["status"] != "running":
                return value
            time.sleep(0.01)
        return self.status(task_id, scope)

    def _persist(self, task: _Task, event_type: str) -> None:
        if self._save:
            self._save(task.plan.task_id, self.snapshot(task.plan.task_id, task.plan.scope))
        if self._events:
            self._events({"type": event_type, "task_id": task.plan.task_id, "owner_id": task.plan.scope.owner_id,
                          "session_id": task.plan.scope.session_id, "revision": task.plan.revision})

    def close(self) -> None:
        with self._lock:
            self._closed = True
            for execution, _future in self._active.values():
                execution.cancelled.set()
        self._pool.shutdown(wait=True)
