import json
import sys
import tempfile,unittest
from unittest import mock
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
 def test_user_tab_borrow_is_explicit_and_inventory_bound(self):
  with tempfile.TemporaryDirectory() as d:
   c=BrowserSkillClient(executable=sys.executable,registry=Path(d)/'a.json');c.set_enabled(True)
   with mock.patch.object(c,'session_tabs',return_value=[{'tab_id':12,'scope':'user','url':'https://www.bilibili.com/'}]) as tabs, \
        mock.patch('extensions.desktop.browser_skill.subprocess.run') as run:
    run.return_value.returncode=0
    run.return_value.stdout=json.dumps({'borrowed':True})
    self.assertEqual(c.borrow_user_tab('s',12),{'borrowed':True})
    tabs.assert_called_once_with('s',scope='user')
    self.assertEqual(run.call_args.args[0][-1], '12')
 def test_user_tab_borrow_rejects_unlisted_or_invalid_tab(self):
  with tempfile.TemporaryDirectory() as d:
   c=BrowserSkillClient(executable=sys.executable,registry=Path(d)/'a.json');c.set_enabled(True)
   with mock.patch.object(c,'session_tabs',return_value=[]):
    with self.assertRaises(PermissionError): c.borrow_user_tab('s',12)
   with self.assertRaises(ValueError): c.borrow_user_tab('s',-1)
 def test_user_tab_capabilities_do_not_claim_in_place_evaluation(self):
  with tempfile.TemporaryDirectory() as d:
   c=BrowserSkillClient(executable=sys.executable,registry=Path(d)/'a.json');c.set_enabled(True)
   with mock.patch.object(c,'session_tabs',return_value=[{'tab_id':12,'scope':'user','url':'https://www.bilibili.com/'}]):
    self.assertEqual(c.user_tab_capabilities('s',12), {
     'tab_id':12,'scope':'user','inventory':True,'evaluate':False,
     'requires_explicit_borrow':True,'url':'https://www.bilibili.com/'})
 def test_transient_replace_retries_same_atomic_operation(self):
  import os
  with tempfile.TemporaryDirectory() as d:
   c=BrowserSkillClient(registry=Path(d)/'auth.json');c.set_enabled(True)
   original=os.replace
   error=PermissionError('sharing failure');error.winerror=32
   with mock.patch('extensions.desktop.browser_skill.os.replace',side_effect=[error,None]) as replace, mock.patch('extensions.desktop.browser_skill.time.sleep') as sleep:
    # The second mocked replacement performs the real atomic operation.
    calls=[]
    def perform(source,target):
     calls.append((source,target))
     if len(calls)==1:raise error
     original(source,target)
    replace.side_effect=perform
    c.set_enabled(False)
    self.assertEqual(calls[0],calls[1]);self.assertEqual(replace.call_count,2)
    sleep.assert_called_once_with(.02)
   self.assertFalse(c.enabled)
   self.assertEqual(list(Path(d).glob('.browser-auth-*')),[])
 def test_permanent_replace_failure_preserves_authorizations(self):
  with tempfile.TemporaryDirectory() as d:
   c=BrowserSkillClient(registry=Path(d)/'auth.json');c.set_enabled(True)
   c.authorize('lesson.test','learning',read=True,send=False)
   before=c.registry.read_bytes()
   for code,count in [(5,5),(17,1),(112,1)]:
    error=OSError('replace failure');error.winerror=code
    with mock.patch('extensions.desktop.browser_skill.os.replace',side_effect=error) as replace, mock.patch('extensions.desktop.browser_skill.time.sleep'), mock.patch('extensions.desktop.browser_skill.shutil.copyfile') as copy:
     with self.assertRaises(OSError):c.set_enabled(False)
     self.assertEqual(replace.call_count,count);copy.assert_not_called()
    self.assertEqual(c.registry.read_bytes(),before)
    self.assertEqual(list(Path(d).glob('.browser-auth-*')),[])
