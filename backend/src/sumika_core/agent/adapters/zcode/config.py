"""Configuration for the optional ZCode app-server process."""

from __future__ import annotations

import os
import shlex
import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Mapping


ZCODE_RUNTIME_VERSION = "external-app-server"
ZCODE_DEFAULT_ARGUMENTS = ("app-server", "--stdio")


@dataclass(slots=True)
class ZCodeRuntimeConfig:
    executable: str | None = None
    arguments: tuple[str, ...] = field(default_factory=lambda: ZCODE_DEFAULT_ARGUMENTS)
    working_directory: str | None = None
    profile_dir: str = ""
    request_timeout: float = 30.0
    startup_timeout: float = 10.0
    enabled: bool = True
    managed: bool = False
    version: str = ZCODE_RUNTIME_VERSION

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["arguments"] = list(self.arguments)
        return value


def config_from_env(
    data_dir: str | Path | None,
    env: Mapping[str, str] | None = None,
) -> ZCodeRuntimeConfig:
    """Read only explicit launcher settings, never ZCode's own config files."""

    values = env if env is not None else os.environ
    executable = str(
        values.get("SUMIKA_ZCODE_EXECUTABLE")
        or values.get("ZCODE_EXECUTABLE")
        or ""
    ).strip() or None
    # Discovery is opt-in so merely installing a command named ``zcode`` does
    # not silently switch a user's Agent runtime.
    if executable is None and str(values.get("SUMIKA_ZCODE_AUTODISCOVER", "0")).lower() in {"1", "true", "yes"}:
        executable = shutil.which("zcode")

    raw_args = values.get("SUMIKA_ZCODE_ARGS")
    arguments = ZCODE_DEFAULT_ARGUMENTS
    if raw_args is not None and raw_args.strip():
        try:
            parsed = tuple(shlex.split(raw_args, posix=False))
        except ValueError as exc:
            raise ValueError("SUMIKA_ZCODE_ARGS contains invalid quoting") from exc
        if parsed:
            arguments = parsed

    working_directory = str(values.get("SUMIKA_ZCODE_WORKING_DIR") or "").strip() or None
    profile_dir = str(values.get("SUMIKA_ZCODE_PROFILE_DIR") or "").strip()
    if not profile_dir and data_dir is not None:
        profile_dir = str((Path(data_dir) / "zcode-profile").resolve())

    def positive_float(name: str, default: float, maximum: float) -> float:
        raw = values.get(name)
        if raw is None or not str(raw).strip():
            return default
        try:
            result = float(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{name} must be a number") from exc
        if result <= 0 or result > maximum:
            raise ValueError(f"{name} must be between 0 and {maximum}")
        return result

    enabled = str(values.get("SUMIKA_ZCODE_ENABLED", "1")).lower() not in {"0", "false", "no"}
    managed = str(values.get("SUMIKA_ZCODE_AUTOSTART", "0")).lower() in {"1", "true", "yes"}
    return ZCodeRuntimeConfig(
        executable=executable,
        arguments=arguments,
        working_directory=working_directory,
        profile_dir=profile_dir,
        request_timeout=positive_float("SUMIKA_ZCODE_REQUEST_TIMEOUT", 30.0, 300.0),
        startup_timeout=positive_float("SUMIKA_ZCODE_STARTUP_TIMEOUT", 10.0, 60.0),
        enabled=enabled,
        managed=managed,
    )
