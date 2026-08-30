"""Run a bounded, read-only preflight for selectable model backends.

The command checks only public health/model-directory endpoints.  It never
sends a chat completion, reads a credential store, inspects ZCode private
files, or prints an HTTP response body.  ZCode is checked only when the
caller explicitly opts in with ``--zcode``; autodiscovery remains opt-in too.

Exit codes:
  0  every requested backend is ready
  2  at least one backend needs configuration or has an unknown quota
  3  a requested backend is unavailable or the command was invalid
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if os.path.join(ROOT, "backend", "src") not in sys.path:
    sys.path.insert(0, os.path.join(ROOT, "backend", "src"))

from sumika_core.agent.adapters.zcode.config import config_from_env  # noqa: E402
from sumika_core.agent.adapters.zcode.runtime import ZCodeAgentRuntime  # noqa: E402


SCHEMA_VERSION = "sumika.model-preflight/v1"
DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434"
_MAX_MODELS = 128


class ModelPreflightError(RuntimeError):
    """A bounded, non-sensitive preflight failure."""


def _safe_base_url(value: str) -> str:
    parsed = urlsplit(str(value or "").strip().rstrip("/"))
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("endpoint must be an http(s) URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("endpoint must not contain credentials, query, or fragment")
    host = parsed.hostname
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    netloc = host
    if parsed.port is not None:
        netloc += f":{parsed.port}"
    return urlunsplit((parsed.scheme, netloc, parsed.path.rstrip("/"), "", ""))


def _request_json(url: str, *, timeout: float) -> Any:
    request = Request(url, headers={"Accept": "application/json"}, method="GET")
    try:
        with urlopen(request, timeout=timeout) as response:
            if response.status != HTTPStatus.OK:
                raise ModelPreflightError(f"HTTP {response.status}")
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        raise ModelPreflightError(f"HTTP {error.code}") from None
    except (URLError, TimeoutError, OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ModelPreflightError(type(error).__name__) from None


def _check(identifier: str, status: str, detail: str, **extra: Any) -> dict[str, Any]:
    result = {"id": identifier, "status": status, "detail": detail}
    result.update(extra)
    return result


def _model_ids(payload: Any) -> list[str] | None:
    if not isinstance(payload, Mapping) or not isinstance(payload.get("data"), list):
        return None
    result: list[str] = []
    for item in payload["data"][:_MAX_MODELS]:
        if not isinstance(item, Mapping):
            continue
        model_id = item.get("id")
        if not isinstance(model_id, str):
            continue
        model_id = model_id.strip()
        if model_id and len(model_id) <= 240 and "\n" not in model_id and model_id not in result:
            result.append(model_id)
    return result


def check_ollama(base_url: str, *, expected_model: str | None = None, timeout: float = 3.0) -> dict[str, Any]:
    """Check one Ollama OpenAI-compatible ``/v1/models`` endpoint."""

    identifier = f"ollama:{base_url}"
    try:
        payload = _request_json(f"{base_url}/v1/models", timeout=timeout)
    except ModelPreflightError as error:
        return _check(identifier, "unavailable", "Ollama /v1/models 不可达", error=str(error))
    models = _model_ids(payload)
    if models is None:
        return _check(identifier, "unavailable", "Ollama 模型目录格式无效")
    expected = str(expected_model or "").strip()
    if expected and expected not in models:
        return _check(
            identifier,
            "needs-action",
            "Ollama 已连接，但目标模型不在目录中",
            models=models,
            expected_model=expected,
        )
    if not models:
        return _check(identifier, "needs-action", "Ollama 已连接但没有可用模型", models=[])
    return _check(
        identifier,
        "ready",
        "Ollama 模型目录可用；未发送聊天请求",
        models=models,
        expected_model=expected or None,
    )


def _safe_zcode_models(value: Any) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    groups = value.get("groups", []) if isinstance(value, Mapping) else []
    if not isinstance(groups, list):
        return result
    for group in groups[:32]:
        if not isinstance(group, Mapping):
            continue
        provider = str(group.get("id") or "").strip()[:160]
        models = group.get("models", [])
        if not provider or not isinstance(models, list):
            continue
        for model in models[:_MAX_MODELS]:
            if not isinstance(model, Mapping):
                continue
            model_id = str(model.get("id") or "").strip()[:240]
            if model_id:
                result.append({"provider": provider, "id": model_id})
            if len(result) >= _MAX_MODELS:
                return result
    return result


def check_zcode(*, environment: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Check the public ZCode app-server without creating a Session."""

    values = dict(environment or os.environ)
    # A separate temporary data directory prevents this read-only probe from
    # creating or reusing a Sumika/ZCode profile in the project or user data.
    with tempfile.TemporaryDirectory(prefix="sumika-model-preflight-") as directory:
        try:
            config = config_from_env(directory, values)
        except (TypeError, ValueError) as error:
            return _check("zcode", "unavailable", "ZCode 配置无效", error_type=type(error).__name__)
        if not config.enabled or not config.executable:
            return _check("zcode", "needs-action", "ZCode 未显式配置；未启动任何进程")
        runtime = ZCodeAgentRuntime(directory, env=values)
        try:
            health = runtime.health()
            if not isinstance(health, Mapping) or health.get("ok") is not True:
                return _check("zcode", "unavailable", "ZCode app-server 健康检查失败", error_type="health-failed")
            models = _safe_zcode_models(runtime.runtime_models())
            quota = runtime.quota_status()
            quota_state = str(quota.get("state") or "unknown") if isinstance(quota, Mapping) else "unknown"
            quota_source = str(quota.get("source") or "unknown") if isinstance(quota, Mapping) else "unknown"
            status = "ready" if models else "needs-action"
            detail = "ZCode 公开模型目录可用；未创建 Session 或发送提示词" if models else "ZCode 已连接但没有公开模型目录"
            return _check(
                "zcode",
                status,
                detail,
                models=models,
                quota={"state": quota_state, "source": quota_source},
                wire_protocol=str(runtime.status().get("wire_protocol") or "unknown"),
            )
        except Exception as error:  # adapter already bounds protocol payloads
            return _check("zcode", "unavailable", "ZCode app-server 不可用", error_type=type(error).__name__)
        finally:
            runtime.close()


def run_preflight(
    ollama_urls: list[str],
    *,
    expected_model: str | None = None,
    include_zcode: bool = False,
    zcode_environment: Mapping[str, str] | None = None,
    timeout: float = 3.0,
) -> dict[str, Any]:
    checked_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    checks: list[dict[str, Any]] = []
    for raw_url in ollama_urls:
        base_url = _safe_base_url(raw_url)
        checks.append(check_ollama(base_url, expected_model=expected_model, timeout=timeout))
    if include_zcode:
        checks.append(check_zcode(environment=zcode_environment))
    statuses = {str(item.get("status")) for item in checks}
    if "unavailable" in statuses:
        overall = "unavailable"
    elif "needs-action" in statuses or any(
        item.get("id") == "zcode" and (item.get("quota") or {}).get("state") == "unknown"
        for item in checks
    ):
        overall = "needs-action"
    else:
        overall = "ready"
    return {
        "schema_version": SCHEMA_VERSION,
        "checked_at": checked_at,
        "overall": overall,
        "checks": checks,
        "chat_requests_sent": 0,
        "credentials_read": False,
    }


def _print_human(report: Mapping[str, Any]) -> None:
    print(f"Sumika model preflight: {report.get('overall', 'unknown')}")
    for item in report.get("checks", []):
        if not isinstance(item, Mapping):
            continue
        print(f"- {item.get('id')}: {item.get('status')} - {item.get('detail')}")
        if item.get("models"):
            ids = [str(model.get("id")) if isinstance(model, Mapping) else str(model) for model in item["models"][:8]]
            print(f"  models: {', '.join(ids)}")
        quota = item.get("quota")
        if isinstance(quota, Mapping):
            print(f"  quota: {quota.get('state', 'unknown')} ({quota.get('source', 'unknown')})")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check Ollama and optionally ZCode without sending model requests")
    parser.add_argument("--ollama-url", action="append", default=None, help="Ollama base URL (repeatable; default: 127.0.0.1:11434)")
    parser.add_argument("--ollama-model", default="", help="optional model id that must be present")
    parser.add_argument("--zcode", action="store_true", help="explicitly check the configured public ZCode app-server")
    parser.add_argument("--zcode-autodiscover", action="store_true", help="opt in to public ZCode install discovery")
    parser.add_argument("--timeout", type=float, default=3.0, help="per-endpoint timeout in seconds")
    parser.add_argument("--json", action="store_true", help="print bounded JSON")
    args = parser.parse_args(argv)
    if not 0.1 <= args.timeout <= 30:
        parser.error("--timeout must be between 0.1 and 30 seconds")
    urls = args.ollama_url or [DEFAULT_OLLAMA_URL]
    environment = dict(os.environ)
    if args.zcode_autodiscover:
        environment["SUMIKA_ZCODE_AUTODISCOVER"] = "1"
    try:
        report = run_preflight(
            urls,
            expected_model=args.ollama_model or None,
            include_zcode=bool(args.zcode),
            zcode_environment=environment,
            timeout=args.timeout,
        )
    except (ValueError, ModelPreflightError) as error:
        print(f"model preflight failed: {error}", file=sys.stderr)
        return 3
    if args.json:
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    else:
        _print_human(report)
    return {"ready": 0, "needs-action": 2, "unavailable": 3}.get(str(report.get("overall")), 3)


if __name__ == "__main__":
    raise SystemExit(main())
