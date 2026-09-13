import unittest
from extensions.roles.context import build
class RoleContextTests(unittest.TestCase):
 def test_blocks_and_original_are_immutable(self):
  original='修改代码，不要把角色口吻写入文件';role={'persona':'毒舌'};payload=build(user_content=original,role_block=role,memory_records=[{'text':'事实'}],task_context={'task':'x'});self.assertEqual(payload['original_user_content'],original);self.assertEqual([x['source'] for x in payload['blocks']],['user','role_context','memory_context','task_context']);payload['blocks'][1]['content']['persona']='changed';self.assertEqual(role['persona'],'毒舌')
 def test_non_text_user_rejected(self):
  with self.assertRaises(ValueError):build(user_content=None)
if __name__=='__main__':unittest.main()
