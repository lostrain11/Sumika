import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from extensions.roles.conversations import Conversations
from ui.server import Bridge


class ConversationTests(unittest.TestCase):
    def test_message_pages_and_clear_are_scoped_and_recoverable(self):
        with tempfile.TemporaryDirectory(dir=Path('.sumika-next')) as tmp:
            store=Conversations(Path(tmp)/'chat.db')
            for i in range(4):
                turn=store.begin('a','room','user'+str(i))
                store.complete(turn,{'text':'reply'+str(i)})
            other=store.begin('b','room','other')
            first=store.page('a','room')
            self.assertEqual([m['text'] for m in first['messages']],['reply2','user3','reply3'])
            second=store.page('a','room',first['before'])
            self.assertFalse(set(m['id'] for m in first['messages']) & set(m['id'] for m in second['messages']))
            last=store.page('a','room',second['before'])
            self.assertFalse(last['has_more'])
            draft=store.prepare('owner','a',turn+':user')
            self.assertEqual(store.clear('a','room'),4)
            self.assertEqual(store.context('a','room'),[])
            self.assertIsNone(store.draft('owner'))
            self.assertEqual(store.messages('b','room')[0]['id'],other+':user')
            with store.connect() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM cleared_role_turns').fetchone()[0],4)

    def test_legacy_import_is_atomic_idempotent_and_never_replays_unknown(self):
        with tempfile.TemporaryDirectory(dir=Path('.sumika-next')) as tmp:
            store = Conversations(Path(tmp)/'chat.db')
            messages = [{'who':'me','text':'原文','at':'2026-01-01'},
                        {'who':'role','text':'回复','at':'2026-01-01'},
                        {'who':'me','text':'未确认','at':'2026-01-02'}]
            self.assertEqual(store.import_legacy('scope','room',messages), 2)
            ids = [x['id'] for x in store.messages('scope','room')]
            self.assertEqual(store.import_legacy('scope','room',messages), 0)
            self.assertEqual([x['id'] for x in store.messages('scope','room')], ids)
            self.assertEqual(len(store.context('scope','room')), 2)
            self.assertEqual(store.messages('scope','room')[-1]['state'], 'unknown')
            with self.assertRaises(ValueError):
                store.import_legacy('scope','bad',messages + [{'who':'invalid'}])
            self.assertEqual(store.messages('scope','bad'), [])
            store.begin('scope','new','new history')
            with self.assertRaises(ValueError): store.import_legacy('scope','new',messages)

    def test_handoff_uses_persisted_source_survives_restart_and_rejects_stale_replace(self):
        with tempfile.TemporaryDirectory(dir=Path(".sumika-next")) as tmp:
            path=Path(tmp)/'chat.db'
            store=Conversations(path)
            source=store.begin('role-a','session','真实用户原文')
            store.complete(source,{'text':'回复'})
            draft=store.prepare('user','role-a',source+':user')
            recovered=Conversations(path)
            self.assertEqual(recovered.draft('user')['original_user_text'],'真实用户原文')
            self.assertIsNone(recovered.draft('other-user'))
            with self.assertRaises(ValueError): store.prepare('user','role-b',source+':user',draft['id'])
            with self.assertRaises(ValueError): store.prepare('user','role-a',source+':user')
            store.dismiss('other-user',draft['id'])
            self.assertIsNotNone(store.draft('user'))
            store.dismiss('user',draft['id'])
            self.assertIsNone(Conversations(path).draft('user'))

    def test_handoff_verified_context_and_result_are_idempotent_and_untrusted_is_rejected(self):
        with tempfile.TemporaryDirectory(dir=Path('.sumika-next')) as tmp:
            store = Conversations(Path(tmp) / 'chat.db')
            source = store.begin('role-a', 'session', '请修复项目')
            store.complete(source, {'text': '收到'})
            draft = store.prepare('user', 'role-a', source + ':user')
            from extensions.roles.handoff import verified_project_context, create_result_receipt
            context = verified_project_context('p1', [{'id':'p1','name':'项目','summary':'摘要'}])
            received = store.receive_handoff('user', draft['id'], context)
            self.assertEqual(received['state'], 'received')
            receipt = create_result_receipt(status='verified', summary='测试通过')
            completed = store.record_handoff_result('user', draft['id'], receipt)
            self.assertEqual(completed['state'], 'completed')
            self.assertEqual(store.record_handoff_result('user', draft['id'], receipt)['state'], 'completed')
            with self.assertRaises(ValueError): store.record_handoff_result('user', draft['id'], {'status':'verified'})

    def test_restart_scope_and_unknown_are_not_replayed_as_context(self):
        with tempfile.TemporaryDirectory(dir=Path(".sumika-next")) as tmp:
            path = Path(tmp)/'chat.db'
            store=Conversations(path)
            first=store.begin('user-a/role-a','session','你好')
            store.complete(first,{'text':'你好呀','task_intent':{'kind':'chat'}})
            unknown=store.begin('user-a/role-a','session','帮我排查错误')
            recovered=Conversations(path)
            self.assertEqual(recovered.messages('user-a/role-b','session'),[])
            self.assertEqual(recovered.messages('user-b/role-a','session'),[])
            self.assertEqual(recovered.messages('user-a/role-a','other'),[])
            rows=recovered.messages('user-a/role-a','session')
            self.assertEqual(rows[-1]['state'],'unknown')
            self.assertEqual(rows[-1]['id'],unknown+':user')
            self.assertEqual([x['content'] for x in recovered.context('user-a/role-a','session')],['你好','你好呀'])

    def test_bridge_restart_and_model_object_reset_restore_history(self):
        with tempfile.TemporaryDirectory(dir=Path(".sumika-next")) as tmp:
            settings=Path(tmp)/'settings.json'
            first=Bridge(settings)
            with patch('extensions.roles.chat.RoleChat.reply',return_value={'text':'已收到','task_intent':None}):
                result=first.chat('原文',session_id='test')
            second=Bridge(settings)
            self.assertEqual(second.transcript('test')[0]['id'],result['source_message_id'])
            def reply(chat,message,**kwargs):
                self.assertEqual(chat.histories['test'],[{'role':'user','content':'原文'},{'role':'assistant','content':'已收到'}])
                raise OSError('provider unavailable')
            with patch('extensions.roles.chat.RoleChat.reply',autospec=True,side_effect=reply):
                with self.assertRaises(OSError): second.chat('第二条',session_id='test')
            self.assertEqual(Bridge(settings).transcript('test')[-1]['state'],'unknown')
