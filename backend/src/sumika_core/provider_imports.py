"""Provider configuration import adapters.

The canonical profile format belongs to Sumika. External applications are
isolated converters that produce a draft profile and never participate in the
runtime provider path.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
import tomllib
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import parse_qs, urlparse

from .provider_profiles import PROFILE_FORMAT


class ProviderImportError(ValueError):
    """Raised when no safe importer can understand a configuration."""


class ProviderImportAdapter(Protocol):
    id: str

    def accepts(self, raw: str, filename: str | None = None) -> bool: ...

    def parse(self, raw: str, filename: str | None = None) -> "ImportedProvider": ...


@dataclass(slots=True)
class ImportedProvider:
    importer_id: str
    profile: dict[str, Any]
    secrets: dict[str, str]
    field_mapping: list[dict[str, str]]
    unsupported_fields: list[dict[str, str]]
    warnings: list[str]

    def preview(self) -> dict[str, Any]:
        profile = {key: value for key, value in self.profile.items() if key != "secrets"}
        return {
            "format": PROFILE_FORMAT,
            "importer_id": self.importer_id,
            "profile": profile,
            "secret_fields": sorted(self.secrets),
            "masked_secrets": {key: _mask_secret(value) for key, value in self.secrets.items()},
            "field_mapping": list(self.field_mapping),
            "unsupported_fields": list(self.unsupported_fields),
            "warnings": list(self.warnings),
        }


class ProviderImportRegistry:
    def __init__(self) -> None:
        self._adapters: list[ProviderImportAdapter] = [CCSwitchV1Importer(), SumikaProfileV1Importer(), OpenAIConfigImporter()]

    def preview(self, raw: str, filename: str | None = None) -> dict[str, Any]:
        return self.parse(raw, filename).preview()

    def parse(self, raw: str, filename: str | None = None) -> ImportedProvider:
        if not isinstance(raw, str) or not raw.strip():
            raise ProviderImportError("Import text must not be empty")
        if len(raw.encode("utf-8")) > 512 * 1024:
            raise ProviderImportError("Provider import is larger than 512 KiB")
        for adapter in self._adapters:
            if adapter.accepts(raw, filename):
                return adapter.parse(raw, filename)
        raise ProviderImportError("Unsupported provider configuration format")


class CCSwitchV1Importer:
    id = "ccswitch-v1"
    _KNOWN_FIELDS = {
        "resource", "app", "name", "enabled", "homepage", "endpoint", "apiKey",
        "model", "notes", "icon", "config", "configFormat", "configUrl",
        "haikuModel", "sonnetModel", "opusModel", "usageEnabled", "usageScript",
        "usageApiKey", "usageBaseUrl", "usageAccessToken", "usageUserId",
        "usageAutoInterval",
    }
    _KNOWN_EMBEDDED_FIELDS = {
        "base_url", "baseUrl", "api_url", "apiUrl", "model", "api_key", "apiKey",
        "OPENAI_API_KEY", "name", "timeout", "headers", "organization", "project",
        "model_provider", "model_providers", "auth", "env",
    }
    def accepts(self, raw: str, filename: str | None = None) -> bool:
        return raw.lstrip().lower().startswith("ccswitch://")

    def parse(self, raw: str, filename: str | None = None) -> ImportedProvider:
        parsed = urlparse(raw.strip())
        if parsed.scheme.lower() != "ccswitch":
            raise ProviderImportError("CC Switch import must use the ccswitch scheme")
        if parsed.hostname != "v1":
            version = parsed.hostname or "missing"
            raise ProviderImportError(f"Unsupported CC Switch protocol version: {version}")
        if parsed.path != "/import":
            raise ProviderImportError("CC Switch provider link must use /import")
        params = {key: values[-1] for key, values in parse_qs(parsed.query, keep_blank_values=True).items()}
        if params.get("resource") != "provider":
            raise ProviderImportError("Only CC Switch provider imports are supported")
        app = params.get("app", "")
        if app != "codex":
            raise ProviderImportError(f"CC Switch app '{app or 'missing'}' is not an OpenAI-compatible Codex profile")

        embedded: dict[str, Any] = {}
        if params.get("config"):
            embedded = _parse_embedded_config(params["config"], params.get("configFormat"))
        endpoints = _split_endpoints(params.get("endpoint") or _find_value(embedded, "base_url", "baseUrl", "api_url", "apiUrl"))
        model = str(params.get("model") or _find_value(embedded, "model") or "").strip()
        api_key = str(params.get("apiKey") or _find_value(embedded, "api_key", "apiKey", "OPENAI_API_KEY") or "").strip()
        name = str(params.get("name") or "CC Switch 导入").strip()
        secrets = {"api_key": api_key} if api_key else {}
        if params.get("usageApiKey"):
            secrets["usage_api_key"] = params["usageApiKey"]
        if params.get("usageAccessToken"):
            secrets["usage_access_token"] = params["usageAccessToken"]

        unsupported: list[dict[str, str]] = []
        unknown_secrets: dict[str, str] = {}
        for key, value in params.items():
            if key in self._KNOWN_FIELDS:
                continue
            if _looks_sensitive(key):
                # Preserve an unrecognized credential for a later explicit
                # adapter without ever putting its value in SQLite, events, or
                # the import preview. Runtime adapters only consume known
                # fields, so this remains inert metadata until the user edits
                # the profile.
                if value:
                    unknown_secrets[f"source:{_safe_secret_name(key)}"] = value
                unsupported.append({"field": key, "value": "[redacted]"})
            else:
                unsupported.append({"field": key, "value": _bounded(value)})
        for key, value in embedded.items():
            if key in self._KNOWN_EMBEDDED_FIELDS:
                continue
            if _looks_sensitive(key):
                if isinstance(value, str) and value:
                    unknown_secrets[f"source:{_safe_secret_name(key)}"] = value
                unsupported.append({"field": f"config.{key}", "value": "[redacted]"})
            else:
                unsupported.append({"field": f"config.{key}", "value": _bounded(value)})
        usage_metadata: dict[str, Any] | None = None
        warnings: list[str] = []
        if params.get("usageScript"):
            script = _decode_base64(params["usageScript"], "usageScript")
            usage_metadata = {
                "enabled_by_source": params.get("usageEnabled", "false").lower() == "true",
                "execution": "blocked_javascript",
                "sha256": hashlib.sha256(script).hexdigest(),
                "size_bytes": len(script),
            }
            warnings.append("CC Switch JavaScript 用量脚本已禁用；Sumika 不会执行任意脚本。")
        if not endpoints:
            warnings.append("未找到服务端点，配置将保存为草稿。")
        if not model:
            warnings.append("未找到模型名称，配置将保存为草稿。")

        source_metadata = {
            "format": PROFILE_FORMAT,
            "kind": "external-import",
            "importer": self.id,
            "external_protocol": "ccswitch-v1",
            "external_app": app,
            "homepage": _bounded(params.get("homepage", "")),
            "notes": _bounded(params.get("notes", "")),
            "unknown_fields": unsupported,
            "sensitive_fields": sorted(
                key.removeprefix("source:") for key in unknown_secrets
            ),
            "usage_script": usage_metadata,
            "raw_sha256": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
        }
        profile = {
            "name": name,
            "adapter_id": "openai-compatible",
            "template_id": "openai-compatible",
            "processing_location": "auto",
            "base_urls": endpoints,
            "active_base_url": endpoints[0] if endpoints else "",
            "model": model,
            "timeout": 60,
            "headers": embedded.get("headers") if isinstance(embedded.get("headers"), dict) else {},
            "organization": str(embedded.get("organization") or "").strip(),
            "project": str(embedded.get("project") or "").strip(),
            "status": "draft",
            "source": source_metadata,
        }
        mapping = [
            {"source": "name", "target": "name", "status": "mapped"},
            {"source": "endpoint", "target": "base_urls", "status": "mapped" if endpoints else "missing"},
            {"source": "apiKey", "target": "Credential Manager / api_key", "status": "mapped" if api_key else "missing"},
            {"source": "model", "target": "model", "status": "mapped" if model else "missing"},
            {"source": "usageScript", "target": "disabled source metadata", "status": "blocked" if usage_metadata else "absent"},
        ]
        return ImportedProvider(
            self.id,
            profile,
            {**secrets, **unknown_secrets},
            mapping,
            unsupported,
            warnings,
        )


class SumikaProfileV1Importer:
    id = "sumika-profile-v1"

    def accepts(self, raw: str, filename: str | None = None) -> bool:
        if not raw.lstrip().startswith("{"):
            return False
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            return False
        return isinstance(value, dict) and value.get("format") == PROFILE_FORMAT

    def parse(self, raw: str, filename: str | None = None) -> ImportedProvider:
        value = json.loads(raw)
        profile = value.get("profile") if isinstance(value.get("profile"), dict) else value
        secrets = value.get("secrets") if isinstance(value.get("secrets"), dict) else {}
        clean_secrets = {str(key): str(item) for key, item in secrets.items() if isinstance(item, str)}
        result = dict(profile)
        result.pop("secrets", None)
        result["source"] = {"format": PROFILE_FORMAT, "kind": "sumika-import", "raw_sha256": hashlib.sha256(raw.encode()).hexdigest()}
        return ImportedProvider(self.id, result, clean_secrets, [], [], [])


class OpenAIConfigImporter:
    id = "openai-config-v1"

    def accepts(self, raw: str, filename: str | None = None) -> bool:
        stripped = raw.lstrip()
        if stripped.startswith("{") or bool(filename and filename.lower().endswith(".toml")):
            return True
        if "model_providers" in raw:
            return True
        # A pasted TOML document has no filename hint. Only claim it when the
        # standard parser recognizes an object, so ordinary text is rejected by
        # the registry instead of producing a confusing TOML error.
        try:
            return isinstance(tomllib.loads(raw), dict)
        except tomllib.TOMLDecodeError:
            return False

    def parse(self, raw: str, filename: str | None = None) -> ImportedProvider:
        try:
            value = json.loads(raw) if raw.lstrip().startswith("{") else tomllib.loads(raw)
        except (json.JSONDecodeError, tomllib.TOMLDecodeError) as exc:
            raise ProviderImportError(f"Invalid JSON/TOML provider configuration: {exc}") from exc
        if not isinstance(value, dict):
            raise ProviderImportError("Provider configuration must be an object")
        flattened = _flatten_openai_config(value)
        endpoints = _split_endpoints(_find_value(flattened, "base_url", "baseUrl", "api_url", "apiUrl"))
        model = str(_find_value(flattened, "model") or "").strip()
        api_key = str(_find_value(flattened, "api_key", "apiKey", "OPENAI_API_KEY") or "").strip()
        name = str(_find_value(flattened, "name") or "导入的 OpenAI-compatible 连接").strip()
        warnings = []
        if not endpoints or not model:
            warnings.append("配置缺少端点或模型，将作为草稿保存。")
        profile = {
            "name": name,
            "adapter_id": "openai-compatible",
            "template_id": "openai-compatible",
            "processing_location": "auto",
            "base_urls": endpoints,
            "active_base_url": endpoints[0] if endpoints else "",
            "model": model,
            "timeout": 60,
            "status": "draft",
            "source": {"format": PROFILE_FORMAT, "kind": "generic-import", "importer": self.id, "raw_sha256": hashlib.sha256(raw.encode()).hexdigest()},
        }
        mapping = [
            {"source": "base_url", "target": "base_urls", "status": "mapped" if endpoints else "missing"},
            {"source": "api_key", "target": "Credential Manager / api_key", "status": "mapped" if api_key else "missing"},
            {"source": "model", "target": "model", "status": "mapped" if model else "missing"},
        ]
        return ImportedProvider(self.id, profile, {"api_key": api_key} if api_key else {}, mapping, [], warnings)


def _parse_embedded_config(value: str, format_hint: str | None) -> dict[str, Any]:
    decoded = _decode_base64(value, "config")
    text = decoded.decode("utf-8", errors="strict")
    try:
        if (format_hint or "").lower() == "json" or text.lstrip().startswith("{"):
            parsed = json.loads(text)
        else:
            parsed = tomllib.loads(text)
    except (json.JSONDecodeError, tomllib.TOMLDecodeError) as exc:
        raise ProviderImportError(f"Invalid embedded CC Switch configuration: {exc}") from exc
    return _flatten_openai_config(parsed) if isinstance(parsed, dict) else {}


def _decode_base64(value: str, field: str) -> bytes:
    padded = value + "=" * (-len(value) % 4)
    try:
        return base64.urlsafe_b64decode(padded.encode("ascii"))
    except (binascii.Error, ValueError, UnicodeEncodeError) as exc:
        raise ProviderImportError(f"Invalid base64 in {field}") from exc


def _flatten_openai_config(value: dict[str, Any]) -> dict[str, Any]:
    result = dict(value)
    provider_id = value.get("model_provider")
    providers = value.get("model_providers")
    if isinstance(providers, dict):
        provider = providers.get(provider_id) if provider_id in providers else next((item for item in providers.values() if isinstance(item, dict)), None)
        if isinstance(provider, dict):
            result.update(provider)
    auth = value.get("auth")
    if isinstance(auth, dict):
        result.update(auth)
    env = value.get("env")
    if isinstance(env, dict):
        result.update(env)
    return result


def _find_value(value: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in value and value[key] not in (None, ""):
            return value[key]
    return None


def _split_endpoints(value: Any) -> list[str]:
    values = value if isinstance(value, list) else str(value or "").split(",")
    result: list[str] = []
    for item in values:
        endpoint = str(item).strip().rstrip("/")
        if endpoint and endpoint not in result:
            parsed = urlparse(endpoint)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
                raise ProviderImportError(f"Invalid HTTP(S) provider endpoint: {endpoint}")
            result.append(endpoint)
    return result


def _mask_secret(value: str) -> str:
    if len(value) <= 6:
        return "*" * len(value)
    return f"{value[:4]}{'*' * min(16, len(value) - 6)}{value[-2:]}"


def _looks_sensitive(name: str) -> bool:
    lowered = name.lower()
    return any(token in lowered for token in ("key", "token", "secret", "authorization", "cookie"))


def _safe_secret_name(value: str) -> str:
    """Bound a source field name before it becomes a credential sub-key."""
    cleaned = re.sub(r"[^A-Za-z0-9_.:-]+", "_", str(value)).strip("._:")
    return (cleaned[:80] or "unknown")


def _bounded(value: str, limit: int = 240) -> str:
    text = re.sub(r"[\r\n]+", " ", str(value or "")).strip()
    return text if len(text) <= limit else f"{text[:limit]}..."
