import json
from pathlib import Path
import unittest
from unittest.mock import patch
import uuid
from tools.import_legacy_profile import migrate
from ui.data_lease import DataLease


class LegacyProfileTests(unittest.TestCase):
    def setUp(self):
        self.base = Path('.sumika-next') / ('legacy-import-test-' + uuid.uuid4().hex)
        self.source = self.base / 'old'
        self.source.mkdir(parents=True)
        (self.source / 'history.json').write_text('{"outcome":"unknown","message":"original"}')
        self.personal = self.base / 'personal'

    def test_copy_preserves_original_and_rejects_repeat(self):
        original = (self.source / 'history.json').read_bytes()
        result = migrate(self.source, self.personal, '0.1.5-rc.2')
        dest = Path(result['destination'])
        self.assertEqual((dest / 'history.json').read_bytes(), original)
        self.assertEqual((self.source / 'history.json').read_bytes(), original)
        self.assertEqual(json.loads((dest / 'sumika-instance.json').read_text()), {})
        with self.assertRaisesRegex(ValueError, 'already exists'):
            migrate(self.source, self.personal, '0.1.5-rc.2')

    def test_live_identity_and_personal_writer_refused(self):
        record = {'profile':str(self.source.resolve()), 'pid':123, 'creation':'test'}
        (self.source / 'sumika-instance.json').write_text(json.dumps(record))
        with patch('tools.import_legacy_profile.process_identity', return_value='test'):
            with self.assertRaisesRegex(ValueError, 'Stop the source'):
                migrate(self.source, self.personal, '0.1.5-rc.2')
        lease = DataLease(self.personal).acquire()
        try:
            with self.assertRaises(OSError):
                migrate(self.source, self.personal, '0.1.5-rc.2')
        finally:
            lease.release()

    def test_stale_identity_retained_and_overlap_rejected(self):
        record = {'profile':str(self.source.resolve()), 'pid':123, 'creation':'old'}
        (self.source / 'sumika-instance.json').write_text(json.dumps(record))
        with patch('tools.import_legacy_profile.process_identity', return_value=None):
            migrate(self.source, self.personal, '0.1.5-rc.2')
        self.assertEqual(json.loads((self.source / 'sumika-instance.json').read_text()), record)
        with self.assertRaisesRegex(ValueError, 'overlap'):
            migrate(self.source, self.source / 'nested', '0.1.5-rc.2')

    def test_generated_dependencies_not_copied(self):
        generated = self.source / 'profiles/node_modules/dependency'
        generated.mkdir(parents=True)
        (generated / 'generated.txt').write_text('generated')
        result = migrate(self.source, self.personal, '0.1.5-rc.2')
        self.assertFalse((Path(result['destination']) / 'profiles/node_modules').exists())
        self.assertTrue((generated / 'generated.txt').is_file())

    def test_copy_failure_never_publishes_partial_profile(self):
        with patch('tools.import_legacy_profile.shutil.copyfile', side_effect=OSError('fixture')):
            with self.assertRaises(OSError):
                migrate(self.source, self.personal, '0.1.5-rc.2')
        self.assertFalse((self.personal / 'dsh-profiles/0.1.5-rc.2').exists())
        self.assertEqual(len(list((self.personal / 'dsh-profiles').glob('.import-*'))), 1)
        self.assertTrue((self.source / 'history.json').is_file())
