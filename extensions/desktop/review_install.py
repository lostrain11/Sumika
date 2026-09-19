"""Install the standalone review plugin into an inactive owned DSH Profile.

Preserves every unrelated row; invalid or ambiguous patch files fail closed.
The caller must hold the Profile lease and have authorization to enable it.
"""
import json
import os
from pathlib import Path
import uuid


def install(home, *, root, python, registry, projects, enabled=True):
    home, root = Path(home).resolve(), Path(root).resolve(strict=True)
    if type(enabled) is not bool or not projects:
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
            raise ValueError('external review override present; reconcile explicitly')
        for entry in row.get('insert', []):
            if entry.get('id') == 'sumika-web-review': matches.append(entry)
    if len(matches) > 1:
        raise ValueError('duplicate review plugins')
    desired = {'id':'sumika-web-review', 'name':str(module), 'config':{
        'enabled':enabled, 'projects':paths, 'workPresets':['standard'],
        'root':str(root), 'python':str(interpreter), 'registry':str(registry),
        'runtimeEntry':str(runtime)}}
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
        os.replace(temporary, patch)
    finally:
        if temporary.exists(): temporary.unlink()
    return {'changed':True, 'path':str(patch), 'backup':str(backup)}
