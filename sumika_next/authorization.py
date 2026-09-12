import hashlib
import hmac
import json
import secrets
import threading
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
        self._retired: set[WorkBinding] = set()
        self._lock = threading.RLock()
        self._versions: dict[str, int] = {}

    def bind(self, binding: WorkBinding) -> None:
        with self._lock:
            self._bind(binding)

    def _bind(self, binding: WorkBinding) -> None:
        if binding in self._retired:
            raise AuthorizationError("retired binding; create a new step or request version")
        if self.instance.trust != Trust.MANAGED:
            raise AuthorizationError("unverified instance")
        if binding.instance_id != self.instance.instance_id or type(binding.request_version) is not int or binding.request_version < 1:
            raise AuthorizationError("invalid binding")
        if not all((binding.request_id, binding.session_id, binding.step_id)):
            raise AuthorizationError("incomplete binding")
        version = self._versions.get(binding.request_id, 0)
        if binding.request_version < version:
            raise AuthorizationError("stale request version")
        if binding.request_version > version:
            for previous in tuple(self._active):
                if previous.request_id == binding.request_id:
                    self.revoke(previous)
            self._versions[binding.request_id] = binding.request_version
        self._active.add(binding)

    def revoke(self, binding: WorkBinding) -> None:
        with self._lock:
            self._active.discard(binding)
            self._retired.add(binding)
            self._pending = {
                nonce: payload for nonce, payload in self._pending.items()
                if json.loads(payload)["binding"] != asdict(binding)
            }

    def _payload(self, request: ToolRequest) -> bytes:
        if request.binding not in self._active:
            raise AuthorizationError("inactive binding")
        if not request.action or not request.target:
            raise AuthorizationError("incomplete action")
        if not isinstance(request.arguments, bytes):
            raise AuthorizationError("arguments must be immutable bytes")
        value = asdict(request)
        value["arguments"] = request.arguments.hex()
        return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()

    def approve(self, request: ToolRequest) -> Approval:
        with self._lock:
            return self._approve(request)

    def _approve(self, request: ToolRequest) -> Approval:
        payload = self._payload(request)
        nonce = secrets.token_hex(24)
        self._pending[nonce] = payload
        signature = hmac.new(self._key, nonce.encode() + payload, hashlib.sha256).hexdigest()
        return Approval(nonce, signature)

    def consume(self, request: ToolRequest, approval: Approval) -> None:
        with self._lock:
            self._consume(request, approval)

    def _consume(self, request: ToolRequest, approval: Approval) -> None:
        payload = self._payload(request)
        expected_payload = self._pending.get(approval.nonce)
        expected = hmac.new(self._key, approval.nonce.encode() + payload, hashlib.sha256).hexdigest()
        if expected_payload != payload or not hmac.compare_digest(expected, approval.signature):
            raise AuthorizationError("invalid approval")
        del self._pending[approval.nonce]
