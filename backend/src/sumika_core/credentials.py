"""Credential storage boundary for provider secrets.

Provider profiles persist only opaque references in SQLite.  On Windows the
secret payload is stored as a generic credential; in-memory applications use
an isolated store so tests never write to the user's credential vault.
"""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
from ctypes import wintypes
from pathlib import Path
from typing import Protocol


class CredentialError(RuntimeError):
    """Raised when the operating-system credential store is unavailable."""


class CredentialStore(Protocol):
    def read(self, reference: str) -> dict[str, str]: ...

    def write(self, reference: str, values: dict[str, str]) -> None: ...

    def delete(self, reference: str) -> None: ...


class MemoryCredentialStore:
    """Process-local credential store used by tests and in-memory cores."""

    def __init__(self) -> None:
        self._values: dict[str, dict[str, str]] = {}

    def read(self, reference: str) -> dict[str, str]:
        return dict(self._values.get(reference, {}))

    def write(self, reference: str, values: dict[str, str]) -> None:
        self._values[reference] = dict(values)

    def delete(self, reference: str) -> None:
        self._values.pop(reference, None)


class UnavailableCredentialStore:
    """Fail closed on platforms without an approved secure credential store."""

    def read(self, reference: str) -> dict[str, str]:
        return {}

    def write(self, reference: str, values: dict[str, str]) -> None:
        if values:
            raise CredentialError("Secure credential storage is unavailable on this platform")

    def delete(self, reference: str) -> None:
        return None


if os.name == "nt":
    class _CredentialW(ctypes.Structure):
        _fields_ = [
            ("Flags", wintypes.DWORD),
            ("Type", wintypes.DWORD),
            ("TargetName", wintypes.LPWSTR),
            ("Comment", wintypes.LPWSTR),
            ("LastWritten", wintypes.FILETIME),
            ("CredentialBlobSize", wintypes.DWORD),
            ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
            ("Persist", wintypes.DWORD),
            ("AttributeCount", wintypes.DWORD),
            ("Attributes", ctypes.c_void_p),
            ("TargetAlias", wintypes.LPWSTR),
            ("UserName", wintypes.LPWSTR),
        ]


class WindowsCredentialStore:
    """Small ctypes wrapper around the Windows Credential Manager API."""

    _TYPE_GENERIC = 1
    _PERSIST_LOCAL_MACHINE = 2
    _ERROR_NOT_FOUND = 1168
    _PREFIX = "Sumika/provider/"

    def __init__(self, namespace: str = "default") -> None:
        if os.name != "nt":
            raise CredentialError("Windows Credential Manager is only available on Windows")
        self._advapi32 = ctypes.WinDLL("Advapi32.dll", use_last_error=True)
        self._namespace = "".join(character for character in namespace if character.isalnum() or character in "-_.")[:64] or "default"
        self._cred_write = self._advapi32.CredWriteW
        self._cred_write.argtypes = [ctypes.POINTER(_CredentialW), wintypes.DWORD]
        self._cred_write.restype = wintypes.BOOL
        self._cred_read = self._advapi32.CredReadW
        self._cred_read.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.POINTER(ctypes.POINTER(_CredentialW)),
        ]
        self._cred_read.restype = wintypes.BOOL
        self._cred_delete = self._advapi32.CredDeleteW
        self._cred_delete.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
        self._cred_delete.restype = wintypes.BOOL
        self._cred_free = self._advapi32.CredFree
        self._cred_free.argtypes = [ctypes.c_void_p]
        self._cred_free.restype = None

    def read(self, reference: str) -> dict[str, str]:
        pointer = ctypes.POINTER(_CredentialW)()
        if not self._cred_read(self._target(reference), self._TYPE_GENERIC, 0, ctypes.byref(pointer)):
            error = ctypes.get_last_error()
            if error == self._ERROR_NOT_FOUND:
                return {}
            raise CredentialError(f"Credential Manager read failed: Windows error {error}")
        try:
            credential = pointer.contents
            payload = ctypes.string_at(credential.CredentialBlob, credential.CredentialBlobSize)
            value = json.loads(payload.decode("utf-8"))
            if not isinstance(value, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in value.items()):
                raise CredentialError("Credential Manager returned an invalid provider secret payload")
            return value
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CredentialError("Credential Manager returned an unreadable provider secret payload") from exc
        finally:
            self._cred_free(pointer)

    def write(self, reference: str, values: dict[str, str]) -> None:
        if not values:
            self.delete(reference)
            return
        payload = json.dumps(values, ensure_ascii=False, sort_keys=True).encode("utf-8")
        if len(payload) > 2400:
            raise CredentialError("Provider secrets exceed the Windows Credential Manager size limit")
        buffer = (ctypes.c_ubyte * len(payload)).from_buffer_copy(payload)
        credential = _CredentialW()
        credential.Type = self._TYPE_GENERIC
        credential.TargetName = self._target(reference)
        credential.Comment = "Sumika provider profile secrets"
        credential.CredentialBlobSize = len(payload)
        credential.CredentialBlob = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))
        credential.Persist = self._PERSIST_LOCAL_MACHINE
        credential.UserName = "Sumika"
        if not self._cred_write(ctypes.byref(credential), 0):
            raise CredentialError(f"Credential Manager write failed: Windows error {ctypes.get_last_error()}")

    def delete(self, reference: str) -> None:
        if self._cred_delete(self._target(reference), self._TYPE_GENERIC, 0):
            return
        error = ctypes.get_last_error()
        if error != self._ERROR_NOT_FOUND:
            raise CredentialError(f"Credential Manager delete failed: Windows error {error}")

    def _target(self, reference: str) -> str:
        if not reference or any(character in reference for character in "\r\n"):
            raise CredentialError("Invalid provider credential reference")
        return f"{self._PREFIX}{self._namespace}/{reference}"


def default_credential_store(*, in_memory: bool = False, namespace: str = "default") -> CredentialStore:
    if in_memory:
        return MemoryCredentialStore()
    if os.name == "nt":
        return WindowsCredentialStore(namespace)
    return UnavailableCredentialStore()


def credential_namespace_for_data_dir(data_dir: str | Path) -> str:
    """Return the stable vault namespace used by one Sumika data directory."""

    return hashlib.sha256(str(Path(data_dir).resolve()).encode("utf-8")).hexdigest()[:20]
