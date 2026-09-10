"""Check distributable Avatar hashes and reject local data in the Git index."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import subprocess


ROOT = Path(__file__).resolve().parents[1]
AVATAR_ROOT = 'assets/avatars/'
MANIFEST = AVATAR_ROOT + 'distribution.json'
PRIVATE_ROOTS = {'.zcode', 'deprecated', 'output', 'test-results', '%systemdrive%'}
MODEL_SUFFIXES = {'.vrm', '.vroid', '.vrma', '.moc3', '.pmx', '.pmd', '.fbx', '.glb', '.gltf'}
SKILL_PATHS = 'backend/src/sumika_core/builtin_skills/resources/tool-registry/config/paths.json'


def check_files(paths, read):
    errors = []
    if SKILL_PATHS in paths:
        try:
            if json.loads(read(SKILL_PATHS)) != {'tool_directories': [], 'download_cache_directory': ''}:
                errors.append('Official tool-registry configuration must contain empty paths.')
        except (ValueError, OSError, subprocess.CalledProcessError):
            errors.append('Invalid official tool-registry configuration.')
    try:
        manifest = json.loads(read(MANIFEST))
        if manifest['schema'] != 'sumika-avatar-distribution/v1':
            raise ValueError('unsupported manifest')
        files = manifest['files']
        if not isinstance(files, dict) or manifest['default'] not in files:
            raise ValueError('missing default')
        for name, digest in files.items():
            if PurePosixPath(name).name != name or '\\' in name or name in {'.', '..'}:
                raise ValueError('invalid asset name')
            if not isinstance(digest, str) or len(digest) != 64 or any(char not in '0123456789abcdef' for char in digest):
                raise ValueError('invalid digest')
    except (ValueError, KeyError, TypeError, OSError, subprocess.CalledProcessError):
        return ['Invalid or missing Avatar distribution manifest']
    allowed = {AVATAR_ROOT + name for name in files}
    for name, digest in files.items():
        path = AVATAR_ROOT + name
        try:
            if path not in paths or hashlib.sha256(read(path)).hexdigest() != digest:
                errors.append(f'Bundled Avatar missing or changed: {path}')
        except (OSError, subprocess.CalledProcessError):
            errors.append(f'Bundled Avatar unreadable: {path}')
    for name in sorted(paths):
        path = PurePosixPath(name)
        parts = tuple(part.lower() for part in path.parts)
        if not parts:
            continue
        if (parts[0].startswith('.sumika') or parts[0] in PRIVATE_ROOTS or
                name in {'example.txt', 'output.txt'} or 'node_modules' in parts or
                parts[:2] in {('frontend', 'dist'), ('src-tauri', 'target')} or
                any(part == '.env' or part.startswith('.env.') for part in parts) or
                path.suffix.lower() in {'.db', '.sqlite3', '.log'} or
                any(marker in path.name.lower() for marker in ('.db-', '.sqlite3-'))):
            errors.append(f'Local data must not be distributed: {name}')
        if name.startswith(AVATAR_ROOT) and name not in allowed | {MANIFEST, AVATAR_ROOT + 'README.md'}:
            errors.append(f'Unreviewed Avatar asset: {name}')
        is_model = path.suffix.lower() in MODEL_SUFFIXES or path.name.lower().endswith(('.model3.json', '.model.json'))
        if is_model and name not in allowed:
            errors.append(f'Unreviewed model must stay local: {name}')
        if name in allowed:
            continue
        if name.startswith('frontend/public/') or path.suffix.lower() in {'.bin', '.dat', '.png', '.jpg', '.jpeg'}:
            try:
                prefix = read(name)[:4]
                if prefix == b'glTF':
                    errors.append(f'Model binary outside reviewed assets: {name}')
            except (OSError, subprocess.CalledProcessError):
                errors.append(f'Unreadable release asset: {name}')
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--staged', action='store_true', help='Check exact Git index bytes before committing')
    args = parser.parse_args()
    command = ['git', 'ls-files', '-z']
    if not args.staged:
        command += ['--cached', '--others', '--exclude-standard']
    paths = set(filter(None, subprocess.check_output(command, cwd=ROOT).decode('utf-8').split('\0')))
    if args.staged:
        def read(name):
            return subprocess.check_output(['git', 'show', ':' + name], cwd=ROOT, stderr=subprocess.DEVNULL)
    else:
        paths.update(path.relative_to(ROOT).as_posix() for directory in (ROOT / 'assets/avatars', ROOT / 'frontend/public', ROOT / 'frontend/src')
                     for path in directory.rglob('*') if path.is_file())
        def read(name):
            return (ROOT / name).read_bytes()
    errors = check_files(paths, read)
    for error in errors:
        print(error)
    if errors:
        return 1
    print(f'Release assets passed: {len(paths)} files checked; only reviewed default Avatar is distributable.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
