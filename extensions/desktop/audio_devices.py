"""Enumerate audio input devices through the isolated desktop environment.

The bridge process does not carry sounddevice, and installing audio libraries
into it would defeat the extension boundary; the probe therefore runs in the
desktop environment interpreter and returns JSON.
"""
import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

PROBE = """
import json
import sounddevice as sd
devices = []
for index, device in enumerate(sd.query_devices()):
    if device.get("max_input_channels", 0) < 1:
        continue
    devices.append({"index": index, "name": device["name"],
                    "channels": device["max_input_channels"],
                    "hostapi": sd.query_hostapis(device["hostapi"])["name"],
                    "default_samplerate": int(round(device.get("default_samplerate") or 0))})
default = sd.default.device
print(json.dumps({"devices": devices,
                  "default_input": default[0] if isinstance(default, (list, tuple)) else None}))
"""


def env_python():
    explicit = os.environ.get("SUMIKA_VOICE_PYTHON")
    if explicit is not None:
        return str(explicit) if explicit and Path(explicit).is_file() else None
    for candidate in (ROOT / ".sumika-next" / "voice-env" / "Scripts" / "python.exe",
                      ROOT / ".sumika-next" / "desktop-env" / "Scripts" / "python.exe"):
        if candidate.is_file():
            return str(candidate)
    return None


def list_input_devices(*, python=None, timeout=60):
    """Return {'devices': [...], 'default_input': int|None} or an explicit error."""
    interpreter = python or env_python()
    if not interpreter:
        return {"devices": [], "default_input": None,
                "error": "desktop environment interpreter not found"}
    try:
        result = subprocess.run([interpreter, "-c", PROBE], capture_output=True, text=True,
                                encoding="utf-8", timeout=timeout)
    except (OSError, subprocess.SubprocessError) as error:
        return {"devices": [], "default_input": None, "error": type(error).__name__}
    if result.returncode:
        return {"devices": [], "default_input": None,
                "error": (result.stderr or "device probe failed").strip()[-200:]}
    try:
        payload = json.loads(result.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {"devices": [], "default_input": None, "error": "invalid device probe output"}
    devices = [dict(item, is_default=item.get("index") == payload.get("default_input"))
               for item in payload.get("devices", []) if isinstance(item, dict)]
    # Put real, non-default-looking devices first but keep indices authoritative.
    return {"devices": devices, "default_input": payload.get("default_input"), "error": None}
