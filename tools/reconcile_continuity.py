"""Inspect unknown continuity outcomes; explicitly permit offline storage sync.

This never sends a prompt, executes a task, repairs a database or asserts that
the original unknown operation succeeded. Evidence is retained, not deleted.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ui.data_lease import DataLease


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def inspect(root, session):
    root = Path(root).resolve(strict=True)
    if not isinstance(session, str) or not session:
        raise ValueError('session identity required')
    base = root/'.sumika-continuity'
    state = base/'adapter-state'/(hashlib.sha256(session.encode()).hexdigest()+'.json')
    dbpath = base/'records.sqlite3'
    for item in (base, state.parent, state, dbpath, base/'project.json'):
        if item.is_symlink() or item.is_junction() or not item.resolve().is_relative_to(root):
            raise ValueError('linked or escaping continuity path')
    pending = json.loads(state.read_text(encoding='utf8'))
    if pending.get('schema_version') != 1 or pending.get('status') != 'pending':
        raise ValueError('expected an unresolved pending operation')
    if pending.get('operation') not in ('ingest', 'recover', 'query', 'report'):
        raise ValueError('unrecognized pending operation')
    project = json.loads((base/'project.json').read_text(encoding='utf8'))
    uuid.UUID(project['project_id'])
    if project.get('schema_version') != 1:
        raise ValueError('unsupported project schema')
    for suffix in ('-wal', '-journal'):
        sidecar = Path(str(dbpath)+suffix)
        if sidecar.exists() and sidecar.stat().st_size:
            raise ValueError('database journal requires offline inspection')
    before = digest(dbpath)
    conn = sqlite3.connect(dbpath.as_uri()+'?mode=ro', uri=True)
    try:
        if conn.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
            raise ValueError('database integrity check failed')
        count = conn.execute('SELECT COUNT(*) FROM records WHERE session=?', (session,)).fetchone()[0]
    finally:
        conn.close()
    if digest(dbpath) != before:
        raise ValueError('database changed during inspection')
    return {'status': 'inspected_unknown', 'project_id': project['project_id'],
            'operation': pending['operation'], 'state_sha256': digest(state),
            'database_sha256': before, 'session_records': count,
            'boundary': 'Integrity is not proof of operation success. No task or storage operation was replayed.'}


def reconcile(root, profile, session, expected_state, expected_database):
    root, profile = Path(root).resolve(strict=True), Path(profile).resolve(strict=True)
    rows = json.loads((profile/'cordis.patch.yml').read_text(encoding='utf8'))
    plugins = [p for r in rows for p in r.get('insert', []) if p.get('id') == 'sumika-continuity']
    if len(plugins) != 1 or str(root) not in {str(Path(p).resolve()) for p in plugins[0].get('config', {}).get('projects', [])}:
        raise ValueError('profile is not bound to this continuity project')
    # Share the managed profile byte lock without creating a fictitious launch
    # or clearing an existing ownership record during offline reconciliation.
    lease = DataLease(profile, filename='sumika-instance.lock').acquire()
    try:
        ownership = profile/'sumika-instance.json'
        if ownership.exists() and json.loads(ownership.read_text(encoding='utf8')) != {}:
            raise ValueError('profile ownership must be reconciled before storage recovery')
        result = inspect(root, session)
        if result['state_sha256'] != expected_state or result['database_sha256'] != expected_database:
            raise ValueError('reviewed state changed; inspect again')
        base = root/'.sumika-continuity'
        state = base/'adapter-state'/(hashlib.sha256(session.encode()).hexdigest()+'.json')
        archive = base/'adapter-state'/'reconciliations'
        if archive.is_symlink() or archive.is_junction():
            raise ValueError('linked recovery evidence directory')
        archive.mkdir(exist_ok=True)
        receipt = archive/(uuid.uuid4().hex+'.json')
        record = {'schema_version': 1, 'disposition': 'allow-storage-sync-no-task-replay',
                  'original_outcome': 'unknown', 'pending': json.loads(state.read_text(encoding='utf8')),
                  'inspection': result}
        with receipt.open('x', encoding='utf8') as stream:
            json.dump(record, stream, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        # Check again before publishing the explicit disposition.
        if digest(state) != expected_state or digest(base/'records.sqlite3') != expected_database:
            raise ValueError('state changed before reconciliation; evidence retained')
        temporary = state.with_name(state.name+'.'+uuid.uuid4().hex+'.tmp')
        with temporary.open('x', encoding='utf8') as stream:
            json.dump({'schema_version': 1, 'status': 'reconciled',
                       'disposition': record['disposition'], 'original_outcome': 'unknown',
                       'receipt': receipt.name}, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, state)
        return {'status': 'storage_sync_permitted', 'receipt': str(receipt),
                'original_outcome': 'unknown', 'tasks_replayed': 0}
    finally:
        lease.release()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--session', required=True)
    parser.add_argument('--profile', type=Path)
    parser.add_argument('--allow-storage-retry', action='store_true')
    parser.add_argument('--expected-state-sha256')
    parser.add_argument('--expected-database-sha256')
    args = parser.parse_args()
    if args.allow_storage_retry:
        if not all((args.profile, args.expected_state_sha256, args.expected_database_sha256)):
            parser.error('explicit retry requires profile and both inspected hashes')
        result = reconcile(args.root, args.profile, args.session, args.expected_state_sha256, args.expected_database_sha256)
    else:
        result = inspect(args.root, args.session)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
