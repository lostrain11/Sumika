import json
import tempfile
import unittest
from pathlib import Path


class SemanticContractTests(unittest.TestCase):
    def test_source_contains_restore_vector_invalidation(self):
        source=Path('extensions/memory/semantic_memory.py').read_text(encoding='utf8')
        self.assertIn('DELETE FROM embeddings',source)
        self.assertIn('def restore_json',source)
        self.assertIn('def reset_scope',source)
