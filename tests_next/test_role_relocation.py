from contextlib import closing
import json,sqlite3,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from tests_next.test_auto_extraction import _settings
from extensions.models.settings import save,load
from extensions.roles.relocation import relocate,resume,rollback,journal,require_settled,inventory
from extensions.roles.conversations import Conversations
from ui.server import Bridge
class RelocationTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(dir='.sumika-next');self.addCleanup(self.tmp.cleanup)
  self.root=Path(self.tmp.name).resolve();self.path=self.root/'settings.json';save(_settings(self.root),self.path)
  self.old=load(self.path)['role']['role_dir'];self.before=self.path.read_bytes();self.target=self.root/'moved'
  self.bridge=Bridge(self.path);self.scope=self.bridge._chat_scope(load(self.path));self.store=self.bridge.conversations
  t=self.store.begin(self.scope,'room','hello');self.store.complete(t,{'text':'reply'});self.store.begin(self.scope,'room','unknown')
  self.draft=self.store.prepare('local-user',self.scope,t+':user')
 def test_success_backup_restart_roster_and_second_move(self):
  result=relocate(self.path,self.target);self.assertEqual(result['state'],'completed')
  self.assertEqual((Path(result['backup'])/'settings.json').read_bytes(),self.before)
  with closing(sqlite3.connect(Path(result['backup'])/'conversations.sqlite3')) as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM role_turns').fetchone()[0],2)
  self.assertEqual(inventory(self.old),inventory(self.target))
  fresh=Bridge(self.path);self.assertEqual(fresh._role_paths()['auto-role'],str(self.target));self.assertEqual(fresh._role_kinds()['auto-role'],'user')
  self.assertEqual(fresh._chat_scope(load(self.path)),self.scope);self.assertEqual(self.store.draft('local-user'),self.draft)
  relocate(self.path,self.root/'again');self.assertEqual(Bridge(self.path)._role_paths()['auto-role'],str(self.root/'again'))
 def test_interruption_after_binding_recovers_without_replay(self):
  with patch('extensions.roles.relocation.save',side_effect=OSError('interrupted')):
   with self.assertRaises(OSError):relocate(self.path,self.target)
  state=journal(self.path)
  with self.assertRaises(ValueError):self.bridge._chat_scope(load(self.path))
  result=resume(self.path,state['id']);self.assertEqual(result['state'],'completed');self.assertEqual(resume(self.path,state['id']),result)
  self.assertEqual(len(self.store.messages(self.scope,'room')),3);self.assertEqual(len(self.store.context(self.scope,'room')),2)
 def test_interrupted_cutover_can_rollback_and_keeps_copy(self):
  with patch('extensions.roles.relocation.save',side_effect=OSError('interrupted')):
   with self.assertRaises(OSError):relocate(self.path,self.target)
  state=journal(self.path);rollback(self.path,state['id']);require_settled(self.path)
  self.assertEqual(self.path.read_bytes(),self.before);self.assertTrue(self.target.exists());self.assertEqual(self.bridge._chat_scope(load(self.path)),self.scope)
 def test_tampered_copy_and_independent_settings_refuse_resume(self):
  with patch('extensions.roles.relocation.save',side_effect=OSError('interrupted')):
   with self.assertRaises(OSError):relocate(self.path,self.target)
  state=journal(self.path);cfg=load(self.path);cfg['temperature']=1.2;save(cfg,self.path)
  with self.assertRaises(ValueError):resume(self.path,state['id'])
  with self.assertRaises(ValueError):rollback(self.path,state['id'])
  self.path.write_bytes(self.before);(self.target/'extra').write_text('changed')
  with self.assertRaises(ValueError):resume(self.path,state['id'])
 def test_nested_existing_and_relative_targets_refused(self):
  for target in [Path(self.old)/'child',self.root,'relative']:
   with self.assertRaises(ValueError):relocate(self.path,target)
  self.assertEqual(self.path.read_bytes(),self.before);self.assertIsNone(journal(self.path))
import threading,urllib.request,urllib.error
from ui.server import serve
class RelocationHTTPTests(unittest.TestCase):
 def test_authorization_pending_fence_and_explicit_recovery(self):
  with tempfile.TemporaryDirectory(dir='.sumika-next') as tmp:
   root=Path(tmp).resolve();settings=root/'settings.json';save(_settings(root),settings)
   with patch('ui.server.user_role_store',return_value=root/'store'):
    server=serve(settings,port=0,schedule_directory=root/'schedules');thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    base=f'http://127.0.0.1:{server.server_port}';op=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    def call(path,payload=None,token=None):
     req=urllib.request.Request(base+path,data=None if payload is None else json.dumps(payload).encode(),headers={'Origin':base,'Content-Type':'application/json','X-Sumika-CSRF':token or ''})
     try:
      with op.open(req) as r:return r.status,json.load(r)
     except urllib.error.HTTPError as e:
      with e:return e.code,json.load(e)
    try:
     token=call('/api/manage/session')[1]['csrf'];revision=call('/api/manage/settings')[1]['revision'];payload={'expected_revision':revision,'target':str(root/'destination'),'confirmed':True}
     self.assertEqual(call('/api/manage/role-relocation',payload)[0],403)
     with patch('extensions.roles.relocation.save',side_effect=OSError('simulated interruption')):
      self.assertEqual(call('/api/manage/role-relocation',payload,token)[0],400)
     record=call('/api/manage/role-relocation')[1]['relocation'];self.assertEqual(record['state'],'prepared')
     self.assertEqual(call('/api/manage/settings',{'expected_revision':revision,'changes':{'temperature':1}},token)[0],409)
     self.assertEqual(call('/api/manage/role-relocation/resume',{'id':record['id'],'confirmed':True},token)[0],200)
     roles=call('/api/roles')[1];self.assertEqual(roles['active']['id'],'auto-role')
    finally:server.shutdown();server.server_close();thread.join(timeout=5)

if __name__=='__main__':unittest.main()
