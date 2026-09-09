"""Read an explicitly selected BrowserSkill tab; never navigate or authenticate.

The host runner accepts an argv tuple (without executable) and keyword timeout,
and returns the BrowserSkill JSON envelope, JSON text/bytes, or CompletedProcess.
An optional local OCR callback accepts keyword session and tab_id and returns
headers plus rows of literal cells. It must use local OCR, never a model or guesses.
Account binding, routing permission and displayed timezone come only from the host.
"""

from __future__ import annotations

import json
import math
import re
from datetime import datetime, timezone
from typing import Any, Callable, Mapping

from ..browser import looks_like_secret_text
from ..model_refresh import RESOURCE_URLS, parse_resource_observation


HEADERS = ("资源包名称", "资源包类型", "资源包状态", "适用场景", "当前余额", "当前可用余额", "购买时间", "生效时间", "到期时间")
FIELDS = ("name", "type", "status", "applicability", "balance", "available_balance", "purchased_at_display", "starts_at_display", "expires_at_display")
MAX_RESPONSE_BYTES = 2_000_000

RESOURCE_TABLE_JS = r"""JSON.stringify((() => {
    const allowedPaths = ['/finance/resourcepack', '/finance-center/resource-package/package-mgmt'];
    if (location.hostname !== 'open.bigmodel.cn' || !allowedPaths.includes(location.pathname)) {
        return {ok: false, reason: 'wrong-page'};
    }
    if (document.querySelector('#tab-my')?.getAttribute('aria-selected') !== 'true') {
        return {ok: false, reason: 'select-my-resource-packs-after-login'};
    }
    const labels = ['资源包名称', '资源包类型', '资源包状态', '适用场景', '当前余额', '当前可用余额', '购买时间', '生效时间', '到期时间'];
    const headers = Array.from(document.querySelectorAll('.el-table__header-wrapper th')).map(cell => cell.textContent.trim());
    if (labels.some((label, index) => headers[index] !== label)) {
        return {ok: false, reason: 'table-schema-changed'};
    }
    const rows = Array.from(document.querySelectorAll('.el-table__body-wrapper tbody tr'));
    if (!rows.length || rows.length > 100) return {ok: false, reason: 'empty-or-unbounded-table'};
    const fields = ['name', 'type', 'status', 'applicability', 'balance', 'available_balance', 'purchased_at_display', 'starts_at_display', 'expires_at_display'];
    const packs = [];
    for (const row of rows) {
        const cells = Array.from(row.querySelectorAll('td')).map(cell => cell.textContent.trim());
        if (cells.length < labels.length || cells.slice(0, labels.length).some(text => !text || text.length > 2000)) {
            return {ok: false, reason: 'incomplete-row'};
        }
        packs.push(Object.fromEntries(fields.map((field, index) => [field, cells[index]])));
    }
    return {
        ok: true,
        schema: 'zhipu-resource-pack-page-observation/v1',
        observed_at: new Date().toISOString(),
        source_url: location.origin + location.pathname,
        source: 'authenticated-page-dom',
        account_binding_verified: false,
        automatic_routing_authorized: false,
        billing_reconciliation: 'unverified',
        displayed_timezone: 'unspecified-by-page',
        scope: 'current-rendered-table-only',
        pagination_display: Array.from(document.querySelectorAll('.el-pagination')).map(element => element.innerText),
        packs
    };
})())"""

_CONTEXT_JS = r"""(() => {
    const allowedPaths = ['/finance/resourcepack', '/finance-center/resource-package/package-mgmt'];
    if (location.origin !== 'https://open.bigmodel.cn' || !allowedPaths.includes(location.pathname)) {
        return {ok: false, reason: 'wrong-page'};
    }
    if (document.querySelector('#tab-my')?.getAttribute('aria-selected') !== 'true') {
        return {ok: false, reason: 'select-my-resource-packs-after-login'};
    }
    return {ok: true, source_url: location.origin + location.pathname};
})()"""
PAGE_CONTEXT_JS = "JSON.stringify(" + _CONTEXT_JS + ")"
DOM_EXPRESSION = "(() => { const context = " + _CONTEXT_JS + r""";
    if (!context.ok) return JSON.stringify(context);
    const headers = Array.from(document.querySelectorAll('.el-table__header-wrapper'));
    const bodies = Array.from(document.querySelectorAll('.el-table__body-wrapper'));
    if (headers.length !== 1 || bodies.length !== 1 || !headers[0].closest('.el-table') ||
        headers[0].closest('.el-table') !== bodies[0].closest('.el-table')) {
        return JSON.stringify({ok: false, reason: 'ambiguous-table'});
    }
    const cells = Array.from(document.querySelectorAll('.el-table__header-wrapper th'));
    const rows = Array.from(document.querySelectorAll('.el-table__body-wrapper tbody tr'));
    if (cells.length !== 9 || rows.some(row => row.querySelectorAll('td').length !== 9)) {
        return JSON.stringify({ok: false, reason: 'table-schema-changed'});
    }
    return """ + RESOURCE_TABLE_JS + "; })()"


class ResourceNeedsReview(ValueError):
    """No trustworthy observation was obtained; errors never echo browser content."""

    state = "needs-review"


def _identifier(value: Any) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9._:-]{1,240}", value) or value.startswith("-") or ".." in value or looks_like_secret_text(value):
        raise ValueError("invalid host resource reader identifier")
    return value


def _json_object(value: Any) -> Mapping[str, Any]:
    try:
        if isinstance(value, bytes):
            if len(value) > MAX_RESPONSE_BYTES:
                raise ValueError
            value = value.decode("utf-8")
        if isinstance(value, str):
            if len(value) > MAX_RESPONSE_BYTES or len(value.encode("utf-8")) > MAX_RESPONSE_BYTES:
                raise ValueError
            value = json.loads(value)
        if not isinstance(value, Mapping) or len(json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")) > MAX_RESPONSE_BYTES:
            raise ValueError
        return value
    except (TypeError, ValueError, RecursionError):
        raise ResourceNeedsReview("invalid or oversized browser resource response") from None


def _cell(value: Any) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 2000 or any(ord(char) < 32 for char in value) or looks_like_secret_text(value):
        raise ResourceNeedsReview("invalid resource table cell")
    if re.search(r"(?:[A-Za-z]:[\\/]|https?://|(?:^|\s)/[A-Za-z]|\.\.[\\/])", value):
        raise ResourceNeedsReview("resource table cell contains unrelated location data")
    return value.strip()


class ZhipuResourceReader:
    def __init__(self, runner: Callable[..., Any], *, session: str, tab_id: int, provider_profile_id: str,
                 account_scope_id: str | None = None, account_binding_verified: bool = False,
                 automatic_routing_authorized: bool = False, displayed_timezone: str | None = None,
                 ocr_reader: Callable[..., Any] | None = None, timeout: float = 15) -> None:
        if not callable(runner) or ocr_reader is not None and not callable(ocr_reader):
            raise ValueError("resource reader requires callable host tools")
        if type(tab_id) is not int or not 0 <= tab_id <= 2**53 - 1:
            raise ValueError("resource reader requires an explicit numeric tab ID")
        if type(timeout) not in {int, float} or not math.isfinite(timeout) or not 0 < timeout <= 60:
            raise ValueError("invalid resource reader timeout")
        if type(account_binding_verified) is not bool or type(automatic_routing_authorized) is not bool:
            raise ValueError("resource authorization flags must be host booleans")
        if account_binding_verified and account_scope_id is None:
            raise ValueError("verified account binding requires a host account scope")
        if displayed_timezone not in (None, "unspecified-by-page", "+08:00", "UTC+08:00"):
            raise ValueError("displayed timezone is unsupported by the resource parser")
        self.runner = runner
        self.session = _identifier(session)
        self.tab_id = tab_id
        self.provider_profile_id = _identifier(provider_profile_id)
        self.account_scope_id = _identifier(account_scope_id) if account_scope_id is not None else None
        self.account_binding_verified = account_binding_verified
        self.automatic_routing_authorized = automatic_routing_authorized
        self.displayed_timezone = displayed_timezone or "unspecified-by-page"
        self.ocr_reader = ocr_reader
        self.timeout = timeout

    def _evaluate(self, expression: str) -> Mapping[str, Any]:
        try:
            response = self.runner(("evaluate", "--session", self.session, "--tab-id", str(self.tab_id), expression, "--json"), timeout=self.timeout)
            if hasattr(response, "returncode"):
                if response.returncode != 0:
                    raise ResourceNeedsReview("browser resource query failed")
                response = response.stdout
            envelope = _json_object(response)
            if envelope.get("ok") is not True:
                raise ResourceNeedsReview("browser resource evaluation failed")
            return _json_object(envelope.get("value"))
        except Exception:
            raise ResourceNeedsReview("browser resource query unavailable") from None

    def _context(self) -> str:
        result = self._evaluate(PAGE_CONTEXT_JS)
        if result.get("ok") is not True or not isinstance(result.get("source_url"), str) or result["source_url"] not in RESOURCE_URLS:
            raise ResourceNeedsReview("select the official resource table after manual login")
        return result["source_url"]

    def _projection(self, raw: Mapping[str, Any], *, source: str, source_url: str) -> dict[str, Any]:
        if source_url not in RESOURCE_URLS:
            raise ResourceNeedsReview("resource observation is not from the official page")
        rows = raw.get("packs")
        if not isinstance(rows, list) or not 1 <= len(rows) <= 100:
            raise ResourceNeedsReview("resource table is empty or unbounded")
        packs = []
        for row in rows:
            if not isinstance(row, Mapping):
                raise ResourceNeedsReview("invalid resource table row")
            packs.append({field: _cell(row.get(field)) for field in FIELDS})
        projection = {"ok": True, "schema": "zhipu-resource-pack-page-observation/v1",
                      "observed_at": datetime.now(timezone.utc).isoformat(), "source_url": source_url, "source": source,
                      "provider_profile_id": self.provider_profile_id, "account_scope_id": self.account_scope_id,
                      "account_binding_verified": self.account_binding_verified,
                      "automatic_routing_authorized": self.automatic_routing_authorized,
                      "displayed_timezone": self.displayed_timezone, "billing_reconciliation": "unverified",
                      "scope": "current-rendered-table-only", "complete": False, "packs": packs}
        try:
            parse_resource_observation(projection, self.provider_profile_id)
        except (TypeError, ValueError, OverflowError):
            raise ResourceNeedsReview("resource table requires review; no balances inferred") from None
        return projection

    def __call__(self) -> dict[str, Any]:
        try:
            raw = self._evaluate(DOM_EXPRESSION)
        except ResourceNeedsReview:
            raw = None
        if raw is not None:
            if raw.get("ok") is True:
                if raw.get("schema") != "zhipu-resource-pack-page-observation/v1" or not isinstance(raw.get("source_url"), str) or raw["source_url"] not in RESOURCE_URLS:
                    raise ResourceNeedsReview("invalid resource page identity")
                try:
                    return self._projection(raw, source="authenticated-page-dom", source_url=raw["source_url"])
                except ResourceNeedsReview:
                    if self.ocr_reader is None:
                        raise
            elif raw.get("reason") not in ("table-schema-changed", "empty-or-unbounded-table", "incomplete-row", "ambiguous-table"):
                raise ResourceNeedsReview("select the official resource table after manual login")
        if self.ocr_reader is None:
            raise ResourceNeedsReview("resource DOM unavailable and no local OCR reader configured")
        source_url = self._context()
        try:
            grid = _json_object(self.ocr_reader(session=self.session, tab_id=self.tab_id))
            if grid.get("headers") != list(HEADERS):
                raise ResourceNeedsReview("local OCR table headers are ambiguous")
            rows = grid.get("rows")
            if not isinstance(rows, list) or not 1 <= len(rows) <= 100 or any(not isinstance(row, list) or len(row) != len(FIELDS) for row in rows):
                raise ResourceNeedsReview("local OCR table is incomplete or unbounded")
            raw = {"packs": [dict(zip(FIELDS, row)) for row in rows]}
        except Exception:
            raise ResourceNeedsReview("local OCR resource table unavailable") from None
        if self._context() != source_url:
            raise ResourceNeedsReview("resource page changed during local OCR")
        return self._projection(raw, source="local-ocr", source_url=source_url)
