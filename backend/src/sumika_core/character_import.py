"""Import community character cards into Sumika persona configs.

Supported containers and specs follow the community card standards used by
SillyTavern-compatible frontends (character-card-spec-v2 and charx-card-specs):

- JSON text: legacy V1 flat cards, ``chara_card_v2`` (spec_version 2.x) and
  ``chara_card_v3`` objects.
- PNG bytes: base64 card JSON embedded in a ``tEXt`` chunk with keyword
  ``chara`` (V2) or ``ccv3`` (V3, preferred when both are present).
- CHARX bytes: ZIP archive with a ``card.json`` member.

The mapping is a generic projection onto the Sumika persona fields; anything
that has no runtime counterpart (world book entries, assets) is preserved in
the ``card_import`` config key so a later re-import or the future Agent-channel
persona bridge can use the untouched original card.
"""

from __future__ import annotations

import base64
import binascii
import io
import json
import re
import struct
import zipfile
from datetime import datetime, timezone
from typing import Any

from .persona import PERSONA_TEXT_LIMITS

_HEX_COLOR = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
ACCENT_EXTENSION_KEYS = ("theme_color", "accent_color", "accent")

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
ZIP_SIGNATURE = b"PK\x03\x04"
CARD_SPEC_V2 = "chara_card_v2"
CARD_SPEC_V3 = "chara_card_v3"
SUPPORTED_SPECS = (CARD_SPEC_V2, CARD_SPEC_V3)
CARD_JSON_MEMBER = "card.json"
CHARX_MAX_CARD_BYTES = 16_000_000


class CharacterCardError(ValueError):
    """Raised when a character card cannot be parsed or does not fit the persona contract."""


def parse_card_text(text: str) -> dict[str, Any]:
    """Parse raw JSON card text (V1 flat, V2, or V3 object)."""
    if not isinstance(text, str) or not text.strip():
        raise CharacterCardError("character card text is empty")
    try:
        card = json.loads(text)
    except json.JSONDecodeError as exc:
        raise CharacterCardError(f"character card is not valid JSON: {exc.msg}") from exc
    if not isinstance(card, dict):
        raise CharacterCardError("character card must be a JSON object")
    return card


def parse_card_bytes(data: bytes) -> dict[str, Any]:
    """Parse card file bytes: PNG (embedded tEXt), CHARX (zip), or raw JSON."""
    if not isinstance(data, (bytes, bytearray)) or not data:
        raise CharacterCardError("character card file is empty")
    data = bytes(data)
    if data.startswith(PNG_SIGNATURE):
        return _decode_png_card(data)
    if data.startswith(ZIP_SIGNATURE):
        return _decode_charx_card(data)
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CharacterCardError(
            "character card file is neither PNG, CHARX, nor UTF-8 JSON"
        ) from exc
    return parse_card_text(text)


def normalize_card(card: dict[str, Any]) -> dict[str, Any]:
    """Validate the card envelope and return its data object plus metadata."""
    if not isinstance(card, dict):
        raise CharacterCardError("character card must be a JSON object")
    spec = card.get("spec")
    if spec is None:
        data = card
        spec, spec_version = "v1", None
    elif spec in SUPPORTED_SPECS:
        data = card.get("data")
        if not isinstance(data, dict):
            raise CharacterCardError(f"{spec} card is missing its data object")
        raw_version = card.get("spec_version")
        spec_version = str(raw_version).strip() if isinstance(raw_version, str) and raw_version.strip() else None
        if spec == CARD_SPEC_V2 and spec_version and not spec_version.startswith("2"):
            raise CharacterCardError(
                f"chara_card_v2 requires spec_version 2.x, got {spec_version!r}"
            )
    else:
        supported = ", ".join((*SUPPORTED_SPECS, "legacy V1 flat cards"))
        raise CharacterCardError(f"unsupported character card spec {spec!r}; supported: {supported}")
    name = data.get("name")
    if not isinstance(name, str) or not name.strip():
        raise CharacterCardError("character card is missing a usable name")
    return {
        "name": name.strip(),
        "spec": spec,
        "spec_version": spec_version,
        "data": data,
        "book_entries": _count_book_entries(data),
    }


def convert_character_card(
    card: dict[str, Any],
    *,
    character_name: str | None = None,
    imported_at: str | None = None,
) -> dict[str, Any]:
    """Project a community card onto a Sumika character config.

    Returns ``{"name", "config", "warnings", "book_entries", "mapped"}``.
    Raises :class:`CharacterCardError` when a persona field would exceed its
    limit; nothing is truncated silently.
    """
    normalized = normalize_card(card)
    name = (character_name or normalized["name"]).strip()
    if not name:
        raise CharacterCardError("character name must not be empty")
    data = normalized["data"]
    warnings: list[str] = []

    persona: dict[str, Any] = {
        "identity": _card_text(data.get("description")),
        "traits": _card_text(data.get("personality")),
        "relationship": _replace_placeholders(_card_text(data.get("scenario")), name),
        "speaking_style": "",
        "behavior": "",
        "boundaries": "",
        "response_length": "balanced",
        "system_prompt": _card_text(data.get("system_prompt")),
        "greeting": _replace_placeholders(_card_text(data.get("first_mes")), name),
    }
    _merge_examples(persona, data, name, warnings)
    _check_limits(persona)

    book_entries = normalized["book_entries"]
    if book_entries:
        warnings.append(
            f"character_book has {book_entries} entries; keyword-triggered lorebook injection "
            "is not implemented, the entries are preserved in config.card_import"
        )

    config: dict[str, Any] = {
        "persona": persona,
        "card_import": {
            "spec": normalized["spec"],
            "spec_version": normalized["spec_version"],
            "imported_at": imported_at or _utc_now(),
            "warnings": list(warnings),
            "card": data,
        },
    }
    accent = _card_accent(data)
    if accent:
        # Community cards sometimes carry a theme color in data.extensions.
        # It maps to the per-character UI accent; the repo default stays
        # neutral when the field is absent or malformed.
        config["theme"] = {"accent": accent}
    return {
        "name": name,
        "config": config,
        "warnings": warnings,
        "book_entries": book_entries,
        "mapped": {key: len(value) for key, value in persona.items() if key in PERSONA_TEXT_LIMITS},
    }


def _decode_png_card(data: bytes) -> dict[str, Any]:
    embedded: dict[str, bytes] = {}
    offset = len(PNG_SIGNATURE)
    while offset + 8 <= len(data):
        (length,) = struct.unpack(">I", data[offset : offset + 4])
        chunk_type = data[offset + 4 : offset + 8]
        chunk = data[offset + 8 : offset + 8 + length]
        if chunk_type == b"tEXt":
            keyword, separator, text = chunk.partition(b"\x00")
            if separator:
                embedded[keyword.decode("latin-1")] = text
        elif chunk_type == b"zTXt":
            keyword, separator, _ = chunk.partition(b"\x00")
            if separator and keyword.decode("latin-1") in {"chara", "ccv3"}:
                raise CharacterCardError(
                    "PNG embeds the character card in a compressed zTXt chunk; "
                    "re-export the card as JSON or an uncompressed PNG"
                )
        elif chunk_type == b"IEND":
            break
        offset += 12 + length
    payload = embedded.get("ccv3") or embedded.get("chara")
    if payload is None:
        raise CharacterCardError(
            "PNG does not contain an embedded character card (missing tEXt chunk 'chara')"
        )
    try:
        raw = base64.b64decode(payload)
        card = json.loads(raw.decode("utf-8"))
    except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CharacterCardError(f"embedded PNG card payload is invalid: {exc}") from exc
    if not isinstance(card, dict):
        raise CharacterCardError("embedded PNG card payload must be a JSON object")
    return card


def _decode_charx_card(data: bytes) -> dict[str, Any]:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            try:
                info = archive.getinfo(CARD_JSON_MEMBER)
            except KeyError as exc:
                raise CharacterCardError(
                    f"CHARX archive is missing {CARD_JSON_MEMBER}"
                ) from exc
            if info.file_size > CHARX_MAX_CARD_BYTES:
                raise CharacterCardError(
                    f"CHARX {CARD_JSON_MEMBER} is too large ({info.file_size} bytes)"
                )
            raw = archive.read(CARD_JSON_MEMBER)
    except zipfile.BadZipFile as exc:
        raise CharacterCardError("CHARX card is not a valid ZIP archive") from exc
    try:
        card = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CharacterCardError(f"CHARX {CARD_JSON_MEMBER} is invalid: {exc}") from exc
    if not isinstance(card, dict):
        raise CharacterCardError(f"CHARX {CARD_JSON_MEMBER} must be a JSON object")
    return card


def _card_accent(data: dict[str, Any]) -> str | None:
    extensions = data.get("extensions")
    if not isinstance(extensions, dict):
        return None
    for key in ACCENT_EXTENSION_KEYS:
        value = extensions.get(key)
        if isinstance(value, str) and _HEX_COLOR.match(value.strip()):
            return value.strip()
    return None


def _count_book_entries(data: dict[str, Any]) -> int:
    book = data.get("character_book")
    if isinstance(book, dict) and isinstance(book.get("entries"), list):
        return len(book["entries"])
    return 0


def _card_text(value: Any) -> str:
    return value if isinstance(value, str) else ""


_CHAR_PLACEHOLDER = re.compile(r"\{\{char\}\}|<bot>", re.IGNORECASE)
_USER_PLACEHOLDER = re.compile(r"\{\{user\}\}|<user>", re.IGNORECASE)


def _replace_placeholders(text: str, name: str) -> str:
    text = _CHAR_PLACEHOLDER.sub(name, text)
    return _USER_PLACEHOLDER.sub("你", text)


def _merge_examples(
    persona: dict[str, Any],
    data: dict[str, Any],
    name: str,
    warnings: list[str],
) -> None:
    raw = _card_text(data.get("mes_example"))
    if not raw.strip():
        return
    rendered = _replace_placeholders(raw, name)
    blocks = [block.strip() for block in rendered.split("<START>") if block.strip()]
    suffix = "\n\n示例对话：\n" + "\n\n".join(blocks)
    limit = PERSONA_TEXT_LIMITS["system_prompt"]
    combined = (persona["system_prompt"] + suffix).strip()
    if len(combined) > limit:
        warnings.append(
            f"mes_example was not injected: the combined system_prompt would exceed the "
            f"{limit}-character limit; the example dialogues remain in config.card_import"
        )
        return
    persona["system_prompt"] = combined


def _check_limits(persona: dict[str, Any]) -> None:
    over: list[str] = []
    for key in PERSONA_TEXT_LIMITS:
        value = persona.get(key)
        if isinstance(value, str) and value and len(value) > PERSONA_TEXT_LIMITS[key]:
            over.append(f"{key}={len(value)}>{PERSONA_TEXT_LIMITS[key]}")
    if over:
        raise CharacterCardError(
            "character card fields exceed Sumika persona limits: " + ", ".join(over)
        )


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
