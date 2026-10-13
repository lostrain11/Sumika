"""P08 behavior library: host scope isolation, event idempotency, explicit
confirmed deletion, bounded fields, pagination and the revision contract."""
import json
import tempfile
import unittest
from pathlib import Path

from extensions.behavior.library import BehaviorLibrary

SCOPE_A = {'user': 'project-a', 'session': 'target-1'}
SCOPE_B = {'user': 'project-b', 'session': 'target-1'}


def event(event_id, kind='flip_burst', **overrides):
    base = {'event_id': event_id, 'kind': kind, 'source': 'reading-tracker',
            'target': '第 3 页'}
    base.update(overrides)
    return base


class BehaviorLibraryTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.library = BehaviorLibrary(Path(self.folder.name)/'behavior.sqlite3')

    # -- idempotency ---------------------------------------------------------
    def test_same_event_id_and_payload_is_a_noop(self):
        first = self.library.observe(event('e1'), scope=SCOPE_A)
        again = self.library.observe(event('e1'), scope=SCOPE_A)
        self.assertEqual(first['status'], 'recorded')
        self.assertEqual(again['status'], 'duplicate')
        records = self.library.list_records(scope=SCOPE_A)['records']
        self.assertEqual(len(records), 1)

    def test_same_event_id_with_different_payload_is_rejected(self):
        self.library.observe(event('e1'), scope=SCOPE_A)
        with self.assertRaises(ValueError):
            self.library.observe(event('e1', kind='long_dwell'), scope=SCOPE_A)
        with self.assertRaises(ValueError):
            self.library.observe(event('e1', target='第 9 页'), scope=SCOPE_A)
        # The stored record is untouched by the rejected writes.
        self.assertEqual(len(self.library.list_records(scope=SCOPE_A)['records']), 1)

    # -- scope isolation -----------------------------------------------------
    def test_scopes_are_isolated(self):
        self.library.observe(event('shared-id'), scope=SCOPE_A)
        # A different host scope may reuse the id: its records are its own.
        self.library.observe(event('shared-id'), scope=SCOPE_B)
        a = self.library.list_records(scope=SCOPE_A)['records']
        b = self.library.list_records(scope=SCOPE_B)['records']
        self.assertEqual([row['event_id'] for row in a], ['shared-id'])
        self.assertEqual([row['event_id'] for row in b], ['shared-id'])
        self.assertEqual(self.library.export(scope=SCOPE_A)['scope_user'],
                         'project-a')
        # Deleting in scope A leaves scope B untouched.
        revision = int(self.library.status()['revision'])
        self.library.delete_records(scope=SCOPE_A, event_ids=['shared-id'],
                                    confirmed=True, revision=revision)
        self.assertEqual(self.library.list_records(scope=SCOPE_A)['records'], [])
        self.assertEqual(len(self.library.list_records(scope=SCOPE_B)['records']), 1)

    # -- bounded fields ------------------------------------------------------
    def test_raw_content_fields_are_structurally_impossible(self):
        for field in ('text', 'pcm', 'screenshot', 'url', 'keys', 'clipboard'):
            with self.assertRaises(ValueError, msg=field):
                self.library.observe(event('e1', **{field: 'blob'}), scope=SCOPE_A)
        with self.assertRaises(ValueError):
            self.library.observe(event('e1', kind='unknown_kind'), scope=SCOPE_A)
        with self.assertRaises(ValueError):
            self.library.observe(event('e1', target='x' * 257), scope=SCOPE_A)
        with self.assertRaises(ValueError):
            self.library.observe(event('e1', features={'nested': {'a': 1}}),
                                 scope=SCOPE_A)
        self.assertEqual(self.library.list_records(scope=SCOPE_A)['records'], [])

    # -- deletion ------------------------------------------------------------
    def test_deletion_requires_confirmation_and_a_selection(self):
        with self.assertRaises(ValueError):
            self.library.delete_records(scope=SCOPE_A, event_ids=['e1'])
        self.library.observe(event('e1'), scope=SCOPE_A)
        with self.assertRaises(ValueError):
            self.library.delete_records(scope=SCOPE_A, confirmed=True,
                                        revision=int(self.library.status()['revision']))
        with self.assertRaises(ValueError):
            self.library.delete_records(scope=SCOPE_A, event_ids=['e1'],
                                        confirmed=True, kinds=('nope',),
                                        revision=int(self.library.status()['revision']))

    def test_confirmed_deletion_covers_feedback_prompts_patterns_and_epoch(self):
        self.library.observe(event('e1'), scope=SCOPE_A)
        self.library.observe(event('e2', kind='long_dwell'), scope=SCOPE_A)
        self.library.feedback({'feedback_id': 'f1', 'user_event_id': 'host-1',
                               'event_id': 'e1', 'verdict': 'confirm'},
                              scope=SCOPE_A)
        revision = int(self.library.status()['revision'])
        # Revision guard: a stale revision mutates nothing.
        with self.assertRaises(ValueError):
            self.library.delete_records(scope=SCOPE_A, event_ids=['e1'],
                                        confirmed=True, revision=revision - 1)
        result = self.library.delete_records(scope=SCOPE_A, event_ids=['e1'],
                                             confirmed=True, revision=revision)
        self.assertEqual(result['status'], 'deleted')
        self.assertEqual(result['deleted_events'], 1)
        self.assertEqual(result['deleted_feedback'], 1)
        self.assertGreater(result['behavior_epoch'], 1)
        remaining = self.library.list_records(scope=SCOPE_A)['records']
        self.assertEqual([row['event_id'] for row in remaining], ['e2'])
        exported = self.library.export(scope=SCOPE_A)
        self.assertEqual(exported['feedback'], [])
        # Epoch advanced: cached readers can detect the invalidation.
        self.assertEqual(self.library.status()['behavior_epoch'],
                         result['behavior_epoch'])

    # -- pagination ----------------------------------------------------------
    def test_list_records_paginates_with_bounded_limit(self):
        for index in range(7):
            self.library.observe(event(f'e{index:02d}'), scope=SCOPE_A)
        with self.assertRaises(ValueError):
            self.library.list_records(scope=SCOPE_A, limit=101)
        page_one = self.library.list_records(scope=SCOPE_A, limit=3)
        self.assertEqual(len(page_one['records']), 3)
        self.assertIsNotNone(page_one['next_cursor'])
        page_two = self.library.list_records(scope=SCOPE_A, limit=3,
                                             cursor=page_one['next_cursor'])
        page_three = self.library.list_records(scope=SCOPE_A, limit=3,
                                               cursor=page_two['next_cursor'])
        seen = [row['event_id'] for row in page_one['records']
                + page_two['records'] + page_three['records']]
        self.assertEqual(len(seen), 7)
        self.assertEqual(len(set(seen)), 7)
        self.assertIsNone(page_three['next_cursor'])

    # -- feedback / correct / configure --------------------------------------
    def test_feedback_dedup_and_revision_guarded_correction(self):
        entry = {'feedback_id': 'f1', 'user_event_id': 'host-1',
                 'event_id': 'e1', 'verdict': 'confirm'}
        self.library.observe(event('e1'), scope=SCOPE_A)
        first = self.library.feedback(entry, scope=SCOPE_A)
        self.assertEqual(first['status'], 'recorded')
        self.assertEqual(self.library.feedback(entry, scope=SCOPE_A)['status'],
                         'duplicate')
        revision = int(self.library.status()['revision'])
        with self.assertRaises(ValueError):
            self.library.correct('f1', '其实是在回看错题', scope=SCOPE_A,
                                 revision=revision + 5)
        corrected = self.library.correct('f1', '其实是在回看错题', scope=SCOPE_A,
                                         revision=revision)
        self.assertEqual(corrected['status'], 'corrected')
        exported = self.library.export(scope=SCOPE_A)['feedback']
        self.assertEqual(exported[0]['verdict'], 'correct')
        self.assertEqual(exported[0]['corrected'], '其实是在回看错题')

    def test_configure_requires_revision_and_toggles_enabled(self):
        revision = int(self.library.status()['revision'])
        with self.assertRaises(ValueError):
            self.library.configure({'enabled': False}, revision=revision + 1)
        result = self.library.configure({'enabled': False}, revision=revision)
        self.assertEqual(result['status'], 'configured')
        self.assertFalse(self.library.status()['enabled'])

    def test_material_identity_is_stable_and_never_exported(self):
        first = self.library.material_identity('E:/Books/lesson.pdf')
        self.assertEqual(first, self.library.material_identity('E:/Books/lesson.pdf'))
        self.assertNotEqual(first, self.library.material_identity('E:/Books/other.pdf'))
        exported = json.dumps(self.library.export(scope=SCOPE_A))
        self.assertNotIn(first, exported)

    def test_context_returns_bounded_latest(self):
        for index in range(5):
            self.library.observe(event(f'e{index}'), scope=SCOPE_A)
        context = self.library.context(scope=SCOPE_A, limit=3)
        self.assertEqual(len(context), 3)


if __name__ == '__main__':
    unittest.main()
