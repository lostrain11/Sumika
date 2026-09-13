import tempfile,unittest
from pathlib import Path
from extensions.memory.embedded_memory import EmbeddedMemory
class EmbeddedMemoryTests(unittest.TestCase):
 def test_scope_update_forget_export(self):
  with tempfile.TemporaryDirectory() as d:
   m=EmbeddedMemory(Path(d)/'m.db')
   try:
    i=m.add('昴喜欢鼓手和游戏',user_id='u',role_id='aoi')['id'];m.add('另一个角色事实',user_id='u',role_id='other');self.assertEqual(m.search('游戏',user_id='u',role_id='aoi')[0]['id'],i);self.assertEqual(m.search('事实',user_id='u',role_id='aoi'),[]);m.forget(i);self.assertEqual(m.search('游戏',user_id='u',role_id='aoi'),[]);self.assertEqual(m.export_json(Path(d)/'out.json')['count'],2)
   finally:m.close()
 def test_restore_role_snapshot_replaces_runtime_memory(self):
  with tempfile.TemporaryDirectory() as d:
   m=EmbeddedMemory(Path(d)/'m.db');m.add('临时互动事实',user_id='u',role_id='a');r=m.restore_role_snapshot(['角色卡事实一','角色卡事实二'],user_id='u',role_id='a');self.assertEqual(r['restored'],2);self.assertFalse(m.search('临时',user_id='u',role_id='a'));self.assertTrue(m.search('角色卡事实一',user_id='u',role_id='a'));m.close()
 def test_export_import_scope(self):
  with tempfile.TemporaryDirectory() as d:
   src=Path(d)/'a.db';m=EmbeddedMemory(src);m.add('安和昴是鼓手',user_id='u',role_id='a');m.add('另一个角色',user_id='u',role_id='b');export=Path(d)/'x.json';m.export_json(export);m.close();n=EmbeddedMemory(Path(d)/'b.db');self.assertEqual(n.import_json(export,user_id='u',role_id='a')['imported'],1);self.assertTrue(n.search('鼓手',user_id='u',role_id='a'));self.assertFalse(n.search('角色',user_id='u',role_id='a'));n.close()
 def test_multihop_relations(self):
  with tempfile.TemporaryDirectory() as d:
   m=EmbeddedMemory(Path(d)/'m.db');m.relate('昴','成员','乐队',user_id='u',role_id='a');m.relate('乐队','主唱','仁菜',user_id='u',role_id='a');self.assertEqual(m.related('昴',user_id='u',role_id='a',depth=2)[1]['object'],'仁菜');m.close()
 def test_relation_edit_delete_and_reset(self):
  with tempfile.TemporaryDirectory() as d:
   m=EmbeddedMemory(Path(d)/'m.db');m.relate('用户','喜欢','鼓手',user_id='u',role_id='a');self.assertEqual(m.edit_relation('用户','喜欢','鼓手','游戏',user_id='u',role_id='a')['updated'],1);self.assertEqual(m.delete_relation('用户','喜欢','游戏',user_id='u',role_id='a')['deleted'],1);m.add('事实',user_id='u',role_id='a');m.reset_scope(user_id='u',role_id='a');self.assertEqual(m.search('事实',user_id='u',role_id='a'),[]);m.close()
 def test_fact_update_history_and_source_filter(self):
  with tempfile.TemporaryDirectory() as d:
   m=EmbeddedMemory(Path(d)/'m.db');m.add('喜好=摇滚',user_id='u',role_id='a',fact_key='喜好');m.add('喜好=爵士',user_id='u',role_id='a',fact_key='喜好');self.assertEqual(m.search('爵士',user_id='u',role_id='a')[0]['text'],'喜好=爵士');self.assertEqual(m.search('摇滚',user_id='u',role_id='a',source='user'),[]);self.assertEqual(m.export_json(Path(d)/'x.json')['count'],2);m.close()
if __name__=='__main__':unittest.main()
