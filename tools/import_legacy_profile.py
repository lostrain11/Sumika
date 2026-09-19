"""Copy a stopped development DSH profile into personal data, without replay."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ui.data_lease import DataLease
from sumika_next.runtime_ownership import process_identity


def inventory(source):
    result = {}
    for directory, dirs, files in os.walk(source):
        relative = Path(directory).relative_to(source)
        if relative.as_posix() == 'profiles':
            # DSH recreates this generated dependency mount on startup.
            dirs[:] = [name for name in dirs if name != 'node_modules']
        for name in dirs + files:
            path = Path(directory) / name
            if path.is_symlink() or path.is_junction():
                raise ValueError('Linked profile content requires separate handling')
        for name in files:
            if relative == Path('.') and name in ('sumika-instance.lock', 'sumika-instance.json'):
                continue
            path = Path(directory) / name
            with path.open('rb') as stream:
                result[path.relative_to(source).as_posix()] = hashlib.file_digest(stream, 'sha256').hexdigest()
    return result


def migrate(source, personal, version):
    source, personal = Path(source).absolute(), Path(personal).absolute()
    if source.is_symlink() or source.is_junction() or not source.is_dir():
        raise ValueError('Source must be a physical directory')
    if not re.fullmatch(r'[0-9][a-z0-9.\-]*', version):
        raise ValueError('Invalid version')
    if personal.is_symlink() or personal.is_junction():
        raise ValueError('Personal directory must not be a link')
    target = personal / 'dsh-profiles' / version
    if source.resolve().is_relative_to(personal.resolve()) or personal.resolve().is_relative_to(source.resolve()):
        raise ValueError('Source and personal directories overlap')
    if target.exists():
        raise ValueError('Destination profile already exists; histories are never merged')
    source_lock, personal_lock = DataLease(source, filename='sumika-instance.lock'), DataLease(personal)
    try:
        source_lock.acquire()
        personal_lock.acquire()
        record = source / 'sumika-instance.json'
        prior = json.loads(record.read_text(encoding='utf-8')) if record.exists() else {}
        if not isinstance(prior, dict):
            raise ValueError('Invalid ownership record')
        if prior:
            if prior.get('profile') != str(source.resolve()) or type(prior.get('pid')) is not int or not isinstance(prior.get('creation'), str):
                raise ValueError('Unrecognized profile ownership')
            if process_identity(prior['pid']) == prior['creation']:
                raise ValueError('Stop the source workbench before migration')
        parent = target.parent
        if parent.is_symlink() or parent.is_junction():
            raise ValueError('Profile parent must not be a link')
        parent.mkdir(parents=True, exist_ok=True)
        staging = parent / ('.import-' + uuid.uuid4().hex)
        staging.mkdir()
        before = inventory(source)
        if not before:
            raise ValueError('Empty source profile')
        for name in before:
            dest = staging / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source / name, dest)
        if inventory(source) != before or inventory(staging) != before:
            raise ValueError('Profile changed or copy verification failed; staging retained')
        (staging / 'sumika-instance.json').write_text('{}', encoding='utf-8')
        if target.exists():
            raise ValueError('Destination appeared during migration')
        staging.rename(target)
        return {'status': 'copied_verified_not_started', 'files': len(before),
                'destination': str(target), 'source_preserved': True,
                'boundary': 'No model calls or task replay; external project paths retained. Original ownership record unchanged.'}
    finally:
        personal_lock.release()
        source_lock.release()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--data', type=Path, required=True)
    parser.add_argument('--version', default='0.1.5-rc.2')
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    if not args.apply:
        print('Read-only: add --apply to copy the stopped profile; no data changed.')
    else:
        print(json.dumps(migrate(args.source, args.data, args.version), ensure_ascii=False))
