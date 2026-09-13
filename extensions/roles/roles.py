"""Harness-neutral role configuration, context boundary and safe package store."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import zipfile


SCHEMA = 1
KINDS = {'card', 'model_2d', 'model_3d', 'voice', 'worldbook', 'scene'}

def list_roles(defaults, user_store=None):
    """Return manifests from built-in and user stores without activating them."""
    result=[]
    for kind, root in [('builtin', Path(defaults)), ('user', Path(user_store) if user_store else None)]:
        if root is None or not root.is_dir(): continue
        for manifest in sorted(root.glob('*/role.json')):
            try:
                data=json.loads(manifest.read_text(encoding='utf8')); validate_config({'schema_version':1,'work_model':'x','role_model':'y','roles':[data]})
                result.append({'id':data['id'],'name':data['name'],'kind':kind,'path':str(manifest.parent)})
            except (OSError, ValueError, json.JSONDecodeError, KeyError):
                continue
    return result

def verify_role(role_dir):
    """Verify a role's recorded file hashes; returns explicit unknown when absent."""
    root=Path(role_dir).resolve(); manifest=root/'role.json'
    if not manifest.is_file(): raise ValueError('role.json missing')
    checks=root/'checksums.json'
    if not checks.is_file(): return {'status':'unknown','checked':0,'reason':'checksums.json missing'}
    data=json.loads(checks.read_text(encoding='utf8')); checked=0
    for name, expected in data.items():
        p=(root/name).resolve()
        if root not in p.parents or not p.is_file(): return {'status':'failed','file':name}
        actual=hashlib.sha256(p.read_bytes()).hexdigest()
        if actual != expected: return {'status':'failed','file':name}
        checked+=1
    return {'status':'ok','checked':checked}

def load_role(role_dir):
    """Load a validated role manifest and safe asset paths without loading model binaries."""
    root=Path(role_dir).resolve(); data=json.loads((root/'role.json').read_text(encoding='utf8'))
    if not isinstance(data,dict) or not data.get('id') or not data.get('name'): raise ValueError('invalid role manifest')
    assets={}
    for kind, name in (data.get('assets') or {}).items():
        if not isinstance(name,str): raise ValueError('asset path must be text')
        p=(root/name).resolve()
        if root not in p.parents or not p.is_file(): raise ValueError(f'missing asset: {kind}')
        assets[kind]=str(p)
    return {'id':data['id'],'name':data['name'],'persona':data.get('persona',''),'worldbook':data.get('worldbook',[]),'assets':assets,'verified':verify_role(root)}


def _text(value, name):
    if not isinstance(value, str) or not value.strip(): raise ValueError(f'{name} must be nonempty text')
    return value


def validate_config(data):
    if not isinstance(data, dict) or data.get('schema_version') != SCHEMA: raise ValueError('invalid role config schema')
    for key in ('work_model', 'role_model'): _text(data.get(key), key)
    roles = data.get('roles', [])
    if not isinstance(roles, list): raise ValueError('roles must be an array')
    ids = set()
    for role in roles:
        if not isinstance(role, dict): raise ValueError('role must be an object')
        rid = _text(role.get('id'), 'role.id')
        if rid in ids: raise ValueError('duplicate role id')
        ids.add(rid); _text(role.get('name'), 'role.name')
        if not isinstance(role.get('enabled', True), bool): raise ValueError('role.enabled must be boolean')
    return data


def context_block(role, memory=()):
    """Return separate source blocks; caller must not merge role text into user content."""
    validate_config({'schema_version': 1, 'work_model': 'x', 'role_model': 'y', 'roles': [role]})
    memories = [m for m in memory if isinstance(m, str) and m.strip()]
    return {'source': 'role_context', 'role_id': role['id'], 'content': {
        'name': role['name'], 'persona': role.get('persona', ''),
        'worldbook': role.get('worldbook', []), 'memories': memories,
    }, 'boundary': 'must not alter original_user_content, code, diff, tool arguments or outcome body'}


def _safe_member(name):
    p = Path(name)
    if p.is_absolute() or '..' in p.parts or name.startswith(('\\', '/')): raise ValueError('unsafe package path')
    return p


def import_package(package, store):
    package = Path(package).resolve(strict=True); store = Path(store).resolve(); store.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(package) as z:
        names = [n for n in z.namelist() if n and not n.endswith('/')]
        members = [(_safe_member(n), n) for n in names]
        if len(members) > 1000 or any(p.parts[0] != 'role.json' and p.parts[0] not in KINDS for p, _ in members): raise ValueError('invalid role package layout')
        role_member = next((name for p, name in members if p == Path('role.json')), None)
        if role_member is None: raise ValueError('package needs role.json')
        with z.open(role_member) as f: manifest = json.load(f)
        if manifest.get('schema_version') != SCHEMA: raise ValueError('unsupported role package schema')
        rid = _text(manifest.get('id'), 'role.id')
        if Path(rid).name != rid: raise ValueError('unsafe role id')
        destination = store / rid
        if destination.exists(): raise ValueError('role already exists; remove/export explicitly first')
        temp = Path(tempfile.mkdtemp(prefix='.role-', dir=store))
        try:
            for member, archive_name in members:
                target = temp / member
                target.parent.mkdir(parents=True, exist_ok=True)
                with z.open(archive_name) as src, target.open('wb') as out: shutil.copyfileobj(src, out)
            (temp/'checksums.json').write_text(json.dumps({str(p): hashlib.sha256((temp/p).read_bytes()).hexdigest() for p, _ in members}, indent=2), encoding='utf-8')
            temp.replace(destination)
        except Exception:
            shutil.rmtree(temp, ignore_errors=True); raise
    return destination


def export_package(role_id, store, output):
    role = (Path(store).resolve() / role_id).resolve()
    if not role.is_dir() or role.parent != Path(store).resolve(): raise ValueError('unknown or unsafe role')
    output = Path(output).resolve(); output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as z:
        for path in role.rglob('*'):
            if path.is_file() and path.name != 'checksums.json': z.write(path, path.relative_to(role).as_posix())
    return output


def main():
    p=argparse.ArgumentParser(); sub=p.add_subparsers(dest='cmd', required=True)
    v=sub.add_parser('validate-config');v.add_argument('path')
    i=sub.add_parser('import-package');i.add_argument('package');i.add_argument('--store',required=True)
    e=sub.add_parser('export-package');e.add_argument('role_id');e.add_argument('--store',required=True);e.add_argument('--output',required=True)
    a=p.parse_args()
    try:
        if a.cmd=='validate-config': validate_config(json.loads(Path(a.path).read_text(encoding='utf-8'))); result={'valid':True}
        elif a.cmd=='import-package': result={'path':str(import_package(a.package,a.store))}
        else: result={'path':str(export_package(a.role_id,a.store,a.output))}
        print(json.dumps(result,ensure_ascii=False)); return 0
    except (OSError,ValueError,KeyError,zipfile.BadZipFile,json.JSONDecodeError) as e: print('roles: '+str(e)); return 2

if __name__=='__main__': raise SystemExit(main())
