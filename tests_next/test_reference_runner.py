import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock
from datetime import datetime, timezone

from extensions.desktop.reference_monitor import ReferenceMonitor
from extensions.desktop.reference_runner import ReferenceRunner, ResearchStopped
from ui.schedule import ScheduleController


class ReferenceRunnerTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)
        registry = self.root/'registry.json'
        registry.write_text(json.dumps({'projects':[]}), encoding='utf8')
        self.monitor = ReferenceMonitor(registry, self.root/'reference.sqlite3')
        self.schedule = ScheduleController(self.root/'schedules')
        self.now = datetime(2026,10,12,2,tzinfo=timezone.utc)
        # Non-discovery tests are offline and start after this month's discovery.
        with self.monitor._db() as db:
            db.execute('INSERT INTO discovery_runs VALUES (?,?,?,1)',
                ('2026-10',self.now.isoformat(),self.now.isoformat()))

    def tearDown(self):
        self.folder.cleanup()

    def queue(self):
        with self.monitor._db() as db:
            db.execute('INSERT INTO reviews VALUES (?,?,?,?,?)',
                ('neko','a'*40,'b'*40,json.dumps({'url':'https://github.com/example/compare','files':['voice.py']}),'pending'))

    def test_no_change_zero_model_calls_and_no_notification(self):
        factory = Mock()
        runner = ReferenceRunner(self.monitor, notify=self.schedule.notify, analyzer_factory=factory)
        self.assertEqual(runner.tick(self.now)['analysis_attempts'],0)
        self.assertEqual(runner.tick(self.now)['check']['status'],'not_due')
        factory.assert_not_called()
        self.assertEqual(self.schedule.state()['reminders'], [])

    def test_monthly_discovery_is_bounded_deduplicated_and_not_installed(self):
        with self.monitor._db() as db:
            db.execute('DELETE FROM discovery_runs')
        items=[{'full_name':f'new/project-{number}', 'html_url':f'https://github.com/new/project-{number}',
                'description':'desktop companion', 'stargazers_count':number,
                'updated_at':'2026-10-10T00:00:00Z','license':{'spdx_id':'MIT'}} for number in range(8)]
        calls=[]
        class Response:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self):return json.dumps({'items':items}).encode()
        runner=ReferenceRunner(self.monitor,notify=self.schedule.notify,
            fetch=lambda request,timeout:(calls.append(request.full_url) or Response()))
        first=self.monitor.discover(now=self.now,fetch=runner._fetch)
        second=self.monitor.discover(now=self.now,fetch=runner._fetch)
        self.assertEqual(first['status'],'checked')
        self.assertEqual(len(first['candidates']),3)
        self.assertEqual(second['status'],'not_due')
        self.assertEqual(len(calls),1)
        with self.monitor._db() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM discoveries').fetchone()[0],3)
        self.assertEqual(json.loads((self.root/'registry.json').read_text(encoding='utf8'))['projects'],[])
        next_month = datetime(2026,11,9,2,tzinfo=timezone.utc)
        third = self.monitor.discover(now=next_month,fetch=runner._fetch)
        self.assertEqual([item['repository'] for item in third['candidates']],
                         ['new/project-3','new/project-4','new/project-5'])

    def test_incomplete_discovery_does_not_commit_empty_month(self):
        with self.monitor._db() as db:
            db.execute('DELETE FROM discovery_runs')
        class Response:
            def __enter__(self): return self
            def __exit__(self,*args): pass
            def read(self): return b'{"items":[],"incomplete_results":true}'
        result = self.monitor.discover(now=self.now,fetch=lambda *args,**kwargs:Response())
        self.assertEqual(result['status'],'error')
        with self.monitor._db() as db:
            self.assertEqual(db.execute('SELECT completed FROM discovery_runs').fetchone()[0],0)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM discoveries').fetchone()[0],0)

    def test_monthly_discovery_failure_retries_without_installing(self):
        with self.monitor._db() as db:
            db.execute('DELETE FROM discovery_runs')
        count=[]
        def fail(*args,**kwargs):
            count.append(1);raise OSError('offline')
        first=self.monitor.discover(now=self.now,fetch=fail)
        self.assertEqual(first['status'],'error')
        self.assertEqual(self.monitor.discover(now=self.now,fetch=fail)['status'],'not_due')
        later=self.now.replace(hour=4)
        self.assertEqual(self.monitor.discover(now=later,fetch=fail)['status'],'error')
        self.assertEqual(len(count),2)

    def test_disabled_model_pending_notice_deduplicates_across_restart(self):
        self.queue()
        for _ in range(2):
            runner = ReferenceRunner(self.monitor, notify=self.schedule.notify, analyzer_factory=lambda:None)
            self.assertEqual(runner.tick(self.now)['analysis_attempts'],0)
        self.assertEqual(len(self.schedule.state()['reminders']),1)
        self.assertEqual(len(self.monitor.pending_reviews()),1)

    def test_related_analysis_uses_existing_inbox_and_ledger_once(self):
        self.queue()
        analyze = Mock(return_value={'classification':'worth-borrowing','summary':'Playback gating changed','modules':['voice']})
        runner = ReferenceRunner(self.monitor, notify=self.schedule.notify, analyzer_factory=lambda:analyze)
        self.assertEqual(runner.tick(self.now)['analysis_attempts'],1)
        self.assertEqual(runner.tick(self.now)['analysis_attempts'],0)
        analyze.assert_called_once()
        notices=self.schedule.state()['reminders']
        self.assertEqual(len(notices),1)
        self.assertIn('Playback gating changed',notices[0]['text'])
        self.assertEqual(self.monitor.analysis_reports()[0]['status'],'complete')

    def test_unrelated_analysis_stays_quiet(self):
        self.queue()
        runner=ReferenceRunner(self.monitor,notify=self.schedule.notify,analyzer_factory=lambda:
            lambda item:{'classification':'unrelated','summary':'Not relevant','modules':[]})
        runner.tick(self.now)
        self.assertEqual(self.schedule.state()['reminders'],[])

    def test_restart_recovers_report_without_replaying_model(self):
        self.queue()
        analyze = Mock(return_value={'classification':'worth-borrowing',
            'summary':'Recovered advice', 'modules':['voice']})
        self.monitor.analyze_pending(analyze, now=self.now)
        factory = Mock()
        runner = ReferenceRunner(self.monitor, notify=self.schedule.notify, analyzer_factory=factory)
        runner.tick(self.now)
        self.assertEqual(len(self.schedule.state()['reminders']),1)
        self.assertEqual(self.monitor.pending_notifications(),[])
        factory.assert_not_called()
        analyze.assert_called_once()

    def test_exit_after_inbox_write_deduplicates_retry(self):
        self.queue()
        self.monitor.analyze_pending(lambda item:{'classification':'needs-validation',
            'summary':'Check timing', 'modules':['voice']}, now=self.now)
        def notify(key, text):
            self.schedule.notify(key,text)
            raise ResearchStopped()
        runner=ReferenceRunner(self.monitor,notify=notify)
        with self.assertRaises(ResearchStopped):runner.tick(self.now)
        self.assertEqual(len(self.monitor.pending_notifications()),1)
        ReferenceRunner(self.monitor,notify=self.schedule.notify).tick(self.now)
        self.assertEqual(len(self.schedule.state()['reminders']),1)
        self.assertEqual(self.monitor.pending_notifications(),[])

    def test_failure_retry_time_does_not_duplicate_notification(self):
        runner=ReferenceRunner(self.monitor,notify=self.schedule.notify)
        for retry in ('first','later'):
            runner._notice({'kind':'reference-check-failed','cycle':'same','projects':['neko'],'retry_at':retry})
        self.assertEqual(len(self.schedule.state()['reminders']),1)

    def test_stop_during_fetch_closes_response_and_prevents_analysis(self):
        entered,release=threading.Event(),threading.Event()
        response=Mock()
        def fetch(*args,**kwargs):
            entered.set()
            self.assertTrue(release.wait(3))
            return response
        runner=ReferenceRunner(self.monitor,notify=Mock(),fetch=fetch)
        stopped=[]
        def run():
            try: runner._fetch('fixture')
            except ResearchStopped: stopped.append(True)
        thread=threading.Thread(target=run)
        thread.start()
        self.assertTrue(entered.wait(2))
        runner.stop();release.set();thread.join(3)
        self.assertFalse(thread.is_alive())
        response.close.assert_called_once()
        self.assertEqual(stopped,[True])
        with self.assertRaises(ResearchStopped):runner.tick(self.now)
