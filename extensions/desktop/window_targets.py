"""Read-only visible-window inventory; enumeration never captures content."""
import ctypes
from ctypes import wintypes
import os

from sumika_next.runtime_ownership import process_identity
from .windows_capture import _identity


def _entry(handle, user32, *, identity=process_identity, validate=_identity):
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(handle, ctypes.byref(pid))
    validate(handle, pid.value)
    length = min(1024, user32.GetWindowTextLengthW(handle))
    if length <= 0:
        return None
    title = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(handle, title, length + 1)
    if not title.value.strip():
        return None
    creation = identity(pid.value)
    if creation is None:
        return None
    return {'handle':int(handle), 'process_id':pid.value,
            'process_creation':creation, 'title':title.value}


def list_window_targets():
    if os.name != 'nt':
        raise OSError('window selection requires Windows')
    user32 = ctypes.WinDLL('user32', use_last_error=True)
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
    user32.EnumWindows.restype = wintypes.BOOL
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    windows = []
    @callback_type
    def collect(handle, parameter):
        try:
            entry = _entry(handle, user32)
            if entry is not None:
                windows.append(entry)
        except (OSError, RuntimeError, ValueError):
            pass  # A disappearing, hidden or excluded window is not a target.
        return True
    if not user32.EnumWindows(collect, 0):
        raise ctypes.WinError(ctypes.get_last_error())
    return {'windows':sorted(windows, key=lambda entry:entry['title'].casefold())[:256]}
