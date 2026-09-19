import sqlite3,unittest
from extensions.roles.handoff import project_index,create_handoff,workbench_prompt
from extensions.models.device import DeviceRegistry
from extensions.models.usage import UsageStore
from extensions.models.prompt import enhance

class ModelExtensionTests(unittest.TestCase):
 def test_handoff_preserves_original_and_marks_role_untrusted(self):
  h=create_handoff(source_message_id='m',original_user_text='把Sumika的网页咨询接上',project_id='sumika',extracted_goal='接入网页咨询',role_notes=['可能需要改浏览器'],confidence='low')
  p=workbench_prompt(h,{'status':'in_progress'})
  self.assertEqual(p['original_user_text'],'把Sumika的网页咨询接上'); self.assertEqual(h['provenance'],'role_model_untrusted'); self.assertIn('untrusted',p['instruction'])
 def test_project_index_is_small_and_validated(self):
  self.assertEqual(project_index([{'id':'p','name':'P','summary':'s','status':'active'}])[0]['id'],'p')
  with self.assertRaises(ValueError):project_index([{'name':'missing'}])
 def test_devices_pair_and_health_unknown(self):
  db=sqlite3.connect(':memory:'); r=DeviceRegistry(db); x=r.register('old','http://127.0.0.1:9','ollama',['role-chat'])
  self.assertTrue(x['token']); self.assertEqual(r.list()[0]['id'],'old'); self.assertEqual(r.health('old')['status'],'unknown')
 def test_usage_status_and_totals(self):
  db=sqlite3.connect(':memory:'); u=UsageStore(db); u.record(scope='p',session='s',provider='ollama',model='m',prompt_tokens=2,completion_tokens=3,total_tokens=5,status='reported'); self.assertEqual(u.totals('p'),{'prompt_tokens':2,'completion_tokens':3,'total_tokens':5})
  with self.assertRaises(ValueError):u.record(scope='p',session='s',provider='x',model='m',status='bad')
 def test_prompt_enhancement_keeps_original(self):
  x=enhance('修复登录测试',strategy='coding'); self.assertEqual(x['original'],'修复登录测试'); self.assertNotEqual(x['enhanced'],x['original']); self.assertFalse(enhance('x',enabled=False)['changed'])

if __name__=='__main__':unittest.main()
