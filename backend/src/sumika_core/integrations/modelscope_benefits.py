"""Fixed ModelScope benefit-page reader; no login, claim submission, or AI.

Normal authenticated navigation may automatically grant the daily benefit.
Only the grant-records view is clicked. The authenticated browser account is
never asserted to match a provider Key; profile/revision checks belong to the
owning service. An injected BrowserSkill runner must honor its timeout contract.
"""

from __future__ import annotations

import json
import math
import re
from datetime import date, datetime, timezone
from decimal import Decimal
from threading import Event
from time import monotonic
from typing import Any

from ..browser.runtime import BrowserRuntimeError, BrowserSkillClient


USAGE_URL = "https://modelscope.cn/magicube/usage"
COMMAND_TIMEOUT = 10.0
LOAD_TIMEOUT_SECONDS = 12.0
MAX_POLLS = 25
POLL_INTERVAL = 0.5
MAX_BROWSERS = 64
MAX_GRANTS = 100
MAX_DOM_BYTES = 32_000

_PAGE_GUARD = r"""
    if (location.href === 'about:blank') return {state: 'pending', reason: 'initial-blank'};
    const visible = element => !element.closest('[hidden], [aria-hidden="true"], [inert]') && element.getClientRects().length > 0 &&
        getComputedStyle(element).display !== 'none' && getComputedStyle(element).visibility !== 'hidden';
    const challenge = document.querySelectorAll('iframe[src*="captcha"], iframe[src*="challenge"], [class*="captcha"], [id*="captcha"], [data-sitekey], input[autocomplete="one-time-code"]');
    if (challenge.length > 100) return {state: 'needs-review', reason: 'unbounded-page'};
    if (Array.from(challenge).some(visible)) return {state: 'challenge', reason: 'challenge'};
    const controls = document.querySelectorAll('button, a, [role="button"], [role="dialog"]');
    if (controls.length > 2000) return {state: 'needs-review', reason: 'unbounded-page'};
    const visibleLabels = Array.from(controls).filter(visible).map(element =>
        element.textContent.length <= 80 ? element.textContent.trim() : '');
    if (visibleLabels.some(label => ['\u5b89\u5168\u9a8c\u8bc1', '\u4eba\u673a\u9a8c\u8bc1', '\u6ed1\u52a8\u9a8c\u8bc1', 'Verify you are human'].includes(label))) {
        return {state: 'challenge', reason: 'challenge'};
    }
    const login = document.querySelectorAll('input[type="password"], input[autocomplete="username"], input[autocomplete="current-password"], form[action*="login"]');
    if (login.length > 100) return {state: 'needs-review', reason: 'unbounded-page'};
    if (Array.from(login).some(visible) || /\/(?:login|signin)(?:\/|$)/i.test(location.pathname) ||
        visibleLabels.some(label => ['\u767b\u5f55', '\u767b\u5f55/\u6ce8\u518c', '\u8bf7\u767b\u5f55', 'Sign in', 'Log in'].includes(label))) {
        return {state: 'login-required', reason: 'login-required'};
    }
    if (location.origin !== 'https://modelscope.cn' || location.pathname !== '/magicube/usage' || location.hash) {
        return {state: 'needs-review', reason: 'wrong-page'};
    }
    if (document.readyState === 'loading') return {state: 'pending', reason: 'page-loading'};
    const recordsLabel = '\u53d1\u653e\u8bb0\u5f55';
    const usageLabel = '\u6d88\u8017\u7edf\u8ba1';
    const earningLabel = '\u8d5a\u9b54\u7c92';
    const label = element => element.textContent.length <= 80 ? element.textContent.trim() : '';
    const semantic = Array.from(document.querySelectorAll('[role="tab"], button, [role="button"]'));
    if (semantic.length > 2000) return {state: 'needs-review', reason: 'unbounded-page'};
    let records = semantic.filter(element => visible(element) && label(element) === recordsLabel);
    let group = null;
    if (!records.length) {
        const containers = Array.from(document.querySelectorAll('div, span'));
        if (containers.length > 6000) return {state: 'needs-review', reason: 'unbounded-page'};
        const groups = containers.filter(element => {
            const children = Array.from(element.children);
            if (children.length < 2 || children.length > 3 ||
                !children.every(child => visible(child) && ['DIV', 'SPAN'].includes(child.tagName))) return false;
            const labels = children.map(label).sort().join('|');
            return labels === [recordsLabel, usageLabel].sort().join('|') ||
                labels === [earningLabel, recordsLabel, usageLabel].sort().join('|');
        });
        if (groups.length > 1) return {state: 'needs-review', reason: 'ambiguous-records-tab'};
        group = groups[0];
        records = group ? Array.from(group.children).filter(element => label(element) === recordsLabel) : [];
    }
    if (!records.length) return {state: 'pending', reason: 'missing-records-tabs'};
    if (records.length !== 1) return {state: 'needs-review', reason: 'ambiguous-records-tab'};
    const record = records[0];
    if (record.disabled || record.closest('form, a, [aria-disabled="true"]') ||
        record.querySelector('a, form, input, [aria-disabled="true"], :disabled')) {
        return {state: 'needs-review', reason: 'ambiguous-records-tab'};
    }
    group = group || record.closest('[role="tablist"]');
    const selection = element => {
        const flags = ['aria-selected', 'aria-pressed'].map(name => element.getAttribute(name)).filter(value => value !== null);
        if (flags.some(value => !['true', 'false'].includes(value)) || new Set(flags).size > 1) return 'invalid';
        return flags.length ? flags[0] === 'true' : null;
    };
    const selected = selection(record);
    if (selected === 'invalid') return {state: 'needs-review', reason: 'ambiguous-records-tab'};
    if (group) {
        const peers = Array.from(group.querySelectorAll('[role="tab"], button, [role="button"]')).filter(visible);
        if (peers.length > 16 || peers.some(element => selection(element) === 'invalid') ||
            peers.filter(element => selection(element) === true).length > 1) {
            return {state: 'needs-review', reason: 'ambiguous-records-tab'};
        }
    }
    let root = null;
    const panelId = record.getAttribute('aria-controls');
    if (panelId !== null) {
        if (!panelId || panelId.length > 160 || /\s/.test(panelId)) return {state: 'needs-review', reason: 'ambiguous-records-tab'};
        const identified = Array.from(document.querySelectorAll('[id]'));
        if (identified.length > 2000) return {state: 'needs-review', reason: 'unbounded-page'};
        const panels = identified.filter(element => element.id === panelId);
        if (panels.length > 1) return {state: 'needs-review', reason: 'ambiguous-records-tab'};
        root = panels[0];
    } else if (group && group.parentElement && !['BODY', 'HTML'].includes(group.parentElement.tagName)) {
        root = group.parentElement;
    }
    const readGrants = () => {
        if (!root || !visible(root)) return {state: 'pending', reason: 'missing-grants'};
        const kinds = new Map([
            ['\u6ce8\u518c\u5e76\u767b\u5f55', 'daily-login'],
            ['\u7ed1\u5b9a\u963f\u91cc\u4e91\u8d26\u53f7', 'aliyun-binding'],
        ]);
        const nodes = Array.from(root.querySelectorAll('div, span, li, article, h1, h2, h3, h4, h5, h6, [role="row"], [role="listitem"]'));
        if (nodes.length > 2000) return {state: 'needs-review', reason: 'unbounded-grants'};
        const labels = nodes.filter(element => visible(element) && !group?.contains(element) && kinds.has(label(element)));
        const titles = labels.filter(element => !labels.some(child => child !== element && element.contains(child)));
        const earningDescriptions = new Map([
            ['\u6ce8\u518c\u5e76\u767b\u5f55', '\u6ce8\u518c\u8d26\u53f7\u540e\u6bcf\u65e5\u767b\u5f55\u5373\u53ef\u83b7\u53d6'],
            ['\u7ed1\u5b9a\u963f\u91cc\u4e91\u8d26\u53f7', '\u7ed1\u5b9a\u963f\u91cc\u4e91\u8d26\u53f7\u540e\u6bcf\u65e5\u767b\u5f55\u5373\u53ef\u83b7\u53d6'],
        ]);
        const datedRecords = nodes.some(element => visible(element) && !group?.contains(element) &&
            /^\d{4}-\d{2}-\d{2}\u83b7\u5f97\uff0c/.test(label(element)));
        if (!datedRecords && titles.length && titles.every(title => title.parentElement?.textContent.includes(earningDescriptions.get(label(title))))) {
            return {state: 'pending', reason: 'missing-grants'};
        }
        if (!titles.length) {
            return datedRecords ? {state: 'needs-review', reason: 'no-grant-evidence'} : {state: 'pending', reason: 'missing-grants'};
        }
        if (titles.length > 100) return {state: 'needs-review', reason: 'unbounded-grants'};
        const grants = [];
        const seen = new Set();
        for (const title of titles) {
            let card = title.parentElement, detail = null;
            for (let depth = 0; depth < 4 && card && card !== root; depth++, card = card.parentElement) {
                if (titles.filter(element => card.contains(element)).length !== 1) break;
                const details = Array.from(card.children).filter(element => !element.contains(title) && visible(element))
                    .map(element => element.innerText).filter(text => typeof text === 'string' && /\u83b7\u5f97|\u6709\u6548\u671f/.test(text));
                if (details.length > 1) return {state: 'needs-review', reason: 'invalid-grant-row'};
                if (details.length === 1) { detail = details[0]; break; }
            }
            if (typeof detail !== 'string' || detail.length > 200) return {state: 'needs-review', reason: 'invalid-grant-row'};
            const lines = detail.split('\n').map(value => value.trim()).filter(Boolean);
            const displayed = lines[0]?.match(/^(\d{4}-\d{2}-\d{2})\u83b7\u5f97\uff0c\u6709\u6548\u671f([1-9][0-9]{0,2})\u5929$/);
            if (!displayed || lines.length !== 2 || !/^[1-9][0-9]{0,8}(\.[0-9]{1,2})?$/.test(lines[1])) {
                return {state: 'needs-review', reason: 'invalid-grant-row'};
            }
            const instant = new Date(displayed[1] + 'T00:00:00Z');
            if (!Number.isFinite(instant.getTime()) || instant.toISOString().slice(0, 10) !== displayed[1]) {
                return {state: 'needs-review', reason: 'invalid-grant-date'};
            }
            const kind = kinds.get(label(title));
            const identity = kind + ':' + displayed[1];
            if (seen.has(identity)) return {state: 'needs-review', reason: 'duplicate-grant'};
            seen.add(identity);
            grants.push({kind, amount: Number(lines[1]), granted_date_display: displayed[1],
                         validity_days_display: Number(displayed[2]), expires_at: null});
        }
        return {state: 'verified', grants};
    };
"""

READ_EXPRESSION = "JSON.stringify((() => {\n" + _PAGE_GUARD + r"""
    if (selected === false) return {state: 'select-records', reason: 'select-grant-records'};
    const evidence = readGrants();
    if (selected === null && evidence.state === 'pending') return {state: 'select-records', reason: 'select-grant-records'};
    if (evidence.state !== 'verified') return evidence;
    const balances = Array.from(document.querySelectorAll('button[aria-label], [role="button"][aria-label]'))
        .filter(element => visible(element) && element.getAttribute('aria-label') === 'Magic Cube');
    if (!balances.length) return {state: 'pending', reason: 'missing-balance'};
    const balance = balances[0].textContent.trim();
    if (balances.length !== 1 || !/^(0|[1-9][0-9]{0,8})(\.[0-9]{1,2})?$/.test(balance)) {
        return {state: 'needs-review', reason: 'invalid-balance'};
    }
    return {state: 'verified', available_balance: Number(balance), unit: 'magicube', grants: evidence.grants};
})())
"""

SELECT_RECORDS_EXPRESSION = "JSON.stringify((() => {\n" + _PAGE_GUARD + r"""
    if (selected === true) return {state: 'pending', reason: 'records-selected'};
    if (selected === null) {
        const evidence = readGrants();
        if (evidence.state === 'verified') return {state: 'pending', reason: 'records-selected'};
        if (evidence.state !== 'pending') return evidence;
    }
    record.click();
    return {state: 'pending', reason: 'records-selected'};
})())
"""

_REASONS = frozenset({
    "unbounded-page", "challenge", "login-required", "wrong-page", "page-loading",
    "ambiguous-records-tab", "select-grant-records", "missing-balance", "invalid-balance",
    "missing-grants", "unbounded-grants", "invalid-grant-row", "invalid-grant-date",
    "duplicate-grant", "no-grant-evidence", "records-selected", "initial-blank", "missing-records-tabs",
})
_BROWSER_NAMES = {
    "edge": "Edge", "microsoft edge": "Edge", "chrome": "Chrome", "google chrome": "Chrome",
    "chromium": "Chromium", "firefox": "Firefox", "brave": "Brave", "safari": "Safari",
}


class _Stopped(Exception):
    def __init__(self, state: str, error: str) -> None:
        self.state = state
        self.error = error


def _identifier(value: Any) -> str:
    if type(value) is int and 0 < value <= 2**31 - 1:
        return str(value)
    if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", value):
        return value
    raise _Stopped("needs-review", "invalid-browser-identifier")


def _field(value: dict[str, Any], *names: str) -> Any:
    values = [value[name] for name in names if name in value]
    if not values or any(item != values[0] for item in values):
        raise _Stopped("needs-review", "ambiguous-browser-metadata")
    return values[0]


def _number(value: Any, *, positive: bool = False) -> int | float:
    if type(value) not in {int, float} or not 0 <= value <= 999_999_999.99 or not math.isfinite(value):
        raise _Stopped("needs-review", "invalid-numeric-evidence")
    if positive and value <= 0:
        raise _Stopped("needs-review", "invalid-numeric-evidence")
    if Decimal(str(value)) * 100 != (Decimal(str(value)) * 100).to_integral_value():
        raise _Stopped("needs-review", "invalid-numeric-evidence")
    return value


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON property")
        result[key] = value
    return result


def _reject_constant(value: str) -> Any:
    raise ValueError("nonfinite JSON constant")


def _project(observation: dict[str, Any]) -> dict[str, Any]:
    balance = _number(observation.get("available_balance"))
    grants = observation.get("grants")
    if observation.get("unit") != "magicube" or not isinstance(grants, list) or not 1 <= len(grants) <= MAX_GRANTS:
        raise _Stopped("needs-review", "invalid-grant-evidence")
    result = []
    seen = set()
    for grant in grants:
        if (not isinstance(grant, dict) or not isinstance(grant.get("kind"), str)
                or grant["kind"] not in {"daily-login", "aliyun-binding"}):
            raise _Stopped("needs-review", "invalid-grant-evidence")
        displayed = grant.get("granted_date_display")
        if not isinstance(displayed, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", displayed):
            raise _Stopped("needs-review", "invalid-grant-date")
        try:
            date.fromisoformat(displayed)
        except ValueError:
            raise _Stopped("needs-review", "invalid-grant-date") from None
        validity = grant.get("validity_days_display")
        if type(validity) is not int or not 1 <= validity <= 999 or grant.get("expires_at") is not None:
            raise _Stopped("needs-review", "invalid-grant-evidence")
        identity = (grant["kind"], displayed)
        if identity in seen:
            raise _Stopped("needs-review", "duplicate-grant")
        seen.add(identity)
        result.append({"kind": grant["kind"], "amount": _number(grant.get("amount"), positive=True),
                       "granted_date_display": displayed, "validity_days_display": validity, "expires_at": None})
    return {"available_balance": balance, "grants": result}


class ModelScopeBenefitsReader:
    def __init__(self, client: BrowserSkillClient) -> None:
        self.client = client

    def _command(self, args: tuple[str, ...], stop_event: Event | None = None, *, deadline: float | None = None) -> Any:
        if stop_event is not None and stop_event.is_set():
            raise _Stopped("interrupted", "interrupted")
        timeout = COMMAND_TIMEOUT if deadline is None else min(COMMAND_TIMEOUT, deadline - monotonic())
        if timeout < 0.1:
            raise _Stopped("needs-review", "page-load-timeout")
        try:
            if self.client.runner == self.client._run:
                response = self.client._run(args, timeout=timeout)
            else:
                response = self.client.runner(args)
        except BrowserRuntimeError as error:
            if error.code in {"user_aborted", "user-aborted", "interrupted"}:
                raise _Stopped("interrupted", "user-aborted") from None
            if error.code in {"login_required", "login-required", "challenge"}:
                raise _Stopped(error.code.replace("_", "-"), error.code.replace("_", "-")) from None
            raise _Stopped("unavailable", "browser-command-failed") from None
        if not isinstance(response, dict):
            raise _Stopped("needs-review", "invalid-browser-response")
        code = response.get("code")
        error_value = response.get("error")
        if isinstance(error_value, dict):
            code = error_value.get("code", code)
        elif isinstance(error_value, str) and error_value in {"user_aborted", "user-aborted", "interrupted"}:
            code = error_value
        if not isinstance(code, str):
            code = None
        if code in {"user_aborted", "user-aborted", "interrupted"} or response.get("user_aborted") is True:
            raise _Stopped("interrupted", "user-aborted")
        if code in {"login_required", "login-required", "challenge"}:
            raise _Stopped(code.replace("_", "-"), code.replace("_", "-"))
        if response.get("ok") is False or error_value:
            raise _Stopped("unavailable", "browser-command-failed")
        if deadline is not None and monotonic() >= deadline:
            raise _Stopped("needs-review", "page-load-timeout")
        return response

    def _browsers(self, stop_event: Event | None = None) -> list[dict[str, str]]:
        value = self._command(("status",), stop_event)
        rows = value.get("browsers")
        if not isinstance(rows, list) or len(rows) > MAX_BROWSERS:
            raise _Stopped("needs-review", "invalid-browser-list")
        result = []
        seen = set()
        for row in rows:
            if not isinstance(row, dict):
                raise _Stopped("needs-review", "invalid-browser-list")
            instance_id = _identifier(_field(row, "instance_id", "instanceId", "id"))
            if instance_id in seen:
                raise _Stopped("needs-review", "ambiguous-browser-metadata")
            seen.add(instance_id)
            name = row.get("browser_name", row.get("browserName", row.get("name", "")))
            browser_name = _BROWSER_NAMES.get(name.lower(), "unknown") if isinstance(name, str) else "unknown"
            result.append({"instance_id": instance_id, "browser_name": browser_name})
        return sorted(result, key=lambda item: item["instance_id"])

    def browsers(self) -> list[dict[str, str]]:
        try:
            return self._browsers()
        except Exception:
            return []

    def _evaluate(self, session_id: str, tab_id: str, expression: str, stop_event: Event, *, deadline: float) -> dict[str, Any]:
        response = self._command(("evaluate", "--session", session_id, "--tab-id", tab_id, expression), stop_event, deadline=deadline)
        value = response.get("value")
        if response.get("ok") is not True or not isinstance(value, str) or len(value.encode("utf-8")) > MAX_DOM_BYTES:
            raise _Stopped("needs-review", "invalid-dom-result")
        try:
            result = json.loads(value, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
        except (ValueError, RecursionError):
            raise _Stopped("needs-review", "invalid-dom-result") from None
        if not isinstance(result, dict):
            raise _Stopped("needs-review", "invalid-dom-result")
        if stop_event.is_set():
            raise _Stopped("interrupted", "interrupted")
        return result

    def read(self, browser_instance_id: str, stop_event: Event) -> dict[str, Any]:
        result: dict[str, Any] = {"state": "unavailable", "checked_at": None, "available_balance": None,
                                  "unit": "magicube", "grants": [], "error": None, "account_binding_verified": False}
        session_id = None
        try:
            instance_id = _identifier(browser_instance_id)
            if instance_id not in {item["instance_id"] for item in self._browsers(stop_event)}:
                raise _Stopped("unavailable", "browser-not-connected")
            created = self._command(("session", "start", "--browser", instance_id, "--no-focus"), stop_event)
            session_id = _identifier(_field(created, "id", "session_id"))
            for field in ("browser_instance", "browser_instance_id", "browserInstanceId"):
                if field in created and created[field] != instance_id:
                    raise _Stopped("needs-review", "browser-instance-mismatch")
            tab = self._command(("tab", "create", "--session", session_id, "--url", "about:blank", "--no-active"), stop_event)
            tab_data = tab.get("tab", tab)
            if not isinstance(tab_data, dict):
                raise _Stopped("needs-review", "invalid-tab-response")
            tab_id = _identifier(_field(tab_data, "id", "tab_id", "tabId"))
            deadline = monotonic() + LOAD_TIMEOUT_SECONDS
            self._command(("navigate", "--session", session_id, "--tab-id", tab_id,
                           "--wait-until", "commit", "--timeout", "8s", USAGE_URL), stop_event, deadline=deadline)
            selected = False
            target_page_seen = False
            for attempt in range(MAX_POLLS):
                observation = self._evaluate(session_id, tab_id, READ_EXPRESSION, stop_event, deadline=deadline)
                state = observation.get("state")
                if not isinstance(state, str):
                    raise _Stopped("needs-review", "invalid-dom-state")
                if observation.get("reason") == "initial-blank":
                    if state != "pending" or target_page_seen:
                        raise _Stopped("needs-review", "wrong-page")
                else:
                    target_page_seen = True
                if state == "verified":
                    result.update(_project(observation), state="verified")
                    break
                if state == "select-records" and not selected:
                    observation = self._evaluate(session_id, tab_id, SELECT_RECORDS_EXPRESSION, stop_event, deadline=deadline)
                    state = observation.get("state")
                    if observation.get("reason") == "initial-blank":
                        raise _Stopped("needs-review", "wrong-page")
                    selected = observation.get("reason") == "records-selected"
                if state in ("user_aborted", "user-aborted"):
                    raise _Stopped("interrupted", "user-aborted")
                if not isinstance(state, str):
                    raise _Stopped("needs-review", "invalid-dom-state")
                if state in {"login-required", "challenge", "interrupted", "unavailable", "needs-review"}:
                    reason = observation.get("reason")
                    raise _Stopped(state, reason if isinstance(reason, str) and reason in _REASONS else "page-unverified")
                if state not in {"pending", "select-records"}:
                    raise _Stopped("needs-review", "invalid-dom-state")
                if attempt + 1 < MAX_POLLS:
                    remaining = deadline - monotonic()
                    if remaining <= 0:
                        raise _Stopped("needs-review", "page-load-timeout")
                    if stop_event.wait(min(POLL_INTERVAL, remaining)):
                        raise _Stopped("interrupted", "interrupted")
            else:
                raise _Stopped("needs-review", "poll-limit")
        except _Stopped as error:
            result.update(state=error.state, error=error.error)
        except Exception:
            result.update(state="unavailable", error="browser-command-failed")
        finally:
            if session_id is not None:
                try:
                    self._command(("session", "stop", session_id))
                except _Stopped as error:
                    if error.state == "interrupted":
                        result.update(state="interrupted", error="user-aborted", available_balance=None, grants=[])
                    elif result["state"] == "verified":
                        result.update(state="needs-review", error="session-close-failed", available_balance=None, grants=[])
                except Exception:
                    if result["state"] == "verified":
                        result.update(state="needs-review", error="session-close-failed", available_balance=None, grants=[])
            if stop_event.is_set():
                result.update(state="interrupted", error="interrupted", available_balance=None, grants=[])
            result["checked_at"] = datetime.now(timezone.utc).isoformat()
        return result
