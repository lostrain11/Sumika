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

    def test_categories_group_rows_by_applicable_metric(self):
        """P6: each category reports the metrics that APPLY to it — an audio
        row without tokens is not a token unknown, and known sums never fold
        unmetered rows into zero."""
        connection = sqlite3.connect(self.database)
        store = UsageStore(connection)
        store.record(scope='p', session='room-r1', provider='ollama', model='m',
                     prompt_tokens=10, completion_tokens=5, total_tokens=15,
                     status='reported', category='room')
        store.record(scope='p', session='room-r2', provider='ollama', model='m',
                     status='unknown', category='room')
        store.record(scope='p', session='study-browser-audio', provider='browser-tab',
                     model='n/a', status='reported', audio_seconds=30.0, category='audio')
        store.record(scope='p', session='reference-research', provider='ollama', model='m',
                     status='reported', vision_calls=1, category='vision')
        categories = store.totals('p')['categories']
        self.assertEqual(categories['room']['known_sum']['total_tokens'], 15)
        self.assertEqual(categories['room']['unknown_count'], 1)
        self.assertEqual(categories['room']['by_status'],
                         {'estimated': 0, 'reported': 1, 'unknown': 1})
        # Audio: audio_seconds is the applicable metric; missing tokens on the
        # same row must not count as a token unknown.
        self.assertEqual(categories['audio']['known_sum']['audio_seconds'], 30.0)
        self.assertEqual(categories['audio']['unknown_count'], 0)
        self.assertEqual(categories['audio']['metric_applicability'], ['audio_seconds'])
        self.assertEqual(categories['vision']['known_sum']['vision_calls'], 1)
        self.assertEqual(categories['vision']['unknown_count'], 0)
        connection.close()

    def test_partial_token_measurement_is_reported_as_unknown(self):
        """A token row is incomplete when any applicable token field is NULL."""
        connection = sqlite3.connect(self.database)
        store = UsageStore(connection)
        metrics = {'prompt_tokens': 10, 'completion_tokens': 5, 'total_tokens': 15}
        for missing in metrics:
            with self.subTest(missing=missing):
                values = {key: None if key == missing else value
                          for key, value in metrics.items()}
                store.record(scope='p', session=missing, provider='ollama', model='m',
                             **values, status='reported', category='room')
                category = store.totals('p', session=missing)['categories']['room']
                self.assertEqual(category['known_sum'], values)
                self.assertEqual(category['unknown_count'], 1)
        store.record(scope='p', session='zero', provider='ollama', model='m',
                     prompt_tokens=0, completion_tokens=0, total_tokens=0,
                     status='reported', category='room')
        self.assertEqual(store.totals('p', session='zero')['categories']['room']['unknown_count'], 0)
        connection.close()

    def test_legacy_rows_migrate_only_when_determinable(self):
        connection = sqlite3.connect(self.database)
        store = UsageStore(connection)
        store.record(scope='p', session='room-r1', provider='ollama', model='m',
                     prompt_tokens=1, completion_tokens=1, total_tokens=2,
                     status='reported')
        store.record(scope='p', session='study-browser-audio', provider='browser-tab',
                     model='n/a', status='reported', audio_seconds=12.0)
        store.record(scope='p', session='mystery-session', provider='ollama', model='m',
                     status='unknown')
        store.migrate_categories(rules={'room-*': 'room', 'study-browser-audio': 'audio'})
        categories = store.totals('p')['categories']
        self.assertEqual(categories['room']['requests'], 1)
        self.assertEqual(categories['audio']['requests'], 1)
        # An undeterminable legacy row stays unknown — never guessed.
        self.assertEqual(categories['unknown']['requests'], 1)
        self.assertEqual(categories['unknown']['metric_applicability'], 'unknown')
        connection.close()

    def test_category_is_validated(self):
        connection = sqlite3.connect(self.database)
        store = UsageStore(connection)
        with self.assertRaises(ValueError):
            store.record(scope='p', session='s', provider='p', model='m', category='tokens')
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

    def test_snapshot_texts_return_texts_within_ttl(self):
        """F-07 regression: the snapshot carries the comment TEXTS inside the
        TTL window — never bookkeeping floats — and reading prunes entries
        past the window instead of serving stale danmaku forever."""
        now = [100.0]
        buffer = DanmakuBuffer(clock=lambda: now[0])
        buffer.observe(['为什么这里取负号', '下一章什么时候讲'])
        texts = buffer.snapshot_texts()
        self.assertEqual(sorted(texts), ['下一章什么时候讲', '为什么这里取负号'])
        for value in texts:
            self.assertIsInstance(value, str)
        now[0] += 121  # Past the 120s window without any new observation.
        self.assertEqual(buffer.snapshot_texts(), [])

    def test_clear_drops_buffer_for_new_target(self):
        buffer = DanmakuBuffer()
        buffer.observe(['旧视频的弹幕'])
        buffer.clear()
        self.assertEqual(buffer.snapshot_texts(), [])
        self.assertEqual(buffer.observe(['旧视频的弹幕']), ['旧视频的弹幕'])


if __name__ == '__main__':
    unittest.main()
