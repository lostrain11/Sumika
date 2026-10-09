"""Run reference research within the client lifetime using the existing ledger."""
from datetime import datetime, timezone
import hashlib
import json
import threading
from urllib.request import urlopen


class ResearchStopped(BaseException):
    pass


class ReferenceRunner:
    def __init__(self, monitor, *, notify, analyzer_factory=None, fetch=urlopen):
        self.monitor = monitor
        self.notify = notify
        self.analyzer_factory = analyzer_factory
        self.fetch = fetch
        self._stop = threading.Event()
        self._thread = None

    def _admit(self):
        if self._stop.is_set():
            raise ResearchStopped()

    def _fetch(self, *args, **kwargs):
        self._admit()
        result = self.fetch(*args, **kwargs)
        if self._stop.is_set():
            result.close()
            raise ResearchStopped()
        return result

    def _notice(self, payload):
        self._admit()
        text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        identity = {key:value for key,value in payload.items() if key != 'retry_at'}
        key = 'reference-research/' + hashlib.sha256(
            json.dumps(identity, sort_keys=True).encode('utf8')).hexdigest()
        self.notify(key, text)

    def tick(self, now=None):
        self._admit()
        self._deliver_reports()
        now = now or datetime.now(timezone.utc)
        discovery = self.monitor.discover(now=now, fetch=self._fetch)
        if discovery['status'] == 'error':
            self._notice({'kind':'reference-discovery-failed','month':discovery['month']})
        elif discovery['candidates']:
            self._notice({'kind':'reference-candidates','month':discovery['month'],
                          'candidates':discovery['candidates']})
        checked = self.monitor.check(now=now, fetch=self._fetch)
        failures = [row['id'] for row in checked.get('projects', []) if row['status'] == 'error']
        if failures:
            self._notice({'kind':'reference-check-failed', 'cycle':checked['cycle'],
                          'projects':failures, 'retry_at':checked.get('retry_at')})
        pending = self.monitor.pending_reviews()
        if not pending:
            return {'check':checked, 'analysis_attempts':0, 'discovery':discovery}
        self._admit()
        analyzer = self.analyzer_factory() if self.analyzer_factory else None
        if analyzer is None:
            self._notice({'kind':'reference-review-pending',
                          'changes':[{'id':row['id'], 'revision':row['revision'],
                                      'source':row['comparison']['url']} for row in pending]})
            return {'check':checked, 'analysis_attempts':0, 'discovery':discovery}
        def analyze(item):
            self._admit()
            return analyzer(item)
        result = self.monitor.analyze_pending(analyze, now=now)
        self._deliver_reports()
        return {'check':checked, 'discovery':discovery, **result}

    def _deliver_reports(self):
        for report in self.monitor.pending_notifications():
            self._admit()
            if (report['status'] != 'complete' or
                    report['report']['classification'] != 'unrelated'):
                self._notice({'kind':'reference-analysis', **report})
            self.monitor.notification_delivered(report['id'], report['revision'])

    def run(self, *, interval=60):
        try:
            while not self._stop.is_set():
                try:
                    self.tick()
                except Exception:
                    # Keep errors generic: provider/network exceptions may carry secrets.
                    self._notice({'kind':'reference-runner-failed',
                                  'cycle':self.monitor.cycle(datetime.now(timezone.utc))})
                self._stop.wait(interval)
        except ResearchStopped:
            return

    def start(self):
        if self._thread is not None:
            raise RuntimeError('reference runner already started')
        self._thread = threading.Thread(target=self.run, daemon=True, name='sumika-reference-research')
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread is not None and self._thread is not threading.current_thread():
            # Finish the admitted request before releasing the client data lease.
            self._thread.join()
