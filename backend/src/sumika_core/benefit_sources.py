"""Credential-free public discovery, independent of registered providers.

Search links are untrusted leads, never fetched or authorized. Public zero
prices are not credits, account quotas, availability, or permission to call a
model. Expiry stays unknown and claiming stays disabled. Scheduling, state,
claims, and UI belong to the caller. collect() raises ValueError on source
failure; an empty list means a valid source had no qualifying observations.

The small price parsers deliberately duplicate the public schemas in
tools/read_siliconflow_public_pricing.py, read_xfyun_public_catalog.py and
register_openrouter_free_candidates.py: backend must not import CLI tools.
Bing relevance and regional availability vary; no result-page fallback exists.
Every RSS/Atom source requires explicit model/API and benefit terms in the same
title. Generic AI tools, navigation, and encyclopedia hits are insufficient;
descriptions and query text cannot supply missing relevance. A valid feed with
only irrelevant results returns [], never unfiltered fallback observations.
Normal system/environment proxies are honored. Earlier community-feed failures
occurred with proxies disabled and do not establish that those feeds are down.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from html import unescape
from html.parser import HTMLParser
from http.client import HTTPException
import ipaddress
import json
import re
import time
import unicodedata
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, unquote, urlencode, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from xml.etree import ElementTree


_BING = "https://www.bing.com/search?"
_CONFIG = (
    ("bing-ai-free-zh", "AI API free and limited-time quotas",
     _BING + urlencode({"q": "AI \u514d\u8d39 API \u9650\u65f6 \u989d\u5ea6", "format": "rss"}), "search", 21600),
    ("bing-llm-credits-en", "Free LLM API credits",
     _BING + urlencode({"q": "free LLM API credits", "format": "rss"}), "search", 21600),
    ("bing-ai-checkin-zh", "AI check-in resource packs",
     _BING + urlencode({"q": "AI \u7b7e\u5230 \u8d44\u6e90\u5305", "format": "rss"}), "search", 21600),
    ("v2ex-share-rss", "V2EX Share and Discover",
     "https://www.v2ex.com/feed/share.xml", "community-rss", 21600),
    ("linuxdo-latest-rss", "LINUX DO latest topics",
     "https://linux.do/latest.rss", "community-rss", 21600),
    ("openrouter-free-models", "OpenRouter public free variants",
     "https://openrouter.ai/api/v1/models", "public-catalog", 21600),
    ("siliconflow-public-pricing", "SiliconFlow public text pricing",
     "https://www.siliconflow.cn/pricing", "public-pricing", 43200),
    ("xfyun-public-catalog", "Xfyun public text catalog",
     "https://maas.xfyun.cn/api/v1/gpt-finetune/model/base/list-v2?page=1&size=9999", "public-catalog", 43200),
    ("groq-public-benefits", "Groq \u516c\u5f00\u5957\u9910\u9650\u989d",
     "https://console.groq.com/docs/rate-limits", "public-benefits", 43200),
    ("cerebras-public-benefits", "Cerebras \u514d\u8d39\u8bd5\u7528\u91d1",
     "https://inference-docs.cerebras.ai/support/rate-limits", "public-benefits", 43200),
    ("cloudflare-public-benefits", "Cloudflare Workers AI \u6bcf\u65e5\u514d\u8d39\u989d\u5ea6",
     "https://developers.cloudflare.com/workers-ai/platform/pricing/", "public-benefits", 43200),
    ("gemini-public-benefits", "Gemini API \u514d\u8d39\u5c42",
     "https://ai.google.dev/gemini-api/docs/pricing", "public-benefits", 43200),
)
SOURCE_SPECS = tuple(dict(zip(("id", "title", "url", "kind", "interval_seconds"), spec)) for spec in _CONFIG)
_SOURCES = {spec[0]: spec for spec in _CONFIG}
_LIMITS = {"search": 1_000_000, "community-rss": 1_000_000, "public-catalog": 8_000_000,
           "public-pricing": 2_000_000, "public-benefits": 2_000_000}
_TYPES = {"search": {"application/rss+xml", "application/xml", "text/xml"},
          "community-rss": {"application/rss+xml", "application/atom+xml", "application/xml", "text/xml"},
          "public-catalog": {"application/json"}, "public-pricing": {"text/html"}, "public-benefits": {"text/html"}}
_MAX_ROWS = 128
_TIMEOUT = 10
_DEADLINE = 20
_PRICE_UNIT = "\u5143/\u767e\u4e07tokens"
_FREE = "\u514d\u8d39"
_SECRET = re.compile(
    r"(?i)(?:\b(?:sk[-_]|hf_|gh[pousr]_|github_pat_|AKIA)[a-z0-9_-]{8,}"
    r"|\beyJ[a-z0-9_-]{8,}\.[a-z0-9_-]+\.[a-z0-9_-]+"
    r"|\bbearer\s+\S+|-----BEGIN [A-Z ]*PRIVATE KEY-----"
    r"|\b(?:api[ _-]?key|access[ _-]?token|refresh[ _-]?token|token|secret|password|authorization)"
    r"\s*[:=]\s*\S+)"
)
_SECRET_PARAMS = {"key", "apikey", "accesskey", "token", "accesstoken", "refreshtoken", "idtoken",
                  "secret", "clientsecret", "password", "passwd", "authorization", "auth",
                  "signature", "sig", "session", "sessionid", "cookie", "credential"}
_MODEL_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9/._:-]{0,199}\Z")
_MODEL_API_TOPIC = re.compile(
    r"(?i)(?<![a-z0-9])(?:LLMs?|API|ChatGPT|Claude|Gemini|GPT|DeepSeek|Qwen|ModelScope)(?![a-z0-9])"
    r"|\b(?:language models?|model inference|AI models?)\b"
    r"|\u5927\u6a21\u578b|\u8bed\u8a00\u6a21\u578b|\u6a21\u578b(?:\u63a5\u53e3|\u63a8\u7406)"
)
_BENEFIT_TOPIC = re.compile(
    r"(?i)\b(?:free|trials?|giveaways?|promos?|check[ -]?in)\b"
    r"|\u514d\u8d39|\u9650\u514d|\u8d60\u9001|\u8d60\u91d1|\u9886\u53d6|\u8bd5\u7528|\u7b7e\u5230"
)
_VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        response.close()
        raise ValueError("public source redirect rejected")


def _fetch(source_id):
    _, _, url, kind, _ = _SOURCES[source_id]
    limit = _LIMITS[kind]
    request = Request(url, headers={"Accept": ", ".join(sorted(_TYPES[kind])),
                                   "Accept-Encoding": "identity", "User-Agent": "Sumika-Public-Discovery/1.0"},
                      method="GET")
    started = time.monotonic()
    try:
        with build_opener(_NoRedirect()).open(request, timeout=_TIMEOUT) as response:
            if response.status != 200 or response.geturl() != url:
                raise ValueError("unexpected public source response")
            media_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
            encoding = response.headers.get("Content-Encoding", "identity").strip().lower()
            if media_type not in _TYPES[kind] or encoding != "identity":
                raise ValueError("unexpected public source encoding")
            length = response.headers.get("Content-Length")
            if length is not None and (not length.isascii() or not length.isdecimal() or int(length) > limit):
                raise ValueError("invalid public source length")
            body = bytearray()
            while True:
                if time.monotonic() - started >= _DEADLINE:
                    raise ValueError("public source deadline exceeded")
                chunk = response.read1(min(65536, limit + 1 - len(body)))
                if time.monotonic() - started >= _DEADLINE:
                    raise ValueError("public source deadline exceeded")
                body.extend(chunk)
                if len(body) > limit:
                    raise ValueError("public source too large")
                if not chunk:
                    break
            if length is not None and len(body) != int(length):
                raise ValueError("incomplete public source")
            return bytes(body)
    except HTTPError as error:
        error.close()
        raise ValueError(f"public source HTTP {error.code}") from None
    except URLError as error:
        raise ValueError(f"public source network unavailable ({type(error.reason).__name__})") from None
    except (OSError, HTTPException, ValueError):
        raise ValueError("public source fetch rejected or unavailable") from None


def _title(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 4096:
        return ""
    value = unicodedata.normalize("NFKC", unescape(value))
    if any(unicodedata.category(character).startswith("C") and character not in "\t\r\n" for character in value):
        return ""
    value = " ".join(value.split())
    if "<" in value or ">" in value or _SECRET.search(value):
        return ""
    return value[:200]


def _lead_url(value):
    """Validate syntax only, without DNS or fetching; downstream must recheck.

    Conservatively exclude all IP literals and non-default HTTPS ports, too.
    A public-looking hostname is not evidence that its destination is safe.
    """
    if not isinstance(value, str) or not 1 <= len(value) <= 2048:
        return ""
    decoded = unquote(value)
    if any(character.isspace() or unicodedata.category(character).startswith("C") for character in decoded):
        return ""
    if any(character in decoded for character in "\\<>\"") or _SECRET.search(decoded):
        return ""
    try:
        parsed = urlsplit(value)
        if parsed.scheme != "https" or parsed.username is not None or parsed.password is not None or parsed.port not in (None, 443):
            return ""
        host = (parsed.hostname or "").encode("idna").decode("ascii").lower().rstrip(".")
        if not host or len(host) > 253 or "." not in host:
            return ""
        try:
            ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            return ""
        labels = host.split(".")
        if re.fullmatch(r"(?:[0-9]+|0x[0-9a-f]+)", labels[-1]) or any(not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in labels):
            return ""
        if host.endswith((".localhost", ".local", ".internal", ".lan", ".home", ".localdomain")):
            return ""
        for name, content in parse_qsl(parsed.query, keep_blank_values=True, max_num_fields=64):
            normalized = re.sub(r"[^a-z0-9]", "", name.lower())
            if normalized in _SECRET_PARAMS or normalized.endswith(("token", "secret", "password", "credential")) or _SECRET.search(content):
                return ""
        return urlunsplit(("https", host, parsed.path or "/", parsed.query, ""))
    except (ValueError, UnicodeError):
        return ""


def _row(title, url, kind, evidence, provider_id="", model_id=""):
    return {"title": title, "url": url, "provider_id": provider_id, "model_id": model_id,
            "kind": kind, "evidence": evidence, "expires_at": None, "claim_strategy": "none"}


def _rss(body, source_id):
    text = body.decode("utf-8-sig")
    if "\x00" in text or "<!DOCTYPE" in text.upper() or "<!ENTITY" in text.upper():
        raise ValueError("unsafe RSS declarations")
    root = ElementTree.fromstring(text)
    community = _SOURCES[source_id][3] == "community-rss"
    atom = "{http://www.w3.org/2005/Atom}"
    if root.tag == "rss" and root.find("channel") is not None:
        entries = root.findall("./channel/item")
        prefix = ""
    elif community and root.tag == atom + "feed":
        entries = root.findall(atom + "entry")
        prefix = atom
    else:
        raise ValueError("RSS channel or community Atom feed required")
    result = []
    seen = set()
    for item in entries:
        title_node = item.find(prefix + "title")
        link_node = next((node for node in item.findall(prefix + "link")
                          if not prefix or node.get("rel", "alternate") == "alternate"), None)
        if title_node is None or link_node is None or len(title_node) or len(link_node):
            continue
        title = _title(title_node.text)
        url = _lead_url(link_node.get("href") if prefix else link_node.text)
        if not title or not url or url in seen:
            continue
        if not (_MODEL_API_TOPIC.search(title) and _BENEFIT_TOPIC.search(title)):
            continue
        seen.add(url)
        evidence = "Unverified community feed lead; offer and quota not verified." if community else "Unverified Bing search lead; offer and quota not verified."
        result.append(_row(title, url, "lead", evidence))
        if len(result) >= _MAX_ROWS:
            break
    return result


def _json(body):
    def unique_object(pairs):
        result = {}
        for name, value in pairs:
            if name in result:
                raise ValueError("duplicate JSON field")
            result[name] = value
        return result

    def invalid_constant(value):
        raise ValueError("non-finite JSON number")

    return json.loads(body, parse_float=Decimal, parse_constant=invalid_constant, object_pairs_hook=unique_object)


def _zero(value):
    if type(value) not in (int, str, Decimal) or len(str(value)) > 64:
        return False
    try:
        number = Decimal(value)
        return number.is_finite() and number == 0
    except InvalidOperation:
        return False


def _model_id(value):
    return isinstance(value, str) and _MODEL_ID.fullmatch(value) is not None and _title(value) == value


def _models(rows, id_key):
    if not isinstance(rows, list) or len(rows) > 10000:
        raise ValueError("bounded public catalog required")
    seen = set()
    for model in rows:
        if not isinstance(model, dict):
            raise ValueError("invalid public model row")
        model_id = model.get(id_key)
        if not _model_id(model_id):
            continue
        if model_id in seen:
            raise ValueError("duplicate public model identity")
        seen.add(model_id)
        yield model_id, model


def _openrouter(body, source_id):
    payload = _json(body)
    result = []
    for model_id, model in _models(payload.get("data") if isinstance(payload, dict) else None, "id"):
        pricing = model.get("pricing")
        architecture = model.get("architecture")
        modalities = architecture.get("input_modalities") if isinstance(architecture, dict) else None
        if not model_id.endswith(":free") or not isinstance(modalities, list) or "text" not in modalities:
            continue
        if not isinstance(pricing, dict) or not {"prompt", "completion"} <= pricing.keys() or not all(_zero(price) for price in pricing.values()):
            continue
        result.append(_row(model_id, _SOURCES[source_id][2], "free-model",
                           "Public zero prices for the exact free variant; quota and availability unknown.", "openrouter", model_id))
    return result


class _PricingRows(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows = []
        self.stack = []

    def handle_starttag(self, tag, attrs):
        row_id = dict(attrs).get("id") or ""
        if not self.stack and not (tag == "div" and row_id.startswith("pricing-row-text-")):
            return
        if len(self.stack) >= 64:
            raise ValueError("pricing markup too deep")
        node = {"tag": tag, "children": []}
        if self.stack:
            self.stack[-1]["children"].append(node)
        if tag not in _VOID_TAGS:
            self.stack.append(node)

    def handle_endtag(self, tag):
        if not self.stack or tag in _VOID_TAGS:
            return
        if self.stack[-1]["tag"] != tag:
            raise ValueError("unbalanced pricing row")
        node = self.stack.pop()
        if not self.stack:
            self.rows.append(node)

    def handle_data(self, value):
        if self.stack and value.strip():
            self.stack[-1]["children"].append(value.strip())


def _leaf_text(node):
    if isinstance(node, str):
        return [node]
    if node["tag"] in {"script", "style", "template"}:
        return []
    return [value for child in node["children"] for value in _leaf_text(child)]


def _siliconflow(body, source_id):
    parser = _PricingRows()
    parser.feed(body.decode("utf-8-sig"))
    parser.close()
    if parser.stack or not parser.rows:
        raise ValueError("complete public text pricing rows required")
    result = []
    seen = set()
    for row in parser.rows:
        cells = [child for child in row["children"] if isinstance(child, dict)]
        if len(cells) != 4:
            continue
        identities = {value for value in _leaf_text(cells[0]) if "/" in value and _model_id(value)}
        if len(identities) != 1:
            raise ValueError("ambiguous public pricing identity")
        model_id = identities.pop()
        if model_id in seen:
            raise ValueError("duplicate public pricing identity")
        seen.add(model_id)
        labels = [" ".join(_leaf_text(cell)) for cell in cells[1:]]
        if labels[:2] != [_FREE, _FREE] or labels[2] not in {"-", _FREE}:
            continue
        evidence = "Public free input/output; cache " + ("unquoted" if labels[2] == "-" else "free") + "; quota and availability unknown."
        result.append(_row(model_id, _SOURCES[source_id][2], "free-model", evidence, "siliconflow", model_id))
    return result


def _has_tag(model, key, name):
    groups = model.get("categoryTree")
    if not isinstance(groups, list):
        return False
    return any(isinstance(group, dict) and group.get("key") == key and isinstance(group.get("children"), list)
               and any(isinstance(child, dict) and child.get("name") == name for child in group["children"])
               for group in groups)


def _xfyun(body, source_id):
    payload = _json(body)
    if not isinstance(payload, dict) or type(payload.get("code")) is not int or payload["code"] != 0 or payload.get("succeed") is not True:
        raise ValueError("successful public catalog required")
    data = payload.get("data")
    result = []
    for model_id, model in _models(data.get("rows") if isinstance(data, dict) else None, "serviceId"):
        if not _has_tag(model, "modelCategory", "\u6587\u672c\u751f\u6210"):
            continue
        price = model.get("price")
        pricing = price.get("inferencePrice") if isinstance(price, dict) else None
        if not isinstance(pricing, dict) or pricing.get("showPrice") is not True:
            continue
        if not all(_zero(pricing.get(field + "Price")) and pricing.get(field + "Unit") == _PRICE_UNIT
                   for field in ("inTokens", "outTokens", "cacheTokens")):
            continue
        if "noCacheTokensPrice" in pricing and not _zero(pricing["noCacheTokensPrice"]):
            continue
        if any(name.endswith("Price") and not name.endswith("OrigPrice") and name != "showPrice" and not _zero(value)
               for name, value in pricing.items()):
            continue
        limited = _has_tag(model, "indexMarker", "\u9650\u65f6\u514d\u8d39")
        evidence = "Public zero inference prices" + (" (limited-time)" if limited else "") + "; expiry, quota and availability unknown."
        result.append(_row(model_id, _SOURCES[source_id][2], "free-model", evidence, "xfyun", model_id))
    return result


class _BenefitHTML(HTMLParser):
    """Read document paragraphs, FAQ regions and table rows, never navigation.

    Native details/summary content is readable document text, including closed
    FAQs. Explicit hidden attributes/styles and executable templates are not.
    This does not execute JavaScript or compute external stylesheet rules.
    """
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.blocks = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        parent = self.stack[-1] if self.stack else {}
        hidden = (parent.get("hidden", False)
                  or tag in {"script", "style", "nav", "header", "footer", "aside", "template", "noscript", "svg", "form"}
                  or attrs.get("role") in {"navigation", "menu", "menubar", "tablist"}
                  or "hidden" in attrs or attrs.get("aria-hidden", "").lower() == "true"
                  or re.search(r"(?:display\s*:\s*none|visibility\s*:\s*hidden)", attrs.get("style", ""), re.I) is not None)
        content = parent.get("content", False) or tag in {"main", "article"} or attrs.get("id") in {"content", "doc-content"}
        if tag == "br" and not hidden:
            self.handle_data(" ")
        if tag in _VOID_TAGS:
            return
        if len(self.stack) >= 128:
            raise ValueError("public benefits markup too deep")
        capture = content and not hidden and (tag in {"p", "li", "tr", "td", "th"} or attrs.get("role") == "region")
        self.stack.append({"tag": tag, "hidden": hidden, "content": content,
                           "parts": [] if capture else None, "cells": []})

    def handle_data(self, value):
        if not self.stack or self.stack[-1]["hidden"]:
            return
        for node in self.stack:
            if node["parts"] is not None:
                node["parts"].append(value)

    def handle_endtag(self, tag):
        if tag in _VOID_TAGS:
            return
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index]["tag"] == tag:
                break
        else:
            return
        if any(node["parts"] is not None for node in self.stack[index + 1:]):
            raise ValueError("unbalanced public benefit block")
        node = self.stack[index]
        del self.stack[index:]
        if node["parts"] is None:
            return
        text = " ".join("".join(node["parts"]).split())
        if tag in {"td", "th"}:
            for parent in reversed(self.stack):
                if parent["tag"] == "tr":
                    parent["cells"].append(text)
                    break
        elif text:
            self.blocks.append({"tag": tag, "text": text, "cells": node["cells"]})
            if len(self.blocks) > 10000:
                raise ValueError("too many public benefit blocks")
        self.handle_data(" ")


_BENEFIT_RULES = {
    "cerebras-public-benefits": (
        "cerebras", "Cerebras \u514d\u8d39\u8bd5\u7528\u91d1\uff08\u9700\u9a8c\u8bc1\u652f\u4ed8\u65b9\u5f0f\uff09",
        re.compile(r"\$[0-9]+(?:\.[0-9]{1,2})? in free credits after adding a verified payment method\. "
                   r"These credits expire [0-9]+ days after they(?:\u2019|')re granted")),
    "cloudflare-public-benefits": (
        "cloudflare", "Cloudflare Workers AI \u6bcf\u65e5\u514d\u8d39\u989d\u5ea6",
        re.compile(r"Our free allocation allows anyone to use a total of [1-9][0-9,]* Neurons per day at no charge\.")),
    "gemini-public-benefits": (
        "gemini", "Gemini API \u514d\u8d39\u5c42",
        re.compile(r"Start building free of charge with generous limits, then scale up with prepaid then "
                   r"pay-as-you-go pricing for your production ready applications\.")),
}


def _public_benefits(body, source_id):
    parser = _BenefitHTML()
    parser.feed(body.decode("utf-8-sig"))
    parser.close()
    if any(node["parts"] is not None for node in parser.stack):
        raise ValueError("incomplete public benefits document")
    evidence = set()
    if source_id == "groq-public-benefits":
        provider_id, title = "groq", "Groq \u516c\u5f00\u514d\u8d39\u5957\u9910\u9650\u989d"
        for block in parser.blocks:
            if (block["tag"] == "tr" and "Free Plan Limits" in block["cells"]
                    and any(re.fullmatch(r"[1-9][0-9,]* (?:requests|tokens) per (?:minute|day)", cell) for cell in block["cells"])):
                evidence.add("; ".join(block["cells"]))
    else:
        provider_id, title, pattern = _BENEFIT_RULES[source_id]
        for block in parser.blocks:
            if block["tag"] in {"p", "div", "li"}:
                match = pattern.search(block["text"])
                if match:
                    evidence.add(match.group())
    if len(evidence) != 1:
        raise ValueError("no unambiguous official free benefit statement")
    label = evidence.pop()
    if len(label) > 160 or _title(label) != label:
        raise ValueError("unsafe or overlong public benefit statement")
    return [_row(title, _SOURCES[source_id][2], "credit-program", label, provider_id)]


_PARSERS = {"bing-ai-free-zh": _rss, "bing-llm-credits-en": _rss, "bing-ai-checkin-zh": _rss,
            "v2ex-share-rss": _rss, "linuxdo-latest-rss": _rss,
            "openrouter-free-models": _openrouter, "siliconflow-public-pricing": _siliconflow,
            "xfyun-public-catalog": _xfyun,
            **{source_id: _public_benefits for source_id in (*_BENEFIT_RULES, "groq-public-benefits")}}


def collect(source_id) -> list[dict]:
    """GET one fixed public source; no credentials, follow-ups or side effects.

    Source IDs are the only input. Mutable exported specs are display metadata,
    not network configuration. Failures are sanitized for downstream display.
    """
    if not isinstance(source_id, str) or source_id not in _SOURCES:
        raise ValueError("unknown benefit source")
    body = _fetch(source_id)
    try:
        rows = _PARSERS[source_id](body, source_id)
        if len(rows) > _MAX_ROWS:
            raise ValueError("too many public observations")
        return rows
    except (ValueError, ElementTree.ParseError, RecursionError, OverflowError, InvalidOperation):
        raise ValueError("invalid public source document") from None
