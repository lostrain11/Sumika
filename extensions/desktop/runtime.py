"""Resolve explicit or bundled capability interpreters without global fallback."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def process_audio_helper(*, root=None):
    root = Path(root) if root is not None else ROOT
    explicit = os.environ.get('SUMIKA_PROCESS_AUDIO_HELPER')
    if explicit is not None:
        return explicit if explicit and Path(explicit).is_file() else None
    helper = root / 'runtime' / 'process-audio' / 'SumikaProcessAudio.exe'
    return str(helper) if helper.is_file() else None


def capability_python(kind, *, root=None):
    if kind not in ('desktop', 'voice'):
        raise ValueError('unknown capability runtime')
    root = Path(root) if root is not None else ROOT
    explicit = os.environ.get(f'SUMIKA_{kind.upper()}_PYTHON')
    if explicit is not None:
        return explicit if explicit and Path(explicit).is_file() else None
    kinds = ('voice', 'desktop') if kind == 'voice' else ('desktop',)
    candidates = [root / 'runtime' / name / 'python.exe' for name in kinds]
    candidates.extend(root / '.sumika-next' / f'{name}-env' / 'Scripts' / 'python.exe'
                      for name in kinds)
    return next((str(path) for path in candidates if path.is_file()), None)
