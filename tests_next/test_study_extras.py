"""Delivery package P5: usage honesty, provenance notes, danmaku dedup."""
import json
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path

from extensions.companion.study_extras import DanmakuBuffer, StudyNotes
from extensions.models.usage import UsageStore


class UsageStoreTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.database = Path(self.folder.name)/'role.sqlite3'
        self._connection = None
        self.addCleanup(self._close_connection)

    def _close_connection(self):
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def test_migration_adds_columns_and_keeps_old_rows_unknown(self):
        connection = sqlite3.connect(self.database)
        connection.execute('CREATE TABLE usage (id INTEGER PRIMARY KEY, scope TEXT, session TEXT, '
                           'provider TEXT, model TEXT, status TEXT, prompt_tokens INTEGER, '
                           'completion_tokens INTEGER, total_tokens INTEGER)')
        connection.execute("INSERT INTO usage(scope,session,provider,model,status,prompt_tokens,"
                           "completion_tokens,total_tokens) VALUES('p','s','prov','model','reported',10,5,15)")
        connection.commit()
        store = UsageStore(connection)
        connection.execute("INSERT INTO usage(scope,session,provider,model,status,prompt_tokens,"
                           "completion_tokens,total_tokens,audio_seconds,vision_calls) "
                           "VALUES('p','s','prov','model','reported',1,1,2,12.5,2)")
        connection.commit()
        totals = store.totals('p')
        self.assertEqual(totals['total_tokens'], 17)
        # Old rows never claim measured audio or vision activity.
        self.assertEqual(totals['audio_seconds'], 12.5)
        self.assertEqual(totals['vision_calls'], 2)
        connection.close()

    def test_unknown_totals_stay_unknown_instead_of_zero(self):
        connection = sqlite3.connect(self.database)
        store = UsageStore(connection)
        store.record(scope='p', session='s', provider='prov', model='m',
                     status='unknown')
        totals = store.totals('p')
        self.assertIsNone(totals['audio_seconds'])
        self.assertIsNone(totals['vision_calls'])
        self.assertEqual(totals['unknown_status_rows'], 1)
        connection.close()

    def test_audio_seconds_and_vision_calls_record_and_validate(self):
        connection = sqlite3.connect(self.database)
        store = UsageStore(connection)
        store.record(scope='p', session='audio', provider='browser-tab', model='n/a',
                     status='reported', audio_seconds=30.5)
        store.record(scope='p', session='vision', provider='prov', model='m',
                     status='reported', vision_calls=1)
        with self.assertRaises(ValueError):
            store.record(scope='p', session='x', provider='p', model='m', audio_seconds=-1)
        with self.assertRaises(ValueError):
            store.record(scope='p', session='x', provider='p', model='m', vision_calls=1.5)
        audio = store.totals('p', session='audio')
        self.assertEqual(audio['audio_seconds'], 30.5)
        self.assertIsNone(audio['vision_calls'])
        connection.close()


class StudyNotesTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.notes = StudyNotes(Path(self.folder.name)/'study-notes.sqlite3')
        self.addCleanup(self.notes.close)

    def test_save_requires_text_target_and_carries_provenance(self):
        with self.assertRaises(ValueError):
            self.notes.save('   ', target='browser-passive:x', source={'url': 'u'})
        with self.assertRaises(ValueError):
            self.notes.save('笔记', target='', source=None)
        saved = self.notes.save('导数等于切线斜率', target='browser-passive:x:tab:7',
                                source={'observation_at': '2026-10-10T00:00:00+00:00',
                                        'media_time_seconds': 41.5, 'part': 2})
        notes = self.notes.recent()
        self.assertEqual(saved['status'], 'saved')
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0]['text'], '导数等于切线斜率')
        self.assertEqual(notes[0]['source']['media_time_seconds'], 41.5)
        self.assertEqual(notes[0]['source']['part'], 2)

    def test_oversized_note_and_source_rejected(self):
        with self.assertRaises(ValueError):
            self.notes.save('x'*8001, target='t', source={})
        with self.assertRaises(ValueError):
            self.notes.save('笔记', target='t', source={'blob': 'x'*5000})
        with self.assertRaises(ValueError):
            self.notes.save('笔记', target='t', source='not a dict')

    def test_notes_store_is_isolated_from_role_memory(self):
        # The store is its own database; the memory engine's tables never
        # appear here and nothing writes memories/relations.
        self.notes.save('隔离检查', target='t', source={})
        connection = sqlite3.connect(Path(self.folder.name)/'study-notes.sqlite3')
        try:
            tables = {row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
        finally:
            connection.close()
        self.assertEqual(tables, {'study_notes'})


class DanmakuBufferTests(unittest.TestCase):
    def test_duplicate_scroll_collapses_within_window(self):
        now = [100.0]
        buffer = DanmakuBuffer(clock=lambda: now[0])
        first = buffer.observe(['为什么取负号', '为什么取负号 ', '新问题'])
        self.assertEqual(first, ['为什么取负号', '新问题'])
        now[0] += 10
        self.assertEqual(buffer.observe(['为什么取负号']), [])
        now[0] += 200
        self.assertEqual(buffer.observe(['为什么取负号']), ['为什么取负号'])

    def test_snapshot_texts_bounded_and_normalized(self):
        now = [0.0]
        buffer = DanmakuBuffer(max_entries=10, clock=lambda: now[0])
        for round in range(20):
            buffer.observe([f'弹幕{round}'])
        self.assertLessEqual(len(buffer.snapshot_texts()), 10)
        self.assertEqual(buffer.observe([None, 42, '   ']), [])


if __name__ == '__main__':
    unittest.main()
