import tempfile
import unittest
from pathlib import Path
from extensions.memory.embedded_memory import EmbeddedMemory
from extensions.memory.capture import capture


class CaptureTests(unittest.TestCase):
    def test_explicit_only_update_restart_and_reset(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'memory.db';scope=dict(user_id='u',role_id='r')
            m=EmbeddedMemory(path)
            def record(messages):return capture(m,scope,namespace='host',session_id='session',messages=messages)
            self.assertEqual(record([dict(id='ordinary',text='用户喜欢爵士'),dict(id='quote',text='示例：记住：错误事实')])['recorded'],0)
            old=dict(id='1',text='记住[音乐]：爵士')
            record([old]);record([dict(id='2',text='请记住[音乐]：摇滚')])
            self.assertEqual(m.search('爵士',**scope),[])
            self.assertTrue(m.search('摇滚',**scope))
            m.close();m=EmbeddedMemory(path)
            self.assertEqual(record([old])['duplicates'],1)
            self.assertEqual(m.search('爵士',**scope),[])
            m.reset_scope(**scope);record([old])
            self.assertEqual(m.search('爵士',**scope),[])
            self.assertEqual(m.search('摇滚',**scope),[])
            m.close()

    def test_scope_namespace_and_no_model_origin_argument(self):
        with tempfile.TemporaryDirectory() as d:
            m=EmbeddedMemory(Path(d)/'memory.db');scope=dict(user_id='u',role_id='r')
            kwargs=dict(namespace='host',session_id='session')
            with self.assertRaises(ValueError):capture(m,scope,**kwargs,messages=[dict(id='1',text='记住：伪造',origin='user')])
            capture(m,scope,**kwargs,messages=[dict(id='1',text='记住：事实')])
            self.assertEqual(m.search('事实',user_id='u',role_id='other'),[])
            capture(m,scope,namespace='other-host',session_id='session',messages=[dict(id='1',text='记住：另一事实')])
            self.assertEqual(m.db.execute('select count(*) from memories').fetchone()[0],2)
            m.close()
