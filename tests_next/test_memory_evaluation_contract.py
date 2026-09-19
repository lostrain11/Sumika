import json
import unittest
from pathlib import Path

class MemoryEvaluationContractTests(unittest.TestCase):
    def test_evidence_contains_governance_dimensions(self):
        data=json.loads(Path('docs/project/memory-quality-evidence.json').read_text(encoding='utf8'))
        for provider in ('keyword','semantic'):
            self.assertIn('forgotten_rejected',data[provider]);self.assertIn('other_scope_clean',data[provider])
            self.assertTrue(data[provider]['forgotten_rejected']);self.assertTrue(data[provider]['other_scope_clean'])
