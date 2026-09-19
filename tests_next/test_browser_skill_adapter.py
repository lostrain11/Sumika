import tempfile,unittest
from pathlib import Path
from extensions.desktop.browser_skill import BrowserSkillClient
class BrowserSkillAdapterTests(unittest.TestCase):
 def test_explicit_authorization_registry(self):
  with tempfile.TemporaryDirectory() as d:
   c=BrowserSkillClient(executable='missing',registry=Path(d)/'a.json');c.set_enabled(True);c.authorize('Example.com','profile',send=True);self.assertTrue(c.permission('example.com','send'));self.assertFalse(c.permission('other','send'));self.assertEqual(c.status()['status'],'error')
   c.revoke('example.com');self.assertFalse(c.permission('example.com','send'))
 def test_disabled_no_io(self):
  self.assertEqual(BrowserSkillClient(registry='missing',enabled=False).status()['status'],'disabled')
 def test_session_requires_available_client(self):
  with self.assertRaises(PermissionError):BrowserSkillClient(executable='missing').session_start()
  with self.assertRaises(PermissionError):BrowserSkillClient(executable='x').session_stop()
