"""Read-only projections for authenticated account-portal evidence.

Readers attach to the caller-selected managed browser. They use no-focus,
short-lived BrowserSkill sessions and never read storage or other tab URLs.
"""

from __future__ import annotations

import json
import math
import re
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from threading import Event
from time import monotonic
from typing import Any

from ..browser.runtime import BrowserRuntimeError, BrowserSkillClient
from .modelscope_benefits import ModelScopeBenefitsReader
from .account_sources import MOARK_RECEIPTS_URL, validate_moark_receipts


SCHEMA = "account-portal-read/v1"
FRESHNESS = timedelta(minutes=15)
CHINA_TIME = timezone(timedelta(hours=8), "Asia/Shanghai")
MAX_DOM_BYTES = 16_000
OLLAMA_SETTINGS_URL = "https://ollama.com/settings"
OLLAMA_STARTER_MODELS = (
    "gemma4:31b",
    "gpt-oss:120b",
    "gpt-oss:20b",
    "nemotron-3-nano:30b",
    "nemotron-3-super",
    "nemotron-3-ultra",
)

MOARK_RECEIPTS_EXPRESSION = r"""
(async (control = {}) => {
  if (location.origin !== 'https://moark.com' || location.pathname !== '/serverless-api')
    return JSON.stringify({state:'needs-review',reason:'wrong-page'});
  const profiles = [...new Set(performance.getEntriesByType('resource').flatMap(row => {
    try {
      const url = new URL(row.name);
      return url.origin === location.origin && /^\/api\/base\/[A-Za-z0-9_-]+\/profile$/.test(url.pathname) ? [url.pathname] : [];
    } catch { return []; }
  }))];
  if (!profiles.length) return JSON.stringify({state:'needs-review',reason:'profile-resource-unavailable'});
  if (profiles.length !== 1) return JSON.stringify({state:'needs-review',reason:'ambiguous-account-profile'});
  if (typeof AbortSignal === 'undefined' || typeof AbortSignal.timeout !== 'function' || typeof AbortSignal.any !== 'function')
    return JSON.stringify({state:'needs-review',reason:'abort-controller-unavailable'});
  const signal = control.signal ? AbortSignal.any([control.signal, AbortSignal.timeout(10000)]) : AbortSignal.timeout(10000);
  const stage = value => { if (typeof control.onStage === 'function') control.onStage(value); };
  const checkActive = () => { if (signal.aborted) throw Error('read-stopped'); };
  const profile = profiles[0];
  const endpoint = profile.replace(/\/profile$/, '/inference-logs');
  const fingerprint = async value => {
    checkActive();
    if (typeof value !== 'string' || !/^[A-Za-z0-9._:-]{1,240}$/.test(value)) throw Error('invalid-identity');
    const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(value));
    return Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, '0')).join('');
  };
  const receipts = [];
  let total = null, skipped = 0;
  let failure = 'official-log-read-failed';
  try {
    const lossless = JSON.parse('1.0000000000000001', (key, value, context) => context?.source);
    if (lossless !== '1.0000000000000001')
      return JSON.stringify({state:'needs-review',reason:'lossless-json-parser-unavailable'});
    for (let page = 1; page <= 20; page++) {
      checkActive();
      stage('fetch');
      failure = 'official-log-read-failed';
      const response = await fetch(`${endpoint}?page=${page}&size=100`, {method:'GET',credentials:'include',redirect:'error',signal});
      if (!response.ok) {
        const reason = response.status === 401 ? 'official-log-auth-rejected' : response.status === 403 ? 'official-log-forbidden'
          : response.status === 429 ? 'official-log-rate-limited' : 'official-log-read-failed';
        return JSON.stringify({state:'needs-review',reason});
      }
      stage('body');
      const text = await response.text();
      checkActive();
      stage('parse');
      failure = 'log-page-too-large';
      if (text.length > 2000000) throw Error('log-page-too-large');
      failure = 'invalid-log-json';
      const body = JSON.parse(text, (key, value, context) => typeof value === 'number' ? context.source : value);
      failure = 'invalid-log-schema';
      if (!/^(0|[1-9][0-9]*)$/.test(body.total) || !Array.isArray(body.items)) throw Error('invalid-log-schema');
      if (total === null) total = Number(body.total);
      failure = 'log-pagination-changed-or-unbounded';
      if (total > 2000 || total !== Number(body.total) || body.items.length !== Math.min(100, total - (page - 1) * 100))
        throw Error('log-pagination-changed-or-unbounded');
      for (const row of body.items) {
        checkActive();
        failure = 'invalid-log-schema';
        if (!row || typeof row !== 'object') throw Error('invalid-log-schema');
        if (row.code !== '200' || row.status !== '1' || row.charge_source !== '0' || row.free !== false) { skipped++; continue; }
        failure = 'invalid-log-amount-or-model';
        if (typeof row.price !== 'string' || !/^(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?$/.test(row.price)
            || typeof row.request?.model !== 'string' || !/^[A-Za-z0-9][A-Za-z0-9/._:-]{0,239}$/.test(row.request.model))
          throw Error('invalid-log-amount-or-model');
        failure = 'invalid-receipt-identity';
        stage('hash');
        receipts.push({evidence_id:await fingerprint(row.id),trace_fingerprint:await fingerprint(row.trace_id),
          package_fingerprint:await fingerprint(row.resource_info?.ident),model_id:row.request.model,
          amount:row.price,unit:'CNY',charge_source:'resource-package',finalized:true});
      }
      if (page * 100 >= total) break;
    }
    checkActive();
    stage('complete');
    return JSON.stringify({schema:'moark-receipts/v1',source_url:'https://moark.com/api/base/{account}/inference-logs',
      state:'verified',receipts,total,skipped});
  } catch {
    const reason = signal.aborted ? control.signal?.aborted ? 'receipt-read-cancelled' : 'official-log-read-timeout' : failure;
    return JSON.stringify({state:'needs-review',reason});
  }
})()
"""

MOARK_RECEIPT_REASONS = frozenset({
    "wrong-page", "profile-resource-unavailable", "ambiguous-account-profile", "lossless-json-parser-unavailable",
    "official-log-auth-rejected", "official-log-forbidden", "official-log-rate-limited", "official-log-read-failed",
    "log-page-too-large", "invalid-log-json", "invalid-log-schema", "log-pagination-changed-or-unbounded",
    "invalid-log-amount-or-model", "invalid-receipt-identity",
    "abort-controller-unavailable", "receipt-read-cancelled", "official-log-read-timeout",
})


class AccountPortalError(RuntimeError):
    """A sanitized account-portal read failure."""

    def __init__(self, state: str, reason: str) -> None:
        super().__init__(reason)
        self.state = state
        self.reason = reason


def _json_object(value: str) -> dict[str, Any]:
    if len(value.encode("utf-8")) > MAX_DOM_BYTES:
        raise AccountPortalError("needs-review", "invalid-dom-result")
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result = {}
        for key, item in pairs:
            if key in result:
                raise ValueError("duplicate JSON property")
            result[key] = item
        return result

    try:
        parsed = json.loads(value, object_pairs_hook=reject_duplicates,
                            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()))
    except (TypeError, ValueError, RecursionError):
        raise AccountPortalError("needs-review", "invalid-dom-result") from None
    if not isinstance(parsed, dict):
        raise AccountPortalError("needs-review", "invalid-dom-result")
    return parsed


def _number(value: Any, *, minimum: Decimal = Decimal(0), maximum: Decimal = Decimal("999999999.99")) -> int | float:
    if type(value) not in {int, float} or isinstance(value, bool) or not math.isfinite(value):
        raise AccountPortalError("needs-review", "invalid-numeric-evidence")
    amount = Decimal(str(value))
    if not minimum <= amount <= maximum or amount.as_tuple().exponent < -2:
        raise AccountPortalError("needs-review", "invalid-numeric-evidence")
    return value


def _identifier(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", value):
        raise ValueError(f"invalid {label}")
    return value


def _tab_identifier(value: Any) -> str:
    if type(value) is int and 0 < value <= 2**31 - 1:
        return str(value)
    if isinstance(value, str) and re.fullmatch(r"[1-9][0-9]{0,9}", value):
        return value
    raise AccountPortalError("needs-review", "invalid-tab-response")


def _stamp(value: datetime | None) -> datetime:
    now = value or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("observed_at must be timezone-aware")
    return now.astimezone(timezone.utc)


def _quality(state: str, reason: str | None) -> dict[str, str | None]:
    return {"state": state, "blocking_reason": reason}


def _failed(source: str, state: str, reason: str, observed_at: datetime) -> dict[str, Any]:
    return {
        "source": source,
        "observed_at": observed_at.isoformat(),
        "fresh_until": (observed_at + FRESHNESS).isoformat(),
        "available_balance": None,
        "unit": None,
        "allowed_models": [],
        "grants": [],
        "displayed_reset": None,
        "account_binding_verified": False,
        "routing_eligible": False,
        "routing_blockers": [reason],
        "quality": _quality(state, reason),
    }


def project_modelscope_portal(observation: dict[str, Any], *, observed_at: datetime | None = None) -> dict[str, Any]:
    """Strictly project a bounded ModelScope DOM observation into public evidence."""

    observed = _stamp(observed_at)
    if not isinstance(observation, dict):
        return _failed("modelscope-magicube", "needs-review", "invalid-dom-result", observed)
    if observation.get("state") != "verified":
        reason = observation.get("reason")
        return _failed("modelscope-magicube", str(observation.get("state") or "needs-review"),
                       reason if isinstance(reason, str) and len(reason) <= 80 else "page-unverified", observed)
    try:
        if observation.get("unit") != "magicube":
            raise AccountPortalError("needs-review", "invalid-unit")
        balance = _number(observation.get("available_balance"))
        raw_grants = observation.get("grants")
        if not isinstance(raw_grants, list) or not 1 <= len(raw_grants) <= 100:
            raise AccountPortalError("needs-review", "invalid-grant-evidence")
        grants: list[dict[str, Any]] = []
        seen = set()
        for raw in raw_grants:
            if not isinstance(raw, dict) or raw.get("kind") not in {"daily-login", "aliyun-binding"}:
                raise AccountPortalError("needs-review", "invalid-grant-evidence")
            displayed = raw.get("granted_date_display")
            days = raw.get("validity_days_display")
            if not isinstance(displayed, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", displayed):
                raise AccountPortalError("needs-review", "invalid-grant-date")
            if type(days) is not int or days != 1:
                raise AccountPortalError("needs-review", "invalid-grant-validity")
            granted = date.fromisoformat(displayed)
            identity = (raw["kind"], displayed)
            if identity in seen:
                raise AccountPortalError("needs-review", "duplicate-grant")
            seen.add(identity)
            safe_until = datetime.combine(granted + timedelta(days=1), time.min, CHINA_TIME)
            grants.append({
                "kind": raw["kind"],
                "amount": _number(raw.get("amount"), minimum=Decimal("0.01")),
                "unit": "magicube",
                "granted_date_display": displayed,
                "validity_days_display": days,
                "exact_expires_at": None,
                "safe_valid_until": safe_until.isoformat(),
                "expiry_precision": "conservative-beijing-day-boundary",
            })
    except (AccountPortalError, ValueError):
        return _failed("modelscope-magicube", "needs-review", "invalid-grant-evidence", observed)
    return {
        "source": "modelscope-magicube",
        "observed_at": observed.isoformat(),
        "fresh_until": (observed + FRESHNESS).isoformat(),
        "available_balance": balance,
        "unit": "magicube",
        "allowed_models": [],
        "grants": grants,
        "displayed_reset": None,
        "account_binding_verified": False,
        "routing_eligible": False,
        "routing_blockers": ["account-binding-unverified", "model-cost-category-unverified"],
        "quality": _quality("verified", "account-binding-unverified"),
    }


def project_ollama_starter_portal(observation: dict[str, Any], *, observed_at: datetime | None = None) -> dict[str, Any]:
    """Project only explicit Starter-plan facts; free quota remains unknown."""

    observed = _stamp(observed_at)
    if not isinstance(observation, dict):
        return _failed("ollama-starter", "needs-review", "invalid-dom-result", observed)
    if observation.get("state") != "verified":
        reason = observation.get("reason")
        return _failed("ollama-starter", str(observation.get("state") or "needs-review"),
                       reason if isinstance(reason, str) and len(reason) <= 80 else "page-unverified", observed)
    try:
        percent = _number(observation.get("free_usage_percent"), maximum=Decimal(100))
        models = observation.get("allowed_models")
        if not isinstance(models, list) or tuple(models) != OLLAMA_STARTER_MODELS:
            raise AccountPortalError("needs-review", "allowed-models-changed")
        extra = _number(observation.get("extra_usage_balance"))
        displayed_reset = observation.get("displayed_reset")
        if displayed_reset is not None and (not isinstance(displayed_reset, str) or not 1 <= len(displayed_reset) <= 160):
            raise AccountPortalError("needs-review", "invalid-reset-display")
    except AccountPortalError as error:
        return _failed("ollama-starter", error.state, error.reason, observed)
    return {
        "source": "ollama-starter",
        "observed_at": observed.isoformat(),
        "fresh_until": (observed + FRESHNESS).isoformat(),
        "available_balance": None,
        "unit": None,
        "allowed_models": list(OLLAMA_STARTER_MODELS),
        "grants": [],
        "displayed_reset": displayed_reset,
        "displayed_free_usage_percent": percent,
        "displayed_extra_usage_balance": {"amount": extra, "unit": "USD"},
        "account_binding_verified": False,
        "routing_eligible": False,
        "routing_blockers": ["account-binding-unverified", "absolute-free-usage-quota-not-displayed"],
        "quality": _quality("observed-with-limitations", "absolute-free-usage-quota-not-displayed"),
    }


OLLAMA_EXPRESSION = r"""
JSON.stringify((() => {
  const visible = node => node && node.getClientRects().length > 0 && getComputedStyle(node).visibility !== 'hidden';
  if (location.origin !== 'https://ollama.com' || location.pathname !== '/settings')
    return {state:'needs-review',reason:'wrong-page'};
  if (Array.from(document.querySelectorAll('input[type="password"],input[autocomplete="username"]')).some(visible))
    return {state:'login-required',reason:'login-required'};
  const exact = value => Array.from(document.querySelectorAll('*'))
    .filter(node => node.children.length === 0 && node.textContent.trim() === value);
  const includedTitle = exact('Included usage');
  const balanceTitle = exact('Balance remaining');
  if (includedTitle.length !== 1 || balanceTitle.length !== 1) return {state:'needs-review',reason:'missing-usage-section'};
  const included = includedTitle[0].closest('h1,h2,h3,h4,h5,h6')?.parentElement?.parentElement;
  const extraAncestors = [balanceTitle[0].parentElement, balanceTitle[0].parentElement?.parentElement,
    balanceTitle[0].parentElement?.parentElement?.parentElement, balanceTitle[0].parentElement?.parentElement?.parentElement?.parentElement];
  const expected = ['gemma4:31b','gpt-oss:120b','gpt-oss:20b','nemotron-3-nano:30b','nemotron-3-super','nemotron-3-ultra'];
  const candidates = Array.from(included?.querySelectorAll('a') || []).filter(node => node.children.length === 0)
    .map(node => node.textContent.trim()).filter(value => /^[a-z][a-z0-9.-]*:[a-z0-9.-]+$|^[a-z]+-[0-9][a-z0-9.-]*-[a-z0-9.-]+$/.test(value));
  const models = [...new Set(candidates)];
  if (models.length !== expected.length || models.some(model => !expected.includes(model)) || expected.some(model => !models.includes(model)))
    return {state:'needs-review',reason:'allowed-models-changed'};
  const free = included?.innerText.match(/Free usage\s*([0-9]{1,3})% used/);
  const balance = extraAncestors.map(node => node?.innerText.match(/\$([0-9]+(?:\.[0-9]{1,2})?)/)).find(Boolean);
  if (!free || !balance || Number(free[1]) > 100) return {state:'needs-review',reason:'invalid-usage-evidence'};
  const reset = Array.from(included?.querySelectorAll('*') || []).filter(node => node.children.length === 0)
    .map(node => node.textContent.trim()).find(value => /^(?:Resets?(?: at| in)?|\u91cd\u7f6e(?:\u65f6\u95f4)?[\uff1a:]?)/.test(value));
  if (reset && reset.length > 160) return {state:'needs-review',reason:'invalid-reset-display'};
  return {state:'verified',free_usage_percent:Number(free[1]),extra_usage_balance:Number(balance[1]),allowed_models:expected,displayed_reset:reset || null};
})())
"""


class AccountPortalReader:
    """Read a provider portal without making session or tab IDs persistent API state."""

    def __init__(self, client: BrowserSkillClient) -> None:
        self.client = client

    def _command(self, args: tuple[str, ...]) -> dict[str, Any]:
        try:
            response = self.client._run(args, timeout=10.0) if self.client.runner == self.client._run else self.client.runner(args)
        except BrowserRuntimeError as error:
            code = error.code or "browser-command-failed"
            raise AccountPortalError("login-required" if code in {"login-required", "login_required"} else "unavailable",
                                     "browser-command-failed") from None
        except Exception:
            raise AccountPortalError("unavailable", "browser-command-failed") from None
        if not isinstance(response, dict) or response.get("ok") is False:
            raise AccountPortalError("unavailable", "browser-command-failed")
        return response

    def _validate_browser(self, browser_instance_id: str) -> None:
        status = self._command(("status",))
        browsers = status.get("browsers")
        if not isinstance(browsers, list) or not any(isinstance(row, dict) and row.get("instance_id") == browser_instance_id for row in browsers):
            raise AccountPortalError("unavailable", "browser-not-connected")

    def _observe(self, session_id: str, tab_id: str, expression: str) -> dict[str, Any]:
        response = self._command(("evaluate", "--session", session_id, "--tab-id", tab_id, expression))
        if not isinstance(response.get("value"), str):
            raise AccountPortalError("needs-review", "invalid-dom-result")
        return _json_object(response["value"])

    def _read_ollama(self, browser: str, stop_event: Event, observed: datetime) -> dict[str, Any]:
        session_id = None
        tab_id = None
        result = _failed("ollama-starter", "unavailable", "browser-command-failed", observed)
        try:
            if stop_event.is_set():
                raise AccountPortalError("interrupted", "interrupted")
            self._validate_browser(browser)
            started = self._command(("session", "start", "--browser", browser, "--no-focus"))
            session_id = _identifier(started.get("id", started.get("session_id")), label="session ID")
            for key in ("browser_instance", "browser_instance_id", "browserInstanceId"):
                if key in started and started[key] != browser:
                    raise AccountPortalError("needs-review", "browser-instance-mismatch")
            created = self._command(("tab", "create", "--session", session_id, "--url", "about:blank", "--no-active"))
            tab = created.get("tab", created)
            if not isinstance(tab, dict):
                raise AccountPortalError("needs-review", "invalid-tab-response")
            tab_id = _tab_identifier(tab.get("id", tab.get("tab_id", tab.get("tabId"))))
            self._command(("navigate", "--session", session_id, "--tab-id", tab_id, "--wait-until", "commit", "--timeout", "8s", OLLAMA_SETTINGS_URL))
            deadline = monotonic() + 12.0
            while monotonic() < deadline:
                if stop_event.is_set():
                    raise AccountPortalError("interrupted", "interrupted")
                observation = self._observe(session_id, tab_id, OLLAMA_EXPRESSION)
                if observation.get("state") == "verified":
                    result = project_ollama_starter_portal(observation, observed_at=observed)
                    break
                loading = (observation.get("state") == "pending" or observation.get("state") == "needs-review"
                           and observation.get("reason") in {"missing-usage-section", "invalid-usage-evidence"})
                if not loading:
                    result = project_ollama_starter_portal(observation, observed_at=observed)
                    break
                stop_event.wait(min(0.5, deadline - monotonic()))
            else:
                result = _failed("ollama-starter", "needs-review", "page-load-timeout", observed)
        except AccountPortalError as error:
            result = _failed("ollama-starter", error.state, error.reason, observed)
        finally:
            cleanup_failed = False
            if session_id and tab_id:
                try:
                    self._command(("tab", "close", "--session", session_id, tab_id))
                except AccountPortalError:
                    cleanup_failed = True
            if session_id:
                try:
                    self._command(("session", "stop", session_id))
                except AccountPortalError:
                    cleanup_failed = True
            if cleanup_failed:
                result = _failed("ollama-starter", "needs-review", "session-cleanup-failed", observed)
        return result

    def read_receipts(self, provider: str, browser_instance_id: str, stop_event: Event | None = None) -> dict[str, Any]:
        """Read exact log amounts in a private session; export hashes, never request bodies."""
        if provider != "moark":
            raise ValueError("unsupported receipt source")
        browser = _identifier(browser_instance_id, label="browser instance ID")
        cancellation = stop_event or Event()
        session_id = tab_id = None
        result = {"state": "needs-review", "reason": "official-log-read-failed"}
        try:
            if cancellation.is_set():
                raise AccountPortalError("interrupted", "interrupted")
            self._validate_browser(browser)
            started = self._command(("session", "start", "--browser", browser, "--no-focus"))
            session_id = _identifier(started.get("id", started.get("session_id")), label="session ID")
            for key in ("browser_instance", "browser_instance_id", "browserInstanceId"):
                if key in started and started[key] != browser:
                    raise AccountPortalError("needs-review", "browser-instance-mismatch")
            created = self._command(("tab", "create", "--session", session_id, "--url", "about:blank", "--no-active"))
            tab = created.get("tab", created)
            tab_id = _tab_identifier(tab.get("id", tab.get("tab_id", tab.get("tabId"))))
            self._command(("navigate", "--session", session_id, "--tab-id", tab_id, "--wait-until", "commit", "--timeout", "8s", "https://moark.com/serverless-api"))
            deadline = monotonic() + 12
            while monotonic() < deadline:
                if cancellation.is_set():
                    raise AccountPortalError("interrupted", "interrupted")
                response = self._command(("evaluate", "--session", session_id, "--tab-id", tab_id, MOARK_RECEIPTS_EXPRESSION))
                value = response.get("value")
                if not isinstance(value, str) or len(value.encode()) > 1000000:
                    raise AccountPortalError("needs-review", "invalid-receipt-projection")
                observation = json.loads(value)
                if observation.get("state") == "verified":
                    result = {"schema": "moark-receipts/v1", "source_url": MOARK_RECEIPTS_URL, "state": "verified",
                              "receipts": validate_moark_receipts(observation), "observed_at": _stamp(None).isoformat()}
                    break
                reason = observation.get("reason")
                result = {"state": "needs-review", "reason": reason if reason in MOARK_RECEIPT_REASONS else "official-log-read-failed"}
                if reason not in {"login-or-profile-required", "profile-resource-unavailable"}:
                    break
                cancellation.wait(max(0, min(0.5, deadline - monotonic())))
        except (AccountPortalError, ValueError, TypeError, AttributeError):
            result = {"state": "needs-review", "reason": "official-log-read-failed"}
        finally:
            cleanup_failed = False
            if session_id and tab_id:
                try:
                    self._command(("tab", "close", "--session", session_id, tab_id))
                except AccountPortalError:
                    cleanup_failed = True
            if session_id:
                try:
                    self._command(("session", "stop", session_id))
                except AccountPortalError:
                    cleanup_failed = True
            if cleanup_failed:
                result = {"state": "needs-review", "reason": "session-cleanup-failed"}
        return result

    def read(self, provider: str, browser_instance_id: str, stop_event: Event | None = None,
             *, observed_at: datetime | None = None) -> dict[str, Any]:
        """Return one provider projection for ``modelscope`` or ``ollama``."""

        browser = _identifier(browser_instance_id, label="browser instance ID")
        observed = _stamp(observed_at)
        cancellation = stop_event or Event()
        if provider == "modelscope":
            raw = ModelScopeBenefitsReader(self.client).read(browser, cancellation)
            return project_modelscope_portal(raw, observed_at=observed)
        if provider == "ollama":
            return self._read_ollama(browser, cancellation, observed)
        raise ValueError("unsupported account portal provider")
