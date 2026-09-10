from __future__ import annotations

import re
from typing import Any


_SECRET_TEXT_RE = re.compile(
    r"(?i)(?:sk-[a-z0-9_-]{8,}|bearer\s+[a-z0-9._~+/=-]{8,}|"
    r"(?:api[_ -]?key|token|password|secret|otp)\s*[:=]\s*[^\s,;]+)"
)


def looks_like_secret_text(value: Any) -> bool:
    return isinstance(value, str) and bool(_SECRET_TEXT_RE.search(value))


__all__ = ["looks_like_secret_text"]

