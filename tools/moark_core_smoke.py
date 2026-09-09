"""Explicit isolated Moark smoke using saved credentials and the real Core path."""
import argparse
import json
import os
from pathlib import Path
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "backend/src"), str(ROOT / "packages/quality-routing/src")]

from sumika_core.credentials import WindowsCredentialStore, credential_namespace_for_data_dir
from sumika_core.server import CoreApplication
from quality_routing import Scope


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--credential-data-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    if args.data_dir.resolve() == args.credential_data_dir.resolve() or args.report.exists():
        raise ValueError("isolated data directory and new report required")
    os.environ.update(SUMIKA_AGENT_RUNTIME="none", SUMIKA_AGENT_AUTOSTART="0", SUMIKA_MODEL_PICKER_URL="")
    app = CoreApplication(args.data_dir, credential_store=WindowsCredentialStore(credential_namespace_for_data_dir(args.credential_data_dir.resolve())))
    report = {"scope": "isolated Core -> ModelPolicy -> QualityRuntime -> guarded HTTP", "model_calls": 0}
    try:
        app.modules.update("llm", enabled=True, implementation_id="openai-compatible", config={"profile_id": "moark-free-candidates"})
        decision = app.model_policy.decide({"task_kind": "extraction", "difficulty": "basic", "task_text": "提取收件城市",
                                            "budget_policy": "free-only", "confirmation_mode": "automatic"})["decision"]
        selected = decision.get("selected_entry") or {}
        report.update(decision=decision["status"], selected_model=selected.get("model_id"),
                      estimated_cash_max=decision.get("cost_estimate", {}).get("cash_max"))
        app.quality.catalog("sumika")
        candidates = [candidate for candidate in app.quality.engine.candidates()
                      if candidate.model_id == "Qwen3-8B" and candidate.reasoning_effort is None]
        if decision["status"] != "selected" or selected.get("model_id") != "Qwen3-8B" or len(candidates) != 1:
            raise ValueError("qualified Moark route not selected")
        candidate = candidates[0]
        scope = Scope("sumika", "moark-smoke")
        app.quality._preflight(candidate, scope)
        started = time.monotonic()
        report["model_calls"] = 1
        result = app.quality._invoke(candidate, scope, "仅根据材料提取收件城市，只输出城市名，不要解释。材料：包裹收件地址为杭州市西湖区文二路。",
                                     threading.Event(), 2048)
        if result.status == "failed" and result.input_tokens == 0 and result.output_tokens == 0:
            report["model_calls"] = 0
        report.update(status=result.status, answer_contract_passed=result.text.strip() in {"杭州", "杭州市"},
                      input_tokens=result.input_tokens, output_tokens=result.output_tokens,
                      latency_ms=round((time.monotonic() - started) * 1000))
    except Exception as error:
        report["failure_class"] = type(error).__name__
    finally:
        app.close()
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=True))


if __name__ == "__main__":
    main()
