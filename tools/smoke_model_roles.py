"""Run an isolated, synthetic Core plan, verified answer and persona delivery."""
import argparse
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "backend/src"), str(ROOT / "packages/quality-routing/src")]

from sumika_core.credentials import WindowsCredentialStore, credential_namespace_for_data_dir
from sumika_core.server import CoreApplication


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--credential-data-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    if args.data_dir.resolve() == args.credential_data_dir.resolve() or args.report.exists():
        raise ValueError("isolated runtime and new report required")
    os.environ.update(SUMIKA_AGENT_RUNTIME="none", SUMIKA_AGENT_AUTOSTART="0", SUMIKA_DSH_ENABLED="0")
    app = CoreApplication(args.data_dir, credential_store=WindowsCredentialStore(credential_namespace_for_data_dir(args.credential_data_dir)))
    report = {"scope": "real-core-leader-executor-review-persona", "checks": {}}
    params = {"assistant_id": "sumika", "session_id": "role-activation-smoke"}
    task_id = None
    try:
        app.model_policy.accounts.refresh(force=True)
        selection = app.quality.select_bindings("sumika")
        report.update(leader=selection["leader_candidate_id"], role=selection["role_candidate_id"])
        if not report["leader"] or not report["role"]:
            raise ValueError("expected bindings unavailable")
        task = app.quality.plan({**params, "goal": '仅根据材料“收件地址：杭州市西湖区”说出收件城市。一个步骤完成即可，用简短中文回答，可以加一句温暖的陪伴话。不要联网、工具或文件操作。',
            "allowed_candidate_ids": app.quality.settings("sumika")["candidate_pool"], "external_allowed": True, "planning_confirmed": True})
        task_id = task["task_id"]
        report["checks"]["plan"] = len(task["plan"]["nodes"]) <= 2
        if not report["checks"]["plan"]:
            raise ValueError("smoke plan exceeds bound")
        app.quality.rpc("quality.task.confirm", {**params, "task_id": task_id, "revision": task["revision"]})
        deadline = time.monotonic() + 150
        while time.monotonic() < deadline:
            task = app.quality.rpc("quality.task.get", {**params, "task_id": task_id})
            if task.get("final_message") or task["status"] in {"failed", "cancelled", "paused", "needs-attention"}:
                break
            time.sleep(0.25)
        report.update(status=task["status"], states=task.get("states"), workflow_error=task.get("workflow_error"))
        report["checks"]["verified_execution"] = task["status"] == "completed"
        results = list(task.get("results", {}).values())
        report["checks"]["correct_fact"] = bool(results) and all("杭州" in row["text"] for row in results)
        final = task.get("final_message") or {}
        report["checks"]["delivered"] = bool(final.get("content")) and "杭州" in final["content"]
        report["budget"] = task.get("budget")
        report["funding"] = app.model_policy.accounts.status()["funding"]
        print(json.dumps({"status": report["status"], "checks": report["checks"]}, ensure_ascii=False), flush=True)
    except Exception as error:
        report["failure_class"] = type(error).__name__
    finally:
        if task_id and not report["checks"].get("delivered"):
            app.quality.rpc("quality.task.cancel", {**params, "task_id": task_id})
        app.close()
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
