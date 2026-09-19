import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from extensions.continuity.continuity import initialize
from sumika_next.runtime_ownership import ProfileLease
from tools.reconcile_continuity import inspect, reconcile


class ReconcileTests(unittest.TestCase):
    def setUp(self):
        parent = Path('.sumika-next/reconcile-tests')
        parent.mkdir(parents=True, exist_ok=True)
        self.root = Path(tempfile.mkdtemp(dir=parent)).resolve()
        self.home = self.root/'profile'
        self.home.mkdir()
        initialize(self.root)
        self.db = self.root/'.sumika-continuity/records.sqlite3'
        self.state = self.root/'.sumika-continuity/adapter-state'/(hashlib.sha256(b'session').hexdigest()+'.json')
        self.state.parent.mkdir()
        self.state.write_text('{"schema_version":1,"status":"pending","operation":"ingest"}')
        (self.home/'cordis.patch.yml').write_text(json.dumps([{'insert':[{'id':'sumika-continuity',
            'config':{'projects':[str(self.root)]}}]}]))

    def test_explicit_reconcile_keeps_original_unknown_evidence_and_database(self):
        original, database = self.state.read_bytes(), self.db.read_bytes()
        result = inspect(self.root, 'session')
        self.assertEqual(self.state.read_bytes(), original)
        outcome = reconcile(self.root, self.home, 'session', result['state_sha256'], result['database_sha256'])
        self.assertEqual(outcome['tasks_replayed'], 0)
        receipt = json.loads(Path(outcome['receipt']).read_text())
        self.assertEqual(receipt['pending'], json.loads(original))
        self.assertEqual(receipt['original_outcome'], 'unknown')
        self.assertEqual(self.db.read_bytes(), database)
        with self.assertRaises(ValueError):
            reconcile(self.root, self.home, 'session', result['state_sha256'], result['database_sha256'])

    def test_changed_review_and_running_profile_refused(self):
        result = inspect(self.root, 'session')
        original = self.state.read_bytes()
        with self.assertRaisesRegex(ValueError, 'reviewed state changed'):
            reconcile(self.root, self.home, 'session', '0'*64, result['database_sha256'])
        lease = ProfileLease(self.home).acquire()
        try:
            with self.assertRaises(OSError):
                reconcile(self.root, self.home, 'session', result['state_sha256'], result['database_sha256'])
        finally:
            lease.release()
        self.assertEqual(self.state.read_bytes(), original)

    def test_corrupt_database_is_not_repaired_or_unfenced(self):
        self.db.write_bytes(b'corrupt')
        original = self.state.read_bytes()
        with self.assertRaises(Exception):
            inspect(self.root, 'session')
        self.assertEqual(self.state.read_bytes(), original)
        self.assertEqual(self.db.read_bytes(), b'corrupt')


if __name__ == '__main__':
    unittest.main()
