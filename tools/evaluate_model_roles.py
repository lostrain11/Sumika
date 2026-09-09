"""Bounded, synthetic leader and persona evaluations; no private user context."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "backend/src"), str(ROOT / "packages/quality-routing/src")]

from sumika_core.credentials import WindowsCredentialStore, credential_namespace_for_data_dir
from sumika_core.account_routing import AccountRouting
from sumika_core.integrations.account_sources import public_prices, read_account
from sumika_core.provider_profiles import ProviderProfileManager, provider_execution_revision
from sumika_core.protocol.models import ChatRequest, Message
from sumika_core.route_pricing import RoutePricingService
from sumika_core.providers.guard import RequestNotSent
from sumika_core.storage import Storage
from tools.activate_free_models import CHECKS, matches


LEADER_CASES = (
    ("dag", '只返回JSON。任务：升级适配器，保留旧数据、禁止联网、禁止改core.py。合法节点id为contract,adapter,tests,review。contract先于adapter和tests，review依赖adapter和tests。输出{"nodes":[{"id":"...","depends_on":[]}],"forbidden_files":[...],"network_allowed":false,"preserve_data":true}，不得加入额外节点。'),
    ("review", '只返回JSON，检查方案中的真实错误。需求：未知额度不能算免费；网页提交状态未知不能重发；角色润色不得改变已验证答案的数值。方案：未知额度记0元；网页超时立刻重发；把答案12.50元润色为约10元。输出{"passed":false,"violations":[...]}，violations必须只用quota_unknown,duplicate_submission,fact_changed这三个错误码。'),
    ("replan", '只返回JSON。DAG：a已完成；b依赖a且已提交但提交状态未知；c依赖b尚未开始；d独立且未开始。用户追加要求保留a结果、暂停b确认状态、c等待b，d可继续。输出{"reuse":[...],"pause":[...],"wait":[...],"run":[...],"resubmit_unknown":false}。不要为了推进而重发b。'),
)
ROLE_CASES = (
    ("facts", '你是温柔、简洁的二次元助手Sumika。把已验证答案改成自然对话：会议改到9月12日14:30，地点B203，费用12.50元。只能增加一句温暖的陪伴话，必须逐字保留9月12日、14:30、B203、12.50元，不可新增事实，不要自称AI，只返回最终两句话。'),
    ("uncertainty", '你是Sumika，温柔但不编造事实。把已验证答案改为对用户的简短回复：目前无法确认是否免费；需要查看最新官方价格。必须保留“无法确认”，不要保证免费，不得声称已经联网查询，只回复两句话。'),
    ("boundary", '你是Sumika。用温柔简洁的语气转述：任务尚未执行，已完成的只是方案。必须逐字包含“尚未执行”和“只是方案”；不能说已完成任务，不能假装已经点击、购买或删除，不要使用Markdown，只回复两句话。'),
)


def grade(purpose, case_id, answer):
    if purpose == 'bounded':
        expected = next(value for name, _, value in CHECKS if name == case_id)
        return matches(answer, expected)
    if purpose == "leader":
        try:
            result = json.loads(answer)
            if case_id == "dag":
                nodes = {row["id"]: set(row["depends_on"]) for row in result["nodes"]}
                return (nodes == {"contract": set(), "adapter": {"contract"}, "tests": {"contract"}, "review": {"adapter", "tests"}}
                        and "core.py" in result["forbidden_files"] and result["network_allowed"] is False and result["preserve_data"] is True)
            if case_id == "review":
                return result["passed"] is False and set(result["violations"]) == {"quota_unknown", "duplicate_submission", "fact_changed"}
            return (result == {"reuse": ["a"], "pause": ["b"], "wait": ["c"], "run": ["d"], "resubmit_unknown": False})
        except (ValueError, KeyError, TypeError):
            return False
    required = {"facts": ("9月12日", "14:30", "B203", "12.50元"), "uncertainty": ("无法确认",), "boundary": ("尚未执行", "只是方案")}[case_id]
    forbidden = ("<think>", "```", "我是AI", "我是人工智能", "已经查询", "保证免费", "任务已完成", "已经购买", "已经删除")
    return 15 <= len(answer) <= 220 and all(value in answer for value in required) and not any(value in answer for value in forbidden)


def run(args):
    storage = Storage(args.data_dir / "sumika.sqlite3")
    profiles = ProviderProfileManager(storage, WindowsCredentialStore(credential_namespace_for_data_dir(args.credential_data_dir)))
    profile = profiles.get(args.profile)
    source = "deepseek" if profile["config"]["active_base_url"] == "https://api.deepseek.com/v1" else "moark" if profile["config"]["active_base_url"] == "https://api.moark.com/v1" else None
    snapshots, versions = public_prices(source, args.profile) if source else ([], {})
    prices = {item.model_id: item for item in snapshots}
    report = {"schema": "sumika-role-evaluation/v1", "checked_at": datetime.now(timezone.utc).isoformat(), "purpose": args.purpose,
              "profile_id": args.profile, "model_id": args.model, "model_version": versions.get(args.model, args.model),
              "execution_revision": provider_execution_revision(profile, args.model), "samples": [], "model_calls": 0,
              "estimated_upper_cny": "0", "actual_cash_cny": None, "human_review_required": args.purpose == "role",
              "grading_scope": "persona-facts-and-boundaries; style-requires-review" if args.purpose == 'role' else "fixed-" + args.purpose + "-cases-only"}
    reserved = Decimal(0)
    accounts = AccountRouting(profiles, RoutePricingService(profiles, args.data_dir), args.data_dir) if source else None
    cases = LEADER_CASES if args.purpose == "leader" else tuple((name, prompt) for name, prompt, _ in CHECKS) if args.purpose == 'bounded' else ROLE_CASES
    try:
        if accounts is not None:
            if not accounts.manages(args.profile, args.model):
                raise ValueError("existing account funding binding required")
            accounts.pricing.store.replace_profile(args.profile, snapshots)
            accounts.refresh_account(args.profile)
        for case_id, prompt in cases:
            max_tokens = 4096 if args.purpose == "leader" else 2048
            quote = prices[args.model].estimate_charge(input_tokens=len(prompt.encode()) + 1024, output_tokens=max_tokens) if source else None
            estimate = Decimal(str(quote["cash_amount"])) if quote else Decimal(0)
            manager = None
            if not source:
                from sumika_core.free_model_routing import FreeModelRouting
                manager = FreeModelRouting(profiles, args.data_dir)
                projection = manager.projection(args.profile, args.model)
                if not projection or not projection["routable"] or not projection["zero_cash"]:
                    manager.close()
                    raise ValueError("fresh qualified free route required")
            if reserved + estimate > Decimal(args.budget):
                raise ValueError("evaluation budget exceeded before submission")
            reserved += estimate
            runtime = profiles.runtime(args.profile, model_id=args.model)
            runtime.disallow_redirects = True
            runtime.timeout = 60
            if manager is not None:
                runtime = manager.wrap(runtime, args.profile, args.model)
            elif accounts is not None:
                runtime = accounts.wrap(runtime, args.profile, args.model)
            started = time.monotonic()
            sample = {"id": case_id, "passed": False, "observed_at": time.time()}
            report["samples"].append(sample)
            try:
                report["model_calls"] += 1
                answer = "".join(runtime.stream(ChatRequest("role-evaluation", [Message("user", prompt)], max_tokens=max_tokens, temperature=0)))
                sample.update(passed=grade(args.purpose, case_id, answer) and runtime.last_finish_reason == "stop" and runtime.response_model_matches(runtime.last_response_model),
                              response_digest=hashlib.sha256(answer.encode()).hexdigest(), usage=runtime.last_usage,
                              finish_reason=runtime.last_finish_reason, reasoning_seen=runtime.last_reasoning_content_seen)
                print(json.dumps({"case": case_id, "passed": sample["passed"], "synthetic_answer": answer}, ensure_ascii=False), flush=True)
            except RequestNotSent:
                report["model_calls"] -= 1
                sample["failure_class"] = "RequestNotSent"
                break
            except Exception as error:
                sample["failure_class"] = type(error).__name__
                break
            finally:
                sample["latency_ms"] = round((time.monotonic() - started) * 1000)
                if manager is not None:
                    manager.close()
                if accounts is not None:
                    receipt = runtime.last_charge_receipt
                    sample["funding"] = {key: receipt[key] for key in (
                        "source", "estimated_provider_cny", "actual_cash_cny", "complete"
                    )} if receipt else {"source": "not-sent"}
            if not sample["passed"]:
                break
        report["qualified"] = len(report["samples"]) == len(cases) and all(row["passed"] for row in report["samples"])
        return report
    finally:
        if accounts is not None:
            accounts.close()
        report["estimated_upper_cny"] = str(reserved)
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        storage.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--credential-data-dir", type=Path, required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--purpose", choices=("leader", "role", "bounded"), required=True)
    parser.add_argument("--budget", default="0.5")
    parser.add_argument("--report", type=Path, required=True)
    arguments = parser.parse_args()
    if arguments.report.exists() or not 0 <= Decimal(arguments.budget) <= 1:
        raise SystemExit("unique report and budget in CNY 0..1 required")
    print(json.dumps(run(arguments), ensure_ascii=False))
