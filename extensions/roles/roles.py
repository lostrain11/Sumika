"""Harness-neutral role configuration, context boundary and safe package store."""
import argparse
import hashlib
import json
from pathlib import Path
from pathlib import PureWindowsPath
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
    if not isinstance(data,dict) or not data or 'role.json' not in data:return {'status':'failed','reason':'invalid checksum manifest'}
    for name, expected in data.items():
        if not isinstance(expected,str) or len(expected)!=64:return {'status':'failed','file':name}
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
    validate_config({'schema_version':1,'work_model':'work','role_model':'role','roles':[data]})
    assets={}
    declarations=data.get('assets',{})
    if not isinstance(declarations,dict):raise ValueError('assets must be an object')
    for kind, name in declarations.items():
        if not isinstance(name,str): raise ValueError('asset path must be text')
        p=(root/name).resolve()
        if root not in p.parents or not p.is_file(): raise ValueError(f'missing asset: {kind}')
        assets[kind]=str(p)
    verified=verify_role(root)
    if verified['status']=='ok':
        checks=json.loads((root/'checksums.json').read_text(encoding='utf8'))
        covered={(root/name).resolve() for name in checks}
        if any(Path(p) not in covered for p in assets.values()):verified={'status':'failed','reason':'declared asset missing from checksums'}
    return {'id':data['id'],'name':data['name'],'enabled':data.get('enabled',True),'persona':data.get('persona',''),'worldbook':data.get('worldbook',[]),'theme':data.get('theme',{}),'assets':assets,'verified':verified}


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
        if not isinstance(role.get('persona',''),str):raise ValueError('persona must be text')
        book=role.get('worldbook',[])
        if not isinstance(book,list):raise ValueError('worldbook must be an array')
        for entry in book:
            if isinstance(entry,str):continue
            if not isinstance(entry,dict) or not isinstance(entry.get('content',''),str) or not isinstance(entry.get('keys',[]),list):raise ValueError('invalid worldbook entry')
        theme=role.get('theme',{})
        if not isinstance(theme,dict) or any(not isinstance(v,str) or len(v)!=7 or not v.startswith('#') or any(c not in '0123456789abcdefABCDEF' for c in v[1:]) for v in theme.values()):raise ValueError('theme colors must be #RRGGBB')
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
    win=PureWindowsPath(name)
    if not name or p.is_absolute() or win.drive or '..' in win.parts or name.startswith(('\\', '/')) or any(c in name for c in ':<>|?*') or any(part.endswith((' ','.')) or PureWindowsPath(part).is_reserved() for part in win.parts): raise ValueError('unsafe package path')
    return p


def import_package(package, store):
    package = Path(package).resolve(strict=True); store = Path(store).resolve(); store.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(package) as z:
        names = [n for n in z.namelist() if n and not n.endswith('/')]
        members = [(_safe_member(n), n) for n in names]
        if len({str(p).casefold() for p,_ in members})!=len(members):raise ValueError('duplicate package path')
        if sum(i.file_size for i in z.infolist())>512*1024*1024:raise ValueError('role package exceeds 512 MiB unpacked limit')
        if any((i.external_attr>>16)&0o170000==0o120000 for i in z.infolist()):raise ValueError('package symlink forbidden')
        if len(members) > 1000 or any(p.parts[0] != 'role.json' and p.parts[0] not in KINDS for p, _ in members): raise ValueError('invalid role package layout')
        role_member = next((name for p, name in members if p == Path('role.json')), None)
        if role_member is None: raise ValueError('package needs role.json')
        with z.open(role_member) as f: manifest = json.load(f)
        if manifest.get('schema_version') != SCHEMA: raise ValueError('unsupported role package schema')
        rid = _text(manifest.get('id'), 'role.id')
        if len(_safe_member(rid).parts)!=1 or '/' in rid or '\\' in rid: raise ValueError('unsafe role id')
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
    role = _role_dir(role_id, store)
    output = Path(output).resolve(); output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as z:
        for path in role.rglob('*'):
            if path.is_file() and path.name != 'checksums.json': z.write(path, path.relative_to(role).as_posix())
    return output


def _role_dir(role_id, store):
    """Resolve one role directory inside a store, refusing anything else."""
    if not isinstance(role_id, str) or not role_id.strip(): raise ValueError('role id required')
    root = Path(store).resolve()
    role = (root / role_id).resolve()
    if role.parent != root or not role.is_dir(): raise ValueError('unknown or unsafe role')
    return role


def attach_asset(role_id, store, kind, source):
    """Copy one file in as a declared asset and refresh the checksum manifest.

    Used for assets a card import cannot carry — typically the user's own VRM —
    so `model_3d` is real and verification keeps saying `ok` afterwards.
    """
    if kind not in KINDS: raise ValueError('unsupported asset kind')
    role = _role_dir(role_id, store)
    src = Path(source).resolve(strict=True)
    if not src.is_file(): raise ValueError('asset source must be a file')
    if src.stat().st_size > 256 * 1024 * 1024: raise ValueError('asset too large')
    name = src.name.strip()
    if not name or name in ('.', '..') or any(c in name for c in '\\/:*?"<>|'):
        raise ValueError('unsafe asset file name')
    relative = f'{kind}/{name}'
    target = (role / relative).resolve()
    if role not in target.parents: raise ValueError('unsafe asset path')
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, target)
    manifest_path = role / 'role.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf8'))
    assets = manifest.get('assets')
    if not isinstance(assets, dict): raise ValueError('invalid role assets')
    assets[kind] = relative
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf8')
    (role / 'checksums.json').write_text(json.dumps({
        path.relative_to(role).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(role.rglob('*'))
        if path.is_file() and path.name != 'checksums.json'}, indent=2) + '\n', encoding='utf8')
    return target


def remove_role(role_id, store):
    """Delete one role directory from a store; used to undo an import."""
    role = _role_dir(role_id, store)
    shutil.rmtree(role)
    return role


def import_card(card, store, role_id):
    """Import a user's Tavern V2/V3 JSON card without executing extensions."""
    card=Path(card).resolve(strict=True)
    if card.stat().st_size>16*1024*1024:raise ValueError('card too large')
    original=card.read_bytes();value=json.loads(original)
    if not isinstance(value,dict) or value.get('spec') not in ('chara_card_v2','chara_card_v3'):raise ValueError('expected V2/V3 character card')
    data=value.get('data')
    if not isinstance(data,dict):raise ValueError('invalid character card data')
    name=_text(data.get('name'),'card.name')
    book=data.get('character_book') or {}
    if not isinstance(book,dict) or not isinstance(book.get('entries',[]),list):raise ValueError('invalid character book')
    worldbook=[]
    for entry in book.get('entries',[]):
        if not isinstance(entry,dict) or not isinstance(entry.get('content'),str):raise ValueError('invalid character book entry')
        worldbook.append({k:entry[k] for k in ('keys','content','enabled','constant') if k in entry})
    fields=[data.get(k,'') for k in ('description','personality','scenario')]
    if any(not isinstance(v,str) for v in fields):raise ValueError('invalid persona text')
    manifest=dict(schema_version=SCHEMA,id=role_id,name=name,persona='\n\n'.join(v for v in fields if v),worldbook=worldbook,assets={'card':'card/original-card.json'},source_format=value['spec'])
    validate_config({'schema_version':1,'work_model':'work','role_model':'role','roles':[manifest]})
    with tempfile.TemporaryDirectory(prefix='sumika-card-') as d:
        package=Path(d)/'card.zip'
        with zipfile.ZipFile(package,'w',zipfile.ZIP_DEFLATED) as z:
            z.writestr('role.json',json.dumps(manifest,ensure_ascii=False,indent=2))
            z.writestr('card/original-card.json',original)
        return import_package(package,store)


def main():
    p=argparse.ArgumentParser(); sub=p.add_subparsers(dest='cmd', required=True)
    v=sub.add_parser('validate-config');v.add_argument('path')
    i=sub.add_parser('import-package');i.add_argument('package');i.add_argument('--store',required=True)
    c=sub.add_parser('import-card');c.add_argument('card');c.add_argument('--store',required=True);c.add_argument('--id',required=True)
    e=sub.add_parser('export-package');e.add_argument('role_id');e.add_argument('--store',required=True);e.add_argument('--output',required=True)
    a=p.parse_args()
    try:
        if a.cmd=='validate-config': validate_config(json.loads(Path(a.path).read_text(encoding='utf-8'))); result={'valid':True}
        elif a.cmd=='import-package': result={'path':str(import_package(a.package,a.store))}
        elif a.cmd=='import-card': result={'path':str(import_card(a.card,a.store,a.id))}
        else: result={'path':str(export_package(a.role_id,a.store,a.output))}
        print(json.dumps(result,ensure_ascii=False)); return 0
    except (OSError,ValueError,KeyError,zipfile.BadZipFile,json.JSONDecodeError) as e: print('roles: '+str(e)); return 2

if __name__=='__main__': raise SystemExit(main())
