"""Explicit personal-data placement shared by standalone extensions and hosts."""
import os
from pathlib import Path


def data_override():
    value = os.environ.get('SUMIKA_DATA_DIR')
    if value is None:
        return None
    if not value.strip() or not Path(value).is_absolute():
        raise ValueError('SUMIKA_DATA_DIR must be an absolute directory')
    return Path(value).resolve()


def user_data_directory():
    explicit = data_override()
    if explicit is not None:
        return explicit
    base = os.environ.get('LOCALAPPDATA') or os.environ.get('XDG_DATA_HOME') or str(Path.home())
    return Path(base)/'Sumika'
