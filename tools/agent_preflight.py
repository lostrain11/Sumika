"""Read-only daily readiness check for the Sumika Agent workflow.

The command intentionally consumes only public Core projections. It never
loads provider credentials, reads chat history, or prints raw API responses.
Exit codes: 0 means ready, 2 means user action is needed, and 3 means the
Core/Agent endpoint is unavailable or the check itself failed.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen


SCHEMA_VERSION = "sumika.agent-preflight.v1"
DEFAULT_CORE_URL = "http://127.0.0.1:8771"


class PreflightError(RuntimeError):
    """A bounded, non-sensitive request failure."""


def _safe_base_url(value: str) -> str:
    parsed = urlsplit(str(value or "").strip().rstrip("/"))
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("core URL must be an http(s) URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("core URL must not contain credentials, query, or fragment")
    host = parsed.hostname
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    netloc = host
    if parsed.port is not None:
        netloc += f":{parsed.port}"
    return urlunsplit((parsed.scheme, netloc, parsed.path.rstrip("/"), "", ""))


def _request_json(base_url: str, path: str, *, method: str = "GET", payload: dict[str, Any] | None = None, timeout: float = 3.0) -> Any:
    body = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = Request(f"{base_url}{path}", data=body, headers=headers, method=method)
    try:
        with urlopen(request, timeout=timeout) as response:
            if response.status != HTTPStatus.OK:
                raise PreflightError(f"HTTP {response.status}")
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        raise PreflightError(f"HTTP {error.code}") from None
    except (URLError, TimeoutError, OSError, UnicodeError, json.JSONDecodeError) as error:
        raise PreflightError(type(error).__name__) from None


def _check(identifier: str, status: str, detail: str, **extra: Any) -> dict[str, Any]:
    result = {"id": identifier, "status": status, "detail": detail}
    result.update(extra)
    return result


def _agent_provider_check(base_url: str, timeout: float) -> dict[str, Any]:
    try:
        value = _request_json(base_url, "/api/agent/provider", timeout=timeout)
    except PreflightError as error:
        return _check("provider", "unavailable", "无法读取 Agent Provider 状态", error=str(error))
    if not isinstance(value, dict):
        return _check("provider", "unavailable", "Agent Provider 返回格式无效")
    state = str(value.get("state") or "unknown")
    ready = value.get("ready") is True
    if ready:
        return _check(
            "provider",
            "ready",
            "Provider 已就绪",
            state=state,
            profile_id=value.get("profile_id"),
            model=value.get("model"),
        )
    if state in {"unconfigured", "not-synced", "restart-required", "unavailable"}:
        return _check(
            "provider",
            "needs-action" if state != "unavailable" else "unavailable",
            str(value.get("reason") or "请在模块页配置并测试 Provider"),
            state=state,
            profile_id=value.get("profile_id"),
            model=value.get("model"),
        )
    return _check("provider", "needs-action", "Provider 尚未确认可用", state=state)


def _workspace_check(base_url: str, timeout: float) -> dict[str, Any]:
    request = {"jsonrpc": "2.0", "id": "sumika-preflight-workspaces", "method": "agent.workspaces", "params": {}}
    try:
        value = _request_json(base_url, "/rpc", method="POST", payload=request, timeout=timeout)
    except PreflightError as error:
        return _check("workspace", "unavailable", "无法读取 Agent Workspace 列表", error=str(error))
    result = value.get("result") if isinstance(value, dict) else None
    workspaces = result.get("workspaces") if isinstance(result, dict) else None
    if not isinstance(workspaces, list):
        return _check("workspace", "unavailable", "Workspace 返回格式无效")
    status = "ready" if workspaces else "needs-action"
    detail = "已有可用 Git Workspace" if workspaces else "请在 Agent 页登记一个 Git Workspace"
    return _check("workspace", status, detail, registered=len(workspaces))


def run_preflight(base_url: str, *, timeout: float = 3.0) -> dict[str, Any]:
    checked_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    checks: list[dict[str, Any]] = []
    try:
        core = _request_json(base_url, "/api/health", timeout=timeout)
    except PreflightError as error:
        checks.append(_check("core", "unavailable", "Sumika Core 不可达", error=str(error)))
        return {
            "schema_version": SCHEMA_VERSION,
            "checked_at": checked_at,
            "core_url": base_url,
            "overall": "unavailable",
            "checks": checks,
            "next_actions": ["启动 Sumika Core 后重新运行此检查"],
        }
    if not isinstance(core, dict) or core.get("ok") is not True:
        checks.append(_check("core", "unavailable", "Sumika Core 未通过健康检查"))
        return {
            "schema_version": SCHEMA_VERSION,
            "checked_at": checked_at,
            "core_url": base_url,
            "overall": "unavailable",
            "checks": checks,
            "next_actions": ["检查 Core 日志并重新启动 Sumika"],
        }
    checks.append(_check("core", "ready", "Sumika Core 已连接", version=core.get("version")))

    try:
        agent = _request_json(base_url, "/api/agent/status", timeout=timeout)
    except PreflightError as error:
        checks.append(_check("agent-runtime", "unavailable", "无法读取 Agent Runtime 状态", error=str(error)))
        return _finish(base_url, checked_at, checks)
    if not isinstance(agent, dict):
        checks.append(_check("agent-runtime", "unavailable", "Agent Runtime 返回格式无效"))
        return _finish(base_url, checked_at, checks)
    agent_ready = agent.get("ready") is True
    checks.append(
        _check(
            "agent-runtime",
            "ready" if agent_ready else "unavailable",
            "Agent Runtime 已连接" if agent_ready else str(agent.get("reason") or "Agent Runtime 未连接"),
            runtime_id=agent.get("runtime_id"),
            version=agent.get("version"),
            state=agent.get("state"),
        )
    )
    if not agent_ready:
        return _finish(base_url, checked_at, checks)

    checks.append(_agent_provider_check(base_url, timeout))
    checks.append(_workspace_check(base_url, timeout))
    try:
        report = _request_json(base_url, "/api/agent/diagnostics", timeout=timeout)
    except PreflightError as error:
        checks.append(_check("capabilities", "unavailable", "无法读取 Agent 能力探针", error=str(error)))
    else:
        summary = report.get("summary") if isinstance(report, dict) else {}
        summary = summary if isinstance(summary, dict) else {}
        available = int(summary.get("available", 0) or 0)
        unavailable = sum(int(value or 0) for key, value in summary.items() if key in {"unavailable", "rejected"})
        checks.append(
            _check(
                "capabilities",
                "ready" if unavailable == 0 else "partial",
                "只读能力探针完成",
                available=available,
                unavailable=unavailable,
                mcp_status=(report.get("mcp") or {}).get("status") if isinstance(report, dict) else None,
            )
        )
    return _finish(base_url, checked_at, checks)


def _finish(base_url: str, checked_at: str, checks: list[dict[str, Any]]) -> dict[str, Any]:
    statuses = {str(item.get("status")) for item in checks}
    if "unavailable" in statuses:
        overall = "unavailable"
    elif "needs-action" in statuses or "partial" in statuses:
        overall = "needs-action"
    else:
        overall = "ready"
    actions: list[str] = []
    if any(item["id"] == "agent-runtime" and item["status"] != "ready" for item in checks):
        actions.append("启动或连接固定版本 DSH Runtime")
    if any(item["id"] == "provider" and item["status"] != "ready" for item in checks):
        actions.append("在模块页配置、测试并启用一个真实 Provider")
    if any(item["id"] == "workspace" and item["status"] != "ready" for item in checks):
        actions.append("在 Agent 页登记一个 Git Workspace")
    return {
        "schema_version": SCHEMA_VERSION,
        "checked_at": checked_at,
        "core_url": base_url,
        "overall": overall,
        "checks": checks,
        "next_actions": actions,
    }


def _print_human(report: dict[str, Any]) -> None:
    print(f"Sumika Agent preflight: {report['overall']}")
    for item in report.get("checks", []):
        suffix = f" ({item['state']})" if item.get("state") else ""
        print(f"- {item['id']}: {item['status']}{suffix} - {item['detail']}")
    for action in report.get("next_actions", []):
        print(f"next: {action}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check Sumika Agent daily readiness without reading secrets")
    parser.add_argument("--core-url", default=DEFAULT_CORE_URL, help="Sumika desktop Core URL")
    parser.add_argument("--timeout", type=float, default=3.0, help="per-request timeout in seconds")
    parser.add_argument("--json", action="store_true", help="print the bounded JSON report")
    args = parser.parse_args(argv)
    try:
        base_url = _safe_base_url(args.core_url)
        if not 0.1 <= args.timeout <= 30:
            raise ValueError("timeout must be between 0.1 and 30 seconds")
        report = run_preflight(base_url, timeout=args.timeout)
    except (ValueError, PreflightError) as error:
        print(f"preflight failed: {error}", file=sys.stderr)
        return 3
    if args.json:
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    else:
        _print_human(report)
    return {"ready": 0, "needs-action": 2, "unavailable": 3}.get(str(report.get("overall")), 3)


if __name__ == "__main__":
    raise SystemExit(main())
