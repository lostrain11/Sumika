"""Windows auto-start and tray launcher wiring, with explicit read-back.

The registry Run entry is the single source of truth for what actually happens
at login; settings only express the user's wish. Both are reported separately so
the UI can never claim auto-start is on when the registry says otherwise.
"""
from pathlib import Path

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "Sumika"


def tray_command(root):
    """Command line used at login: hidden PowerShell running the tray script."""
    script = Path(root).resolve() / "tools" / "sumika_tray.ps1"
    return (f'powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden '
            f'-File "{script}"')


def read(registry=None):
    """Return {'registry_present': bool, 'command': str|None, 'supported': bool}."""
    registry = registry or _winreg()
    if registry is None:
        return {"supported": False, "registry_present": False, "command": None}
    try:
        with registry.OpenKey(registry.HKEY_CURRENT_USER, RUN_KEY) as key:
            command, _ = registry.QueryValueEx(key, VALUE_NAME)
    except FileNotFoundError:
        return {"supported": True, "registry_present": False, "command": None}
    except OSError:
        return {"supported": False, "registry_present": False, "command": None}
    return {"supported": True, "registry_present": True, "command": command}


def apply(enabled, root, registry=None):
    """Create or remove the login entry for the tray launcher."""
    registry = registry or _winreg()
    if registry is None:
        return {"supported": False, "applied": False, "reason": "registry unavailable"}
    command = tray_command(root)
    try:
        with registry.CreateKeyEx(registry.HKEY_CURRENT_USER, RUN_KEY, 0,
                                  registry.KEY_SET_VALUE) as key:
            if enabled:
                registry.SetValueEx(key, VALUE_NAME, 0, registry.REG_SZ, command)
            else:
                try:
                    registry.DeleteValue(key, VALUE_NAME)
                except FileNotFoundError:
                    pass
    except OSError as error:
        return {"supported": True, "applied": False, "reason": type(error).__name__}
    return {"supported": True, "applied": True, "enabled": bool(enabled), "command": command}


def _winreg():
    try:
        import winreg
    except ImportError:
        return None
    return winreg
