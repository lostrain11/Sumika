"""Character persona defaults, validation, and provider context rendering."""

from __future__ import annotations

from typing import Any


PERSONA_TEXT_LIMITS = {
    "identity": 4_000,
    "traits": 4_000,
    "relationship": 2_000,
    "speaking_style": 3_000,
    "behavior": 3_000,
    "boundaries": 3_000,
    "system_prompt": 20_000,
    "greeting": 2_000,
}
RESPONSE_LENGTHS = {"concise", "balanced", "detailed"}
PERSONA_DEFAULTS = {
    "identity": "",
    "traits": "",
    "relationship": "",
    "speaking_style": "",
    "behavior": "",
    "boundaries": "",
    "response_length": "balanced",
    "system_prompt": "",
    "greeting": "",
}


def normalize_persona(value: Any) -> dict[str, Any]:
    """Return a backward-compatible persona object with validated fields."""
    if value is None:
        value = {}
    if not isinstance(value, dict):
        raise ValueError("persona must be an object")
    result = dict(value)
    for key, default in PERSONA_DEFAULTS.items():
        raw = result.get(key, default)
        if raw is None and key != "response_length":
            raw = default
        if key == "response_length":
            if not isinstance(raw, str) or raw not in RESPONSE_LENGTHS:
                raise ValueError("persona.response_length is invalid")
        else:
            limit = PERSONA_TEXT_LIMITS[key]
            if not isinstance(raw, str) or len(raw) > limit:
                raise ValueError(f"persona.{key} is invalid")
        result[key] = raw
    return result


def _has_structured_content(persona: dict[str, Any]) -> bool:
    return any(
        str(persona.get(key) or "").strip()
        for key in (
            "identity",
            "traits",
            "relationship",
            "speaking_style",
            "behavior",
            "boundaries",
            "system_prompt",
        )
    ) or persona.get("response_length") != "balanced"


def build_persona_context(
    character_name: str,
    language: str | None,
    persona_value: Any,
) -> str | None:
    """Build deterministic instructions for an OpenAI-compatible system message.

    Empty legacy profiles return ``None`` so existing requests keep their old
    message shape until the user configures persona data.
    """
    persona = normalize_persona(persona_value)
    if not _has_structured_content(persona):
        return None

    lines = [f"你正在以角色“{character_name}”回应。"]
    if language:
        lines.append(f"回复语言：{language}。")
    labels = (
        ("identity", "角色身份/定位"),
        ("traits", "核心特质"),
        ("relationship", "与用户关系"),
        ("speaking_style", "说话风格"),
        ("behavior", "行为习惯"),
        ("boundaries", "边界/禁忌"),
    )
    for key, label in labels:
        value = str(persona.get(key) or "").strip()
        if value:
            lines.append(f"{label}：\n{value}")

    length_instruction = {
        "concise": "回答保持简洁，优先使用短句。",
        "balanced": "回答保持自然、适中的详细程度。",
        "detailed": "需要时提供完整解释和必要的上下文。",
    }[persona["response_length"]]
    lines.append(f"回答长度：{length_instruction}")

    custom_prompt = str(persona.get("system_prompt") or "").strip()
    if custom_prompt:
        lines.append(f"自定义系统提示词：\n{custom_prompt}")
    return "\n\n".join(lines)
