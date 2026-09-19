import json
from pathlib import Path
import tempfile
import unittest
from extensions.roles.service import RoleSession


class RoleServiceTests(unittest.TestCase):
    def test_context_reset_relations_restart_and_scope(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);role=root/'role';role.mkdir()
            (role/'role.json').write_text(json.dumps(dict(id='r',name='角色',persona='角色卡基础',worldbook=[dict(keys=['游戏'],content='游戏背景')],assets={})),encoding='utf8')
            config=dict(role_dir=role,database=root/'db',user_id='u',project_id='p',work_model='work',role_model='role')
            s=RoleSession(**config)
            s.request('remember',dict(text='喜欢游戏'))
            s.request('relate',dict(subject='用户',predicate='关系',object='朋友'))
            result=s.request('context',dict(user_content='游戏\n```code```',mode='work',query='游戏'))
            self.assertEqual(result['model'],'work')
            self.assertEqual(result['context']['original_user_content'],'游戏\n```code```')
            s.close();s=RoleSession(**config)
            self.assertTrue(s.request('search',dict(query='游戏')))
            s.request('reset_to_card',{})
            self.assertEqual(s.request('relations',dict(subject='用户')),[])
            self.assertTrue(s.request('search',dict(query='基础')))
            self.assertFalse(s.request('search',dict(query='喜欢')))
            s.close()

    def test_disabled_no_database_or_role_read(self):
        s=RoleSession('missing','missing',user_id='u',project_id='p',work_model='w',role_model='r',enabled=False)
        self.assertEqual(s.request('remember',{'text':'test'}),{'disabled':True})
        s.close()
