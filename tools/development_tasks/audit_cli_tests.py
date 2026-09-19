"""External acceptance for the copied CLI task; model cannot edit this file."""
import contextlib
import io
import json
from pathlib import Path
import uuid
import unittest
from unittest.mock import patch
import audit_package_licenses as audit


@contextlib.contextmanager
def evidence_directory():
    # Python 3.14 mkdtemp applies a protected Windows ACL that excludes the
    # restricted DSH token. Ordinary owned workspace directories inherit the
    # existing sandbox grant. Retain outputs as evidence; never widen permissions.
    directory = Path.cwd()/('audit-test-'+uuid.uuid4().hex)
    directory.mkdir()
    yield directory


class AuditCLI(unittest.TestCase):
    def invoke(self, strict, findings):
        with evidence_directory() as directory:
            root = Path(directory)
            output = root/'report.json'
            report = {'status': 'inventory_only_review_required', 'counts': {'npm': 1},
                      'finding_counts': {'missing': 1} if findings else {}, 'declarations': {'MIT': 1},
                      'dependencies': [{'name': 'probe', 'findings': ['missing'] if findings else []}]}
            argv = ['audit', str(root), '--output', str(output)] + (['--fail-on-findings'] if strict else [])
            with patch('sys.argv', argv), patch.object(audit, 'audit', return_value=report), contextlib.redirect_stdout(io.StringIO()):
                result = audit.main()
            self.assertEqual(json.loads(output.read_text(encoding='utf8')), report)
            return result

    def test_default_inventory_not_clearance(self):
        self.assertEqual(self.invoke(False, True), 0)

    def test_strict_findings_written_before_failure(self):
        self.assertEqual(self.invoke(True, True), 2)

    def test_strict_no_findings(self):
        self.assertEqual(self.invoke(True, False), 0)

    def test_existing_report_is_preserved(self):
        with evidence_directory() as directory:
            root = Path(directory)
            output = root/'report.json'
            output.write_bytes(b'original evidence')
            with patch('sys.argv', ['audit', str(root), '--output', str(output), '--fail-on-findings']), patch.object(audit, 'audit') as scan:
                with self.assertRaises(ValueError):
                    audit.main()
                scan.assert_not_called()
            self.assertEqual(output.read_bytes(), b'original evidence')


if __name__ == '__main__':
    unittest.main()
