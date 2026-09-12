"""Bounded Windows listener identity observations and verified native shutdown.

This is not an OS-adversary sandbox: parent metadata can be manipulated by
privileged/native callers. Snapshots are not atomic, and a process or listener
can change immediately after verification (TOCTOU). Native-owned launch and
profile provenance must be checked elsewhere. No connections are made.
"""

import ctypes
from ctypes import wintypes
import re
import sys


_FIELDS = ("root_pid", "root_created", "listener_pid", "listener_created")
_MAX_TABLE_BYTES = 16 * 1024 * 1024
_MAX_PROCESSES = 131072
_MAX_DEPTH = 256
_STOP_TIMEOUT_MS = 5000


class _ProcessEntry(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", wintypes.LONG),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", wintypes.WCHAR * 260),
    ]


class _TcpRow(ctypes.Structure):
    _fields_ = [
        ("state", wintypes.DWORD),
        ("local_addr", wintypes.DWORD),
        ("local_port", wintypes.DWORD),
        ("remote_addr", wintypes.DWORD),
        ("remote_port", wintypes.DWORD),
        ("pid", wintypes.DWORD),
    ]


def _port(endpoint: str) -> int:
    if type(endpoint) is not str:
        raise ValueError("endpoint must be a loopback HTTP URL")
    match = re.fullmatch(r"http://127\.0\.0\.1:([0-9]{1,5})/?", endpoint)
    if match is None or not 1 <= int(match[1]) <= 65535:
        raise ValueError("endpoint must be http://127.0.0.1:<port> with optional slash")
    return int(match[1])


def _pid(value: int) -> None:
    if type(value) is not int or not 1 <= value <= 0xFFFFFFFF:
        raise ValueError("PID must be a positive DWORD integer")


class _Windows:
    def __init__(self):
        if sys.platform != "win32":
            raise OSError("Windows process identity requires Windows")
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.ip = ctypes.WinDLL("iphlpapi", use_last_error=True)
        signatures = (
            (self.kernel.OpenProcess, [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD], wintypes.HANDLE),
            (self.kernel.CloseHandle, [wintypes.HANDLE], wintypes.BOOL),
            (self.kernel.WaitForSingleObject, [wintypes.HANDLE, wintypes.DWORD], wintypes.DWORD),
            (self.kernel.TerminateProcess, [wintypes.HANDLE, wintypes.UINT], wintypes.BOOL),
            (self.kernel.GetProcessTimes, [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4, wintypes.BOOL),
            (self.kernel.CreateToolhelp32Snapshot, [wintypes.DWORD, wintypes.DWORD], wintypes.HANDLE),
            (self.kernel.Process32FirstW, [wintypes.HANDLE, ctypes.POINTER(_ProcessEntry)], wintypes.BOOL),
            (self.kernel.Process32NextW, [wintypes.HANDLE, ctypes.POINTER(_ProcessEntry)], wintypes.BOOL),
            (self.ip.GetExtendedTcpTable, [ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD), wintypes.BOOL, wintypes.ULONG, ctypes.c_int, wintypes.ULONG], wintypes.DWORD),
        )
        for function, arguments, result in signatures:
            function.argtypes = arguments
            function.restype = result

    def open(self, pid, *, terminate=False):
        access = 0x1000 | 0x00100000
        if terminate:
            access |= 0x0001
        handle = self.kernel.OpenProcess(access, False, pid)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        return handle

    def close(self, handle):
        if not self.kernel.CloseHandle(handle):
            raise ctypes.WinError(ctypes.get_last_error())

    def created(self, handle):
        wait = self.kernel.WaitForSingleObject(handle, 0)
        if wait == 0xFFFFFFFF:
            raise ctypes.WinError(ctypes.get_last_error())
        if wait != 258:
            raise OSError("process is no longer live")
        created, exited, kernel, user = (wintypes.FILETIME() for _ in range(4))
        if not self.kernel.GetProcessTimes(handle, ctypes.byref(created), ctypes.byref(exited), ctypes.byref(kernel), ctypes.byref(user)):
            raise ctypes.WinError(ctypes.get_last_error())
        timestamp = (created.dwHighDateTime << 32) | created.dwLowDateTime
        if not timestamp:
            raise OSError("missing process creation time")
        return timestamp

    def parents(self):
        handle = self.kernel.CreateToolhelp32Snapshot(0x00000002, 0)
        if handle == ctypes.c_void_p(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            entry = _ProcessEntry()
            entry.dwSize = ctypes.sizeof(entry)
            result = {}
            success = self.kernel.Process32FirstW(handle, ctypes.byref(entry))
            while success:
                if len(result) >= _MAX_PROCESSES or entry.th32ProcessID in result:
                    raise OSError("invalid or oversized process snapshot")
                result[entry.th32ProcessID] = entry.th32ParentProcessID
                success = self.kernel.Process32NextW(handle, ctypes.byref(entry))
            error = ctypes.get_last_error()
            if error != 18:
                raise ctypes.WinError(error)
            return result
        finally:
            self.close(handle)

    def listener(self, port):
        size = wintypes.DWORD(0)
        buffer = None
        for _ in range(4):
            capacity = len(buffer) if buffer is not None else 0
            status = self.ip.GetExtendedTcpTable(buffer, ctypes.byref(size), False, 2, 3, 0)
            if status == 122:
                if not 4 <= size.value <= _MAX_TABLE_BYTES:
                    raise OSError("TCP table exceeds observation bound")
                buffer = ctypes.create_string_buffer(size.value)
                continue
            if status:
                raise ctypes.WinError(status)
            if buffer is None or not 4 <= size.value <= capacity:
                raise OSError("invalid TCP table size")
            count = wintypes.DWORD.from_buffer_copy(buffer).value
            row_size = ctypes.sizeof(_TcpRow)
            if 4 + count * row_size > size.value:
                raise OSError("truncated TCP table")
            candidates = []
            for index in range(count):
                row = _TcpRow.from_buffer_copy(buffer, 4 + index * row_size)
                local_port = int.from_bytes(row.local_port.to_bytes(4, "little")[:2], "big")
                if row.state == 2 and local_port == port and row.local_addr in (0, 0x0100007F):
                    candidates.append(row)
            if len(candidates) != 1 or candidates[0].local_addr != 0x0100007F:
                raise OSError("missing, wildcard, or ambiguous loopback listener")
            _pid(candidates[0].pid)
            return candidates[0].pid
        raise OSError("TCP table did not stabilize within observation bound")


def observe_listener(root_pid: int, endpoint: str) -> dict:
    """Return four integer identity fields, or fail closed with ValueError/OSError.

    All ancestors must still be live. Hold handles while checking creation order,
    repeat parent/listener snapshots, then reopen PIDs and recheck creation times.
    This also accepts a live cmd wrapper as the root; it never launches or kills.
    """
    _pid(root_pid)
    port = _port(endpoint)
    api = _Windows()
    handles = {}
    created = {}
    try:
        handles[root_pid] = api.open(root_pid)
        created[root_pid] = api.created(handles[root_pid])
        listener_pid = api.listener(port)
        parents = api.parents()
        current = listener_pid
        seen = set()
        edges = []
        for _ in range(_MAX_DEPTH):
            if current in seen or current not in parents:
                raise OSError("missing or cyclic process ancestry")
            seen.add(current)
            if current not in handles:
                handles[current] = api.open(current)
                created[current] = api.created(handles[current])
            if current == root_pid:
                break
            parent = parents[current]
            if not parent:
                raise OSError("listener does not descend from root")
            edges.append((parent, current))
            current = parent
        else:
            raise OSError("process ancestry exceeds observation bound")
        for parent, child in edges:
            if created[parent] > created[child]:
                raise OSError("parent PID was reused after child creation")
        repeated = api.parents()
        if any(repeated.get(child) != parent for parent, child in edges):
            raise OSError("process ancestry changed")
        if api.listener(port) != listener_pid:
            raise OSError("listener identity changed")
        for pid, handle in handles.items():
            reopened = api.open(pid)
            try:
                if api.created(reopened) != created[pid] or api.created(handle) != created[pid]:
                    raise OSError("process identity changed")
            finally:
                api.close(reopened)
        if api.created(handles[root_pid]) != created[root_pid]:
            raise OSError("root identity changed")
        return dict(zip(_FIELDS, (root_pid, created[root_pid], listener_pid, created[listener_pid])))
    finally:
        close_error = None
        for handle in handles.values():
            try:
                api.close(handle)
            except OSError as error:
                close_error = error
        if close_error is not None:
            raise close_error


def verify_listener(receipt: dict, endpoint: str) -> dict:
    """Reobserve and return the matching receipt; never accept bools as integers."""
    if type(receipt) is not dict or set(receipt) != set(_FIELDS):
        raise ValueError("receipt must contain exactly the four identity fields")
    expected = receipt.copy()
    if any(type(expected[field]) is not int or expected[field] <= 0 for field in _FIELDS):
        raise ValueError("receipt identity fields must be positive strict integers")
    _pid(expected["root_pid"])
    _pid(expected["listener_pid"])
    observed = observe_listener(expected["root_pid"], endpoint)
    if observed != expected:
        raise OSError("listener receipt no longer matches")
    return observed


def stop_verified_listener(receipt: dict, endpoint: str) -> None:
    """Stop only the verified listener through a creation-checked process handle.

    Internal native-owned shutdown only, not a public RPC. The caller must use
    its stored launch receipt and keep its wrapper alive until this returns;
    it can then reap/stop the wrapper. A root that is itself the listener is
    stopped here and can subsequently be reaped with child.wait().

    Root liveness is checked immediately before termination, but cannot be
    guaranteed against concurrent exit. Endpoint ownership remains subject to
    snapshot TOCTOU; the held handle prevents termination of a reused PID.
    Timeout/failure raises OSError and does not imply termination was undone.
    """
    observed = verify_listener(receipt, endpoint)
    api = _Windows()
    root = api.open(observed["root_pid"])
    try:
        if api.created(root) != observed["root_created"]:
            raise OSError("root identity changed before shutdown")
        listener = api.open(observed["listener_pid"], terminate=True)
        try:
            if api.created(listener) != observed["listener_created"]:
                raise OSError("listener identity changed before shutdown")
            if api.created(root) != observed["root_created"]:
                raise OSError("root identity changed before shutdown")
            if not api.kernel.TerminateProcess(listener, 1):
                raise ctypes.WinError(ctypes.get_last_error())
            wait = api.kernel.WaitForSingleObject(listener, _STOP_TIMEOUT_MS)
            if wait == 0xFFFFFFFF:
                raise ctypes.WinError(ctypes.get_last_error())
            if wait != 0:
                raise OSError("listener shutdown did not complete within wait bound")
        finally:
            api.close(listener)
    finally:
        api.close(root)
