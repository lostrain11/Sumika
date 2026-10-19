import json
import tempfile
import unittest
from pathlib import Path
from extensions.memory.embedded_memory import EmbeddedMemory
from extensions.memory.semantic_memory import SemanticMemory
from extensions.memory.embedding_runtime import validate_embeddings


class SemanticContractTests(unittest.TestCase):
    def test_source_contains_restore_vector_invalidation(self):
        source=Path('extensions/memory/semantic_memory.py').read_text(encoding='utf8')
        self.assertIn('DELETE FROM embeddings',source)
        self.assertIn('def restore_json',source)
        self.assertIn('def reset_scope',source)


class SemanticVectorBoundaryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.memory = SemanticMemory.__new__(SemanticMemory)
        EmbeddedMemory.__init__(self.memory, Path(temporary.name)/'memory.db')
        self.addCleanup(self.memory.close)
        self.memory.model_id, self.memory.threshold = 'test-model', .45
        self.memory.embedding_python = None
        self.memory.db.execute('CREATE TABLE embeddings(memory_id INTEGER,model TEXT,vector TEXT,PRIMARY KEY(memory_id,model))')
        self.scope = dict(user_id='user', role_id='role')
        self.record = self.memory.add('用户喜欢茉莉花茶', **self.scope)
        self.vectors, self.query = [[1., 0.]], [1., 0.]
        owner = self
        class Embedder:
            def embed(self, texts): return iter(owner.vectors)
            def query_embed(self, query): return iter([owner.query])
        self.memory.embedder = Embedder()

    def search(self):
        return self.memory.search('喜欢喝什么', **self.scope)

    def cache(self, value):
        self.memory.db.execute('INSERT OR REPLACE INTO embeddings VALUES(?,?,?)',
            (self.record['id'], self.memory.model_id, value))
        self.memory.db.commit()

    def test_bad_batch_never_writes_partial_cache(self):
        for vectors, query in (([], [1., 0.]), ([[1., 0.], [1., 0.]], [1., 0.]),
                ([[1.]], [1., 0.]), ([[0., 0.]], [1., 0.]),
                ([[float('nan'), 1.]], [1., 0.]), ([[1., 0.]], [float('inf'), 0.])):
            with self.subTest(vectors=vectors, query=query):
                self.vectors, self.query = vectors, query
                with self.assertRaisesRegex(RuntimeError, '无效向量'):
                    self.search()
                self.assertEqual(self.memory.db.execute('SELECT count(*) FROM embeddings').fetchone()[0], 0)

    def test_invalid_cached_vectors_fail_closed(self):
        for value in ('not json', '[1]', '[0, 0]', '[true, 0]', '[NaN, 0]', '{}'):
            with self.subTest(cache=value):
                self.cache(value)
                with self.assertRaisesRegex(RuntimeError, '重建记忆索引'):
                    self.search()

    def test_valid_cache_is_reused_and_scope_remains_isolated(self):
        self.assertEqual(self.search()[0]['text'], '用户喜欢茉莉花茶')
        self.vectors = []  # A cache hit must not require re-embedding the fact.
        self.assertEqual(self.search()[0]['text'], '用户喜欢茉莉花茶')
        self.assertEqual(self.memory.search('喜欢喝什么', user_id='other', role_id='role'), [])

    def test_nonzero_finite_vectors_do_not_underflow_or_overflow_score(self):
        for scale in (1e-300, 1e300):
            with self.subTest(scale=scale):
                self.memory.db.execute('DELETE FROM embeddings')
                self.memory.db.commit()
                self.vectors, self.query = [[scale, 0.]], [scale, 0.]
                self.assertEqual(self.search()[0]['score'], 1.)

    def test_shared_validator_rejects_non_numeric_and_empty_query(self):
        for vectors, query in (([[True, 0]], [1, 0]), ([[1, 0]], []),
                               ([[1, 0]], [1e308, 1e308, 1e308, 1e308])):
            with self.subTest(query=query):
                with self.assertRaises(RuntimeError):
                    validate_embeddings(vectors, query, count=1)
