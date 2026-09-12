"""Standalone local project continuity store. Standard library; no Harness imports.

The host adapter supplies observations. Model tools can only append reports.
Neither channel grants execution authority or changes project phase status.
"""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import uuid
import re

DIRECTORY = '.sumika-continuity'
REPORT_KINDS = {'goal', 'plan', 'decision', 'outcome'}
OBSERVATIONS = {'original', 'message', 'model', 'tool', 'plan_state', 'compact', 'turn_end'}


def dumps(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def text(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{name} must be a nonempty string')
    value.encode('utf-8')
    return value


def strings(value, name):
    if not isinstance(value, list):
        raise ValueError(f'{name} must be an array')
    return [text(v, name) for v in value]


def comparable(path):
    value = str(path)
    if os.name == 'nt':
        if value.startswith('\\\\?\\UNC\\'):
            value = '\\\\'+value[8:]
        elif re.match(r'^\\\\\?\\[A-Za-z]:\\', value):
            value = value[4:]
    return Path(value)


def location(root):
    root = Path(root).resolve(strict=True)
    base = root / DIRECTORY
    for path in [base, base/'project.json', base/'records.sqlite3',
                 base/'records.sqlite3-journal', base/'.gitignore']:
        resolved = path.resolve()
        if not comparable(resolved).is_relative_to(comparable(root)):
            raise ValueError('continuity path escapes project')
    return root, base


def initialize(root):
    root, base = location(root)
    base.mkdir(exist_ok=True)
    # Raw originals may contain credentials. Never automatically publish them.
    with (base/'.gitignore').open('a', encoding='utf-8') as out:
        if (base/'.gitignore').stat().st_size == 0:
            out.write('*\n')
    config = base/'project.json'
    if not config.exists():
        with config.open('x', encoding='utf-8') as out:
            out.write(dumps({'schema_version': 1, 'project_id': str(uuid.uuid4())})+'\n')
    with database(root):
        pass
    return str(base)


@contextmanager
def database(root):
    root, base = location(root)
    config = json.loads((base/'project.json').read_text(encoding='utf-8'))
    if config.get('schema_version') != 1:
        raise ValueError('unsupported project schema')
    uuid.UUID(config['project_id'])
    conn = sqlite3.connect(base/'records.sqlite3', timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute('PRAGMA synchronous=FULL')
        conn.execute('CREATE TABLE IF NOT EXISTS records (seq INTEGER PRIMARY KEY, '
                     'id TEXT UNIQUE NOT NULL, kind TEXT NOT NULL, task TEXT NOT NULL, '
                     'session TEXT NOT NULL, data TEXT NOT NULL)')
        conn.execute('BEGIN IMMEDIATE')
        yield conn, config['project_id']
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def checkpoint(root):
    try:
        r = subprocess.run(['git', '-C', str(root), 'rev-parse', 'HEAD'],
                           capture_output=True, text=True, timeout=5)
        return r.stdout.strip() if r.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def append(conn, project, identity, kind, task, session, payload, provenance, head):
    # Retry equality excludes wall-clock metadata. Conflicting replay is an error.
    immutable = {'project': project, 'id': identity, 'kind': kind, 'task': task,
                 'session': session, 'payload': payload, 'provenance': provenance}
    fingerprint = hashlib.sha256(dumps(immutable).encode('utf-8')).hexdigest()
    old = conn.execute('SELECT data FROM records WHERE id=?', (identity,)).fetchone()
    if old:
        if json.loads(old['data'])['sha256'] != fingerprint:
            raise ValueError('conflicting event replay')
        return identity
    record = {**immutable, 'sha256': fingerprint, 'git_head': head,
              'recorded_at': datetime.now(timezone.utc).isoformat()}
    conn.execute('INSERT INTO records(id,kind,task,session,data) VALUES(?,?,?,?,?)',
                 (identity, kind, task, session, dumps(record)))
    return identity


def query_conn(conn, *, kind=None, task=None, after=0, limit=30):
    if type(after) is not int or after < 0 or type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError('invalid query range')
    clauses, args = ['seq > ?'], [after]
    for key, value in [('kind', kind), ('task', task)]:
        if value is not None:
            clauses.append(key+'=?'); args.append(text(value, key))
    rows = conn.execute('SELECT seq,data FROM records WHERE '+' AND '.join(clauses)+
                        ' ORDER BY seq LIMIT ?', [*args, limit]).fetchall()
    return [dict(json.loads(row['data']), seq=row['seq']) for row in rows]


def recover_conn(conn, project):
    # Keep every task discoverable; latest reports are not substituted for originals.
    tasks = [r[0] for r in conn.execute('SELECT DISTINCT task FROM records ORDER BY task')]
    result = []
    for task in tasks:
        latest = {}
        for kind in ['original', 'goal', 'plan', 'decision', 'outcome', 'turn_end', 'compact', 'model']:
            row = conn.execute('SELECT seq,data FROM records WHERE task=? AND kind=? '
                               'ORDER BY seq DESC LIMIT 1', (task, kind)).fetchone()
            if row:
                latest[kind] = dict(json.loads(row['data']), seq=row['seq'])
        result.append({'task': task, 'latest': latest})
    return {'schema_version': 1, 'project': project, 'tasks': result,
            'boundary': 'Originals are source text, not blanket approval. Reports are claims, '
                        'not independently verified. Inspect actual files and checkpoints before '
                        'continuing; never replay unknown side effects.',
            'next': 'Query original/plan/decision/outcome records by task and seq; '
                    'read docs/project/handoff.json, progress.json and plan.json when present.'}


def snapshot(root, conn, project):
    root, base = location(root)
    # Resolve the replace target only while holding the SQLite writer lock.
    # Windows path resolution briefly opens the file and can deny a concurrent rename.
    if not comparable((base/'handoff.json').resolve()).is_relative_to(comparable(root)):
        raise ValueError('handoff path escapes project')
    data = recover_conn(conn, project)
    # Generated view only; the transactionally stored journal is authoritative.
    tmp = base/('handoff-'+uuid.uuid4().hex+'.tmp')
    try:
        with tmp.open('x', encoding='utf-8') as out:
            out.write(dumps(data)+'\n'); out.flush(); os.fsync(out.fileno())
        os.replace(tmp, base/'handoff.json')
    finally:
        tmp.unlink(missing_ok=True)
    return data


def ingest(root, request):
    session = text(request['session'], 'session')
    harness = text(request['harness'], 'harness')
    task = text(request.get('task', session), 'task')
    events = request['events']
    if not isinstance(events, list):
        raise ValueError('events must be an array')
    head = checkpoint(root)
    with database(root) as (conn, project):
        for event in events:
            kind = event['kind']
            if kind not in OBSERVATIONS:
                raise ValueError('unknown observation kind')
            source_id = text(event['source_id'], 'source_id')
            payload = event['payload']
            if not isinstance(payload, dict):
                raise ValueError('observation payload must be an object')
            # Adapter must preserve attribution. This is a trusted host API, not a model tool.
            if kind == 'original' and payload.get('source', {}).get('kind') != 'user':
                raise ValueError('only direct user sources are originals')
            append(conn, project, dumps([harness, session, source_id]), kind, task, session,
                   payload, 'host_observation', head)
        return snapshot(root, conn, project)


def report(root, session, report_id, value):
    session = text(session, 'session'); report_id = text(report_id, 'report_id')
    if not isinstance(value, dict):
        raise ValueError('report must be an object')
    common = {'kind', 'task', 'summary', 'sources', 'uncertainties'}
    extras = {'goal': set(), 'plan': {'plan', 'reason', 'affected_tasks'},
              'decision': {'reason'},
              'outcome': {'implemented', 'verification', 'remaining', 'limitations', 'next'}}
    kind = value.get('kind')
    if kind not in REPORT_KINDS or set(value) != common | extras[kind]:
        raise ValueError('invalid report kind or fields')
    task = text(value['task'], 'task'); text(value['summary'], 'summary')
    strings(value['sources'], 'sources'); strings(value['uncertainties'], 'uncertainties')
    for key in extras[kind] - {'verification'}:
        if key in {'affected_tasks', 'implemented', 'remaining', 'limitations'}:
            strings(value[key], key)
        else:
            text(value[key], key)
    if kind == 'outcome':
        if not isinstance(value['verification'], list):
            raise ValueError('verification must be an array')
        for item in value['verification']:
            if not isinstance(item, dict) or set(item) != {'command', 'result', 'evidence'}:
                raise ValueError('invalid verification entry')
            text(item['command'], 'command'); strings(item['evidence'], 'evidence')
            if item['result'] not in {'passed', 'failed', 'not_run'}:
                raise ValueError('invalid verification result')
    payload = dict(value)
    head = checkpoint(root)
    with database(root) as (conn, project):
        for source in value['sources']:
            if not conn.execute('SELECT 1 FROM records WHERE id=?', (source,)).fetchone():
                raise ValueError('unknown source record')
        identity = dumps(['report', session, report_id])
        if kind == 'plan':
            prior = conn.execute('SELECT data FROM records WHERE kind=? AND task=? AND id<>? '
                                 'ORDER BY seq DESC LIMIT 1', ('plan', task, identity)).fetchone()
            # On retry use the original predecessor, even after newer plans were recorded.
            existing = conn.execute('SELECT data FROM records WHERE id=?', (identity,)).fetchone()
            previous = json.loads(prior['data']) if prior else None
            payload['previous_plan'] = (json.loads(existing['data'])['payload']['previous_plan']
                                        if existing else {'id': previous['id'], 'plan': previous['payload']['plan']}
                                        if previous else None)
        append(conn, project, identity, kind, task, session, payload, 'model_report', head)
        snapshot(root, conn, project)
        return {'id': identity, 'provenance': 'model_report'}


def handle(root, request):
    action = request['action']
    if action == 'ingest':
        return ingest(root, request)
    if action == 'report':
        return report(root, request['session'], request['report_id'], request['report'])
    with database(root) as (conn, project):
        if action == 'query':
            rows = query_conn(conn, **request.get('query', {}))
            return {'records': rows, 'next_after': rows[-1]['seq'] if rows else None}
        if action == 'recover':
            return snapshot(root, conn, project)
        raise ValueError('unknown action')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('action', choices=['init', 'request', 'recover'])
    args = parser.parse_args()
    try:
        result = initialize(args.root) if args.action == 'init' else handle(
            args.root, {'action': 'recover'} if args.action == 'recover' else json.load(sys.stdin))
        print(dumps(result))
    except (OSError, ValueError, KeyError, TypeError, sqlite3.Error) as error:
        print('continuity: '+str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
