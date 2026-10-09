import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch
import uuid
from extensions.models.settings import example, save
from tools.manage_personal_data import migrate, cleanup, location_digest, validate_target
from sumika_next.paths import user_data_directory
from ui.data_lease import DataLease


class PersonalDataManagementTests(unittest.TestCase):
    def setUp(self):
        self.base = Path('.sumika-next') / ('data-management-' + uuid.uuid4().hex)
        self.base = self.base.resolve(); self.base.mkdir()
        self.local = self.base / 'local'; self.local.mkdir()
        self.source = self.local / 'Sumika'; self.source.mkdir()
        # Test destinations must be outside the product root, simulated by patching it.
        self.env = patch.dict(os.environ, {'LOCALAPPDATA':str(self.local)})
        self.env.start(); self.addCleanup(self.env.stop)
        override = os.environ.pop('SUMIKA_DATA_DIR', None)
        if override is not None: self.addCleanup(os.environ.__setitem__, 'SUMIKA_DATA_DIR', override)
        self.product = patch('tools.manage_personal_data.ROOT', self.base / 'product')
        self.product.start(); self.addCleanup(self.product.stop)
        config = example(Path('extensions/roles/defaults/sampleA').resolve(), self.source / 'memory.sqlite3')
        save(config, self.source / 'role-model-settings.json')

    def test_migration_verifies_copy_rebinds_and_switches_last(self):
        (self.source/'notes.txt').write_text('keep original')
        destination=self.base/'moved'
        result=migrate(self.source, destination, None)
        self.assertEqual(result['status'], 'complete')
        self.assertEqual(user_data_directory(), destination)
        self.assertEqual((self.source/'notes.txt').read_text(), 'keep original')
        self.assertEqual((destination/'notes.txt').read_text(), 'keep original')
        config=json.loads((destination/'role-model-settings.json').read_text())
        self.assertEqual(config['role']['database'], str(destination/'memory.sqlite3'))

    def test_conflict_and_copy_failure_do_not_switch(self):
        loc=self.local/'Sumika-location.json'
        loc.write_text(json.dumps({'directory':str(self.source)}))
        with self.assertRaisesRegex(ValueError, '已改变'):
            migrate(self.source, self.base/'conflict', None)
        with patch('tools.manage_personal_data.restore', side_effect=OSError('fixture')):
            with self.assertRaises(OSError):
                migrate(self.source, self.base/'failed', location_digest())
        self.assertEqual(user_data_directory(), self.source)

    def test_live_writer_blocks_migration_and_cleanup(self):
        lock=DataLease(self.source).acquire()
        try:
            with self.assertRaises(OSError):migrate(self.source, self.base/'new', None)
            with self.assertRaises(OSError):cleanup(self.source, True)
        finally:lock.release()
        self.assertTrue((self.source/'role-model-settings.json').exists())

    def test_cleanup_requires_confirmation_and_preserves_unknown_paths(self):
        with self.assertRaises(ValueError):cleanup(self.source)
        (self.source/'my-model.gguf').write_text('external-like custom file')
        called=[]
        # Never actually delete fixtures; verify the deletion plan through unlink interception.
        with patch.object(Path,'unlink',lambda path,**kw: called.append(path)):
            result=cleanup(self.source,True)
        self.assertIn(self.source/'role-model-settings.json',called)
        self.assertNotIn(self.source/'my-model.gguf',called)
        self.assertIn('my-model.gguf',result['preserved_unknown'])

    def test_invalid_locator_and_overlaps_fail_closed(self):
        (self.local/'Sumika-location.json').write_text('{"directory":"relative"}')
        with self.assertRaises(ValueError):user_data_directory()
        with self.assertRaises(ValueError):validate_target(self.source,self.source/'nested')

    def test_explicit_override_has_priority(self):
        (self.local/'Sumika-location.json').write_text('{"directory":"relative"}')
        with patch.dict(os.environ,{'SUMIKA_DATA_DIR':str(self.source)}):
            self.assertEqual(user_data_directory(),self.source)
