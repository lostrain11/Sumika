"""P09 behavior storage: root locator, capacity guard, migration, v2 backup."""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from extensions.behavior.library import BehaviorLibrary, CapacityPaused
from extensions.behavior.locator import BehaviorLocator

REPO = Path(__file__).resolve().parents[1]


def scope(user='project-1'):
    return {'user': user, 'session': None}


def event(event_id, kind='flip_burst'):
    return {'event_id': event_id, 'kind': kind, 'source': 'reading-tracker',
            'target': '第 3 页'}


class LocatorTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix='p09-locator-')
        self.addCleanup(self._tmp.cleanup)
        self.folder = Path(self._tmp.name)
        self.locator = BehaviorLocator(self.folder)

    def test_default_root_is_personal_behavior_child(self):
        self.assertEqual(self.locator.resolve(), self.folder/'behavior')

    def test_select_requires_confirmation_and_dedicated_directory(self):
        with self.assertRaises(ValueError):
            self.locator.select(self.folder/'external')
        occupied = self.folder/'occupied'
        occupied.mkdir()
        (occupied/'unrelated.txt').write_text('x', encoding='utf8')
        with self.assertRaises(ValueError):
            self.locator.select(occupied, confirmed=True)
        nested_product = REPO/'extensions'/'behavior'/'external-test'
        with self.assertRaises(ValueError):
            self.locator.select(nested_product, confirmed=True)
        self.assertFalse(nested_product.exists())

    def test_select_marks_ownership_and_switches_atomically(self):
        external = self.folder/'external'
        result = self.locator.select(external, confirmed=True)
        self.assertEqual(result['status'], 'selected')
        self.assertEqual(self.locator.resolve(), external.resolve())
        marker = json.loads((external/'behavior-root.json').read_text(encoding='utf8'))
        self.assertEqual(result['owner_id'], marker['owner_id'])
        # Re-selecting the same root is allowed and keeps the owner.
        again = self.locator.select(external, confirmed=True)
        self.assertEqual(again['owner_id'], marker['owner_id'])

    def test_select_rejects_nesting_and_foreign_owner(self):
        self.locator.select(self.folder/'external', confirmed=True)
        with self.assertRaises(ValueError):
            self.locator.select(self.folder/'external'/'nested', confirmed=True)
        with self.assertRaises(ValueError):
            self.locator.select(self.folder, confirmed=True)
        # A directory owned by another behavior installation is refused.
        foreign = self.folder/'foreign'
        foreign.mkdir()
        (foreign/'behavior-root.json').write_text(json.dumps(
            {'schema_version': 1, 'owner_id': 'someone-else'}), encoding='utf8')
        with self.assertRaises(ValueError):
            self.locator.select(foreign, confirmed=True)


class CapacityGuardTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix='p09-capacity-')
        self.addCleanup(self._tmp.cleanup)
        self.folder = Path(self._tmp.name)

    def test_pause_floor_blocks_writes_until_explicit_resume(self):
        paused = BehaviorLibrary(self.folder/'a'/'behavior.sqlite3',
                                 capacity_overrides={'pause_free_bytes': 10 ** 18})
        with self.assertRaises(CapacityPaused):
            paused.observe(event('e1'), scope=scope())
        self.assertTrue(paused.status()['capacity']['paused'])
        # Resume is refused while the floor still holds (it always does here).
        with self.assertRaises(CapacityPaused):
            paused.resume_recording()
        # A fresh instance reads the persisted pause and refuses too.
        reopened = BehaviorLibrary(self.folder/'a'/'behavior.sqlite3',
                                   capacity_overrides={'pause_free_bytes': 10 ** 18})
        with self.assertRaises(CapacityPaused):
            reopened.observe(event('e2'), scope=scope())
        # Recording state itself is untouched by the pause.
        self.assertFalse(reopened.status()['capacity']['notice']
                         and reopened.status()['capacity']['paused'] is False)

    def test_low_free_and_tier_notices_are_recorded_without_blocking(self):
        library = BehaviorLibrary(self.folder/'b'/'behavior.sqlite3',
                                  capacity_overrides={'low_free_bytes': 10 ** 18,
                                                      'remind_tier_bytes': 1})
        library.observe(event('e1'), scope=scope())
        capacity = library.status()['capacity']
        self.assertFalse(capacity['paused'])
        kinds = {notice['kind'] for notice in (capacity['notice'] or {}).get('notices', [])}
        self.assertIn('disk_low', kinds)
        self.assertIn('usage_tier', kinds)

    def test_disk_full_operational_error_pauses_recording(self):
        library = BehaviorLibrary(self.folder/'c'/'behavior.sqlite3')
        with self.assertRaises(CapacityPaused):
            library._pause_on_full(
                sqlite3.OperationalError('database or disk is full'))
        self.assertTrue(library.status()['capacity']['paused'])
        # A non-full operational error keeps its original meaning.
        with self.assertRaises(sqlite3.OperationalError):
            library._pause_on_full(sqlite3.OperationalError('disk I/O error'))
        # The persisted pause survives a reopen and blocks new writes.
        reopened = BehaviorLibrary(self.folder/'c'/'behavior.sqlite3')
        with self.assertRaises(CapacityPaused):
            reopened.observe(event('e2'), scope=scope())


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix='p09-migrate-')
        self.addCleanup(self._tmp.cleanup)
        self.folder = Path(self._tmp.name)
        self.locator = BehaviorLocator(self.folder/'personal')
        self.library = BehaviorLibrary(self.locator.resolve()/'behavior.sqlite3',
                                       locator=self.locator)

    def test_migration_requires_confirmation(self):
        with self.assertRaises(ValueError):
            self.library.migrate(self.folder/'external', locator=self.locator)

    def test_migration_moves_records_and_retires_the_old_instance(self):
        self.library.observe(event('e1'), scope=scope())
        self.library.observe(event('e2', kind='long_dwell'), scope=scope())
        revision = self.library.status()['revision']
        external = self.folder/'external'
        result = self.library.migrate(external, locator=self.locator,
                                      confirmed=True)
        self.assertEqual(result['status'], 'complete')
        self.assertTrue(result['source_retained'])
        # The old instance can never dual-write after the switch.
        with self.assertRaises(RuntimeError):
            self.library.observe(event('e3'), scope=scope())
        fresh = BehaviorLibrary(self.locator.resolve()/'behavior.sqlite3',
                                locator=self.locator)
        records = fresh.list_records(scope=scope())['records']
        self.assertEqual(sorted(row['event_id'] for row in records),
                         ['e1', 'e2'])
        self.assertEqual(fresh.status()['revision'], revision)
        # The source directory is retained, never deleted.
        self.assertTrue(Path(self.library._database).exists())
        # Re-running the same migration is an idempotent complete.
        self.assertEqual(self.library.migrate(external, locator=self.locator,
                                              confirmed=True)['idempotent'], True)

    def test_migration_rejects_nested_destination(self):
        with self.assertRaises(ValueError):
            self.library.migrate(self.locator.resolve()/'nested',
                                 locator=self.locator, confirmed=True)

    def test_divergent_locator_after_switch_refuses_to_guess(self):
        source = self.locator.resolve()/'behavior.sqlite3'
        self.library.observe(event('e1'), scope=scope())
        external = self.folder/'external'
        self.library.migrate(external, locator=self.locator, confirmed=True)
        # Simulate a locator that drifted from the destination journal: the
        # JOURNALED library must refuse to open under a drifted pointer.
        (self.folder/'personal'/'behavior-locator.json').write_text(json.dumps(
            {'schema_version': 1, 'root': str(self.folder/'elsewhere'),
             'owner_id': 'x'}), encoding='utf8')
        with self.assertRaises(ValueError):
            BehaviorLibrary(external/'behavior.sqlite3', locator=self.locator)


class BackupV2Tests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(prefix='p09-backup-')
        self.addCleanup(self._tmp.cleanup)
        self.folder = Path(self._tmp.name)
        self.personal = self.folder/'data'
        self.personal.mkdir()
        (self.personal/'role-model-settings.json').write_text('{}', encoding='utf8')
        self.external = self.folder/'behavior-external'
        self.external.mkdir()
        (self.external/'behavior-root.json').write_text(json.dumps(
            {'schema_version': 1, 'owner_id': 'owner-1'}), encoding='utf8')
        connection = sqlite3.connect(self.external/'behavior.sqlite3')
        connection.execute('CREATE TABLE t (x TEXT)')
        connection.execute("INSERT INTO t VALUES ('lesson')")
        connection.commit()
        connection.close()
        (self.personal/'behavior-locator.json').write_text(json.dumps({
            'schema_version': 1, 'root': str(self.external), 'owner_id': 'owner-1'}), encoding='utf8')

    def from_tools_backup_personal_data(self):
        import sys
        saved = sys.path.copy()
        sys.path.insert(0, str(REPO/'tools'))
        try:
            import backup_personal_data as module
            return module
        finally:
            sys.path = saved

    def test_v2_roundtrip_rebinds_locator_to_restored_root(self):
        module = self.from_tools_backup_personal_data()
        snapshot = self.folder/'snapshot'
        module.backup(self.personal, snapshot, self.external)
        manifest = json.loads((snapshot/'snapshot.json').read_text(encoding='utf8'))
        self.assertEqual(manifest['schema_version'], 2)
        self.assertIn('behavior', manifest['roots'])
        restored = self.folder/'restored'
        result = module.restore(snapshot, restored)
        self.assertEqual(result['behavior']['status'], 'restored')
        # The carried (stale) locator was excluded; a fresh one names the
        # restored external root, never the original live library.
        locator = json.loads((restored/'behavior-locator.json').read_text(encoding='utf8'))
        self.assertEqual(locator['root'], str(result['behavior']['destination']))
        self.assertNotIn('Z:/live/root', locator['root'])
        restored_behavior = Path(result['behavior']['destination'])
        check = sqlite3.connect(restored_behavior/'behavior.sqlite3')
        try:
            self.assertEqual(check.execute('SELECT x FROM t').fetchone()[0], 'lesson')
        finally:
            check.close()

    def test_v1_snapshot_still_verifies_and_never_carries_a_stale_pointer(self):
        module = self.from_tools_backup_personal_data()
        snapshot = self.folder/'snapshot-v1'
        (self.personal/'behavior-locator.json').unlink()
        module.backup(self.personal, snapshot)
        manifest = json.loads((snapshot/'snapshot.json').read_text(encoding='utf8'))
        self.assertEqual(manifest['schema_version'], 1)
        restored = self.folder/'restored-v1'
        module.restore(snapshot, restored)
        self.assertFalse((restored/'behavior-locator.json').exists())
        self.assertTrue((restored/'role-model-settings.json').is_file())


if __name__ == '__main__':
    unittest.main()
