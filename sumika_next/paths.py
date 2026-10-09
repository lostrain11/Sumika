"""Explicit personal-data placement shared by standalone extensions and hosts."""
import os
import json
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
    locator = Path(base) / 'Sumika-location.json'
    if locator.exists():
        data = json.loads(locator.read_text(encoding='utf-8-sig'))
        directory = data.get('directory') if isinstance(data, dict) else None
        if not isinstance(directory, str) or not directory.strip() or not Path(directory).is_absolute():
            raise ValueError('invalid personal data location; original data has not been changed')
        return Path(directory).resolve()
    return Path(base)/'Sumika'
