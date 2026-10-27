"""Read-only view of the plugins installed in the managed DSH profile.

The profile's package.json is the authority for what the user installed. We do
not import plugin code, start DSH, or expose dependency specs/paths; the UI only
needs a count and the active state that DSH's bundle list already records.
"""
from __future__ import annotations

import json
import re
from pathlib import Path


def _version(profile, name, spec):
    """Prefer the installed package version over the package.json range."""
    try:
        manifest = json.loads((profile / "node_modules" / name / "package.json").read_text(encoding="utf-8"))
        value = manifest.get("version")
        if isinstance(value, str) and value.strip():
            return value.strip()
    except (OSError, ValueError, TypeError):
        pass
    if isinstance(spec, str) and re.fullmatch(r"\d+\.\d+\.\d+(?:[-+].*)?", spec.strip()):
        return spec.strip()
    return None


def profile_plugins(home):
    """Return installed/active plugin names without user content or paths.

    ``home`` is the managed DSH home (the directory containing ``profiles``).
    Missing or malformed profiles are reported as unavailable rather than
    raising into the HTTP handler.
    """
    if home is None:
        return {"available": False, "installed": [], "count": 0, "active_count": 0}
    profile = Path(home) / "profiles" / "web"
    try:
        document = json.loads((profile / "package.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"available": False, "installed": [], "count": 0, "active_count": 0}
    dependencies = document.get("dependencies") if isinstance(document, dict) else None
    if not isinstance(dependencies, dict):
        dependencies = {}
    dsh = document.get("dsh") if isinstance(document, dict) else None
    profile_block = dsh.get("profile") if isinstance(dsh, dict) else None
    bundles = profile_block.get("bundles") if isinstance(profile_block, dict) else None
    active = {item for item in bundles if isinstance(item, str)} if isinstance(bundles, list) else set()
    installed = []
    for name, spec in sorted(dependencies.items()):
        if not isinstance(name, str) or not name.strip():
            continue
        installed.append({
            "name": name,
            "version": _version(profile, name, spec),
            "active": name in active,
        })
    return {
        "available": True,
        "installed": installed,
        "count": len(installed),
        "active_count": sum(1 for item in installed if item["active"]),
    }
