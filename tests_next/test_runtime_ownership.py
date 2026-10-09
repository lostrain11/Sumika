import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from sumika_next.runtime_ownership import ProfileLease, process_identity


@unittest.skipUnless(os.name=='nt','Windows lifecycle')
class OwnershipTests(unittest.TestCase):
    def test_release_write_failure_closes_lock_and_keeps_unknown_record(self):
        with tempfile.TemporaryDirectory(dir=Path('.sumika-next')) as tmp:
            lease = ProfileLease(tmp).acquire()
            record = lease.record.read_bytes()
            with patch.object(lease, '_write', side_effect=PermissionError('denied')):
                with self.assertRaises(PermissionError):
                    lease.release()
            self.assertIsNone(lease.file)
            self.assertEqual(lease.record.read_bytes(), record)
            # The stale starting record continues to reject another writer.
            with self.assertRaisesRegex(ValueError, 'incomplete'):
                ProfileLease(tmp).acquire()

    def test_live_owner_and_second_writer_are_blocked(self):
        with tempfile.TemporaryDirectory(dir=Path(".sumika-next")) as tmp:
            lease=ProfileLease(tmp).acquire()
            try:
                lease.bind(SimpleNamespace(pid=os.getpid()))
                self.assertEqual(json.loads(lease.record.read_text())['creation'],process_identity(os.getpid()))
                with self.assertRaises(OSError): ProfileLease(tmp).acquire()
                # Simulate launcher death releasing the OS lock, with child alive.
                lease.file.close();lease.file=None
                with self.assertRaisesRegex(ValueError,'still alive'): ProfileLease(tmp).acquire()
            finally:
                if lease.file: lease.release()

    def test_corrupt_incomplete_and_inaccessible_records_fail_closed(self):
        with tempfile.TemporaryDirectory(dir=Path(".sumika-next")) as tmp:
            record=Path(tmp)/'sumika-instance.json'
            for content in ('{','[]',json.dumps({'profile':str(Path(tmp).resolve()),'state':'starting'})):
                record.write_text(content)
                with self.assertRaises(ValueError): ProfileLease(tmp).acquire()
            record.write_text(json.dumps({'profile':str(Path(tmp).resolve()),'pid':123,'creation':'old'}))
            with patch('sumika_next.runtime_ownership.process_identity',side_effect=OSError('denied')):
                with self.assertRaises(OSError): ProfileLease(tmp).acquire()
            # Reused PID is not our old child; allow a fresh writer, never kill it.
            with patch('sumika_next.runtime_ownership.process_identity',return_value='new'):
                lease=ProfileLease(tmp).acquire();lease.release()
            self.assertEqual(json.loads(record.read_text()),{})
