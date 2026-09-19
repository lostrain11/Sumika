import tempfile,unittest
from unittest.mock import Mock
from pathlib import Path
from extensions.desktop.browser_skill import BrowserSkillClient
from extensions.desktop.browser_consultation_bridge import BrowserConsultationBridge
class BridgeTests(unittest.TestCase):
 def bridge(self):
  client=Mock();client.permission.return_value=True
  client.session_list.return_value=[{'session_id':'s'}]
  bridge=BrowserConsultationBridge(client,'s',tab_id=7)
  return bridge
 def inventory(self,url='https://example.com/chat',scope='agent'):
  return {'tabs':[{'tab_id':7,'url':url,'scope':scope}]}
 def test_cross_origin_navigation_never_calls_cli(self):
  b=self.bridge();b._run=Mock()
  for url in ('https://evil.test','https://example.com.evil.test','http://example.com','https://example.com:444','https://example.com@evil.test'):
   with self.assertRaises((ValueError,PermissionError)):b.navigate('example.com',url)
  b._run.assert_not_called()
 def test_redirect_and_user_tab_block_before_fill(self):
  for inventory in (self.inventory('https://evil.test'),self.inventory(scope='user'),{'tabs':[]}):
   b=self.bridge();b._run=Mock(return_value=inventory)
   with self.assertRaises(PermissionError):b.send('example.com','#q','private prompt')
   self.assertEqual(b._run.call_count,1)
 def test_fill_is_pinned_and_not_reported_as_submitted(self):
  b=self.bridge();b._run=Mock(side_effect=[self.inventory(),{'ok':True},self.inventory()])
  result=b.send('example.com','#q','hello')
  self.assertFalse(result['submitted'])
  self.assertIn('--tab-id',b._run.call_args_list[1].args[0])
  self.assertNotIn('click',str(b._run.call_args_list))
 def test_navigation_redirect_and_observation_race_rejected(self):
  b=self.bridge();b._run=Mock(side_effect=[self.inventory(),{},self.inventory('https://evil.test')])
  with self.assertRaises(PermissionError):b.navigate('example.com','https://example.com/chat')
  b=self.bridge();b._run=Mock(side_effect=[self.inventory(),{'text':'private'},self.inventory('https://evil.test')])
  with self.assertRaises(PermissionError):b.observe('example.com')
 def test_missing_explicit_tab_fails_closed(self):
  client=Mock();client.permission.return_value=True
  client.session_list.return_value=[{'session_id':'s'}]
  b=BrowserConsultationBridge(client,'s');b._run=Mock()
  with self.assertRaises(PermissionError):b.send('example.com','#q','hello')
  b._run.assert_not_called()
 def test_inactive_session_fails_before_browser_operation(self):
  b=self.bridge(); b.client.session_list.return_value=[]; b._run=Mock()
  with self.assertRaises(PermissionError): b.observe('example.com')
  b._run.assert_not_called()
 def test_permissions_gate_operations(self):
  with tempfile.TemporaryDirectory() as d:
   c=BrowserSkillClient(executable='missing',registry=Path(d)/'a.json');b=BrowserConsultationBridge(c,'s')
   with self.assertRaises(PermissionError):b.navigate('example','https://example.com')
   c.set_enabled(True)
   c.authorize('example','p',read=True,send=False)
   with self.assertRaises(PermissionError):b.send('example','#q','hello')
   with self.assertRaises(ValueError):b.observe('example',max_tokens=10)
