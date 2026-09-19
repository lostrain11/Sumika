import json, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
from tools.evaluate_role_models import call, multi_turn

class RoleModelEvaluatorTests(unittest.TestCase):
 def test_empty_endpoint_response_is_unknown(self):
  class R:
   def __enter__(self): return self
   def __exit__(self,*x): pass
   def read(self): return json.dumps({'choices':[]}).encode()
  with patch('tools.evaluate_role_models.urllib.request.urlopen',return_value=R()):
   self.assertEqual(call('http://127.0.0.1:1','m','x',1)['status'],'unknown')

 def test_multiturn_carries_replies_but_resets_new_session(self):
  histories=[]
  def respond(endpoint,model,messages,timeout):
   histories.append([dict(message) for message in messages])
   return {'text':'test reply','status':'passed'}
  with patch('tools.evaluate_role_models.call',side_effect=respond):
   results=multi_turn('http://127.0.0.1:1','m',1)
  self.assertEqual(len(results),6)
  self.assertEqual(histories[1][2],{'role':'assistant','content':'test reply'})
  self.assertEqual(len(histories[-1]),2)
  self.assertNotIn('小林',str(histories[-1]))

 def test_multiturn_stops_after_unknown_response(self):
  with patch('tools.evaluate_role_models.call',return_value={'status':'unknown'}):
   self.assertEqual(len(multi_turn('http://127.0.0.1:1','m',1)),1)

if __name__=='__main__':unittest.main()
