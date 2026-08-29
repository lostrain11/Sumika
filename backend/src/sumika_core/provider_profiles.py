"""Saved provider profiles independent from runtime adapter implementations."""

from __future__ import annotations

import ipaddress
import hashlib
import json
import re
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

from .credentials import CredentialError, CredentialStore
from .providers.openai_compatible import OpenAICompatibleProvider
from .storage import Storage


PROFILE_FORMAT = "sumika-provider-profile/v1"
CREDENTIAL_REVISION_KEY = "credential_revision"
LEGACY_OLLAMA_PROFILE_ID = "local-ollama"
LEGACY_OPENAI_PROFILE_ID = "legacy-openai-compatible"
SENSITIVE_HEADER_NAMES = {
    "authorization",
    "proxy-authorization",
    "x-api-key",
    "api-key",
    "cookie",
    "set-cookie",
}

PROVIDER_TEMPLATES: tuple[dict[str, Any], ...] = (
    {"id": "ollama", "name": "Ollama", "base_url": "http://127.0.0.1:11434/v1", "model": "qwen3:4b", "processing_location": "local"},
    {"id": "lm-studio", "name": "LM Studio", "base_url": "http://127.0.0.1:1234/v1", "model": "", "processing_location": "local"},
    {"id": "llama-cpp", "name": "llama.cpp server", "base_url": "http://127.0.0.1:8080/v1", "model": "", "processing_location": "local"},
    {"id": "vllm", "name": "vLLM", "base_url": "http://127.0.0.1:8000/v1", "model": "", "processing_location": "local"},
    {"id": "localai", "name": "LocalAI", "base_url": "http://127.0.0.1:8080/v1", "model": "", "processing_location": "local"},
    {"id": "openai", "name": "OpenAI", "base_url": "https://api.openai.com/v1", "model": "", "processing_location": "cloud"},
    {"id": "openrouter", "name": "OpenRouter", "base_url": "https://openrouter.ai/api/v1", "model": "", "processing_location": "cloud"},
    {"id": "deepseek", "name": "DeepSeek", "base_url": "https://api.deepseek.com/v1", "model": "", "processing_location": "cloud"},
    {"id": "siliconflow", "name": "SiliconFlow", "base_url": "https://api.siliconflow.cn/v1", "model": "", "processing_location": "cloud"},
    {
        "id": "zhipu-bigmodel",
        "name": "智谱 BigModel",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "model": "glm-4.5-air",
        "model_options": ["glm-4.5-air", "glm-4.7", "glm-4.6v"],
        "processing_location": "cloud",
    },
    {"id": "openai-compatible", "name": "通用 OpenAI-compatible", "base_url": "", "model": "", "processing_location": "auto"},
)
_TEMPLATES = {item["id"]: item for item in PROVIDER_TEMPLATES}


class ProviderProfileError(ValueError):
    """Raised when a provider profile cannot be saved or used."""


class ProviderProfileManager:
    def __init__(self, storage: Storage, credentials: CredentialStore) -> None:
        self.storage = storage
        self.credentials = credentials

    def templates(self) -> list[dict[str, Any]]:
        return [dict(item) for item in PROVIDER_TEMPLATES]

    def ensure_legacy_profile(self, legacy_config: dict[str, Any] | None = None) -> dict[str, Any]:
        config = dict(legacy_config or {})
        base_url = str(config.get("base_url") or "").strip()
        is_ollama = _is_local_ollama_url(base_url)
        profile_id = LEGACY_OLLAMA_PROFILE_ID if is_ollama else LEGACY_OPENAI_PROFILE_ID
        existing = self.storage.get_provider_profile(profile_id)
        if existing is not None:
            return self.public(existing)
        payload = {
            "id": profile_id,
            "name": "本地 Ollama" if is_ollama else "迁移的 OpenAI-compatible 连接",
            "adapter_id": "openai-compatible",
            "template_id": "ollama" if is_ollama else "openai-compatible",
            "processing_location": "local" if is_ollama else "auto",
            "base_urls": [base_url],
            "active_base_url": base_url,
            "model": config.get("model") or "",
            "timeout": config.get("timeout", 60),
            "status": "unavailable",
            "source": {"format": PROFILE_FORMAT, "kind": "migration", "adapter": "builtin"},
        }
        return self.save(payload)

    def list(self, *, include_archived: bool = False) -> list[dict[str, Any]]:
        return [
            self.public(profile)
            for profile in self.storage.list_provider_profiles(
                capability="llm", include_archived=include_archived
            )
        ]

    def get(self, profile_id: str, *, include_secrets: bool = False) -> dict[str, Any]:
        profile = self.storage.get_provider_profile(profile_id)
        if profile is None:
            raise ProviderProfileError(f"Unknown provider profile: {profile_id}")
        result = self.public(profile)
        if include_secrets:
            result["secrets"] = self._read_secrets(profile)
        return result

    def save(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ProviderProfileError("Provider profile must be an object")
        profile_id = _profile_id(payload.get("id"))
        existing = self.storage.get_provider_profile(profile_id)
        name = str(payload.get("name") or (existing or {}).get("name") or "").strip()
        if not name or len(name) > 80:
            raise ProviderProfileError("Profile name must contain 1 to 80 characters")
        adapter_id = str(payload.get("adapter_id") or (existing or {}).get("adapter_id") or "openai-compatible")
        if adapter_id != "openai-compatible":
            raise ProviderProfileError(f"Unsupported provider adapter: {adapter_id}")
        template_id = str(payload.get("template_id") or (existing or {}).get("template_id") or "openai-compatible")
        if template_id not in _TEMPLATES:
            template_id = "openai-compatible"
        existing_config = dict((existing or {}).get("config") or {})
        config, detected_secrets = _normalize_config(payload, existing_config, _TEMPLATES[template_id])
        # Only a successful health check can mark a profile available. Editing
        # a complete profile makes it unavailable until it is tested again.
        status = "unavailable"
        if not config.get("active_base_url") or not config.get("model"):
            status = "draft"
        processing_location = str(
            payload.get("processing_location")
            or (existing or {}).get("processing_location")
            or _TEMPLATES[template_id]["processing_location"]
        )
        if processing_location not in {"auto", "local", "cloud"}:
            raise ProviderProfileError("processing_location must be auto, local, or cloud")

        credential_ref = str((existing or {}).get("credential_ref") or profile_id)
        existing_secrets = self._read_secrets(existing) if existing else {}
        secrets = dict(existing_secrets)
        supplied_secrets = payload.get("secrets") if isinstance(payload.get("secrets"), dict) else {}
        api_key = payload.get("api_key")
        if isinstance(api_key, str):
            supplied_secrets = {**supplied_secrets, "api_key": api_key}
        for key, value in {**detected_secrets, **supplied_secrets}.items():
            if isinstance(key, str) and isinstance(value, str):
                if value:
                    secrets[key] = value
                elif key in secrets:
                    secrets.pop(key)
        clear_secrets = payload.get("clear_secrets")
        if isinstance(clear_secrets, list):
            for key in clear_secrets:
                secrets.pop(str(key), None)
        if secrets:
            if existing is not None and secrets == existing_secrets:
                config[CREDENTIAL_REVISION_KEY] = provider_credential_revision(existing)
            else:
                config[CREDENTIAL_REVISION_KEY] = uuid4().hex
        else:
            config.pop(CREDENTIAL_REVISION_KEY, None)
        try:
            self.credentials.write(credential_ref, secrets)
        except CredentialError as exc:
            raise ProviderProfileError(str(exc)) from exc

        source = _redact_source(payload.get("source") or (existing or {}).get("source") or {"format": PROFILE_FORMAT, "kind": "manual"})
        profile = self.storage.upsert_provider_profile(
            profile_id=profile_id,
            name=name,
            capability="llm",
            adapter_id=adapter_id,
            template_id=template_id,
            processing_location=processing_location,
            status=status,
            config=config,
            credential_ref=credential_ref if secrets else None,
            secret_fields=sorted(secrets),
            source=source,
        )
        return self.public(profile)

    def health(self, profile_id: str, *, allow_chat_probe: bool = False) -> dict[str, Any]:
        profile = self.storage.get_provider_profile(profile_id)
        if profile is None or profile.get("archived_at"):
            raise ProviderProfileError(f"Unknown active provider profile: {profile_id}")
        if not profile["config"].get("active_base_url") or not profile["config"].get("model"):
            updated = self.storage.update_provider_profile_state(profile_id, status="draft")
            return {"ok": False, "profile": self.public(updated or profile), "error": "Profile is incomplete"}
        provider = self.runtime(profile_id)
        result = provider.health_check(allow_chat_probe=allow_chat_probe)
        # Passive catalog refreshes must not invalidate a profile that passed
        # an explicit chat probe merely because its gateway omits GET /models.
        # Network/authentication failures still update the profile normally.
        catalog_missing = (
            result.get("status") == "unconfigured"
            and result.get("error") == "model catalogue unavailable; run an explicit connection test"
        )
        if catalog_missing and profile.get("status") == "available":
            return {
                **result,
                "ok": True,
                "status": "available",
                "model_catalog": "not-exposed",
                "profile_id": profile_id,
                "profile": self.public(profile),
            }
        status = "available" if result.get("ok") else "unavailable"
        updated = self.storage.update_provider_profile_state(profile_id, status=status)
        return {**result, "profile_id": profile_id, "profile": self.public(updated or profile)}

    def runtime(self, profile_id: str) -> OpenAICompatibleProvider:
        profile = self.storage.get_provider_profile(profile_id)
        if profile is None or profile.get("archived_at"):
            raise ProviderProfileError(f"Unknown active provider profile: {profile_id}")
        config = profile["config"]
        secrets = self._read_secrets(profile)
        headers = dict(config.get("headers") or {})
        headers.update(secrets.get("headers") if isinstance(secrets.get("headers"), dict) else {})
        # Secret headers are stored as individual entries for simple audit.
        for key, value in secrets.items():
            if key.startswith("header:"):
                headers[key.removeprefix("header:")] = value
        return OpenAICompatibleProvider(
            base_url=str(config.get("active_base_url") or ""),
            model=str(config.get("model") or ""),
            api_key=secrets.get("api_key"),
            timeout=float(config.get("timeout") or 60),
            headers=headers,
            ollama=profile.get("template_id") == "ollama",
        )

    def mark_used(self, profile_id: str) -> dict[str, Any]:
        profile = self.storage.update_provider_profile_state(profile_id, mark_used=True)
        if profile is None:
            raise ProviderProfileError(f"Unknown provider profile: {profile_id}")
        return self.public(profile)

    def archive(self, profile_id: str) -> dict[str, Any]:
        profile = self.storage.update_provider_profile_state(profile_id, archived=True)
        if profile is None:
            raise ProviderProfileError(f"Unknown provider profile: {profile_id}")
        return self.public(profile)

    def restore(self, profile_id: str) -> dict[str, Any]:
        profile = self.storage.update_provider_profile_state(profile_id, archived=False)
        if profile is None:
            raise ProviderProfileError(f"Unknown provider profile: {profile_id}")
        return self.public(profile)

    def validate_snapshot_profiles(self, rows: list[dict[str, Any]]) -> None:
        for row in rows:
            profile_id = str(row.get("id") or "")
            _profile_id(profile_id)
            if row.get("adapter_id") != "openai-compatible":
                raise ProviderProfileError(f"Unsupported provider adapter in snapshot: {row.get('adapter_id')}")
            if row.get("capability") != "llm":
                raise ProviderProfileError("Provider snapshot capability must be llm")
            if row.get("status") not in {"draft", "available", "unavailable", "archived"}:
                raise ProviderProfileError("Invalid provider profile status in snapshot")
            if row.get("processing_location") not in {"auto", "local", "cloud"}:
                raise ProviderProfileError("Invalid provider processing location in snapshot")
            credential_ref = row.get("credential_ref")
            if credential_ref not in {None, profile_id}:
                raise ProviderProfileError("Provider snapshot credential reference must match its profile id")
            try:
                config = json.loads(row.get("config_json", "{}"))
                secret_fields = json.loads(row.get("secret_fields_json", "[]"))
                source = json.loads(row.get("source_json", "{}"))
            except json.JSONDecodeError as exc:
                raise ProviderProfileError("Provider snapshot contains invalid JSON") from exc
            if not isinstance(config, dict) or not isinstance(source, dict):
                raise ProviderProfileError("Provider snapshot config and source must be objects")
            if not isinstance(secret_fields, list) or not all(isinstance(item, str) for item in secret_fields):
                raise ProviderProfileError("Provider snapshot secret_fields must be an array of names")
            _normalize_config(config, {}, _TEMPLATES.get(str(row.get("template_id")), _TEMPLATES["openai-compatible"]))
            if _contains_unredacted_secret(source):
                raise ProviderProfileError("Provider snapshot source metadata contains an unredacted secret")

    def public(self, profile: dict[str, Any]) -> dict[str, Any]:
        result = {key: value for key, value in profile.items() if key != "credential_ref"}
        result["has_secrets"] = bool(profile.get("secret_fields"))
        result["resolved_processing_location"] = resolve_processing_location(
            str(profile.get("processing_location") or "auto"),
            str(profile.get("config", {}).get("active_base_url") or ""),
        )
        return result

    def _read_secrets(self, profile: dict[str, Any] | None) -> dict[str, Any]:
        reference = str((profile or {}).get("credential_ref") or "")
        if not reference:
            return {}
        try:
            return self.credentials.read(reference)
        except CredentialError as exc:
            raise ProviderProfileError(str(exc)) from exc


def resolve_processing_location(selection: str, base_url: str) -> str:
    if selection in {"local", "cloud"}:
        return selection
    parsed = urlparse(base_url)
    host = (parsed.hostname or "").lower()
    if host in {"localhost", "::1"} or host.endswith(".local"):
        return "local"
    try:
        address = ipaddress.ip_address(host)
        return "local" if address.is_loopback or address.is_private or address.is_link_local else "cloud"
    except ValueError:
        return "cloud"


def provider_credential_revision(profile: dict[str, Any]) -> str:
    """Return a non-secret revision that changes whenever profile secrets change."""

    config = profile.get("config") if isinstance(profile.get("config"), dict) else {}
    explicit = str(config.get(CREDENTIAL_REVISION_KEY) or "").strip().lower()
    if re.fullmatch(r"[a-f0-9]{16,64}", explicit):
        return explicit
    profile_id = str(profile.get("id") or "")
    created_at = str(profile.get("created_at") or "legacy")
    return hashlib.sha256(f"{profile_id}\0{created_at}".encode("utf-8")).hexdigest()[:32]


def _is_local_ollama_url(base_url: str) -> bool:
    parsed = urlparse(base_url)
    host = (parsed.hostname or "").lower()
    return (
        host in {"127.0.0.1", "localhost", "::1"}
        and parsed.port == 11434
        and parsed.path.rstrip("/") in {"", "/v1"}
    )


def _profile_id(value: Any) -> str:
    if value is None or not str(value).strip():
        return str(uuid4())
    profile_id = str(value).strip()
    if len(profile_id) > 96 or not all(character.isalnum() or character in "-_." for character in profile_id):
        raise ProviderProfileError("Invalid provider profile id")
    return profile_id


def _normalize_config(
    payload: dict[str, Any],
    existing: dict[str, Any],
    template: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, str]]:
    nested = payload.get("config") if isinstance(payload.get("config"), dict) else {}
    # Public Sumika profile exports keep connection fields under ``config``;
    # manual drawer submissions keep them at the top level. Accept both while
    # letting explicit top-level edits win.
    values = {**nested, **payload}
    raw_urls = values.get("base_urls")
    if raw_urls is None:
        single = values.get("base_url") or values.get("active_base_url")
        raw_urls = [single] if single is not None else existing.get("base_urls") or [template.get("base_url", "")]
    if not isinstance(raw_urls, list):
        raise ProviderProfileError("base_urls must be an array")
    base_urls: list[str] = []
    for value in raw_urls:
        text = str(value or "").strip().rstrip("/")
        if not text:
            continue
        _validate_url(text)
        if text not in base_urls:
            base_urls.append(text)
    active = str(values.get("active_base_url") or values.get("base_url") or existing.get("active_base_url") or (base_urls[0] if base_urls else "")).strip().rstrip("/")
    if active:
        _validate_url(active)
        if active not in base_urls:
            base_urls.insert(0, active)
    model = str(values.get("model") if "model" in values else existing.get("model", template.get("model", ""))).strip()
    timeout_value = values.get("timeout", existing.get("timeout", 60))
    if isinstance(timeout_value, bool) or not isinstance(timeout_value, (int, float)) or not 1 <= float(timeout_value) <= 300:
        raise ProviderProfileError("timeout must be between 1 and 300 seconds")
    raw_headers = values.get("headers", existing.get("headers", {}))
    if not isinstance(raw_headers, dict):
        raise ProviderProfileError("headers must be an object")
    headers: dict[str, str] = {}
    secrets: dict[str, str] = {}
    for raw_name, raw_value in raw_headers.items():
        name = str(raw_name).strip()
        value = str(raw_value)
        if not name or any(character in name for character in "\r\n") or any(character in value for character in "\r\n"):
            raise ProviderProfileError("Header names and values must be single-line strings")
        if _is_sensitive_header(name):
            secrets[f"header:{name}"] = value
        else:
            headers[name] = value
    usage_query = values.get("usage_query", existing.get("usage_query"))
    if usage_query is not None:
        usage_query = _validate_usage_query(usage_query)
    return {
        "format": PROFILE_FORMAT,
        "base_urls": base_urls,
        "active_base_url": active,
        "model": model,
        "timeout": float(timeout_value),
        "headers": headers,
        "organization": str(values.get("organization", existing.get("organization", ""))).strip(),
        "project": str(values.get("project", existing.get("project", ""))).strip(),
        "usage_query": usage_query,
    }, secrets


def _validate_url(value: str) -> None:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ProviderProfileError(f"Invalid HTTP(S) provider URL: {value}")
    if parsed.username or parsed.password:
        raise ProviderProfileError("Provider URLs must not embed credentials")


def _is_sensitive_header(name: str) -> bool:
    lowered = name.lower()
    return lowered in SENSITIVE_HEADER_NAMES or any(token in lowered for token in ("token", "secret", "api-key", "apikey"))


def _validate_usage_query(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ProviderProfileError("usage_query must be an object")
    if any(key in value for key in ("script", "javascript", "function", "code")):
        raise ProviderProfileError("Executable usage scripts are not supported")
    method = str(value.get("method") or "GET").upper()
    if method not in {"GET", "POST"}:
        raise ProviderProfileError("usage_query method must be GET or POST")
    url = str(value.get("url") or "").strip()
    if url and "{{baseUrl}}" not in url:
        _validate_url(url)
    fields = value.get("fields") or {}
    if not isinstance(fields, dict) or not all(isinstance(key, str) and isinstance(item, str) for key, item in fields.items()):
        raise ProviderProfileError("usage_query fields must map labels to JSON paths")
    return {"enabled": bool(value.get("enabled", False)), "method": method, "url": url, "fields": fields}


def _redact_source(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {"format": PROFILE_FORMAT, "kind": "manual"}
    result: dict[str, Any] = {}
    for key, item in value.items():
        lowered = str(key).lower()
        if any(token in lowered for token in ("key", "token", "secret", "authorization", "cookie")):
            result[str(key)] = "[redacted]"
        elif isinstance(item, (str, int, float, bool)) or item is None:
            result[str(key)] = item
        elif isinstance(item, list):
            result[str(key)] = [entry for entry in item if isinstance(entry, (str, int, float, bool)) or entry is None]
        elif isinstance(item, dict):
            result[str(key)] = _redact_source(item)
    result.setdefault("format", PROFILE_FORMAT)
    return result


def _contains_unredacted_secret(value: dict[str, Any]) -> bool:
    for key, item in value.items():
        lowered = str(key).lower()
        if any(token in lowered for token in ("key", "token", "secret", "authorization", "cookie")):
            if item is not None and item != "" and item != "[redacted]":
                return True
        elif isinstance(item, dict) and _contains_unredacted_secret(item):
            return True
    return False
