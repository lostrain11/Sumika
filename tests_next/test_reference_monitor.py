import json
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
import threading
import io
from contextlib import redirect_stdout
from urllib.error import HTTPError
from pathlib import Path
from unittest.mock import patch

from extensions.desktop.reference_monitor import ReferenceMonitor


class ReferenceMonitorTests(unittest.TestCase):
    def queue_reviews(self, count):
        with self.monitor._db() as db:
            for number in range(count):
                db.execute('INSERT INTO reviews VALUES (?,?,?,?,?)',
                    (f'project-{number}',f'{number:040x}','abcdef1234567',
                     json.dumps({'url':f'https://api.github.com/repos/example/project/compare/{number}',
                                 'files':['src/voice.py']}),'pending'))

    def test_analysis_quota_survives_concurrent_and_restarted_runner(self):
        self.queue_reviews(7)
        analyzer=lambda item: {'classification':'needs-validation','summary':'Check interrupt handling','modules':['voice']}
        now=datetime(2026,10,12,2,tzinfo=timezone.utc)
        results=[]
        workers=[threading.Thread(target=lambda:results.append(self.monitor.analyze_pending(analyzer,now=now))) for _ in range(2)]
        for worker in workers: worker.start()
        for worker in workers: worker.join(3)
        self.assertEqual(sum(result['analysis_attempts'] for result in results),5)
        restarted=ReferenceMonitor(self.registry,self.monitor.database)
        self.assertEqual(restarted.analyze_pending(analyzer,now=now)['analysis_attempts'],0)
        self.assertEqual(restarted.analyze_pending(analyzer,now=now+timedelta(days=7))['analysis_attempts'],2)
        self.assertTrue(restarted.analysis_reports()[0]['report']['sources'])

    def test_analysis_failure_not_replayed_or_leaked(self):
        self.queue_reviews(1)
        analyzer=unittest.mock.Mock(side_effect=RuntimeError('secret-provider-key'))
        first=self.monitor.analyze_pending(analyzer)
        self.assertEqual(first['reports'][0]['status'],'needs-attention')
        self.assertNotIn('secret-provider-key',json.dumps(first))
        self.assertEqual(self.monitor.analyze_pending(analyzer)['analysis_attempts'],0)
        self.assertEqual(analyzer.call_count,1)

    def test_empty_analysis_does_not_call_model(self):
        analyzer=unittest.mock.Mock()
        self.assertEqual(self.monitor.analyze_pending(analyzer)['analysis_attempts'],0)
        analyzer.assert_not_called()

    def test_interrupted_analysis_remains_started_without_replay(self):
        self.queue_reviews(1)
        with self.assertRaises(KeyboardInterrupt):
            self.monitor.analyze_pending(lambda item: (_ for _ in ()).throw(KeyboardInterrupt()))
        restarted=ReferenceMonitor(self.registry,self.monitor.database)
        analyzer=unittest.mock.Mock()
        self.assertEqual(restarted.analyze_pending(analyzer)['analysis_attempts'],0)
        analyzer.assert_not_called()
        self.assertEqual(restarted.analysis_reports()[0]['status'],'started')

    def test_invalid_analysis_cannot_become_completed_report(self):
        self.queue_reviews(1)
        result=self.monitor.analyze_pending(lambda item:{'classification':'worth-borrowing','summary':'Apply update','modules':[],'install':True})
        self.assertEqual(result['reports'][0]['status'],'needs-attention')

    def test_default_registry_uses_product_root_and_offline_pending_uses_personal_data(self):
        from tools.check_reference_projects import default_registry, main
        root=Path(self.directory.name)
        packaged=root/'extensions/desktop/reference-projects.json'
        packaged.parent.mkdir(parents=True)
        packaged.write_bytes(self.registry.read_bytes())
        self.assertEqual(default_registry(root),packaged)
        source=root/'docs/project/reference-projects.json'
        source.parent.mkdir(parents=True)
        source.write_bytes(self.registry.read_bytes())
        self.assertEqual(default_registry(root),source)
        data=root/'personal'
        with patch('sys.argv',['check_reference_projects','--pending']), \
             patch('tools.check_reference_projects.default_registry',return_value=packaged), \
             patch('tools.check_reference_projects.user_data_directory',return_value=data), \
             patch.object(ReferenceMonitor,'check') as check, redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(),0)
        check.assert_not_called()
        self.assertEqual(json.loads(output.getvalue())['pending_reviews'],[])
        self.assertTrue((data/'reference-projects.sqlite3').is_file())

    def test_cli_failed_check_has_nonzero_exit_and_structured_report(self):
        from tools.check_reference_projects import main
        result={'status':'checked','model_calls':0,'projects':[{'status':'error','error':'quota'}]}
        with patch('sys.argv', ['check_reference_projects', '--database', str(self.monitor.database),
                                '--registry', str(self.registry)]), \
             patch.object(ReferenceMonitor, 'check', return_value=result), redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(), 2)
        self.assertEqual(json.loads(output.getvalue()), result)

    def test_retry_reuses_same_cycle_success_and_fetches_missing_only(self):
        self.registry.write_text(json.dumps({'projects':[
            {'id':'first','url':'https://github.com/example/first'},
            {'id':'second','url':'https://github.com/example/second'}]}))
        now = datetime(2026,10,12,2,tzinfo=timezone.utc)
        calls = []
        original = self.fetch()
        def partial(request, **kwargs):
            calls.append(request.full_url)
            if '/second/' in request.full_url:
                raise OSError('offline')
            return original(request, **kwargs)
        self.assertFalse(self.monitor.check(now=now,fetch=partial)['complete'])
        calls.clear()
        def recovered(request, **kwargs):
            calls.append(request.full_url)
            return original(request, **kwargs)
        result = self.monitor.check(now=now+timedelta(hours=1),fetch=recovered)
        self.assertTrue(result['complete'])
        self.assertEqual(len(calls),1)
        self.assertIn('/second/',calls[0])
        self.assertTrue(result['projects'][0]['reused_cycle_result'])
        calls.clear()
        self.monitor.check(now=now+timedelta(hours=2),force=True,fetch=recovered)
        self.assertEqual(len(calls),2)
        calls.clear()
        self.monitor.check(now=now+timedelta(days=7),fetch=recovered)
        self.assertEqual(len(calls),2)

    def test_quota_failure_stops_batch_and_obeys_server_retry(self):
        now = datetime(2026, 10, 12, 2, tzinfo=timezone.utc)
        self.registry.write_text(json.dumps({'projects':[
            {'id':'a','url':'https://github.com/example/a'},
            {'id':'b','url':'https://github.com/example/b'}]}))
        error = HTTPError('https://api.github.com', 403, 'rate limit exceeded',
            {'X-RateLimit-Remaining':'0', 'Retry-After':'7200'}, None)
        with patch.object(self.monitor, 'fetch_revision', side_effect=error) as fetch:
            result=self.monitor.check(now=now)
        self.assertEqual(fetch.call_count, 1)
        self.assertTrue(result['rate_limited'])
        self.assertFalse(self.monitor.due(now=now+timedelta(hours=1)))
        self.assertTrue(self.monitor.due(now=now+timedelta(hours=2)))
        self.assertEqual(result['model_calls'], 0)

    def test_rate_limit_headers_and_permission_error_distinction(self):
        now=datetime(2026, 10, 12, 2, tzinfo=timezone.utc)
        retry=now+timedelta(hours=3)
        for headers in ({'Retry-After':'Mon, 12 Oct 2026 05:00:00 GMT'},
                        {'X-RateLimit-Reset':str(int(retry.timestamp()))}):
            self.assertEqual(self.monitor.rate_limit_retry(HTTPError('url',429,'quota',headers,None),now),retry)
        self.assertIsNone(self.monitor.rate_limit_retry(HTTPError('url',403,'Forbidden',{},None),now))
        self.assertEqual(self.monitor.rate_limit_retry(HTTPError('url',429,'quota',{'Retry-After':'bad'},None),now),now+timedelta(hours=1))

    @staticmethod
    def fetch(sha='abcdef1234567'):
        return lambda *args, **kwargs: type('Response', (), {
            '__enter__':lambda s:s, '__exit__':lambda *a:None,
            'read':lambda s:json.dumps([{'sha':sha}]).encode()})()

    def test_monday_shanghai_boundary_and_merged_startup_catchup(self):
        before = datetime(2026, 10, 12, 1, 59, tzinfo=timezone.utc)
        at = before + timedelta(minutes=1)
        self.monitor.check(now=before, fetch=self.fetch())
        self.assertFalse(self.monitor.due(now=before))
        self.assertTrue(self.monitor.due(now=at))
        result = self.monitor.check(now=at+timedelta(days=30), fetch=self.fetch())
        self.assertEqual(result['checked'], 1)
        self.assertEqual(result['cycle'], '2026-11-09T10:00:00+08:00')
        self.assertFalse(self.monitor.due(now=at+timedelta(days=30)))

    def test_error_preserves_revision_and_has_retry_cooldown(self):
        now = datetime(2026, 10, 12, 2, tzinfo=timezone.utc)
        self.monitor.check(now=now, fetch=self.fetch())
        failed = self.monitor.check(now=now+timedelta(days=7),
            fetch=lambda *a, **kw: (_ for _ in ()).throw(OSError('rate limited')))
        self.assertEqual(failed['projects'][0]['revision'], 'abcdef1234567')
        self.assertFalse(self.monitor.due(now=now+timedelta(days=7, minutes=59)))
        retry = self.monitor.check(now=now+timedelta(days=7, hours=1), fetch=self.fetch())
        self.assertEqual(retry['projects'][0]['status'], 'unchanged')

    def test_concurrent_check_claim_and_crash_lease(self):
        now = datetime(2026, 10, 12, 2, tzinfo=timezone.utc)
        entered, release = threading.Event(), threading.Event()
        def blocked(*args, **kwargs):
            entered.set()
            release.wait(3)
            return self.fetch()()
        results = []
        worker = threading.Thread(target=lambda:results.append(self.monitor.check(now=now, fetch=blocked)))
        worker.start()
        try:
            self.assertTrue(entered.wait(2))
            with patch.object(self.monitor, 'fetch_revision') as fetch:
                self.assertEqual(self.monitor.check(now=now)['status'], 'not_due')
                fetch.assert_not_called()
        finally:
            release.set()
            worker.join(3)
        self.assertEqual(results[0]['checked'], 1)
        later = now+timedelta(days=7)
        self.assertIsNotNone(self.monitor._claim(later, False))
        self.assertFalse(self.monitor.due(now=later+timedelta(minutes=19)))
        self.assertTrue(self.monitor.due(now=later+timedelta(minutes=20)))

    def test_partial_run_does_not_complete_period(self):
        self.registry.write_text(json.dumps({'projects':[
            {'id':'a','url':'https://github.com/example/a'},
            {'id':'b','url':'https://github.com/example/b'}]}))
        now=datetime(2026, 10, 12, 2, tzinfo=timezone.utc)
        self.assertFalse(self.monitor.check(now=now, limit=1, fetch=self.fetch())['complete'])
        self.assertTrue(self.monitor.due(now=now+timedelta(hours=1)))

    def test_naive_clock_rejected(self):
        with self.assertRaises(ValueError): self.monitor.due(now=datetime(2026, 10, 12))

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        root = Path(self.directory.name)
        self.registry = root / 'references.json'
        self.registry.write_text(json.dumps({'projects': [
            {'id': 'demo', 'url': 'https://github.com/example/project'}]}), encoding='utf8')
        self.monitor = ReferenceMonitor(self.registry, root / 'checks.sqlite3')

    def tearDown(self): self.directory.cleanup()

    def test_first_check_baseline_then_no_change_and_change(self):
        def fetch(request, timeout):
            class Response:
                def __enter__(self): return self
                def __exit__(self, *args): pass
                def read(self): return b'[{"sha":"abcdef1234567"}]'
            return Response()
        first = self.monitor.check(force=True, fetch=fetch)
        self.assertEqual(first['projects'][0]['status'], 'baseline')
        second = self.monitor.check(force=True, fetch=fetch)
        self.assertEqual(second['projects'][0]['status'], 'unchanged')
        def changed(request, timeout):
            class Response:
                def __enter__(self): return self
                def __exit__(self, *args): pass
                def read(self):
                    return (b'{"status":"ahead","files":[{"filename":"src/voice.py"}]}'
                            if '/compare/' in request.full_url else b'[{"sha":"fedcba1234567"}]')
            return Response()
        self.assertEqual(self.monitor.check(force=True, fetch=changed)['projects'][0]['status'], 'changed')

    def test_related_change_queue_survives_unchanged_check(self):
        self.registry.write_text(json.dumps({'projects':[{'id':'demo','url':'https://github.com/example/project'}],
            'relevance_paths':{'demo':['src/*']}}))
        self.monitor.check(force=True, fetch=self.fetch())
        def changed(request, **kwargs):
            payload = ({'status':'ahead','files':[{'filename':'src/voice.py'}]}
                       if '/compare/' in request.full_url else [{'sha':'fedcba1234567'}])
            return type('Response', (), {'__enter__':lambda s:s,'__exit__':lambda *a:None,
                                        'read':lambda s:json.dumps(payload).encode()})()
        result=self.monitor.check(force=True,fetch=changed)
        self.assertEqual(result['pending_reviews'][0]['comparison']['classification'],'worth-reviewing')
        self.assertEqual(result['model_calls'],0)
        with patch.object(self.monitor,'compare') as compare:
            result=self.monitor.check(force=True,fetch=self.fetch('fedcba1234567'))
        compare.assert_not_called()
        self.assertEqual(len(result['pending_reviews']),1)
        queued=self.monitor.check(fetch=self.fetch('fedcba1234567'))
        self.assertEqual(queued['status'],'not_due')
        self.assertEqual(len(queued['pending_reviews']),1)

    def test_compare_failure_preserves_baseline_for_retry(self):
        self.monitor.check(force=True,fetch=self.fetch())
        with patch.object(self.monitor,'compare',side_effect=OSError('offline')):
            result=self.monitor.check(force=True,fetch=self.fetch('fedcba1234567'))
        self.assertEqual(result['projects'][0]['status'],'error')
        self.assertEqual(result['projects'][0]['revision'],'abcdef1234567')
        self.assertEqual(self.monitor.pending_reviews(),[])

    def test_unrelated_rename_and_truncated_comparison(self):
        self.registry.write_text(json.dumps({'projects':[{'id':'demo','url':'https://github.com/example/project'}],
            'relevance_paths':{'demo':['src/*']}}))
        def compare(files):
            def fetch(*args, **kwargs):
                return type('Response', (), {'__enter__':lambda s:s,'__exit__':lambda *a:None,
                    'read':lambda s:json.dumps({'status':'ahead','files':[
                        dict(row,patch='diff --git a/src/voice.py b/src/voice.py\n+@@ -1 +1 @@\n-old\n+new')
                        for row in files]}).encode()})()
            return self.monitor.compare(self.monitor.projects()[0],'abcdef1234567','fedcba1234567',fetch=fetch)
        self.assertEqual(compare([{'filename':'docs/help.md'}])['classification'],'unrelated')
        evidence=compare([{'filename':'src/voice.py'}])
        self.assertIn('src/voice.py',evidence['patches'])
        self.assertEqual(compare([{'filename':'archive/voice.py','previous_filename':'src/voice.py'}])['classification'],'worth-reviewing')
        result=compare([{'filename':f'docs/{i}.md'} for i in range(300)])
        self.assertEqual(result['classification'],'needs-validation')
        self.assertTrue(result['incomplete'])

    def test_diff_evidence_budget_missing_and_unrelated_files(self):
        self.registry.write_text(json.dumps({'projects':[{'id':'demo','url':'https://github.com/example/project'}],
            'relevance_paths':{'demo':['src/*']}}))
        def compare(files):
            def fetch(*args, **kwargs):
                return type('Response', (), {'__enter__':lambda s:s,'__exit__':lambda *a:None,
                    'read':lambda s:json.dumps({'status':'ahead','files':files}).encode()})()
            return self.monitor.compare(self.monitor.projects()[0],'abcdef1234567','fedcba1234567',fetch=fetch)
        result=compare([{'filename':'src/a.py','patch':'界'*10000},
                        {'filename':'src/b.bin'}, {'filename':'docs/readme','patch':'ignore'}])
        self.assertLessEqual(sum(len(p.encode('utf8')) for p in result['patches'].values()),12000)
        self.assertTrue(result['patch_truncated'])
        self.assertEqual(result['missing_patches'],['src/b.bin'])
        result=compare([{'filename':'docs/a','patch':'ignored'}])
        self.assertEqual(result['patches'],{})
        self.assertFalse(result['patch_truncated'])
        result=compare([{'filename':'archive/a.py','previous_filename':'src/a.py','patch':'+change'}])
        self.assertEqual(result['patches'],{'archive/a.py':'+change'})

    def test_weekly_due_and_not_due(self):
        now = datetime(2026, 10, 12, tzinfo=timezone.utc)
        self.assertTrue(self.monitor.due(now=now))
        fetch = lambda *args, **kwargs: type('Response', (), {'__enter__': lambda s: s, '__exit__': lambda *a: None, 'read': lambda s: b'[{"sha":"abcdef1234567"}]'})()
        self.monitor.check(force=True, fetch=fetch, now=now)
        self.assertFalse(self.monitor.due(now=now))
        self.assertTrue(self.monitor.due(now=now.replace(day=20)))

    def test_errors_are_recorded_without_install_or_model(self):
        result = self.monitor.check(force=True, fetch=lambda *args, **kwargs: (_ for _ in ()).throw(OSError('offline')))
        self.assertEqual(result['model_calls'], 0)
        self.assertEqual(result['projects'][0]['status'], 'error')
