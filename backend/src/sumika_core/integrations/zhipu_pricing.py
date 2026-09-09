"""Bounded, credential-free public pricing observations, never routing evidence.

Only static tables with exact model cells and explicit input/output prices can
prove free pricing. Every additional price column must also be explicitly free.
Unsupported markup (including a JavaScript-only shell) needs human review; no
scripts, links, redirects, authenticated APIs, or browser state are followed.
"""

from __future__ import annotations

import hashlib
import http.client
import re
import json
import os
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from decimal import Decimal
from html.parser import HTMLParser
from typing import Any
from pathlib import Path


PRICING_URL = "https://bigmodel.cn/pricing"
ALLOWED_PRICING_URLS = frozenset({PRICING_URL})
MAX_BODY_BYTES = 2_000_000
MAX_ROWS = 512
REQUEST_TIMEOUT_SECONDS = 15
MODEL_ID = re.compile(r"glm-[a-z0-9]+(?:[.-][a-z0-9]+)*", re.IGNORECASE)


class PricingNeedsReview(ValueError):
    """The public response cannot establish trustworthy pricing observations."""

    state = "needs-review"


def fetch_rendered_pricing_observations() -> list[dict[str, Any]]:
    """Isolated public browser, no login profile, installed dependencies only."""
    executable = shutil.which("node")
    script = Path(__file__).resolve().parents[4] / "tools" / "read_zhipu_public_pricing.mjs"
    if not executable or not script.is_file():
        raise PricingNeedsReview("public DOM reader is not installed")
    environment = {key: value for key, value in os.environ.items()
                   if key.upper() in {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "LOCALAPPDATA", "USERPROFILE", "HOME", "PLAYWRIGHT_BROWSERS_PATH"}}
    try:
        result = subprocess.run([executable, str(script)], capture_output=True, text=True, encoding="utf-8",
                                timeout=45, env=environment,
                                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        if result.returncode or len(result.stdout) > MAX_BODY_BYTES:
            raise PricingNeedsReview("public DOM reader failed")
        rows = json.loads(result.stdout)
        if not isinstance(rows, list) or not 1 <= len(rows) <= MAX_ROWS:
            raise PricingNeedsReview("invalid public DOM evidence")
        return rows
    except (OSError, ValueError, subprocess.SubprocessError):
        raise PricingNeedsReview("public DOM reader unavailable") from None


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("redirects are disabled")


def read_bounded(response: Any, limit: int, timeout: float) -> bytes:
    """Read at most limit+1 bytes, with a deadline and bounded socket reads."""
    length = response.headers.get("Content-Length")
    if length is not None and (not length.isascii() or not length.isdecimal() or int(length) > limit):
        raise ValueError("response length is invalid or exceeds the limit")
    deadline = time.monotonic() + timeout
    chunks: list[bytes] = []
    size = 0
    reader = getattr(response, "read1", response.read)
    while size <= limit:
        if time.monotonic() >= deadline:
            raise ValueError("response deadline exceeded")
        chunk = reader(min(65_536, limit + 1 - size))
        if not chunk:
            if length is not None and size != int(length):
                raise ValueError("response body is incomplete")
            return b"".join(chunks)
        chunks.append(chunk)
        size += len(chunk)
    raise ValueError("response exceeds the byte limit")


class _Tables(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[dict[str, Any]] = []
        self.table: dict[str, Any] | None = None
        self.row: list[str] | None = None
        self.cell: list[str] | None = None
        self.cell_length = 0
        self.row_count = 0
        self.ignored: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if self.ignored:
            return
        if tag in {"script", "style", "template", "noscript"}:
            self.ignored = tag
            return
        attributes = dict(attrs)
        if tag == "table":
            if self.table is not None or len(self.tables) >= 64:
                raise PricingNeedsReview("unsupported or excessive pricing tables")
            self.table = {"rows": [], "ambiguous": False}
            self.tables.append(self.table)
        if self.table is None:
            return
        if "hidden" in attributes or attributes.get("aria-hidden") == "true" or "style" in attributes:
            self.table["ambiguous"] = True
        if tag == "tr":
            if self.row is not None:
                self.table["ambiguous"] = True
            self.row = []
            self.row_count += 1
            if self.row_count > MAX_ROWS + 64:
                raise PricingNeedsReview("too many pricing rows")
        if tag in {"th", "td"} and self.row is not None:
            if self.cell is not None:
                self.table["ambiguous"] = True
            self.cell = []
            self.cell_length = 0
            if any(attributes.get(key, "1") != "1" for key in ("rowspan", "colspan")):
                self.table["ambiguous"] = True
        if tag == "br" and self.cell is not None:
            self.handle_data(" ")

    def handle_data(self, data: str) -> None:
        if self.cell is not None and not self.ignored:
            self.cell_length += len(data)
            if self.cell_length > 2048:
                raise PricingNeedsReview("pricing cell exceeds the text limit")
            self.cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        if self.ignored:
            if tag == self.ignored:
                self.ignored = None
            return
        if tag in {"th", "td"} and self.cell is not None and self.row is not None:
            self.row.append(" ".join("".join(self.cell).split()))
            self.cell = None
            if len(self.row) > 32:
                raise PricingNeedsReview("too many pricing columns")
        if tag == "tr" and self.row is not None and self.table is not None:
            if self.cell is not None:
                self.table["ambiguous"] = True
            self.table["rows"].append(self.row)
            self.row = None
            self.cell = None
        if tag == "table":
            if self.table is not None and self.row is not None:
                self.table["ambiguous"] = True
            self.table = None
            self.row = None
            self.cell = None


def _column_role(text: str) -> str | None:
    normalized = re.sub(r"\s+", "", text).lower()
    normalized = re.sub(
        r"[（(](?:(?:元|cny|rmb|usd)/)?(?:百万|千|1m|1k|permillion|1000000|1000)tokens?[)）]$",
        "", normalized,
    )
    if normalized in {"模型", "模型名称", "模型编码", "model", "modelid", "modelname"}:
        return "model"
    for role, pattern in (
        ("input", r"(?:输入|input)(?:价格|单价|price|pricing|tokens?)?"),
        ("output", r"(?:输出|output)(?:价格|单价|price|pricing|tokens?)?"),
        ("cache", r"(?:缓存|缓存命中|缓存读取|缓存写入|缓存输入|cacheread|cachewrite|cachedinput)(?:价格|单价|price|tokens?)?"),
    ):
        if re.fullmatch(pattern, normalized):
            return role
    return None


def _free_price(text: str) -> bool | None:
    normalized = re.sub(r"\s+", "", text).lower()
    if normalized in {"免费", "free"}:
        return True
    match = re.fullmatch(
        r"[¥￥$]?(\d+(?:\.\d+)?)(?:元|cny|rmb|usd)?"
        r"(?:/(?:百万|千|1m|1k|million|1000000|1000)?(?:tokens?|次|张|秒))?",
        normalized,
    )
    if match:
        return Decimal(match.group(1)) == 0
    return None


def parse_pricing_observations(
    body: str | bytes, *, observed_at: str, source_url: str = PRICING_URL,
) -> list[dict[str, Any]]:
    """Return sorted observations; false means free is NOT established.

    Duplicate model/tier rows are combined conservatively: any explicit paid
    dimension or unknown row prevents a free claim. Missing rows say nothing
    about retirement. The caller must supply the actual observation time.
    """
    if source_url not in ALLOWED_PRICING_URLS:
        raise PricingNeedsReview("pricing URL is not allowlisted")
    try:
        observed = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
        if observed.utcoffset() is None:
            raise ValueError
        encoded = body.encode("utf-8") if isinstance(body, str) else body
        if len(encoded) > MAX_BODY_BYTES:
            raise ValueError
        document = encoded.decode("utf-8", "strict")
    except (AttributeError, TypeError, ValueError) as error:
        raise PricingNeedsReview("invalid pricing document or observation timestamp") from error
    parser = _Tables()
    parser.feed(document)
    parser.close()
    if parser.table is not None:
        raise PricingNeedsReview("incomplete pricing table")
    claims: dict[str, list[bool | None]] = {}
    for table in parser.tables:
        roles: list[str | None] = []
        for cells in table["rows"]:
            models = [(index, cell.lower()) for index, cell in enumerate(cells) if MODEL_ID.fullmatch(cell)]
            if not models:
                candidate_roles = [_column_role(cell) for cell in cells]
                if "model" in candidate_roles:
                    roles = candidate_roles
                continue
            claim = None
            if (len(models) == 1 and not table["ambiguous"] and len(roles) == len(cells)
                    and roles.count("model") == 1 and roles[models[0][0]] == "model"):
                dimensions = [_free_price(cell) for cell, role in zip(cells, roles) if role in {"input", "output", "cache"}]
                if False in dimensions:
                    claim = False
                elif "input" in roles and "output" in roles and None not in roles and all(value is True for value in dimensions):
                    claim = True
            for _, model_id in models:
                claims.setdefault(model_id, []).append(claim)
                if len(claims) > MAX_ROWS:
                    raise PricingNeedsReview("too many observed models")
    if not claims:
        raise PricingNeedsReview("no static exact-model pricing rows; SPA or unsupported markup needs review")
    version = hashlib.sha256(encoded).hexdigest()
    return [{
        "provider_id": "zhipu-official",
        "model_id": model_id,
        "source_url": source_url,
        "observed_at": observed.astimezone(timezone.utc).isoformat(),
        "source_version": version,
        "free_claim": all(value is True for value in values),
        "availability_state": "observed",
    } for model_id, values in sorted(claims.items())]


def fetch_pricing_observations(url: str = PRICING_URL, *, opener: Any = None) -> list[dict[str, Any]]:
    """GET the fixed public URL once, or raise PricingNeedsReview; never use keys."""
    if url not in ALLOWED_PRICING_URLS:
        raise PricingNeedsReview("pricing URL is not allowlisted")
    request = urllib.request.Request(url, headers={
        "User-Agent": "Sumika-model-observer/1.0",
        "Accept": "text/html, application/xhtml+xml",
        "Accept-Encoding": "identity",
    }, method="GET")
    if opener is None:
        opener = urllib.request.build_opener(NoRedirect())
    try:
        with opener.open(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            if response.status != 200 or response.geturl() not in ALLOWED_PRICING_URLS:
                raise ValueError("unexpected pricing response")
            content_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
            if content_type not in {"text/html", "application/xhtml+xml"}:
                raise ValueError("unsupported pricing content type")
            if response.headers.get("Content-Encoding", "identity").lower() != "identity":
                raise ValueError("encoded pricing response is unsupported")
            body = read_bounded(response, MAX_BODY_BYTES, REQUEST_TIMEOUT_SECONDS)
    except urllib.error.HTTPError as error:
        error.close()
        raise PricingNeedsReview("public pricing HTTP request rejected") from None
    except (OSError, ValueError, http.client.HTTPException):
        raise PricingNeedsReview("public pricing fetch failed validation or is unavailable") from None
    return parse_pricing_observations(body, observed_at=datetime.now(timezone.utc).isoformat())
