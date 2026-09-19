import concurrent.futures
import json
from pathlib import Path
import tempfile
import unittest
from extensions.memory.embedded_memory import EmbeddedMemory
from extensions.memory.write_policy import MemoryWriter


class MemoryWriteTests(unittest.TestCase):
    def test_backup_preserves_events_proposals_and_scope(self):
        with tempfile.TemporaryDirectory() as d:
            scope=dict(user_id='u',role_id='r')
            m=EmbeddedMemory(Path(d)/'db');w=MemoryWriter(m,scope)
            w.record(origin='user',event_id='u1',text='喜欢爵士',fact_key='music')
            w.record(origin='model',event_id='m1',text='喜欢摇滚',fact_key='music')
            MemoryWriter(m,dict(user_id='other',role_id='r')).record(origin='model',event_id='private',text='其他用户')
            p=Path(d)/'backup.json';m.export_json(p,**scope)
            data=json.loads(p.read_text(encoding='utf8'))
            self.assertEqual(data['schema_version'],3)
            self.assertEqual(len(data['proposals']),1)
            m.close()
            restored=EmbeddedMemory(Path(d)/'restored')
            restored.restore_json(p,**scope);writer=MemoryWriter(restored,scope)
            result=writer.record(origin='user',event_id='u1',text='喜欢爵士',fact_key='music')
            self.assertTrue(result['duplicate'])
            restored.forget(result['id'])
            restored.import_json(p,**scope)
            self.assertEqual(restored.search('爵士',**scope),[])
            restored.restore_json(p,**scope)
            self.assertEqual(len(restored.search('爵士',**scope)),1)
            self.assertEqual(restored.search('摇滚',**scope),[])
            with self.assertRaises(ValueError):writer.record(origin='model',event_id='m1',text='changed')
            restored.reset_scope(**scope)
            self.assertTrue(writer.record(origin='user',event_id='u1',text='喜欢爵士',fact_key='music')['duplicate'])
            self.assertEqual(restored.search('爵士',**scope),[])
            restored.close()

    def test_proposal_conflict_rolls_back_entire_restore(self):
        with tempfile.TemporaryDirectory() as d:
            scope=dict(user_id='u',role_id='r');m=EmbeddedMemory(Path(d)/'db');w=MemoryWriter(m,scope)
            w.record(origin='user',event_id='u1',text='原始事实')
            w.record(origin='model',event_id='m1',text='猜测')
            p=Path(d)/'backup.json';m.export_json(p)
            data=json.loads(p.read_text(encoding='utf8'))
            data['memories'][0]['active']=0
            data['proposals'][0]['data']['text']='冲突猜测'
            p.write_text(json.dumps(data),encoding='utf8')
            with self.assertRaises(ValueError):m.restore_json(p,**scope)
            m.add('之后写入',**scope)
            self.assertTrue(m.search('原始事实',**scope))
            self.assertEqual(m.db.execute('SELECT count(*) FROM memory_proposals').fetchone()[0],1)
            m.close()

    def test_legacy_backup_and_invalid_identity(self):
        with tempfile.TemporaryDirectory() as d:
            scope=dict(user_id='u',role_id='r');m=EmbeddedMemory(Path(d)/'db')
            m.add('旧版事实',**scope);p=Path(d)/'backup.json';m.export_json(p)
            data=json.loads(p.read_text(encoding='utf8'));data['schema_version']=2
            del data['proposals'];del data['memories'][0]['event_id']
            p.write_text(json.dumps(data),encoding='utf8');m.restore_json(p,**scope)
            self.assertEqual(len(m.search('旧版事实',**scope)),1)
            data['memories'][0]['event_id']=[]
            p.write_text(json.dumps(data),encoding='utf8')
            with self.assertRaises(ValueError):m.restore_json(p,**scope)
            self.assertEqual(len(m.search('旧版事实',**scope)),1)
            m.close()

    def test_retry_cannot_resurrect_deleted_fact_or_override_event(self):
        with tempfile.TemporaryDirectory() as d:
            m=EmbeddedMemory(Path(d)/'db');w=MemoryWriter(m,dict(user_id='u',role_id='r'))
            result=w.record(origin='user',event_id='native-1',text='喜欢爵士',fact_key='music')
            m.forget(result['id'])
            self.assertTrue(w.record(origin='user',event_id='native-1',text='喜欢爵士',fact_key='music')['duplicate'])
            self.assertEqual(m.search('爵士',user_id='u',role_id='r'),[])
            with self.assertRaises(ValueError):w.record(origin='user',event_id='native-1',text='喜欢摇滚',fact_key='music')
            m.close()

    def test_model_proposal_cannot_replace_confirmed_fact(self):
        with tempfile.TemporaryDirectory() as d:
            m=EmbeddedMemory(Path(d)/'db');w=MemoryWriter(m,dict(user_id='u',role_id='r'))
            w.record(origin='user',event_id='u1',text='用户喜欢爵士',fact_key='music')
            self.assertFalse(w.record(origin='model',event_id='m1',text='用户喜欢摇滚',fact_key='music')['retrievable'])
            self.assertTrue(m.search('爵士',user_id='u',role_id='r'))
            self.assertEqual(m.search('摇滚',user_id='u',role_id='r'),[])
            m.close()

    def test_duplicate_writes_across_connections(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'db';m=EmbeddedMemory(p);m.close()
            def write(_):
                memory=EmbeddedMemory(p)
                try:return memory.add('same fact',user_id='u',role_id='r',event_id='event')['id']
                finally:memory.close()
            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
                ids=list(pool.map(write,range(12)))
            self.assertEqual(len(set(ids)),1)
