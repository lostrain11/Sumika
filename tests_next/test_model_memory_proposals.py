import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests_next.test_auto_extraction import _settings
from extensions.roles.chat import RoleChat, open_session
from extensions.memory.model_proposer import list_proposals, resolve
from extensions.memory.model_proposer import collect


class ModelMemoryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir='.sumika-next')
        self.root=Path(self.temp.name)
        self.settings=_settings(self.root)
        self.settings['memory']['model_proposals']=True

    def tearDown(self):
        self.temp.cleanup()

    def reply(self, *, invalid=False, task_intent=False, intent_first=False):
        chat=RoleChat(self.settings)
        def generate(_provider,messages,*args):
            marker=re.search(r'\[sumika-memory-[a-f0-9]+\]',messages[0]['content'])
            text='好的。'
            memories=[{'text':'用户喜欢绿茶。','quote':'我喜欢绿茶','kind':'preference','confidence':0.9}]
            intent={'kind':'discussion','confidence':'high','evidence':''}
            envelope=({'intent':intent,'memories':memories} if intent_first else {'memories':memories,'intent':intent})
            if marker:
                text+=marker[0]+('not json' if invalid else json.dumps(envelope))
            return {'text':text,'usage_status':'unknown'}
        with patch.object(chat,'_provider'),patch.object(chat,'_generate',side_effect=generate) as call:
            result=chat.reply('我喜欢绿茶',source_message_id='turn:user',task_intent=task_intent)
            self.assertEqual(call.call_count,1)
            self.assertEqual(result['text'],'好的。')
            return result

    def test_task_intent_and_memory_metadata_work_in_both_orders(self):
        for first in (True,False):
            result=self.reply(task_intent=True,intent_first=first)
            self.assertEqual(result['task_intent']['kind'],'discussion')

    def test_pending_not_recalled_reopen_confirm_and_idempotence(self):
        self.assertEqual(self.reply()['memory_proposals'],1)
        self.assertEqual(self.reply()['memory_proposals'],0)
        session=open_session(self.settings)
        try:
            self.assertEqual(session.request('search',{'query':'绿茶'}),[])
            proposal=list_proposals(session)[0]
            self.assertEqual(proposal['quote'],'我喜欢绿茶')
            resolve(session,proposal['event_id'],True)
            resolve(session,proposal['event_id'],True)
            self.assertEqual(len(session.request('search',{'query':'绿茶'})),1)
            self.assertEqual(list_proposals(session)[0]['status'],'accepted')
            session.request('export',{'path':str(self.root/'export.json')})
        finally:session.close()
        other={**self.settings,'role':{**self.settings['role'],'database':str(self.root/'restored.db')}}
        session=open_session(other)
        try:
            session.request('restore',{'path':str(self.root/'export.json')})
            self.assertEqual(list_proposals(session)[0]['status'],'accepted')
            self.assertEqual(list_proposals(session)[0]['quote'],'我喜欢绿茶')
        finally:session.close()

    def test_disabled_or_bad_output_never_creates_proposals(self):
        self.assertEqual(self.reply(invalid=True)['memory_proposals'],0)
        self.settings['memory']['model_proposals']=False
        self.assertEqual(self.reply()['memory_proposals'],0)
        self.settings['memory'].update(model_proposals=True,enabled=False)
        self.assertEqual(self.reply()['memory_proposals'],0)

    def test_reject_persists_and_foreign_scope_cannot_resolve(self):
        self.reply()
        other={**self.settings,'role':{**self.settings['role'],'user_id':'other'}}
        session=open_session(other)
        try:
            self.assertEqual(list_proposals(session),[])
            with self.assertRaises(ValueError):resolve(session,'turn:user:proposal:0',True)
        finally:session.close()

        session=open_session(self.settings)
        try:resolve(session,'turn:user:proposal:0',False)
        finally:session.close()
        self.reply()
        session=open_session(self.settings)
        try:
            self.assertEqual(list_proposals(session)[0]['status'],'rejected')
            self.assertEqual(session.request('search',{'query':'绿茶'}),[])
        finally:session.close()

    def test_fabricated_quote_and_secret_quote_not_persisted(self):
        session=open_session(self.settings)
        try:
            for quote in ('我喜欢咖啡','sk-abcdef1234567890'):
                raw='回复[memory]'+json.dumps([{'text':'用户喜欢茶。','quote':quote,
                    'kind':'preference','confidence':0.9}])
                visible,count=collect(raw,'[memory]','我喜欢茶。sk-abcdef1234567890','source',session)
                self.assertEqual((visible,count),('回复',0))
            self.assertEqual(list_proposals(session),[])
        finally:session.close()

    def test_hypothesis_and_quoted_character_are_filtered_even_when_model_proposes(self):
        session=open_session(self.settings)
        try:
            for message,quote in [('如果我喜欢咖啡，你会推荐什么？','我喜欢咖啡'),
                                  ('小说里的主角说：“我住在成都。”','我住在成都')]:
                raw='回复[memory]'+json.dumps([{'text':'用户的偏好','quote':quote,
                    'kind':'preference','confidence':0.99}])
                self.assertEqual(collect(raw,'[memory]',message,'source',session),('回复',0))
            self.assertEqual(list_proposals(session),[])
        finally:session.close()
