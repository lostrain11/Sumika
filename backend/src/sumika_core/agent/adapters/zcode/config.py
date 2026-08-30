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
ZCODE_WIRE_PROTOCOLS = frozenset({"auto", "zcode", "jsonrpc"})
_ZCODE_AUTODISCOVER_VALUES = frozenset({"1", "true", "yes"})


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
    # ``auto`` starts with the public ZCode wire and switches to standard
    # JSON-RPC only after a read-only probe proves that the service needs it.
    wire_protocol: str = "auto"
    # ``protocol`` is a constructor/env compatibility alias used by older
    # callers.  It is normalized into ``wire_protocol`` below.
    protocol: str | None = None

    def __post_init__(self) -> None:
        selected = self.protocol if self.protocol is not None else self.wire_protocol
        selected = str(selected or "auto").strip().lower()
        if selected not in ZCODE_WIRE_PROTOCOLS:
            raise ValueError(
                "ZCode wire protocol must be one of: auto, zcode, jsonrpc"
            )
        self.wire_protocol = selected
        self.protocol = selected

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["arguments"] = list(self.arguments)
        return value


def config_from_env(
    data_dir: str | Path | None,
    env: Mapping[str, str] | None = None,
) -> ZCodeRuntimeConfig:
    """Read launcher settings without inspecting ZCode's private state.

    Windows desktop builds ship the public app-server as a Node bundle next to
    the Electron executable.  When opt-in discovery is enabled, resolve that
    bundle to ``node <install>\\resources\\glm\\zcode.cjs app-server --stdio``.
    This avoids launching the single-instance Electron shell (which exits
    after forwarding the command to the already running desktop app).  No
    settings, cookies, credentials, or account files are read.
    """

    values = env if env is not None else os.environ
    executable = str(
        values.get("SUMIKA_ZCODE_EXECUTABLE")
        or values.get("ZCODE_EXECUTABLE")
        or ""
    ).strip() or None
    # ZCode for Windows is commonly shipped as a Node script.  Accept an
    # explicit Node/script pair without inspecting ZCode's private config.
    script = str(values.get("SUMIKA_ZCODE_SCRIPT") or "").strip() or None
    autodiscover = str(values.get("SUMIKA_ZCODE_AUTODISCOVER", "0")).strip().lower() in _ZCODE_AUTODISCOVER_VALUES
    auto_discovered = False

    if executable is None and autodiscover:
        executable = _discover_zcode_executable(values)
        auto_discovered = bool(executable)

    # An explicit Electron path is also safe to normalize when its bundled
    # public script is present.  If no script can be found, preserve the
    # caller's executable unchanged rather than guessing a private entrypoint.
    if script is None and executable:
        script = _bundled_zcode_script(executable)

    if executable is None and script:
        executable = _node_executable(values)

    # A discovered/identified Electron shell must be replaced by Node.  This
    # is limited to paths for which we found the adjacent public script, so a
    # normal user-provided wrapper or CLI binary is not changed.
    if script and executable and _bundled_zcode_script(executable) and (
        auto_discovered or Path(executable).suffix.lower() in {".exe", ".cmd", ".bat"}
    ):
        node = _node_executable(values)
        if node:
            executable = node

    raw_args = values.get("SUMIKA_ZCODE_ARGS")
    arguments = ZCODE_DEFAULT_ARGUMENTS
    if script and executable:
        arguments = (script, *ZCODE_DEFAULT_ARGUMENTS)
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
    raw_protocol = str(
        values.get("SUMIKA_ZCODE_PROTOCOL")
        or values.get("SUMIKA_ZCODE_WIRE_PROTOCOL")
        or "auto"
    ).strip().lower()
    if raw_protocol not in ZCODE_WIRE_PROTOCOLS:
        raise ValueError("SUMIKA_ZCODE_PROTOCOL must be auto, zcode, or jsonrpc")
    return ZCodeRuntimeConfig(
        executable=executable,
        arguments=arguments,
        working_directory=working_directory,
        profile_dir=profile_dir,
        request_timeout=positive_float("SUMIKA_ZCODE_REQUEST_TIMEOUT", 30.0, 300.0),
        startup_timeout=positive_float("SUMIKA_ZCODE_STARTUP_TIMEOUT", 10.0, 60.0),
        enabled=enabled,
        managed=managed,
        wire_protocol=raw_protocol,
    )


def _node_executable(values: Mapping[str, str]) -> str | None:
    """Return an explicitly configured or PATH-resolved Node executable."""

    explicit = str(values.get("SUMIKA_ZCODE_NODE") or "").strip()
    if explicit:
        return explicit
    return shutil.which("node") or shutil.which("node.exe")


def _bundled_zcode_script(executable: str | None) -> str | None:
    """Find the public bundled script adjacent to a Windows ZCode shell."""

    raw = str(executable or "").strip()
    if not raw:
        return None
    try:
        path = Path(raw)
    except (TypeError, ValueError):
        return None
    # ``resources/glm/zcode.cjs`` is the published app-server entrypoint in
    # current Windows builds.  Keep a second layout for unpacked test builds.
    candidates = (
        path.parent / "resources" / "glm" / "zcode.cjs",
        path.parent.parent / "resources" / "glm" / "zcode.cjs",
    )
    for candidate in candidates:
        try:
            if candidate.is_file():
                return str(candidate.resolve())
        except (OSError, RuntimeError):
            continue
    return None


def _discover_zcode_executable(values: Mapping[str, str]) -> str | None:
    """Discover only explicitly named install roots or PATH commands."""

    roots: list[str] = []
    for key in ("SUMIKA_ZCODE_INSTALL_DIR", "ZCODE_INSTALL_DIR"):
        raw = str(values.get(key) or "").strip()
        if raw and raw not in roots:
            roots.append(raw)
    for root in roots:
        try:
            base = Path(root)
        except (TypeError, ValueError):
            continue
        for candidate in (base / "ZCode.exe", base / "zcode.exe", base / "zcode"):
            try:
                if candidate.is_file():
                    return str(candidate.resolve())
            except (OSError, RuntimeError):
                continue
    return shutil.which("zcode") or shutil.which("zcode.exe")
