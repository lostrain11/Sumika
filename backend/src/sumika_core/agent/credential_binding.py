"""Read the active Provider secret for a managed Agent runtime launch."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path

from ..credentials import (
    CredentialStore,
    credential_namespace_for_data_dir,
    default_credential_store,
)
from ..provider_profiles import provider_credential_revision
from .adapters.dsh.mcp_config import load_mcp_launch_bindings


LAUNCH_PROTOCOL_MAGIC = b"SUMIKA_DSH_CREDENTIAL_V2"
LOCAL_DSH_CREDENTIAL_REF = "SUMIKA_LOCAL_PROVIDER_API_KEY"
LOCAL_DSH_CREDENTIAL_VALUE = "sumika-local"
_MAX_LAUNCH_BINDINGS = 33
_MAX_LAUNCH_PAYLOAD_BYTES = 24 * 1024


class CredentialBindingError(RuntimeError):
    """Raised when the active secure credential cannot be prepared safely."""


@dataclass(frozen=True, slots=True)
class DSHCredentialBinding:
    environment_name: str
    value: str


def dsh_route_id(profile_id: str) -> str:
    slug = "".join(
        character if character.isascii() and (character.isalnum() or character == "-") else "-"
        for character in profile_id.lower()
    ).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    if not slug:
        slug = hashlib.sha256(profile_id.encode("utf-8")).hexdigest()[:12]
    digest = hashlib.sha256(profile_id.encode("utf-8")).hexdigest()[:10]
    return f"sumika-{slug[:48]}-{digest}"


def dsh_remote_credential_ref(profile: dict[str, object]) -> str:
    route_id = dsh_route_id(str(profile.get("id") or ""))
    revision = provider_credential_revision(profile)
    digest = hashlib.sha256(f"{route_id}\0{revision}".encode("utf-8")).hexdigest()[:16].upper()
    return f"SUMIKA_{digest}_API_KEY"


def load_active_dsh_credential_binding(
    data_dir: str | Path,
    *,
    credential_store: CredentialStore | None = None,
) -> DSHCredentialBinding | None:
    """Load only the enabled LLM profile's API key from secure storage."""

    resolved_dir = Path(data_dir).resolve()
    database = resolved_dir / "sumika.sqlite3"
    if not database.is_file():
        return None
    connection = sqlite3.connect(f"{database.as_uri()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        module = connection.execute(
            "SELECT enabled, implementation_id, config_json FROM module_settings WHERE module_id='llm'"
        ).fetchone()
        if module is None or not bool(module["enabled"]) or module["implementation_id"] != "openai-compatible":
            return None
        module_config = _json_object(module["config_json"], "LLM module config")
        profile_id = str(module_config.get("profile_id") or "").strip()
        if not profile_id:
            return None
        profile = connection.execute(
            """
            SELECT id, config_json, credential_ref, secret_fields_json, created_at
            FROM provider_profiles
            WHERE id=? AND archived_at IS NULL AND status='available'
            """,
            (profile_id,),
        ).fetchone()
        if profile is None:
            return None
        secret_fields = _json_array(profile["secret_fields_json"], "Provider secret fields")
        credential_ref = str(profile["credential_ref"] or "")
        if "api_key" not in secret_fields or not credential_ref:
            return None
        store = credential_store or default_credential_store(
            namespace=credential_namespace_for_data_dir(resolved_dir)
        )
        api_key = store.read(credential_ref).get("api_key")
        if not isinstance(api_key, str) or not api_key:
            raise CredentialBindingError("active Provider API key is missing from secure storage")
        if "\0" in api_key:
            raise CredentialBindingError("active Provider API key cannot be represented in an environment block")
        profile_view: dict[str, object] = {
            "id": profile["id"],
            "config": _json_object(profile["config_json"], "Provider config"),
            "created_at": profile["created_at"],
        }
        return DSHCredentialBinding(dsh_remote_credential_ref(profile_view), api_key)
    except sqlite3.Error as exc:
        raise CredentialBindingError("Provider configuration database could not be read") from exc
    finally:
        connection.close()


def load_dsh_launch_bindings(
    data_dir: str | Path,
    profile_dir: str | Path,
    *,
    credential_store: CredentialStore | None = None,
) -> list[DSHCredentialBinding]:
    """Load Provider and managed MCP credentials for one private DSH launch."""

    resolved_dir = Path(data_dir).resolve()
    store = credential_store or default_credential_store(
        namespace=credential_namespace_for_data_dir(resolved_dir)
    )
    result: list[DSHCredentialBinding] = []
    provider = load_active_dsh_credential_binding(resolved_dir, credential_store=store)
    if provider is not None:
        result.append(provider)
    try:
        mcp_bindings = load_mcp_launch_bindings(profile_dir, store)
    except Exception as exc:
        raise CredentialBindingError("managed MCP credentials could not be prepared") from exc
    result.extend(DSHCredentialBinding(name, value) for name, value in mcp_bindings)
    if len(result) > _MAX_LAUNCH_BINDINGS:
        raise CredentialBindingError("too many protected credentials for one DSH launch")
    names: set[str] = set()
    for binding in result:
        if binding.environment_name in names:
            raise CredentialBindingError("protected DSH credential names are not unique")
        names.add(binding.environment_name)
    return result


def encode_launch_bindings(bindings: list[DSHCredentialBinding]) -> bytes:
    if len(bindings) > _MAX_LAUNCH_BINDINGS:
        raise CredentialBindingError("too many protected credentials for one DSH launch")
    fields: list[bytes] = [LAUNCH_PROTOCOL_MAGIC, b"loaded", str(len(bindings)).encode("ascii")]
    names: set[str] = set()
    for binding in bindings:
        try:
            name = binding.environment_name.encode("ascii")
            value = binding.value.encode("utf-8")
        except (UnicodeEncodeError, AttributeError) as exc:
            raise CredentialBindingError("protected DSH credential cannot be encoded") from exc
        if (
            not name
            or binding.environment_name in names
            or b"\0" in name
            or not value
            or b"\0" in value
        ):
            raise CredentialBindingError("protected DSH credential metadata is invalid")
        names.add(binding.environment_name)
        fields.extend((name, value))
    fields.append(b"")
    payload = b"\0".join(fields)
    if len(payload) > _MAX_LAUNCH_PAYLOAD_BYTES:
        raise CredentialBindingError("protected DSH credential payload is too large")
    return payload


def encode_launch_binding(binding: DSHCredentialBinding | None) -> bytes:
    """Compatibility wrapper used by focused Provider bridge tests."""

    return encode_launch_bindings([] if binding is None else [binding])


def _json_object(value: str, label: str) -> dict[str, object]:
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError as exc:
        raise CredentialBindingError(f"{label} is invalid") from exc
    if not isinstance(decoded, dict):
        raise CredentialBindingError(f"{label} is invalid")
    return decoded


def _json_array(value: str, label: str) -> list[object]:
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError as exc:
        raise CredentialBindingError(f"{label} is invalid") from exc
    if not isinstance(decoded, list):
        raise CredentialBindingError(f"{label} is invalid")
    return decoded


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare protected credentials for one DSH launch")
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--profile-dir", required=True)
    args = parser.parse_args()
    try:
        bindings = load_dsh_launch_bindings(args.data_dir, args.profile_dir)
    except Exception as exc:  # The parent receives only a type, never a secret or path.
        print(f"credential bridge failed: {type(exc).__name__}", file=sys.stderr)
        raise SystemExit(1) from None
    sys.stdout.buffer.write(encode_launch_bindings(bindings))


if __name__ == "__main__":
    main()
