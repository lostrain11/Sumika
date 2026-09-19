"""Deterministic proposer for the auto-extraction path.

Deliberately model-free: it only recognises plain self-statements in the user's
own message. ExtractionGate checks metadata and limits, not semantic truth;
conservative matching here is therefore required. Questions, quotations and
negations are skipped instead of being guessed at.
"""
import re
import hashlib

_TAIL = r"(?P<value>[^，。！？；\n]{1,40})"
_NAME = r"(?P<value>[\u4e00-\u9fffA-Za-z0-9]{1,20})"

PATTERNS = (
    (re.compile(r"我(?:现在)?叫" + _NAME), "fact", 0.9, "user.name", "用户的名字是{value}。"),
    (re.compile(r"我(?:现在)?(?:住在|搬到)" + _TAIL), "fact", 0.85, "user.location",
     "用户住在{value}。"),
    (re.compile(r"我(?:现在)?(?:喜欢|爱|迷上)" + _TAIL), "preference", 0.85, "user.like",
     "用户喜欢{value}。"),
)

_NEGATION = re.compile(r"我(?:现在)?不|并不|没有|不喜欢|不爱")
_QUESTION_TAIL = ("吗", "呢", "?", "？")
_UNCERTAIN = re.compile(r"[\"'“”‘’「」『』]|如果|假如|假设|要是|比如|例如|开玩笑|骗你|并非|才怪|不是真的|曾经|以前")


def propose(message, *, message_id):
    """Return candidate facts from one user message (never from role output)."""
    if not isinstance(message, str) or not message.strip():
        return []
    if not isinstance(message_id, str) or not message_id.strip():
        raise ValueError("message id required")
    text = message.strip()
    if text.endswith(_QUESTION_TAIL) or _UNCERTAIN.search(text):
        return []
    if _NEGATION.search(text):
        return []
    proposals = []
    for pattern, kind, confidence, fact_key, template in PATTERNS:
        match = pattern.fullmatch(text.rstrip("。！!"))
        if not match:
            continue
        value = match.group("value").strip().strip("的").strip().rstrip("了啦哦啊呀呢")
        value = value.strip()
        if not value:
            continue
        # Likes are independent facts, unlike the single current name/location.
        if fact_key == "user.like":
            fact_key += "." + hashlib.sha256(value.encode("utf8")).hexdigest()[:24]
        proposals.append({"text": template.format(value=value),
                          "kind": kind, "confidence": confidence, "fact_key": fact_key,
                          "message_ids": [message_id], "source": "user_message"})
        # One fact per statement is enough; the pattern order is by specificity.
        break
    return proposals
