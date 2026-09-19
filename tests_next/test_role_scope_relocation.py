import json,shutil,tempfile,unittest
from pathlib import Path
from extensions.roles.conversations import Conversations
class ScopeRelocationTests(unittest.TestCase):
 def test_legacy_identity_messages_and_handoffs_survive_move_and_restart(self):
  with tempfile.TemporaryDirectory(dir='.sumika-next') as tmp:
   root=Path(tmp).resolve();old=root/'old';new=root/'new';old.mkdir();(old/'role.json').write_text('{}')
   store=Conversations(root/'chat.db')
   legacy=json.dumps(['user',str(old),'project'],ensure_ascii=False)
   turn=store.begin(legacy,'room','原文');store.complete(turn,{'text':'回复'})
   unknown=store.begin(legacy,'room','未确认');draft=store.prepare('user',legacy,turn+':user')
   scope=store.scope_for('user',old,'project');self.assertEqual(scope,legacy)
   before=store.messages(scope,'room');shutil.move(str(old),str(new))
   store.relocate_scope('user','project',old,new,expected_scope=scope)
   fresh=Conversations(root/'chat.db');resolved=fresh.scope_for('user',new,'project')
   self.assertEqual(resolved,scope);self.assertEqual(fresh.messages(resolved,'room'),before)
   self.assertEqual(fresh.draft('user'),draft);self.assertEqual(len(fresh.context(resolved,'room')),2)
   self.assertEqual(fresh.relocate_scope('user','project',old,new,expected_scope=scope),scope)
   with self.assertRaises(ValueError):fresh.scope_for('user',old,'project')
   self.assertEqual(fresh.messages(fresh.scope_for('other',new,'project'),'room'),[])
   self.assertEqual(fresh.messages(fresh.scope_for('user',new,'other'),'room'),[])
 def test_conflict_and_stale_identity_do_not_merge_or_retire_source(self):
  with tempfile.TemporaryDirectory(dir='.sumika-next') as tmp:
   root=Path(tmp).resolve();a=root/'a';b=root/'b';store=Conversations(root/'db')
   scope=store.scope_for('u',a,'p')
   with self.assertRaises(ValueError):store.relocate_scope('u','p',a,b,expected_scope='stale')
   legacy=json.dumps(['u',str(b),'p'],ensure_ascii=False);store.begin(legacy,'room','target')
   with self.assertRaises(ValueError):store.relocate_scope('u','p',a,b,expected_scope=scope)
   store.clear(legacy,'room')
   with self.assertRaises(ValueError):store.relocate_scope('u','p',a,b,expected_scope=scope)
   self.assertEqual(store.scope_for('u',a,'p'),scope)
 def test_registered_empty_target_is_not_silently_replaced(self):
  with tempfile.TemporaryDirectory(dir='.sumika-next') as tmp:
   root=Path(tmp).resolve();store=Conversations(root/'db');scope=store.scope_for('u',root/'a','p');other=store.scope_for('u',root/'b','p')
   with self.assertRaises(ValueError):store.relocate_scope('u','p',root/'a',root/'b',expected_scope=scope)
   self.assertEqual(store.scope_for('u',root/'b','p'),other)
