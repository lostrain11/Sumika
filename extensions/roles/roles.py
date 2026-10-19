"""Harness-neutral role configuration, context boundary and safe package store."""
import argparse
import hashlib
import json
import os
from pathlib import Path
from pathlib import PureWindowsPath
import shutil
import tempfile
import time
import uuid
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
                if kind == 'builtin' and data['id'] in {'sumika-guide'}:
                    continue
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
    return {'id':data['id'],'name':data['name'],'enabled':data.get('enabled',True),'persona':data.get('persona',''),'worldbook':data.get('worldbook',[]),'theme':data.get('theme',{}),'assets':assets,'verified':verified,
            'context_edits':data.get('context_edits',{})}


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
        edits=role.get('context_edits',{})
        if not isinstance(edits,dict) or set(edits)-{'background','worldbook'}:
            raise ValueError('invalid role context edits')
        if 'background' in edits and (not isinstance(edits['background'],str) or len(edits['background'])>32000):
            raise ValueError('background must be text of at most 32000 characters')
        if 'worldbook' in edits:
            validate_worldbook(edits['worldbook'])
        book=role.get('worldbook',[])
        if not isinstance(book,list):raise ValueError('worldbook must be an array')
        for entry in book:
            if isinstance(entry,str):continue
            if not isinstance(entry,dict) or not isinstance(entry.get('content',''),str) or not isinstance(entry.get('keys',[]),list):raise ValueError('invalid worldbook entry')
        theme=role.get('theme',{})
        if not isinstance(theme,dict) or any(not isinstance(v,str) or len(v)!=7 or not v.startswith('#') or any(c not in '0123456789abcdefABCDEF' for c in v[1:]) for v in theme.values()):raise ValueError('theme colors must be #RRGGBB')
    return data


def validate_worldbook(entries):
    if not isinstance(entries,list) or len(entries)>500:
        raise ValueError('worldbook must contain at most 500 entries')
    for entry in entries:
        if not isinstance(entry,dict) or not isinstance(entry.get('content',''),str) or len(entry.get('content',''))>32000:
            raise ValueError('invalid worldbook content')
        for key in ('keys','secondary_keys'):
            values=entry.get(key,[])
            if not isinstance(values,list) or any(not isinstance(v,str) or len(v)>256 for v in values):
                raise ValueError('worldbook keys must be text arrays')
        for flag in ('enabled','constant','selective','case_sensitive'):
            if flag in entry and type(entry[flag]) is not bool:
                raise ValueError('worldbook flags must be booleans')
        if type(entry.get('insertion_order',0)) is not int:
            raise ValueError('worldbook order must be integer')
    if len(json.dumps(entries,ensure_ascii=False))>512000:
        raise ValueError('worldbook too large')
    return entries


def edit_context(role_id, store, changes):
    """Keep original card and unknown manifest/entry fields intact."""
    if not isinstance(changes,dict) or set(changes)!={'background','worldbook','theme'}:
        raise ValueError('background, worldbook and theme required')
    role=_role_dir(role_id,store)
    target=role/'role.json'
    manifest=json.loads(target.read_text(encoding='utf8'))
    manifest['context_edits']={key:changes[key] for key in ('background','worldbook')}
    manifest['theme']=changes['theme']
    validate_config({'schema_version':1,'work_model':'x','role_model':'y','roles':[manifest]})
    target.write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    _refresh_checksums(role)


def editable_context(role):
    """Project full card entries, retaining advanced fields for round trips."""
    compiled={}
    if role.get('assets',{}).get('card'):
        from extensions.roles.card_context import compile_card
        try: compiled=compile_card(role['assets']['card'])
        except (ValueError,OSError): pass
    edits=role.get('context_edits',{})
    entries=edits.get('worldbook',compiled.get('worldbook',role.get('worldbook',[])))
    return {'background':edits.get('background',compiled.get('scenario','')),
            'worldbook':[dict(entry) if isinstance(entry,dict) else
                         {'content':entry,'keys':[],'constant':True} for entry in entries],
            'theme':dict(role.get('theme',{}))}


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


def _publish_role_directory(source, destination):
    """Retry only an unapplied Windows directory rename, never replace a role.

    WinError 5 can be transient even under an inherited store ACL. The actual
    owner of such a short-lived denial is unknown; do not change permissions.
    """
    identity = source.stat()
    for attempt in range(4):
        try:
            source.rename(destination)
            return
        except PermissionError as error:
            if (getattr(error, 'winerror', None) not in (5, 32, 33)
                    or attempt == 3 or destination.exists() or not source.is_dir()):
                raise
            current = source.stat()
            if (current.st_dev, current.st_ino) != (identity.st_dev, identity.st_ino):
                raise
            time.sleep((attempt + 1) * 0.04)


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
        if not isinstance(manifest, dict): raise ValueError('role manifest must be an object')
        if manifest.get('schema_version') != SCHEMA: raise ValueError('unsupported role package schema')
        rid = _text(manifest.get('id'), 'role.id')
        if len(_safe_member(rid).parts)!=1 or '/' in rid or '\\' in rid: raise ValueError('unsafe role id')
        destination = store / rid
        if destination.exists(): raise ValueError('role already exists; remove/export explicitly first')
        # Do not use tempfile.mkdtemp here.  On Windows/Python 3.14 it may
        # create a child with a restricted ACL, making the same-volume
        # directory publish fail with WinError 5.  Creating the random staging
        # directory under the already-authorized store preserves isolation and
        # keeps the final rename atomic.
        temp = None
        for _ in range(8):
            candidate = store / ('.role-' + uuid.uuid4().hex)
            try:
                candidate.mkdir()
                temp = candidate
                break
            except FileExistsError:
                continue
        if temp is None:
            raise OSError('could not create role staging directory')
        try:
            for member, archive_name in members:
                target = temp / member
                target.parent.mkdir(parents=True, exist_ok=True)
                with z.open(archive_name) as src, target.open('wb') as out: shutil.copyfileobj(src, out)
            (temp/'checksums.json').write_text(json.dumps({str(p): hashlib.sha256((temp/p).read_bytes()).hexdigest() for p, _ in members}, indent=2), encoding='utf-8')
            if load_role(temp)['verified']['status'] != 'ok':
                raise ValueError('role package validation failed')
            # New role publication must not request Windows REPLACE_EXISTING.
            # Target conflicts remain errors; never retry or merge directories.
            _publish_role_directory(temp, destination)
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


def _atomic_bytes(path, content):
    temporary = path.with_name('.' + path.name + '-' + uuid.uuid4().hex)
    try:
        temporary.write_bytes(content)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _asset_directory_files(source):
    """Explicit whole-directory import, never follow reparse points or links."""
    files = []
    total = 0
    for current, directories, names in os.walk(source, followlinks=False):
        for name in directories + names:
            path = Path(current) / name
            if path.is_symlink() or path.is_junction():
                raise ValueError('linked asset resources are not supported')
            relative = path.relative_to(source)
            _safe_member(relative.as_posix())
            if path.is_file():
                size = path.stat().st_size
                total += size
                if size > 256 * 1024 * 1024 or total > 512 * 1024 * 1024:
                    raise ValueError('asset directory exceeds size limit')
                files.append((path, relative))
                if len(files) > 990:
                    raise ValueError('asset directory has too many files')
    if not files:
        raise ValueError('asset directory is empty')
    return files


def _copy_asset_bytes(source, destination, *, total=0):
    copied = 0
    while chunk := source.read(1024 * 1024):
        copied += len(chunk)
        total += len(chunk)
        if copied > 256 * 1024 * 1024 or total > 512 * 1024 * 1024:
            raise ValueError('asset changed or exceeds size limit')
        destination.write(chunk)
    return total


def attach_asset(role_id, store, kind, source):
    """Import a file or an explicit multi-file resource bundle, with rollback.

    Directory resources retain all relative dependencies in a ZIP; importing
    them does not install code or assert renderer/voice-provider compatibility.
    Existing resources are never overwritten in place.
    """
    if kind not in KINDS: raise ValueError('unsupported asset kind')
    role = _role_dir(role_id, store)
    raw_source = Path(source)
    if raw_source.is_symlink() or raw_source.is_junction():
        raise ValueError('linked asset source is not supported')
    src = raw_source.resolve(strict=True)
    is_directory = src.is_dir()
    if is_directory and kind not in ('model_2d', 'voice', 'scene'):
        raise ValueError('directory bundles are supported for 2D, voice and scene resources; use a standalone VRM file for 3D')
    if not is_directory and not src.is_file(): raise ValueError('asset source must be a file or directory')
    if not is_directory and src.stat().st_size > 256 * 1024 * 1024: raise ValueError('asset too large')
    if is_directory and (src == role or src in role.parents or role in src.parents):
        raise ValueError('asset directory must be outside the target role')
    members = _asset_directory_files(src) if is_directory else None
    name = src.name.strip()
    if not name or name in ('.', '..') or any(c in name for c in '\\/:*?"<>|'):
        raise ValueError('unsafe asset file name')
    _safe_member(name)
    name = name + '.zip' if is_directory else name
    relative = f'{kind}/{uuid.uuid4().hex}/{name}'
    target = (role / relative).resolve()
    if role not in target.parents: raise ValueError('unsafe asset path')
    manifest_path = role / 'role.json'
    checks_path = role / 'checksums.json'
    original_manifest = manifest_path.read_bytes()
    original_checks = checks_path.read_bytes() if checks_path.exists() else None
    manifest = json.loads(original_manifest)
    assets = manifest.get('assets')
    if not isinstance(assets, dict): raise ValueError('invalid role assets')
    assets[kind] = relative
    target.parent.mkdir(parents=True, exist_ok=False)
    metadata_started = False
    try:
        if members is not None:
            total = 0
            with zipfile.ZipFile(target, 'x', zipfile.ZIP_DEFLATED) as archive:
                for path, member in members:
                    if (path.is_symlink() or path.is_junction() or not path.is_file()
                            or src not in path.resolve().parents):
                        raise ValueError('asset directory changed during import')
                    with path.open('rb') as input_file, archive.open(member.as_posix(), 'w') as output_file:
                        total = _copy_asset_bytes(input_file, output_file, total=total)
        else:
            with src.open('rb') as input_file, target.open('xb') as output_file:
                _copy_asset_bytes(input_file, output_file)
        role_files = [p for p in role.rglob('*') if p.is_file()]
        if len(role_files) > 1000 or sum(p.stat().st_size for p in role_files) > 512 * 1024 * 1024:
            raise ValueError('role resources exceed package size limit')
        metadata_started = True
        _atomic_bytes(manifest_path, (json.dumps(manifest, ensure_ascii=False, indent=2)+'\n').encode('utf8'))
        _refresh_checksums(role)
        if load_role(role)['verified']['status'] != 'ok':
            raise ValueError('attached resource verification failed')
    except Exception:
        if metadata_started:
            _atomic_bytes(manifest_path, original_manifest)
            if original_checks is None:
                checks_path.unlink(missing_ok=True)
            else:
                _atomic_bytes(checks_path, original_checks)
        shutil.rmtree(target.parent)
        raise
    return target


def _refresh_checksums(role):
    """Rewrite a role's checksum manifest over every file it currently holds."""
    _atomic_bytes(role / 'checksums.json', (json.dumps({
        path.relative_to(role).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(role.rglob('*'))
        if path.is_file() and path.name != 'checksums.json'}, indent=2) + '\n').encode('utf8'))
    return role / 'checksums.json'


def rename_role(role_id, store, name):
    """Replace the label the client shows; the card's own name is untouched."""
    if not isinstance(name, str) or not name.strip(): raise ValueError('name required')
    if len(name.strip()) > 60: raise ValueError('name too long')
    role = _role_dir(role_id, store)
    manifest_path = role / 'role.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf8'))
    manifest['name'] = name.strip()
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf8')
    _refresh_checksums(role)
    return manifest['name']


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
    # Keep model/card staging beside the selected user store, not C: TEMP.
    staging_parent=Path(store).resolve().parent
    staging_parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='sumika-card-',dir=staging_parent) as d:
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
