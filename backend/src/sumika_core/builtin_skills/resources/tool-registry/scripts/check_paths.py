from __future__ import annotations

import argparse
import json
import os
import stat
from pathlib import Path


def directory_error(value, writable=False):
    if not isinstance(value, str) or not value.strip():
        return "empty"
    path = Path(value)
    if not path.is_absolute() or any(ord(char) < 32 for char in value):
        return "absolute-directory-required"
    try:
        for parent in [*reversed(path.parents), path]:
            info = parent.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                return "linked-directory-not-supported"
        if not path.is_dir():
            return "not-a-directory"
        if not os.access(path, os.R_OK | os.X_OK | (os.W_OK if writable else 0)):
            return "not-accessible"
    except FileNotFoundError:
        return "not-found"
    except OSError:
        return "not-accessible"
    return None


def check_paths(config_path, operation, data_root=None):
    if operation not in {"reuse", "cache"}:
        return {"status": "invalid-operation"}
    config_path = Path(config_path).absolute()
    try:
        if directory_error(str(config_path.parent)) is not None:
            raise ValueError("invalid configuration parent")
        if config_path.is_symlink() or config_path.stat().st_size > 32768:
            raise ValueError("invalid configuration file")
        config = json.loads(config_path.read_text(encoding="utf-8-sig"))
        if not isinstance(config, dict):
            raise ValueError("configuration must be an object")
    except (OSError, ValueError):
        return {"status": "configuration-unavailable", "config_path": str(config_path)}
    configured = config.get("tool_directories", []) if operation == "reuse" else config.get("download_cache_directory", "")
    if operation == "reuse":
        if not isinstance(configured, list) or len(configured) > 32 or any(not isinstance(item, str) for item in configured):
            return {"status": "invalid-configuration", "config_path": str(config_path)}
        paths = configured
    else:
        if not isinstance(configured, str):
            return {"status": "invalid-configuration", "config_path": str(config_path)}
        paths = [configured] if configured.strip() else []
    if not paths:
        result = {"status": "configuration-empty", "config_path": str(config_path), "operation": operation}
        if directory_error(data_root) is not None:
            return {**result, "recommendation_unavailable": "valid-data-root-not-provided"}
        root = Path(data_root).absolute()
        suggested = {key: config[key] for key in ("tool_directories", "download_cache_directory") if key in config}
        target = root / ("tools" if operation == "reuse" else "tool-cache")
        target_error = directory_error(str(target))
        if target_error not in {None, "not-found"}:
            return {**result, "recommendation_unavailable": target_error, "suggested_path": str(target)}
        suggested["tool_directories" if operation == "reuse" else "download_cache_directory"] = [str(target)] if operation == "reuse" else str(target)
        return {**result, "recommendation": {"path": str(target), "exists": target.exists(),
                "configuration": suggested, "copyable_configuration": json.dumps(suggested, ensure_ascii=False, indent=2)},
                "action": "Ask the user to configure; no files have been changed."}
    errors = [{"path": path, "reason": reason} for path in paths if (reason := directory_error(path, writable=operation == "cache"))]
    if errors:
        return {"status": "path-unavailable", "config_path": str(config_path), "errors": errors}
    return {"status": "ready", "paths": list(dict.fromkeys(str(Path(path).absolute()) for path in paths))}


def main():
    parser = argparse.ArgumentParser(description="Check Skill paths without scanning or changing files.")
    parser.add_argument("--config", required=True)
    parser.add_argument("--operation", required=True, choices=("reuse", "cache"))
    parser.add_argument("--data-root")
    args = parser.parse_args()
    result = check_paths(args.config, args.operation, args.data_root)
    print(json.dumps(result, ensure_ascii=True))
    return 0 if result["status"] == "ready" else 2


if __name__ == "__main__":
    raise SystemExit(main())
