import hashlib
import hmac
import json
import secrets
from dataclasses import asdict, dataclass

from .contracts import HarnessInstance, ToolRequest, Trust, WorkBinding


class AuthorizationError(ValueError):
    pass


@dataclass(frozen=True)
class Approval:
    nonce: str
    signature: str


class Authority:
    """In-process trusted approval boundary; never exposed as an HTTP endpoint."""

    def __init__(self, instance: HarnessInstance):
        self.instance = instance
        self._key = secrets.token_bytes(32)
        self._pending: dict[str, bytes] = {}
        self._active: set[WorkBinding] = set()

    def bind(self, binding: WorkBinding) -> None:
        if self.instance.trust != Trust.MANAGED:
            raise AuthorizationError("unverified instance")
        if binding.instance_id != self.instance.instance_id or binding.request_version < 1:
            raise AuthorizationError("invalid binding")
        if not all((binding.request_id, binding.session_id, binding.step_id)):
            raise AuthorizationError("incomplete binding")
        self._active.add(binding)

    def revoke(self, binding: WorkBinding) -> None:
        self._active.discard(binding)

    def _payload(self, request: ToolRequest) -> bytes:
        if request.binding not in self._active:
            raise AuthorizationError("inactive binding")
        if not request.action or not request.target:
            raise AuthorizationError("incomplete action")
        return json.dumps(asdict(request), sort_keys=True, separators=(",", ":")).encode()

    def approve(self, request: ToolRequest) -> Approval:
        payload = self._payload(request)
        nonce = secrets.token_hex(24)
        self._pending[nonce] = payload
        signature = hmac.new(self._key, nonce.encode() + payload, hashlib.sha256).hexdigest()
        return Approval(nonce, signature)

    def consume(self, request: ToolRequest, approval: Approval) -> None:
        payload = self._payload(request)
        expected_payload = self._pending.get(approval.nonce)
        expected = hmac.new(self._key, approval.nonce.encode() + payload, hashlib.sha256).hexdigest()
        if expected_payload != payload or not hmac.compare_digest(expected, approval.signature):
            raise AuthorizationError("invalid approval")
        del self._pending[approval.nonce]

