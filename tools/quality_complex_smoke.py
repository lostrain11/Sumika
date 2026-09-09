"""Isolated synthetic complex DAG smoke. Fixture mode is offline; live mode requires explicit opt-in.

Live usage: --live --data-dir ISOLATED_CORE --credential-data-dir APPROVED_VAULT
--report NEW_REPORT --budget 0.50 --max-calls 24. No quality evidence is created in live mode.
Optional --inject-validation-failures labels host-injected faults, not model failures.
Use --inject-validation-node facts --inject-validation-failures 2 to require an actual
non-leader repair/upgrade transition; the compatible default injection target is schedule.
Optional --revise-goal pauses after verified execution, revises the synthetic goal and reconfirms.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack
from dataclasses import replace
from decimal import Decimal
import json
import logging
import os
from pathlib import Path
import sys
import threading
import time
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "backend/src"), str(ROOT / "packages/quality-routing/src")]

from quality_routing import QualityEvidence, Scope, Verification
from sumika_core.agent.supervisor import RuntimeRouteDescriptor
from sumika_core.providers.guard import RequestNotSent
from sumika_core.quality import QualityRoutingService
from sumika_core.storage import Storage


GOAL = """Synthetic event-planning task, not a real event. Do not use tools, browse, write files or execute actions.
Material: setup starts at 09:00 and lasts 20 minutes. Validation follows setup and lasts 30 minutes.
Demo follows successful validation and lasts 20 minutes. A failed validation requires one 10-minute
repair before demo. Independent backup preparation lasts 15 minutes from 09:00 and must finish before demo.
The fee is 12.50 CNY. Provider quota is unknown. A previous external submission has unknown status.
Analyze dependencies, both earliest finish times, and safety boundaries; unknown submission must not be resent.
Use exactly four DAG nodes: facts (literal extraction of fee, quota and backup duration only, no dependencies), boundaries (literal safety extraction,
no dependencies), schedule (reasoning, depends on facts), final (synthesis, depends on schedule and boundaries).
facts and boundaries may use bounded-text when qualified. schedule and final require your reasoning baseline.
Use text capability, input_tokens=16000, output_tokens=4096 (bounded-text output_tokens=1024).
The final deliverable must contain one JSON object with keys normal_end, repaired_end, fee (decimal string),
quota ("unknown"), resubmit_unknown (false), executed (false), order (setup, validation, demo).
A short warm introduction outside that JSON is permitted; no additional facts or action claims.
"""
REVISED_GOAL = GOAL.replace("Demo follows successful validation and lasts 20 minutes.",
                            "Demo follows successful validation and lasts 30 minutes.")
INJECTION_NODES = ("facts", "boundaries", "schedule", "final")


class SmokeGuard:
    def __init__(self, allowed, *, budget="0.50", max_calls=24):
        self.allowed = frozenset(allowed)
        self.limit = Decimal(budget)
        if not self.limit.is_finite() or not 0 <= self.limit <= 2 or type(max_calls) is not int or not 1 <= max_calls <= 40:
            raise ValueError("budget must be 0..2 CNY and max_calls 1..40")
        self.max_calls = max_calls
        self.reserved = Decimal(0)
        self.calls = []
        self.stopped = False
        self.lock = threading.Lock()

    def wrap(self, invoke):
        def guarded(candidate, scope, prompt, cancelled, max_tokens):
            with self.lock:
                if self.stopped or candidate.candidate_id not in self.allowed or candidate.channel != "api":
                    raise RequestNotSent("complex-smoke-route-blocked")
                if cancelled.is_set():
                    raise RequestNotSent("complex-smoke-cancelled")
                input_bound = len(prompt.encode("utf-8")) + 1024
                forecast = candidate.quote(input_bound, max_tokens)
                cost = forecast.effective_cost_cny
                if (not forecast.available or cost is None or input_bound > 96000 or not 1 <= max_tokens <= 16000 or
                        len(self.calls) >= self.max_calls or self.reserved + cost > self.limit):
                    self.stopped = True
                    raise RequestNotSent("complex-smoke-budget-or-funding-blocked")
                self.reserved += cost
                record = {"candidate_id": candidate.candidate_id, "reserved_upper_cny": str(cost),
                          "input_bound": input_bound, "max_output_tokens": max_tokens, "status": "submitted"}
                self.calls.append(record)
            try:
                result = invoke(candidate, scope, prompt, cancelled, max_tokens)
            except RequestNotSent:
                with self.lock:
                    self.reserved -= cost
                    record.update(status="not-sent", reserved_upper_cny="0", released_upper_cny=str(cost),
                                  input_tokens=0, output_tokens=0, failure_code="request-not-sent")
                raise
            except Exception:
                with self.lock:
                    self.stopped = True
                    record["status"] = "submission-unknown"
                raise
            with self.lock:
                record.update(status=result.status, input_tokens=result.input_tokens, output_tokens=result.output_tokens,
                              requested_reasoning_effort=candidate.reasoning_effort,
                              applied_reasoning_effort=result.applied_reasoning_effort)
                if result.status == "unknown" or result.possibly_sent and result.status != "completed":
                    self.stopped = True
            return result
        return guarded

    def summary(self):
        return {"model_call_attempts": len(self.calls), "reserved_upper_cny": str(self.reserved),
                "known_not_sent_attempts": sum(record["status"] == "not-sent" for record in self.calls),
                "actual_billed_cny": None, "budget_limit_cny": str(self.limit), "calls": self.calls,
                "cost_evidence": "conservative-request-reservations-not-actual-billing"}


def expected(revised=False):
    return {"normal_end": "10:20" if revised else "10:10", "repaired_end": "10:30" if revised else "10:20",
            "fee": "12.50", "quota": "unknown", "resubmit_unknown": False, "executed": False,
            "order": ["setup", "validation", "demo"]}


def grade(text, revised=False):
    try:
        start = text.index("{")
        payload, consumed = json.JSONDecoder().raw_decode(text[start:])
        suffix = text[start + consumed:].strip()
        return payload == expected(revised) and suffix in {"", "```"}
    except (ValueError, TypeError):
        return False


def _upgrade_assertions(attempts, node_id, leader_id, upgraded_nodes):
    target = [attempt for attempt in attempts if attempt["node_id"] == node_id]
    first = target[0] if target else {}
    repaired = target[1] if len(target) > 1 else {}
    upgraded = target[2] if len(target) > 2 else {}
    same_candidate = bool(first and repaired and first["candidate_id"] == repaired["candidate_id"]
                          and first["revision"] == repaired["revision"])
    failed_pair = same_candidate and all(not attempt["effective_verification_passed"] for attempt in (first, repaired))
    changed = bool(upgraded and upgraded["candidate_id"] != first["candidate_id"]
                   and upgraded["revision"] == first["revision"])
    verified_upgrade = changed and any(attempt["candidate_id"] == upgraded["candidate_id"]
                                       and attempt["revision"] == first["revision"]
                                       and attempt["model_review_passed"] and attempt["effective_verification_passed"]
                                       and not attempt["host_injected_failure"] for attempt in target[2:])
    checks = {"upgrade_started_with_non_leader": bool(first and first["candidate_id"] != leader_id),
              "same_candidate_failed_twice": failed_pair,
              "upgrade_recorded": node_id in upgraded_nodes,
              "upgraded_candidate_changed": changed,
              "upgraded_execution_verified": verified_upgrade}
    evidence = {"node_id": node_id, "leader_candidate_id": leader_id,
                "initial_candidate_id": first.get("candidate_id"), "initial_revision": first.get("revision"),
                "upgraded_candidate_id": upgraded.get("candidate_id") if changed else None,
                "failure_sources": ["host-injected" if attempt["host_injected_failure"] else "model-review"
                                    for attempt in target[:2] if not attempt["effective_verification_passed"]]}
    return checks, evidence


def run_workflow(service, *, assistant_id, allowed, guard, live=False, inject_validation_failures=0,
                 inject_validation_node="schedule", revise_goal=False, timeout=300):
    if type(inject_validation_failures) is not int or not 0 <= inject_validation_failures <= 2:
        raise ValueError("injection must be 0, 1 or 2")
    if inject_validation_node not in INJECTION_NODES:
        raise ValueError("injection target must be a synthetic DAG node")
    params = {"assistant_id": assistant_id, "session_id": "complex-synthetic-" + str(time.time_ns())}
    scope = Scope(assistant_id, params["session_id"])
    checks = {}
    report = {"schema": "sumika-complex-smoke/v1", "mode": "live-models-synthetic-task" if live else "offline-scripted-fixture",
              "quality_claim": "this synthetic workflow only; no general task equivalence",
              "fault_source": "host-injected-after-successful-review" if inject_validation_failures else "none",
              "fault_interpretation": "host-injected failures are not evidence of real model capability failures",
              "injection_target_node": inject_validation_node,
              "requested_validation_failures": inject_validation_failures,
              "injected_validation_failures": 0, "checks": checks, "passed": False}
    task_id = None
    verified_attempts = []
    injection_identity = None
    original_verify = service.engine._verifier
    def verify(execution, outcome):
        nonlocal injection_identity
        check = original_verify(execution, outcome)
        identity = (execution.candidate.candidate_id, execution.revision)
        if execution.node.node_id == inject_validation_node and injection_identity is None:
            injection_identity = identity
        injected = (check.passed and execution.node.node_id == inject_validation_node and identity == injection_identity
                    and report["injected_validation_failures"] < inject_validation_failures)
        verified_attempts.append({"node_id": execution.node.node_id, "candidate_id": execution.candidate.candidate_id,
                                  "revision": execution.revision, "model_review_passed": check.passed,
                                  "host_injected_failure": injected, "effective_verification_passed": check.passed and not injected})
        if injected:
            report["injected_validation_failures"] += 1
            return Verification(False, ("synthetic-host-injection",), "synthetic-host-injected-validation-fault-not-a-model-failure")
        if check.passed and revise_goal and execution.revision == 1 and execution.node.node_id == "final":
            service.engine.pause(execution.task_id, execution.scope)
        return check

    def wait_stopped():
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            value = service.status(task_id, scope)
            if task_id not in service._running:
                return value
            time.sleep(0.02)
        raise TimeoutError("complex-smoke-timeout")

    with patch.object(service, "_invoke_unlocked", side_effect=guard.wrap(service._invoke_unlocked)), patch.object(service.engine, "_verifier", side_effect=verify):
        try:
            task = service.plan({**params, "goal": GOAL, "allowed_candidate_ids": list(allowed),
                                 "external_allowed": True, "planning_confirmed": True})
            task_id = task["task_id"]
            task_params = {**params, "task_id": task_id}
            graph = {row["node_id"]: set(row["dependencies"]) for row in task["plan"]["nodes"]}
            checks["four_node_dag"] = graph == {"facts": set(), "boundaries": set(), "schedule": {"facts"}, "final": {"schedule", "boundaries"}}
            checks["awaits_confirmation"] = task["status"] == "awaiting-confirmation"
            if not all(checks.values()):
                raise ValueError("synthetic-plan-contract-not-met")
            service.rpc("quality.task.confirm", {**task_params, "revision": task["revision"]})
            task = wait_stopped()
            if inject_validation_failures == 2:
                initial_snapshot = service.engine.snapshot(task_id, scope)
                upgrade_checks, upgrade_evidence = _upgrade_assertions(
                    verified_attempts, inject_validation_node, task["selection"]["leader_candidate_id"], initial_snapshot["upgrades"])
                checks.update(upgrade_checks)
                report["upgrade_evidence"] = upgrade_evidence
            if revise_goal:
                if task["status"] != "paused" or set(task["states"].values()) != {"completed"}:
                    raise ValueError("expected-host-pause-before-delivery")
                facts_attempt = task["results"]["facts"]["attempt_id"]
                task = service.rpc("quality.task.revise", {**task_params, "goal": REVISED_GOAL,
                                                          "reason": "Synthetic user change: demo duration increases by ten minutes"})
                checks["semantic_change_reconfirmed"] = task["status"] == "awaiting-confirmation"
                checks["unaffected_result_reused"] = task["results"].get("facts", {}).get("attempt_id") == facts_attempt
                if not all(checks.values()):
                    raise ValueError("synthetic-revision-contract-not-met")
                wait_stopped()
                service.rpc("quality.task.confirm", {**task_params, "revision": task["revision"]})
                task = wait_stopped()
            final = (task.get("final_message") or {}).get("content", "")
            checks["workflow_completed"] = task["status"] == "completed" and bool(final)
            checks["complex_constraints"] = grade(task["results"].get("final", {}).get("text", ""), revise_goal)
            checks["role_facts_preserved"] = grade(final, revise_goal)
            checks["verified_terminal_retained"] = bool(final) and final.endswith(task["results"].get("final", {}).get("text", ""))
            checks["fault_injection_exercised"] = (report["injected_validation_failures"] == inject_validation_failures or
                inject_validation_failures == 2 and checks.get("same_candidate_failed_twice") is True and
                checks.get("upgraded_execution_verified") is True)
            snapshot = service.engine.snapshot(task_id, scope)
            report.update(status=task["status"], revision=task["revision"], states=task["states"],
                          attempts=snapshot["attempts"], upgraded_nodes=snapshot["upgrades"],
                          workflow_error_present=bool(task.get("workflow_error")))
            report["passed"] = all(checks.values())
        except Exception as error:
            report["failure_class"] = type(error).__name__
        finally:
            if task_id and not report["passed"]:
                current = service.engine.snapshot(task_id, scope)
                report.update(status=current["status"], revision=current["revision"], states=current["states"],
                              attempts=current["attempts"], upgraded_nodes=current["upgrades"],
                              unknown_attempts_present=bool(current.get("unknown_attempts")))
                service.rpc("quality.task.cancel", {**params, "task_id": task_id})
    report["verification_attempts"] = verified_attempts
    report.update(guard.summary())
    return report


class FixtureProvider:
    last_usage = {"input_tokens": 100, "output_tokens": 40}
    last_finish_reason = "stop"

    def stream(self, request):
        prompt = request.messages[0].content
        revised = "Demo follows successful validation and lasts 30 minutes." in prompt
        if "Return only a JSON object with nodes" in prompt:
            revision = " revised-duration" if revised else ""
            rows = [("facts", "Extract literal material", []), ("boundaries", "Extract safety boundaries", []),
                    ("schedule", "Analyze schedule" + revision, ["facts"]), ("final", "Synthesize result" + revision, ["schedule", "boundaries"])]
            yield json.dumps({"nodes": [{"node_id": name, "goal": goal, "dependencies": dependencies,
                                        "task_type": "synthetic-extraction-v1" if name in {"facts", "boundaries"} else "synthetic-complex-v1",
                                        "acceptance": ["Preserve schedule, 12.50 fee, unknown quota and no replay"],
                                        "input_tokens": 16000, "output_tokens": 1024 if name in {"facts", "boundaries"} else 4096}
                                       for name, goal, dependencies in rows]})
        elif "Verify the task result" in prompt:
            yield '{"passed":true,"reason":"scripted-fixture-check-not-model-evidence"}'
        elif "short in-character introduction" in prompt:
            yield "Here is the carefully checked plan."
        elif "Extract literal material" in prompt:
            yield '{"fee":"12.50","quota":"unknown","backup_minutes":15}'
        elif "Extract safety boundaries" in prompt:
            yield '{"resubmit_unknown":false,"executed":false}'
        else:
            yield json.dumps(expected(revised))


def fixture_service():
    storage = Storage(":memory:")
    storage.create_character("synthetic", "Synthetic", {"persona": {}})
    route = RuntimeRouteDescriptor("leader", label="Fixture leader", kind="provider", status="ready", routable=True,
                                   capabilities=("text",), executor="fixture", provider_profile_id="leader-profile",
                                   auth_state="authorized", health_state="healthy", cost_class="local", quota_state="not-applicable",
                                   processing_location="local", metadata={"model_entry": {"model_id": "scripted-fixture"}})
    cheap = replace(route, route_id="cheap", provider_profile_id="cheap-profile")
    app = SimpleNamespace(storage=storage, logger=SimpleNamespace(warning=lambda *args: None),
                          events=SimpleNamespace(publish=lambda event: None),
                          provider_profiles=SimpleNamespace(runtime=lambda *args, **kwargs: FixtureProvider(),
                                                            get=lambda *args: {"status": "available"}, mark_used=lambda *args: None),
                          route_supervisor=SimpleNamespace(registered_routes=lambda: (route, cheap)),
                          _refresh_route_supervisor_catalog=lambda **kwargs: None)
    service = QualityRoutingService(app)
    service.register_quality_evidence("cheap", (QualityEvidence("synthetic-extraction-v1", "leader", time.time() + 3600, "scripted-fixture-only"),))
    service.update_settings({"assistant_id": "synthetic", "leader_candidate_id": "leader", "role_candidate_id": "cheap"})
    return service


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--credential-data-dir", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--budget", default="0.50")
    parser.add_argument("--max-calls", type=int, default=24)
    parser.add_argument("--inject-validation-failures", type=int, choices=(0, 1, 2), default=0)
    parser.add_argument("--inject-validation-node", choices=INJECTION_NODES, default="schedule")
    parser.add_argument("--revise-goal", action="store_true")
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--leader-evaluation", type=Path)
    parser.add_argument("--executor-evaluation", type=Path)
    args = parser.parse_args(argv)
    if not 30 <= args.timeout <= 900:
        parser.error("timeout must be 30..900 seconds")
    if args.report.exists():
        parser.error("a new report path is required")
    if args.live and (not args.data_dir or not args.credential_data_dir or args.data_dir.resolve() == args.credential_data_dir.resolve()):
        parser.error("live mode requires a prepared isolated runtime distinct from the approved credential data directory")
    logging.disable(logging.CRITICAL)
    SmokeGuard([], budget=args.budget, max_calls=args.max_calls)
    with ExitStack() as stack:
        if args.live:
            from sumika_core.credentials import WindowsCredentialStore, credential_namespace_for_data_dir
            from sumika_core.server import CoreApplication
            environment = {name: value for name, value in os.environ.items() if not name.startswith("SUMIKA_")}
            environment.update(SUMIKA_AGENT_RUNTIME="none", SUMIKA_AGENT_AUTOSTART="0", SUMIKA_DSH_ENABLED="0", SUMIKA_ZCODE_AUTODISCOVER="0")
            stack.enter_context(patch.dict(os.environ, environment, clear=True))
            app = CoreApplication(args.data_dir, credential_store=WindowsCredentialStore(credential_namespace_for_data_dir(args.credential_data_dir)))
            stack.callback(app.close)
            service, assistant = app.quality, "sumika"
            app.model_policy.accounts.refresh(force=True)
            app.model_policy.free_models.refresh()
            from tools.quality_smoke_leader import use_evaluated_leader, use_evaluated_executor
            use_evaluated_leader(service, getattr(args, 'leader_evaluation', None), stack)
            use_evaluated_executor(service, args.executor_evaluation)
            configured = service.settings(assistant)["candidate_pool"]
            allowed = [candidate["candidate_id"] for candidate in service.catalog(assistant)["candidates"]
                       if candidate["candidate_id"] in configured and candidate["channel"] == "api"
                       and candidate["available"] and candidate["authorized"]]
        else:
            service, assistant, allowed = fixture_service(), "synthetic", ["leader", "cheap"]
            stack.callback(service.app.storage.close)
            stack.callback(service.close)
        guard = SmokeGuard(allowed, budget=args.budget, max_calls=args.max_calls)
        report = run_workflow(service, assistant_id=assistant, allowed=allowed, guard=guard, live=args.live,
                              inject_validation_failures=args.inject_validation_failures,
                              inject_validation_node=args.inject_validation_node, revise_goal=args.revise_goal, timeout=args.timeout)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    with args.report.open("x", encoding="utf-8") as output:
        output.write(json.dumps(report, ensure_ascii=True, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
