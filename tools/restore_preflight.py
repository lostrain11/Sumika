"""Read-only role dependency preflight over an integrity-verified private snapshot.

Readiness here means path presence, never database validity or model availability.
No settings, paths, credentials, raw errors or conversation content are returned.
"""
import hashlib
import json
import os
from pathlib import Path
import stat

if __package__:
    from . import backup_personal_data as snapshots
else:
    import backup_personal_data as snapshots


def local_absolute(value):
    # Classify lexically before any filesystem call, including resolve().
    if not isinstance(value, str) or not value or '\x00' in value:
        return None
    if value.replace('\\', '/').startswith('//'):
        return None  # Includes UNC and Win32 device/extended path namespaces.
    path = Path(value)
    if not path.is_absolute():
        return None
    return Path(os.path.normpath(value))


def presence(path, kind):
    """Do not traverse a reparse point or confuse inaccessible with absent."""
    current = Path(path.anchor)
    try:
        for part in (None, *path.parts[1:]):
            if part is not None:
                current = current/part
            info = current.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400):
                return 'unknown'
        return 'present' if (stat.S_ISDIR(info.st_mode) if kind == 'directory' else stat.S_ISREG(info.st_mode)) else 'missing'
    except (FileNotFoundError, NotADirectoryError):
        return 'missing'
    except OSError:
        return 'unknown'


def inspect_snapshot(snapshot):
    manifest = snapshots.verify_snapshot(snapshot)
    payload = Path(snapshot).absolute()/'data'
    result = {'schema_version': 1, 'integrity': 'verified', 'status': 'ready',
              'dependencies': [], 'issues': [],
              'boundary': 'Role resource path presence only; other dependencies and runtime availability are not certified. No activation or replay.'}

    def read_record(name):
        expected = manifest['files'].get(name)
        if expected is None:
            return None
        raw = (payload/name).read_bytes()
        if len(raw) != expected['size'] or hashlib.sha256(raw).hexdigest() != expected['sha256']:
            raise ValueError('snapshot changed during inspection')
        return json.loads(raw)

    try:
        settings = read_record('role-model-settings.json')
    except (UnicodeError, json.JSONDecodeError):
        settings = None
        result['issues'].append('role_settings_invalid')
    if 'role-model-settings.json' in manifest['files']:
        if not isinstance(settings, dict) or not isinstance(settings.get('role'), dict):
            if 'role_settings_invalid' not in result['issues']:
                result['issues'].append('role_settings_invalid')
        else:
            source = local_absolute(manifest.get('source'))
            for field, kind in (('role_dir', 'directory'), ('database', 'file')):
                path = local_absolute(settings['role'].get(field))
                dependency = {'field': 'role.'+field, 'scope': 'unknown', 'availability': 'unknown'}
                if source is not None and path is not None:
                    if path.is_relative_to(source):
                        dependency['scope'] = 'internal'
                        relative = path.relative_to(source)
                        path = payload/relative
                        # The v1 restore copies manifest files, not arbitrary
                        # payload entries or empty directories.
                        archived = [Path(name) for name in manifest['files']]
                        recoverable = (relative in archived if kind == 'file' else
                                       relative == Path('.') or any(name != relative and name.is_relative_to(relative) for name in archived))
                        if not recoverable:
                            dependency['availability'] = 'missing'
                            result['dependencies'].append(dependency)
                            continue
                    else:
                        dependency['scope'] = 'external'
                    dependency['availability'] = presence(path, kind)
                result['dependencies'].append(dependency)
    try:
        journal = read_record('role-restore-state.json')
    except (UnicodeError, json.JSONDecodeError):
        journal = None
    if 'role-restore-state.json' in manifest['files']:
        valid = isinstance(journal, dict) and type(journal.get('schema_version')) is int and journal.get('schema_version') == 1
        if valid and journal.get('status') == 'pending':
            result['issues'].append('role_rebind_pending')
        elif not (valid and journal.get('status') == 'complete'
                  and all(isinstance(journal.get(key), str) for key in ('source', 'destination'))
                  and all(isinstance(journal.get(key), dict) for key in ('original_config', 'target_config'))
                  and all(isinstance(journal.get(key), list) for key in ('moves', 'fields'))):
            result['issues'].append('role_rebind_state_invalid')
    states = [d['availability'] for d in result['dependencies']]
    if any(issue != 'role_rebind_pending' for issue in result['issues']) or 'unknown' in states:
        result['status'] = 'unknown'
    elif result['issues'] or 'missing' in states:
        result['status'] = 'needs_attention'
    return result
