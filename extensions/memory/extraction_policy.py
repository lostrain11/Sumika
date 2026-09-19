"""Gate for remembering facts extracted from ordinary chat.

A proposer (usually a model) suggests facts; this layer decides what may be
written. Nothing is stored because a model felt it was important: the fact must
be traceable to the user's own message, confident enough, declarative, and free
of credentials. Role-model opinions are never stored as user facts.
"""
import re
import math

CONFIDENCE_THRESHOLD = 0.8
ALLOWED_KINDS = ("preference", "fact", "relationship")
MAX_TEXT_CHARS = 200
MAX_WRITES_PER_TURN = 3

_SPACE = re.compile(r"\s+")
_SECRET = re.compile(r"(sk-[A-Za-z0-9]{8,})|(bearer\s+[A-Za-z0-9._-]{16,})|(password\s*[:=])|"
                     r"(token\s*[:=])|([A-Fa-f0-9]{32,})", re.IGNORECASE)


def normalize(text):
    if not isinstance(text, str):
        raise ValueError("text required")
    return _SPACE.sub("", text).strip()


class ExtractionGate:
    def __init__(self, *, threshold=CONFIDENCE_THRESHOLD,
                 max_writes_per_turn=MAX_WRITES_PER_TURN, max_chars=MAX_TEXT_CHARS):
        if type(threshold) not in (int, float) or not math.isfinite(threshold) or not 0 <= threshold <= 1:
            raise ValueError("invalid threshold")
        if type(max_writes_per_turn) is not int or max_writes_per_turn < 1:
            raise ValueError("invalid per-turn limit")
        if type(max_chars) is not int or max_chars < 1:
            raise ValueError("invalid length limit")
        self.threshold = threshold
        self.max_writes_per_turn = max_writes_per_turn
        self.max_chars = max_chars

    def review(self, proposals, *, user_message_ids, existing_texts=()):
        """Return accepted writes and explicit rejection reasons."""
        if not isinstance(proposals, (list, tuple)):
            raise ValueError("proposals must be a list")
        if not isinstance(user_message_ids, (set, list, tuple)):
            raise ValueError("user message ids required")
        user_ids = set(user_message_ids)
        seen = {normalize(text) for text in existing_texts}
        accepted, rejected = [], []
        for proposal in proposals:
            if not isinstance(proposal, dict):
                raise ValueError("invalid proposal")
            text = normalize(proposal.get("text", ""))
            if not text:
                rejected.append({"text": "", "reason": "empty_text"})
                continue
            if len(text) > self.max_chars:
                rejected.append({"text": text[:60], "reason": "too_long"})
                continue
            if _SECRET.search(text):
                rejected.append({"text": text[:60], "reason": "contains_credential"})
                continue
            if proposal.get("source") == "role_model" or proposal.get("kind") == "opinion":
                rejected.append({"text": text[:60], "reason": "role_opinion_is_not_a_user_fact"})
                continue
            if proposal.get("kind") not in ALLOWED_KINDS:
                rejected.append({"text": text[:60], "reason": "kind_not_allowed"})
                continue
            confidence = proposal.get("confidence")
            if (type(confidence) not in (int, float) or not math.isfinite(confidence)
                    or not self.threshold <= confidence <= 1):
                rejected.append({"text": text[:60], "reason": "below_threshold"})
                continue
            ids = proposal.get("message_ids")
            if not isinstance(ids, (set, list, tuple)) or not set(ids) & user_ids:
                rejected.append({"text": text[:60], "reason": "not_traceable_to_user_message"})
                continue
            if text in seen:
                rejected.append({"text": text[:60], "reason": "duplicate"})
                continue
            if len(accepted) >= self.max_writes_per_turn:
                rejected.append({"text": text[:60], "reason": "turn_limit"})
                continue
            seen.add(text)
            accepted.append({"text": text, "kind": proposal["kind"], "confidence": confidence,
                             "fact_key": proposal.get("fact_key"),
                             "event_id": proposal.get("event_id"),
                             "source": "auto-extract",
                             "message_ids": sorted(set(ids) & user_ids)})
        return {"accepted": accepted, "rejected": rejected,
                "threshold": self.threshold, "limit": self.max_writes_per_turn}
