"""Install the standalone review plugin into an inactive owned DSH Profile.

Preserves every unrelated row; invalid or ambiguous patch files fail closed.
The caller must hold the Profile lease and have authorization to enable it.
"""
import json
import os
from pathlib import Path
import time
import uuid


def _replace_profile_patch(temporary, patch):
    """Atomically replace a Windows profile patch across transient sharing locks."""
    for attempt in range(5):
        try:
            os.replace(temporary, patch)
            return
        except OSError as exc:
            # Do not broaden this into a generic retry: ordinary failures must
            # remain visible and the old profile must stay untouched.
            if getattr(exc, 'winerror', None) not in (5, 32, 33) or attempt == 4:
                raise
            time.sleep(0.02 * (attempt + 1))


def install(home, *, root, python, registry, projects=(), enabled=True,
            registered_workspaces=False, work_presets=None, managed=False):
    home, root = Path(home).resolve(), Path(root).resolve(strict=True)
    if type(enabled) is not bool or type(registered_workspaces) is not bool or (not projects and not registered_workspaces):
        raise ValueError('explicit enabled flag and work projects required')
    interpreter = Path(python).resolve(strict=True)
    paths = [str(Path(p).resolve(strict=True)) for p in projects]
    module = root/'extensions/desktop/review_dsh.mjs'
    runtime = (root/'runtime/dsh/node_modules/@deepseek-ai/dsh/package.json').resolve(strict=True)
    if not module.is_file():
        raise ValueError('review plugin missing')
    registry = Path(registry)
    if not registry.is_absolute():
        raise ValueError('absolute personal registry required')
    patch = home/'cordis.patch.yml'
    original = patch.read_bytes() if patch.exists() else b'[]'
    rows = json.loads(original)
    if not isinstance(rows, list) or any(not isinstance(r, dict) for r in rows):
        raise ValueError('unexpected Profile patch shape')
    matches = []
    for row in rows:
        if row.get('id') == 'sumika-web-review':
            if managed:
                # Native plugin management may add its own override row.
                # Automatic installation must not undo it or block Workbench.
                return {'changed':False, 'path':str(patch), 'reason':'user review override preserved'}
            raise ValueError('external review override present; reconcile explicitly')
        entries = row.get('insert', [])
        if not isinstance(entries, list) or any(not isinstance(entry, dict) for entry in entries):
            raise ValueError('unexpected Profile insert shape')
        for entry in entries:
            if entry.get('id') == 'sumika-web-review': matches.append(entry)
    if len(matches) > 1:
        raise ValueError('duplicate review plugins')
    presets = ['standard'] if work_presets is None else work_presets
    if managed and matches:
        # Relocation refreshes transport paths, never broadens a user's scope
        # or turns a deliberately disabled native plugin back on.
        old = matches[0].get('config', {})
        if not isinstance(old, dict):
            raise ValueError('invalid existing review configuration')
        enabled = old.get('enabled')
        paths = old.get('projects', [])
        registered_workspaces = old.get('registeredWorkspaces', False)
        presets = old.get('workPresets')
    if (type(enabled) is not bool or type(registered_workspaces) is not bool
            or not isinstance(paths, list) or any(not isinstance(p, str) or not Path(p).is_absolute() for p in paths)
            or (not paths and not registered_workspaces)
            or not isinstance(presets, list) or not presets
            or any(not isinstance(p, str) or not p or p == 'sumika-role' for p in presets)):
        raise ValueError('invalid explicit review scope')
    desired = {'id':'sumika-web-review', 'name':str(module), 'config':{
        'enabled':enabled, 'projects':paths, 'workPresets':presets,
        'root':str(root), 'python':str(interpreter), 'registry':str(registry),
        'runtimeEntry':str(runtime)}}
    if registered_workspaces:
        desired['config']['registeredWorkspaces'] = True
    runner = root/'tools/run_module.py'
    if not runner.is_file():
        raise ValueError('packaged module runner missing')
    desired['config']['runner'] = str(runner)
    if managed and matches and 'disabled' in matches[0]:
        desired['disabled'] = matches[0]['disabled']
    if matches and matches[0] == desired:
        return {'changed':False, 'path':str(patch)}
    home.mkdir(parents=True, exist_ok=True)
    backup = home/'backups'/('before-web-review-'+uuid.uuid4().hex+'.json')
    backup.parent.mkdir(exist_ok=True)
    backup.write_bytes(original)
    if backup.read_bytes() != original:
        raise OSError('Profile backup verification failed')
    if matches:
        matches[0].clear();matches[0].update(desired)
    else:
        rows.append({'insert':[desired]})
    temporary = patch.with_name('review-patch-'+uuid.uuid4().hex+'.tmp')
    try:
        with temporary.open('x', encoding='utf8') as stream:
            json.dump(rows, stream, ensure_ascii=False, indent=2)
            stream.flush();os.fsync(stream.fileno())
        _replace_profile_patch(temporary, patch)
    finally:
        if temporary.exists(): temporary.unlink()
    return {'changed':True, 'path':str(patch), 'backup':str(backup)}
