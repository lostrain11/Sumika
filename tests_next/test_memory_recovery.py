import json
import tempfile
import unittest
from pathlib import Path
from extensions.memory.embedded_memory import EmbeddedMemory


class RecoveryTests(unittest.TestCase):
    def test_failed_restore_preserves_data_and_later_commit(self):
        with tempfile.TemporaryDirectory() as d:
            m = EmbeddedMemory(Path(d)/'db')
            scope = dict(user_id='u', role_id='r')
            m.add('原始事实', **scope)
            p = Path(d)/'backup.json'
            m.export_json(p)
            data = json.loads(p.read_text(encoding='utf8'))
            data['memories'].append(dict(data['memories'][0], source=None))
            p.write_text(json.dumps(data), encoding='utf8')
            with self.assertRaises(ValueError): m.restore_json(p, **scope)
            m.add('随后写入', **scope)
            self.assertEqual(len(m.search('原始事实', **scope)), 1)
            m.close()

    def test_relations_roundtrip_and_other_scope_untouched(self):
        with tempfile.TemporaryDirectory() as d:
            m = EmbeddedMemory(Path(d)/'db')
            scope = dict(user_id='u', role_id='r')
            m.add('原始事实', **scope)
            m.relate('用户', '关系', '朋友', **scope)
            p = Path(d)/'backup.json'
            m.export_json(p)
            m.edit_relation('用户','关系','朋友','陌生人', **scope)
            m.add('其他角色', user_id='u',role_id='b')
            m.restore_json(p, **scope)
            self.assertEqual(m.related('用户', **scope)[0]['object'], '朋友')
            self.assertTrue(m.search('其他角色', user_id='u',role_id='b'))
            m.close()

    def test_literal_search_and_disabled_restore(self):
        with tempfile.TemporaryDirectory() as d:
            m = EmbeddedMemory(Path(d)/'db')
            for q in ('', '"', 'a:b', 'NOT', '('):
                self.assertEqual(m.search(q, user_id='u',role_id='r'), [])
            m.close()
            disabled = EmbeddedMemory(Path(d)/'absent', enabled=False)
            self.assertTrue(disabled.restore_role_snapshot(['x'],user_id='u',role_id='r')['disabled'])
            self.assertFalse((Path(d)/'absent').exists())
