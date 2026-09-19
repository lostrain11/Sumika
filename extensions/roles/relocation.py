"""Recoverable active-role relocation. Caller holds the Bridge admission lock.

Copies resources without deleting the source. Durable pending state blocks chat
until explicit resume; no model calls, task replay or automatic recovery.
"""
from contextlib import closing
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import uuid
from extensions.models.settings import load,save
from extensions.roles.roles import load_role
from extensions.roles.conversations import Conversations


def digest(path):
    with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


def inventory(root):
    root=Path(root)
    if root.is_symlink() or root.is_junction():raise ValueError('linked role directory refused')
    rows={}
    for base,dirs,files in os.walk(root,followlinks=False):
        for name in dirs+files:
            p=Path(base)/name
            if p.is_symlink() or p.is_junction():raise ValueError('linked role resource refused')
        for name in files:
            p=Path(base)/name;rows[p.relative_to(root).as_posix()]=digest(p)
    if not rows or load_role(root)['verified']['status']!='ok':raise ValueError('role verification failed')
    return rows


def journal_path(settings_path):return Path(settings_path).resolve().parent/'role-relocation.json'


def journal(settings_path):
    p=journal_path(settings_path)
    return json.loads(p.read_text(encoding='utf8')) if p.exists() else None


def _write(settings_path,value):
    path=journal_path(settings_path);tmp=path.with_suffix('.tmp')
    with tmp.open('w',encoding='utf8') as out:
        json.dump(value,out,ensure_ascii=False,indent=2);out.flush();os.fsync(out.fileno())
    os.replace(tmp,path)


def require_settled(settings_path):
    state=journal(settings_path)
    if state and state['state'] not in ('completed','cancelled'):raise ValueError('role relocation pending; explicitly recover before changing data')


def relocate(settings_path,target):
    settings_path=Path(settings_path).resolve();require_settled(settings_path)
    config=load(settings_path);source=Path(config['role']['role_dir']).resolve(strict=True)
    target=Path(target)
    if not target.is_absolute():raise ValueError('absolute target required')
    # Parent must already exist; disallow nested copying and overwrites.
    parent=target.parent.resolve(strict=True);target=parent/target.name
    if target.exists() or target.is_symlink() or source==target or source in target.parents or target in source.parents:
        raise ValueError('target must be new and outside source')
    before=inventory(source);raw=settings_path.read_bytes()
    run=settings_path.parent/'backups'/('role-relocation-'+uuid.uuid4().hex);run.mkdir(parents=True)
    (run/'settings.json').write_bytes(raw)
    if (run/'settings.json').read_bytes()!=raw:raise OSError('settings backup mismatch')
    store=Conversations(settings_path.parent/'role-conversations.sqlite3')
    with closing(sqlite3.connect(store.path)) as db,closing(sqlite3.connect(run/'conversations.sqlite3')) as backup:
        db.backup(backup)
        if backup.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise OSError('database backup invalid')
    # Copy first. An interruption leaves an unreferenced copy; never overwrite it.
    shutil.copytree(source,target)
    if inventory(target)!=before or inventory(source)!=before:raise OSError('resource copy mismatch; original retained')
    if settings_path.read_bytes()!=raw:raise ValueError('settings changed; copied resource retained but not activated')
    desired=copy.deepcopy(config);desired['role']['role_dir']=str(target)
    scope=store.scope_for(config['role']['user_id'],source,config['role']['project_id'])
    state={'id':run.name,'state':'prepared','source':str(source),'target':str(target),
           'source_settings_sha256':hashlib.sha256(raw).hexdigest(),'desired':desired,
           'files':before,'scope':scope,'backup':str(run)}
    _write(settings_path,state)
    return resume(settings_path,state['id'])


def resume(settings_path,expected_id):
    settings_path=Path(settings_path).resolve();state=journal(settings_path)
    if not state or state['id']!=expected_id:raise ValueError('relocation receipt changed')
    if state['state'] in ('rolling_back','cancelled'):raise ValueError('relocation is rolling back or cancelled')
    if state['state']=='completed':return {'id':state['id'],'state':'completed','backup':state['backup'],'target':state['target']}
    if inventory(state['target'])!=state['files']:raise ValueError('target resources changed; recovery refused')
    current=load(settings_path)
    if digest(settings_path)!=state['source_settings_sha256'] and current!=state['desired']:
        raise ValueError('settings changed independently; recovery refused')
    role=state['desired']['role'];store=Conversations(settings_path.parent/'role-conversations.sqlite3')
    store.relocate_scope(role['user_id'],role['project_id'],state['source'],state['target'],expected_scope=state['scope'])
    save(state['desired'],settings_path)
    if load(settings_path)!=state['desired']:raise OSError('settings publication verification failed')
    state['state']='completed';_write(settings_path,state)
    return {'id':state['id'],'state':'completed','backup':state['backup'],'target':state['target']}

def rollback(settings_path,expected_id):
    """Recover a pending cutover only; never undo a completed migration with new chat."""
    settings_path=Path(settings_path).resolve();state=journal(settings_path)
    if not state or state['id']!=expected_id:raise ValueError('relocation receipt changed')
    if state['state']=='cancelled':return {'id':state['id'],'state':'cancelled'}
    if state['state']=='completed':raise ValueError('completed migration requires a new migration, not rollback')
    if inventory(state['source'])!=state['files']:raise ValueError('source changed; rollback refused')
    backup=Path(state['backup'])/'settings.json'
    if digest(backup)!=state['source_settings_sha256']:raise ValueError('backup checksum mismatch')
    if digest(settings_path)!=state['source_settings_sha256'] and load(settings_path)!=state['desired']:
        raise ValueError('settings changed independently; rollback refused')
    state['state']='rolling_back';_write(settings_path,state)
    tmp=settings_path.with_suffix('.rollback.tmp');tmp.write_bytes(backup.read_bytes());os.replace(tmp,settings_path)
    role=state['desired']['role'];store=Conversations(settings_path.parent/'role-conversations.sqlite3')
    with store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        rows=db.execute('SELECT location,scope FROM role_scope_bindings WHERE owner=? AND project=? AND location IN (?,?)',
            (role['user_id'],role['project_id'],state['source'],state['target'])).fetchall()
        if any(scope!=state['scope'] for _,scope in rows):raise ValueError('scope changed independently')
        db.execute('DELETE FROM role_scope_bindings WHERE owner=? AND project=? AND location=? AND scope=?',
            (role['user_id'],role['project_id'],state['target'],state['scope']))
        db.execute('UPDATE role_scope_bindings SET retired=0 WHERE owner=? AND project=? AND location=? AND scope=?',
            (role['user_id'],role['project_id'],state['source'],state['scope']))
    state['state']='cancelled';_write(settings_path,state)
    return {'id':state['id'],'state':'cancelled','copy_retained':state['target']}
