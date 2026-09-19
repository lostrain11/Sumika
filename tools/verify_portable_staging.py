"""Verify an extracted release inventory; never infer runtime readiness from it."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath

REQUIRED = ('Sumika.exe', 'tools/start_sumika.ps1', 'tools/start_ui_bridge.ps1',
            'ui/server.py', 'sumika_next/cli.py', 'runtime/dsh/release.json')
ALLOWED_ROOTS = frozenset(('Sumika.exe', 'package-manifest.json', 'tools', 'ui',
                         'extensions', 'sumika_next', 'runtime', 'licenses'))
FORBIDDEN_PARTS = frozenset(('.sumika-next', '.sumika-continuity', '.git',
                             '__pycache__', '.pytest_cache', '.env', 'env.ps1'))
INVALID_NAME_CHARS = frozenset('<>:"/\\|?*')
# Device names remain reserved with extensions; Windows also recognizes the
# superscript digits 1, 2 and 3 in COM/LPT device names.
RESERVED_DEVICE_NAMES = (frozenset(('CON', 'PRN', 'AUX', 'NUL', 'CONIN$', 'CONOUT$'))
                         | frozenset(prefix + n for prefix in ('COM', 'LPT')
                                     for n in '123456789\u00b9\u00b2\u00b3'))


def safe_path(value):
    if not isinstance(value, str) or not value or "\\" in value or ':' in value:
        raise ValueError('invalid inventory path')
    parts = value.split('/')
    if any(p in ('', '.', '..') or p.endswith((' ', '.')) for p in parts):
        raise ValueError('invalid inventory path')
    for part in parts:
        if any(c in INVALID_NAME_CHARS or ord(c) < 32 or ord(c) == 127 for c in part):
            raise ValueError('invalid inventory path')
        if part.split('.', 1)[0].rstrip(' ').upper() in RESERVED_DEVICE_NAMES:
            raise ValueError('invalid inventory path')
    if parts[0] not in ALLOWED_ROOTS or value == 'package-manifest.json':
        raise ValueError('unexpected release root')
    for part in parts:
        low = part.casefold()
        if low in FORBIDDEN_PARTS or low.startswith('.env.') or '.update-' in low or low.endswith(('.sqlite3', '.db', '.log', '.pyc', '.pem', '.key')):
            raise ValueError('runtime data or credential file in release')
    return value


def validate_inventory_paths(paths):
    """Reject an inventory that cannot exist as a real file tree.

    Every path is validated with the same safe_path rules used when walking
    the release. Case-insensitive duplicates are rejected, as is any pair
    where one path is a file and the other lives beneath it. Shared parent
    directories are valid: only a path that is itself declared as an entry
    may not also be an ancestor of another entry.
    """
    declared = set()
    for value in paths:
        name = safe_path(value)
        folded = name.casefold()
        if folded in declared:
            raise ValueError('duplicate inventory path')
        declared.add(folded)
    for name in declared:
        parts = name.split('/')
        for index in range(1, len(parts)):
            if '/'.join(parts[:index]) in declared:
                raise ValueError('inventory path is both a file and a directory')
    return None


def digest(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def verify(root):
    root = Path(root).absolute()
    display_root = str(root)
    # Clean Windows may not enable LongPathsEnabled. Use extended paths for
    # filesystem access without changing machine policy or resolving links.
    if os.name == 'nt' and not str(root).startswith('\\\\?\\'):
        value = str(root)
        root = Path('\\\\?\\UNC\\' + value[2:] if value.startswith('\\\\')
                    else '\\\\?\\' + value)
    if root.is_symlink() or root.is_junction() or not root.is_dir():
        raise ValueError('staging root must be a physical directory')
    manifest = root / 'package-manifest.json'
    if manifest.is_symlink() or not manifest.is_file():
        raise ValueError('package manifest missing or linked')
    data = json.loads(manifest.read_text(encoding='utf-8-sig'))
    if data.get('kind') != 'portable-staging' or data.get('schema_version') != 2:
        raise ValueError('a version 2 file inventory is required')
    files = data.get('files')
    if not isinstance(files, list) or not files:
        raise ValueError('empty release inventory')
    rows = []
    for row in files:
        if not isinstance(row, dict):
            raise ValueError('invalid inventory entry')
        rows.append(row)
    validate_inventory_paths([row.get('path') for row in rows])
    expected = {}
    for row in rows:
        name = safe_path(row.get('path'))
        checksum, size = row.get('sha256'), row.get('size')
        if (not isinstance(checksum, str) or len(checksum) != 64
                or any(c not in '0123456789abcdef' for c in checksum)
                or type(size) is not int or size < 0):
            raise ValueError('invalid inventory hash or size')
        expected[name] = row
    actual = set()
    def walk_error(error):
        raise error

    for directory, directories, filenames in os.walk(root, followlinks=False, onerror=walk_error):
        for name in directories + filenames:
            path = Path(directory) / name
            relative = path.relative_to(root).as_posix()
            if path.is_symlink() or path.is_junction():
                raise ValueError('release contains a filesystem link')
            if relative == 'package-manifest.json':
                continue
            safe_path(relative)
            if path.is_file():
                actual.add(relative)
    if actual != set(expected):
        raise ValueError('release files differ from inventory')
    if not set(REQUIRED).issubset(actual):
        raise ValueError('required release files missing')
    for name, row in expected.items():
        path = root / PurePosixPath(name)
        if path.stat().st_size != row['size'] or digest(path) != row['sha256']:
            raise ValueError('release file integrity mismatch: ' + name)
    return {'status': 'inventory_verified', 'root': display_root, 'files': len(actual),
            'boundary': 'File integrity only; dependency completeness, licensing and clean-machine startup require separate acceptance.'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    args = parser.parse_args()
    print(json.dumps(verify(args.root), ensure_ascii=False, indent=2))
