import unittest
from unittest.mock import patch
from extensions.models.settings import example,validate
from extensions.models.auxiliary import enhance_prompt,classify_task
import json
class AuxiliaryTests(unittest.TestCase):
 def setUp(self):
  self.settings=validate(example('role','db'));self.settings['auxiliary']['enabled']=True
 def output(self,text):
  return patch('extensions.models.auxiliary._generate',return_value={'status':'reported','text':json.dumps({'enhanced':text}), 'finish_reason':'stop'})
 def test_disabled_capability_never_calls(self):
  with patch('extensions.models.auxiliary._generate') as generate:
   self.assertEqual(classify_task(self.settings,'修复 Sumika')['status'],'disabled');generate.assert_not_called()
 def test_disabled_global_never_calls(self):
  self.settings['prompt_enhancement']['enabled']=False
  with patch('extensions.models.auxiliary._generate') as generate:
   self.assertFalse(enhance_prompt(self.settings,'文字')['changed']);generate.assert_not_called()
 def test_code_and_diff_skipped(self):
  with patch('extensions.models.auxiliary._generate') as generate:
   for text in ['检查\n```py\nx=1\n```','diff --git a/x b/x']:
    self.assertEqual(enhance_prompt(self.settings,text)['enhanced'],text)
   generate.assert_not_called()
 def test_lost_constraint_and_code_rejected(self):
  for original,rewritten in [('整理文档，不改代码。','整理文档。'),('说明 `{"enabled":false}`','说明 `{"enabled": false}`'),('润色说明','安装工具后润色说明')]:
   with self.output(rewritten):self.assertEqual(enhance_prompt(self.settings,original)['enhanced'],original)
 def test_success_keeps_original_and_requires_confirmation(self):
  with self.output('请润色这段说明，不改代码。'):
   out=enhance_prompt(self.settings,'润色说明，不改代码。');self.assertTrue(out['changed']);self.assertTrue(out['requires_confirmation']);self.assertIn('原文',out['diff'])
 def test_truncation_and_bad_json_rejected(self):
  for value in [{'status':'reported','text':'oops'}, {'status':'reported','text':'{"enhanced":"文字"}','finish_reason':'length'}]:
   with patch('extensions.models.auxiliary._generate',return_value=value):self.assertFalse(enhance_prompt(self.settings,'文字')['changed'])
if __name__=='__main__':unittest.main()
