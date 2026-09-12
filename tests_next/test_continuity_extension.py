import importlib.util
import json
from pathlib import Path
import sqlite3
import unittest
from concurrent.futures import ThreadPoolExecutor

from tests_next.scratch import ScratchDirectory as TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('independent_continuity', ROOT/'extensions/continuity/continuity.py')
core = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(core)


class ExtensionTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        core.initialize(self.root)

    def ingest(self, events, session='one'):
        return core.handle(self.root, {'action': 'ingest', 'harness': 'test',
            'session': session, 'events': events})

    def original(self, value='原文\r\n  ```x```  ', source_id='1'):
        return {'source_id': source_id, 'kind': 'original',
                'payload': {'source': {'kind': 'user'}, 'content': [{'type': 'text', 'text': value}]}}

    def query(self, **query):
        return core.handle(self.root, {'action': 'query', 'query': query})['records']

    def plan(self, plan='first'):
        return {'kind': 'plan', 'task': 'task', 'summary': 'plan update', 'sources': [],
                'uncertainties': ['scope unconfirmed'], 'plan': plan, 'reason': 'new evidence',
                'affected_tasks': ['task']}

    def test_original_preserved_and_replay_idempotent(self):
        event = self.original()
        self.ingest([event]); self.ingest([event])
        rows = self.query()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['payload'], event['payload'])
        self.assertEqual(rows[0]['provenance'], 'host_observation')

    def test_conflicting_replay_rolls_back_batch(self):
        self.ingest([self.original()])
        with self.assertRaisesRegex(ValueError, 'conflicting'):
            self.ingest([self.original(source_id='2'), self.original('changed')])
        self.assertEqual(len(self.query()), 1)

    def test_plugin_is_not_original(self):
        e = self.original(); e['payload']['source']['kind'] = 'plugin'
        with self.assertRaises(ValueError): self.ingest([e])

    def test_model_cannot_write_original_or_authority(self):
        for kind in ['original', 'approval', 'complete']:
            p = self.plan(); p['kind'] = kind
            with self.assertRaises(ValueError): core.report(self.root, 'one', 'id', p)

    def test_plan_history_retry_and_cross_model_recovery(self):
        core.report(self.root, 'one', 'p1', self.plan())
        core.report(self.root, 'two', 'p2', self.plan('second'))
        core.report(self.root, 'one', 'p1', self.plan())
        records = self.query(kind='plan')
        self.assertEqual(len(records), 2)
        self.assertEqual(records[1]['payload']['previous_plan']['plan'], 'first')
        state = core.handle(self.root, {'action': 'recover'})
        self.assertEqual(state['tasks'][0]['latest']['plan']['payload']['plan'], 'second')

    def test_unknown_sources_rejected(self):
        p = self.plan(); p['sources'] = ['not-real']
        with self.assertRaises(ValueError): core.report(self.root, 'one', 'p', p)

    def test_failed_not_run_and_remaining_preserved(self):
        p = {'kind': 'outcome', 'task': 'task', 'summary': 'partial', 'sources': [],
             'uncertainties': [], 'implemented': ['reader'], 'remaining': ['writer'],
             'limitations': ['offline'], 'next': 'implement writer',
             'verification': [{'command': 'test', 'result': 'failed', 'evidence': []},
                              {'command': 'live', 'result': 'not_run', 'evidence': []}]}
        core.report(self.root, 'one', 'o1', p)
        r = self.query(kind='outcome')[0]
        self.assertEqual(r['payload'], p)
        self.assertEqual(r['provenance'], 'model_report')
        self.assertFalse((self.root/'docs/project/progress.json').exists())

    def test_query_pagination_and_project_isolation(self):
        for i in range(4): self.ingest([self.original(str(i), str(i))])
        first = self.query(limit=2)
        second = self.query(after=first[-1]['seq'], limit=2)
        self.assertEqual(len({r['id'] for r in first+second}), 4)
        with TemporaryDirectory() as other:
            core.initialize(other)
            self.assertEqual(core.handle(other, {'action': 'query'})['records'], [])

    def test_view_can_be_rebuilt(self):
        self.ingest([self.original()])
        path = self.root/core.DIRECTORY/'handoff.json'
        path.write_text('invalid')
        core.handle(self.root, {'action': 'recover'})
        self.assertEqual(len(json.loads(path.read_text(encoding='utf-8'))['tasks']), 1)

    def test_invalid_query_bounds_and_utf8_rejected(self):
        for q in [{'after': -1}, {'limit': 0}, {'limit': 101}]:
            with self.assertRaises(ValueError): self.query(**q)
        with self.assertRaises(UnicodeError): self.ingest([self.original('\ud800')])

    def test_local_raw_records_ignored(self):
        self.assertEqual((self.root/core.DIRECTORY/'.gitignore').read_text(), '*\n')

    def test_concurrent_writers_do_not_lose_or_duplicate_records(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda i: self.ingest([self.original(str(i), str(i))]), range(12)))
        self.assertEqual(len(results), 12)
        self.assertEqual(len(self.query()), 12)

    def test_goal_decision_source_links_and_unknown_fields(self):
        self.ingest([self.original()]); source = self.query()[0]['id']
        goal = {'kind': 'goal', 'task': 'task', 'summary': 'current objective',
                'sources': [source], 'uncertainties': []}
        core.report(self.root, 'two', 'g', goal)
        core.report(self.root, 'two', 'd', dict(goal, kind='decision', reason='user clarified'))
        self.assertEqual(self.query(kind='decision')[0]['payload']['sources'], [source])
        with self.assertRaises(ValueError):
            core.report(self.root, 'two', 'unsafe', dict(goal, approved=True))

    def test_same_id_different_report_does_not_overwrite(self):
        core.report(self.root, 'one', 'p', self.plan())
        with self.assertRaisesRegex(ValueError, 'conflicting'):
            core.report(self.root, 'one', 'p', self.plan('replacement'))
        self.assertEqual(self.query(kind='plan')[0]['payload']['plan'], 'first')

    def test_database_error_is_not_an_empty_success(self):
        path = self.root/core.DIRECTORY/'records.sqlite3'
        path.write_bytes(b'not a sqlite database')
        with self.assertRaises(sqlite3.DatabaseError):
            core.handle(self.root, {'action': 'recover'})


if __name__ == '__main__':
    unittest.main()
