"""Pinned configuration owned exclusively by the DSH adapter."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

DSH_VERSION = "0.1.1-rc.2"
DSH_COMMIT = "b150a551b8d465e31e418e1b2eaf5e79bbb7d28e"
DSH_REPOSITORY = "https://github.com/deepseek-ai/deepseek-harness"
DSH_DEFAULT_ENDPOINT = "http://127.0.0.1:3080"


@dataclass(slots=True)
class DSHRuntimeConfig:
    version: str = DSH_VERSION
    commit: str = DSH_COMMIT
    repository: str = DSH_REPOSITORY
    endpoint: str = DSH_DEFAULT_ENDPOINT
    profile_dir: str = ""
    executable: str | None = None
    version_verified: bool = False
    managed: bool = True
    enabled: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def default_profile_dir(data_dir: str | Path | None) -> str:
    if data_dir is None:
        return ""
    return str((Path(data_dir) / "dsh-profile").resolve())
