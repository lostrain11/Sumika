"""Read-only reference project update monitor.

It records only project metadata and revisions in SQLite. It never installs,
upgrades, executes, or changes a referenced project.
"""
from datetime import datetime, timezone, timedelta
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlparse
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from email.utils import parsedate_to_datetime
from fnmatch import fnmatchcase
import re
import uuid


class ReferenceMonitor:
    def __init__(self, registry, database):
        self.registry = Path(registry).resolve()
        self.database = Path(database).resolve()
        self.database.parent.mkdir(parents=True, exist_ok=True)
        with self._db() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS checks
                (project_id TEXT PRIMARY KEY, revision TEXT, checked_at TEXT NOT NULL,
                 status TEXT NOT NULL, error TEXT)''')
            db.execute('''CREATE TABLE IF NOT EXISTS periods
                (cycle TEXT PRIMARY KEY, attempted_at TEXT NOT NULL,
                 retry_at TEXT NOT NULL, completed INTEGER NOT NULL)''')
            db.execute('''CREATE TABLE IF NOT EXISTS reviews
                (project_id TEXT NOT NULL, revision TEXT NOT NULL, previous TEXT NOT NULL,
                 evidence TEXT NOT NULL, status TEXT NOT NULL,
                 PRIMARY KEY(project_id, revision))''')
            db.execute('''CREATE TABLE IF NOT EXISTS analyses
                (project_id TEXT NOT NULL, revision TEXT NOT NULL, cycle TEXT NOT NULL,
                 token TEXT NOT NULL, status TEXT NOT NULL, report TEXT,
                 PRIMARY KEY(project_id, revision))''')
            db.execute('''CREATE TABLE IF NOT EXISTS analysis_notifications
                (project_id TEXT NOT NULL, revision TEXT NOT NULL,
                 PRIMARY KEY(project_id, revision))''')
            db.execute('''CREATE TABLE IF NOT EXISTS discovery_runs
                (month TEXT PRIMARY KEY, attempted_at TEXT NOT NULL,
                 retry_at TEXT NOT NULL, completed INTEGER NOT NULL)''')
            db.execute('''CREATE TABLE IF NOT EXISTS discoveries
                (month TEXT NOT NULL, repository TEXT NOT NULL, evidence TEXT NOT NULL,
                 PRIMARY KEY(month, repository))''')

    @contextmanager
    def _db(self):
        db = sqlite3.connect(self.database)
        try:
            yield db
            db.commit()
        finally:
            db.close()

    def projects(self):
        data = json.loads(self.registry.read_text(encoding='utf8'))
        rows = data.get('projects')
        if not isinstance(rows, list):
            raise ValueError('reference project list missing')
        return [row for row in rows if isinstance(row, dict) and isinstance(row.get('id'), str)]

    def pending_reviews(self, limit=5):
        if type(limit) is not int or not 1 <= limit <= 5:
            raise ValueError('review limit must be between one and five')
        with self._db() as db:
            rows = db.execute("SELECT project_id,revision,previous,evidence FROM reviews WHERE status='pending' ORDER BY rowid LIMIT ?", (limit,)).fetchall()
        return [{'id':row[0], 'revision':row[1], 'previous':row[2],
                 'comparison':json.loads(row[3])} for row in rows]

    def analyze_pending(self, analyzer, *, now=None):
        """Claim before invoking the configured adapter; never replay unknown calls."""
        now = self._now(now)
        cycle = self.cycle(now)
        outcomes = []
        for _ in range(5):
            with self._db() as db:
                db.execute('BEGIN IMMEDIATE')
                count = db.execute('SELECT COUNT(*) FROM analyses WHERE cycle=?', (cycle,)).fetchone()[0]
                if count >= 5:
                    break
                row = db.execute("SELECT project_id,revision,previous,evidence FROM reviews WHERE status='pending' ORDER BY rowid LIMIT 1").fetchone()
                if row is None:
                    break
                token = uuid.uuid4().hex
                db.execute('INSERT INTO analyses VALUES (?,?,?,?,?,NULL)',
                           (row[0], row[1], cycle, token, 'started'))
                db.execute("UPDATE reviews SET status='analyzing' WHERE project_id=? AND revision=?", row[:2])
            evidence = json.loads(row[3])
            item = {'id':row[0], 'revision':row[1], 'previous':row[2], 'comparison':evidence}
            try:
                report = analyzer(item)
                if not isinstance(report, dict) or set(report) != {'classification','summary','modules'}:
                    raise ValueError('invalid reference analysis report')
                if report['classification'] not in ('worth-borrowing','needs-validation','unrelated'):
                    raise ValueError('invalid reference analysis classification')
                if not isinstance(report['summary'], str) or not report['summary'].strip() or len(report['summary'])>12000:
                    raise ValueError('invalid reference analysis summary')
                if not isinstance(report['modules'], list) or len(report['modules'])>20 or any(
                        not isinstance(module, str) or not module.strip() or len(module)>200 for module in report['modules']):
                    raise ValueError('invalid reference analysis modules')
                report = dict(report, sources=[evidence['url']], revision=row[1], previous=row[2])
                status = 'complete'
            except Exception:
                # Provider errors can contain credentials or uncertain paid state.
                # Store a generic failure and do not automatically call again.
                status, report = 'needs-attention', {'error':'analysis result unavailable; no automatic replay',
                                                   'sources':[evidence['url']]}
            with self._db() as db:
                db.execute('UPDATE analyses SET status=?,report=? WHERE project_id=? AND revision=? AND token=?',
                           (status,json.dumps(report),row[0],row[1],token))
                db.execute('UPDATE reviews SET status=? WHERE project_id=? AND revision=?',
                           (status,row[0],row[1]))
            outcomes.append({'id':row[0], 'revision':row[1], 'status':status, 'report':report})
        return {'cycle':cycle, 'analysis_attempts':len(outcomes), 'reports':outcomes}

    def analysis_reports(self):
        with self._db() as db:
            rows=db.execute('SELECT project_id,revision,status,report FROM analyses ORDER BY rowid DESC LIMIT 5').fetchall()
        return [{'id':row[0], 'revision':row[1], 'status':row[2],
                 'report':json.loads(row[3]) if row[3] else None} for row in rows]

    def pending_notifications(self):
        with self._db() as db:
            rows = db.execute('''SELECT a.project_id,a.revision,a.status,a.report
                FROM analyses a LEFT JOIN analysis_notifications n
                ON a.project_id=n.project_id AND a.revision=n.revision
                WHERE n.project_id IS NULL AND a.status IN ('complete','needs-attention')
                ORDER BY a.rowid LIMIT 50''').fetchall()
        return [{'id':row[0], 'revision':row[1], 'status':row[2],
                 'report':json.loads(row[3])} for row in rows]

    def notification_delivered(self, project_id, revision):
        with self._db() as db:
            db.execute('INSERT OR IGNORE INTO analysis_notifications VALUES (?,?)',
                       (project_id, revision))

    def discover(self, *, now=None, fetch=urlopen):
        now = self._now(now)
        local = now.astimezone(timezone(timedelta(hours=8)))
        month = local.strftime('%Y-%m')
        if self.cycle(now)[:7] != month:
            return {'status':'not_due','month':month,'candidates':[]}
        with self._db() as db:
            db.execute('BEGIN IMMEDIATE')
            run = db.execute('SELECT retry_at,completed FROM discovery_runs WHERE month=?', (month,)).fetchone()
            if run and (now < datetime.fromisoformat(run[0]) or run[1]):
                candidates = [json.loads(row[0]) for row in db.execute(
                    'SELECT evidence FROM discoveries WHERE month=? ORDER BY rowid LIMIT 3', (month,))] if run[1] else []
                return {'status':'not_due', 'month':month, 'candidates':candidates}
            db.execute('INSERT OR REPLACE INTO discovery_runs VALUES (?,?,?,0)',
                (month, now.isoformat(), (now+timedelta(minutes=20)).isoformat()))
        try:
            params = urlencode({'q':'"ai companion" OR "screen understanding" OR "learning assistant" archived:false stars:>=10',
                                'sort':'updated','order':'desc','per_page':30})
            request = Request('https://api.github.com/search/repositories?'+params,
                headers={'Accept':'application/vnd.github+json',
                         'User-Agent':'Sumika-reference-monitor/1'})
            with fetch(request, timeout=15) as response:
                value = json.loads(response.read().decode('utf8'))
            if (not isinstance(value, dict) or not isinstance(value.get('items'), list)
                    or value.get('incomplete_results') is True):
                raise ValueError('GitHub discovery response is invalid')
            known = {row['url'].rstrip('/').casefold() for row in self.projects() if isinstance(row.get('url'), str)}
            with self._db() as db:
                known.update('https://github.com/' + row[0].casefold()
                    for row in db.execute('SELECT DISTINCT repository FROM discoveries'))
            candidates = []
            for row in value['items']:
                if not isinstance(row, dict):
                    continue
                repository, url = row.get('full_name'), row.get('html_url')
                if (not isinstance(repository, str) or not re.fullmatch(r'[^/\s]{1,100}/[^/\s]{1,100}', repository)
                        or not isinstance(url, str) or url.casefold() != ('https://github.com/' + repository).casefold()
                        or url.rstrip('/').casefold() in known or not isinstance(row.get('description'), (str, type(None)))):
                    continue
                evidence = {'repository':repository, 'url':url,
                    'classification':'needs-validation',
                    'description':(row.get('description') or '')[:1000],
                    'stars':row.get('stargazers_count') if type(row.get('stargazers_count')) is int else None,
                    'updated_at':row.get('updated_at') if isinstance(row.get('updated_at'), str) else None,
                    'license':(row.get('license') or {}).get('spdx_id') if isinstance(row.get('license'), dict) else None}
                candidates.append(evidence)
                known.add(url.casefold())
                if len(candidates) == 3:
                    break
            with self._db() as db:
                for item in candidates:
                    db.execute('INSERT OR IGNORE INTO discoveries VALUES (?,?,?)',
                        (month,item['repository'],json.dumps(item,ensure_ascii=False)))
                db.execute('UPDATE discovery_runs SET retry_at=?,completed=1 WHERE month=? AND attempted_at=?',
                    (now.isoformat(), month, now.isoformat()))
            return {'status':'checked','month':month,'candidates':candidates,'model_calls':0}
        except Exception as error:
            retry = self.rate_limit_retry(error, now) or now+timedelta(hours=1)
            with self._db() as db:
                db.execute('UPDATE discovery_runs SET retry_at=?,completed=0 WHERE month=? AND attempted_at=?',
                    (retry.isoformat(),month,now.isoformat()))
            return {'status':'error','month':month,'candidates':[],'retry_at':retry.isoformat()}

    def compare(self, project, previous, revision, *, fetch=urlopen):
        if not all(re.fullmatch(r'[0-9a-fA-F]{7,40}', sha) for sha in (previous, revision)):
            raise ValueError('invalid comparison revision')
        endpoint = self._github_api(project['url']).split('/commits?')[0]
        url = f'{endpoint}/compare/{previous}...{revision}'
        request = Request(url, headers={'Accept':'application/vnd.github+json',
                                       'User-Agent':'Sumika-reference-monitor/1'})
        with fetch(request, timeout=15) as response:
            value = json.loads(response.read().decode('utf8'))
        if not isinstance(value, dict) or not isinstance(value.get('files'), list):
            raise ValueError('GitHub comparison response is invalid')
        files = []
        raw_patches = {}
        for row in value['files']:
            if not isinstance(row, dict) or not isinstance(row.get('filename'), str):
                raise ValueError('GitHub comparison file is invalid')
            files.append(row['filename'])
            if isinstance(row.get('patch'), str):
                raw_patches[row['filename']] = row['patch']
            if isinstance(row.get('previous_filename'), str):
                files.append(row['previous_filename'])
        patterns = json.loads(self.registry.read_text(encoding='utf8')).get('relevance_paths', {}).get(project['id'])
        if patterns is not None and (not isinstance(patterns, list) or not patterns
                or any(not isinstance(p, str) or not p for p in patterns)):
            raise ValueError('invalid reference relevance paths')
        # GitHub caps compare files at 300; a rewritten history or unconfigured
        # project cannot be confidently classified as unrelated.
        uncertain = len(value['files']) >= 300 or value.get('status') not in ('ahead', 'identical') or patterns is None
        relevant = files if patterns is None else [name for name in files
                    if any(fnmatchcase(name, pattern) for pattern in patterns)]
        selected = [row['filename'] for row in value['files']
                    if row['filename'] in relevant or row.get('previous_filename') in relevant]
        patches, patch_bytes, patch_truncated = {}, 0, False
        for name in selected:
            patch = raw_patches.get(name)
            if patch is None:
                continue
            remaining = 12_000 - patch_bytes
            if remaining <= 0:
                patch_truncated = True
                break
            if len(patch.encode('utf8')) > remaining:
                patches[name] = patch.encode('utf8')[:remaining].decode('utf8', errors='ignore')
                patch_truncated = True
                break
            patches[name] = patch
            patch_bytes += len(patch.encode('utf8'))
        if any(name in raw_patches and name not in patches for name in selected):
            patch_truncated = True
        return {'url':url, 'files':files, 'relevant_files':relevant,
                'patches':patches, 'patch_truncated':patch_truncated,
                'missing_patches':[name for name in selected if name not in raw_patches],
                'classification':'needs-validation' if uncertain else
                    'worth-reviewing' if relevant else 'unrelated',
                'incomplete':uncertain}

    def due(self, *, now=None, force=False):
        now = self._now(now)
        cycle = self.cycle(now)
        with self._db() as db:
            row = db.execute('SELECT retry_at, completed FROM periods WHERE cycle=?', (cycle,)).fetchone()
        return not row or (now >= datetime.fromisoformat(row[0]) and (force or not row[1]))

    @staticmethod
    def _now(now):
        now = now or datetime.now(timezone.utc)
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError('timezone-aware reference check time required')
        return now.astimezone(timezone.utc)

    @classmethod
    def cycle(cls, now):
        local = cls._now(now).astimezone(timezone(timedelta(hours=8)))
        monday = (local - timedelta(days=local.weekday())).replace(hour=10, minute=0, second=0, microsecond=0)
        if local < monday:
            monday -= timedelta(days=7)
        return monday.isoformat()

    def _claim(self, now, force):
        cycle = self.cycle(now)
        with self._db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT retry_at,completed FROM periods WHERE cycle=?', (cycle,)).fetchone()
            if row and (now < datetime.fromisoformat(row[0]) or (row[1] and not force)):
                return None
            # Recover an interrupted runner after a bounded lease. No catch-up
            # replay of every missed week: only the current due cycle is claimed.
            db.execute('INSERT OR REPLACE INTO periods VALUES (?,?,?,0)',
                (cycle, now.isoformat(), (now+timedelta(minutes=20)).isoformat()))
        return cycle

    @staticmethod
    def _github_api(url):
        parsed = urlparse(url)
        if parsed.netloc.casefold() != 'github.com':
            raise ValueError('only GitHub metadata is supported by this monitor')
        parts = [part for part in parsed.path.split('/') if part]
        if len(parts) < 2:
            raise ValueError('invalid GitHub project URL')
        return f'https://api.github.com/repos/{parts[0]}/{parts[1]}/commits?per_page=1'

    @classmethod
    def fetch_revision(cls, url, *, fetch=urlopen):
        request = Request(cls._github_api(url), headers={'Accept': 'application/vnd.github+json', 'User-Agent': 'Sumika-reference-monitor/1'})
        with fetch(request, timeout=15) as response:
            value = json.loads(response.read().decode('utf8'))
        if not isinstance(value, list) or not value or not isinstance(value[0], dict):
            raise ValueError('GitHub commit response is invalid')
        sha = value[0].get('sha')
        if not isinstance(sha, str) or len(sha) < 7:
            raise ValueError('GitHub revision is missing')
        return sha

    @staticmethod
    def rate_limit_retry(error, now):
        if not isinstance(error, HTTPError):
            return None
        headers = error.headers or {}
        if error.code != 429 and not (error.code == 403 and (
                headers.get('X-RateLimit-Remaining') == '0' or 'rate limit' in str(error).lower())):
            return None
        retry = now + timedelta(hours=1)
        for name in ('Retry-After', 'X-RateLimit-Reset'):
            value = headers.get(name)
            if not value:
                continue
            try:
                if name == 'X-RateLimit-Reset':
                    candidate = datetime.fromtimestamp(int(value), timezone.utc)
                elif value.isdigit():
                    candidate = now + timedelta(seconds=int(value))
                else:
                    candidate = parsedate_to_datetime(value).astimezone(timezone.utc)
                retry = max(retry, candidate)
            except (ValueError, TypeError, OverflowError, OSError):
                pass
        return retry

    def check(self, *, now=None, force=False, fetch=urlopen, limit=None):
        now = self._now(now)
        rows = self.projects()
        if limit is not None:
            if type(limit) is not int or limit < 1:
                raise ValueError('invalid project limit')
            rows = rows[:limit]
        cycle = self._claim(now, force)
        if cycle is None:
            return {'status': 'not_due', 'checked': 0, 'model_calls': 0,
                    'pending_reviews':self.pending_reviews()}
        results = []
        retry_at = now + timedelta(hours=1)
        rate_limited = False
        for project in rows:
            with self._db() as db:
                project_id, status, revision, error = project['id'], 'error', None, None
                comparison = None
                previous = db.execute('SELECT revision FROM checks WHERE project_id=?', (project_id,)).fetchone()
                successful = db.execute('SELECT revision,checked_at,status FROM checks WHERE project_id=?',
                                        (project_id,)).fetchone()
            if (not force and successful and successful[2] in ('baseline','unchanged','changed')
                    and self.cycle(datetime.fromisoformat(successful[1])) == cycle):
                # A quota/partial retry completes this cycle's missing work.
                # Rechecking successes can consume the remaining public quota
                # before reaching the failed project, indefinitely starving it.
                results.append({'id':project_id,'status':successful[2],
                    'revision':successful[0],'error':None,'comparison':None,
                    'reused_cycle_result':True})
                continue
            try:
                revision = self.fetch_revision(project['url'], fetch=fetch)
                status = ('baseline' if not previous or not previous[0] else
                          'unchanged' if previous[0] == revision else 'changed')
                if status == 'changed':
                    comparison = self.compare(project, previous[0], revision, fetch=fetch)
            except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
                status = 'error'
                error = str(exc)
                revision = previous[0] if previous else None
                quota_retry = self.rate_limit_retry(exc, now)
                if quota_retry is not None:
                    retry_at = max(retry_at, quota_retry)
                    rate_limited = True
            with self._db() as db:
                if comparison is not None:
                    db.execute('INSERT OR IGNORE INTO reviews VALUES (?,?,?,?,?)',
                        (project_id, revision, previous[0], json.dumps(comparison),
                         'unrelated' if comparison['classification']=='unrelated' else 'pending'))
                db.execute('INSERT OR REPLACE INTO checks VALUES (?,?,?,?,?)',
                           (project_id, revision, now.isoformat(), status, error))
            results.append({'id': project_id, 'status': status, 'revision': revision, 'error': error,
                            'comparison':comparison})
            if rate_limited:
                break
        complete = len(rows) == len(self.projects()) and all(row['status'] != 'error' for row in results)
        with self._db() as db:
            db.execute('UPDATE periods SET retry_at=?,completed=? WHERE cycle=? AND attempted_at=?',
                (retry_at.isoformat() if not complete else now.isoformat(),
                 int(complete), cycle, now.isoformat()))
        return {'status': 'checked', 'cycle':cycle, 'complete':complete,
                'retry_at':None if complete else retry_at.isoformat(),
                'rate_limited':rate_limited,
                'checked': len(results), 'model_calls': 0, 'projects': results,
                'pending_reviews':self.pending_reviews()}
