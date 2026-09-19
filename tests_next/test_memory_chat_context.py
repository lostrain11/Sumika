"""Exercise stored memories at the actual role provider boundary, not just search."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from tests_next.test_auto_extraction import _settings
from extensions.roles.chat import RoleChat, open_session


class MemoryChatContextTests(unittest.TestCase):
    def test_memory_reaches_provider_with_or_without_compiled_card(self):
        for compiled in (False,True):
            with self.subTest(compiled=compiled), tempfile.TemporaryDirectory(dir='.sumika-next') as directory:
                settings=_settings(Path(directory));settings['role']['card_context_enabled']=compiled
                session=open_session(settings)
                try:
                    saved=session.request('remember',{'text':'测试暗号是蓝色纸鹤','event_id':'fixture:user'})
                finally:session.close()
                # The latest user message also contains the fact. Check only the
                # system reference, so a missing memory injection cannot pass.
                def system(config):
                    with patch('extensions.roles.chat.CloudProvider') as provider:
                        provider.return_value.generate.return_value={'text':'收到。','usage_status':'unknown'}
                        RoleChat(config).reply('测试暗号是蓝色纸鹤')
                        call=provider.return_value.generate.call_args
                        messages=call.args[0] if call.args else call.kwargs['messages']
                        return messages[0]['content']
                self.assertIn('测试暗号是蓝色纸鹤',system(settings))
                off=copy.deepcopy(settings);off['memory'].update(enabled=False,auto_extract=True)
                self.assertNotIn('测试暗号是蓝色纸鹤',system(off))
                # Explicit local management remains possible with chat recall off.
                management=open_session(off)
                try:self.assertEqual(len(management.request('search',{'query':'测试暗号是蓝色纸鹤'})),1)
                finally:management.close()
                other=copy.deepcopy(settings);other['role']['user_id']='different-user'
                self.assertNotIn('测试暗号是蓝色纸鹤',system(other))
                session=open_session(settings)
                try:session.request('forget',saved)
                finally:session.close()
                self.assertNotIn('测试暗号是蓝色纸鹤',system(settings))

    def test_disabled_semantic_chat_never_requires_embedding_runtime(self):
        with tempfile.TemporaryDirectory(dir='.sumika-next') as directory:
            settings=_settings(Path(directory))
            settings['role']['memory_provider']='semantic';settings['memory']['enabled']=False
            with patch('extensions.memory.embedding_runtime.installed_runtime',side_effect=AssertionError('must not load')):
                session=open_session(settings,for_chat=True)
                try:self.assertEqual(session.request('context',{'user_content':'test','mode':'role'})['role_context']['memory'],[])
                finally:session.close()

    def test_new_process_restores_memory_without_cross_scope_leak(self):
        with tempfile.TemporaryDirectory(dir='.sumika-next') as directory:
            root=Path(directory);settings=_settings(root)
            session=open_session(settings)
            try:session.request('remember',{'text':'重启测试事实','event_id':'restart:user'})
            finally:session.close()
            config=root/'fixture.json';config.write_text(json.dumps(settings),encoding='utf8')
            script='''import json,sys
from extensions.roles.chat import open_session
s=json.load(open(sys.argv[1],encoding='utf8'))
r=open_session(s)
try: assert len(r.request('search',{'query':'重启测试事实'}))==1
finally:r.close()
s['role']['project_id']='other'
r=open_session(s)
try: assert r.request('search',{'query':'重启测试事实'})==[]
finally:r.close()
'''
            result=subprocess.run([sys.executable,'-X','utf8','-B','-c',script,str(config)],capture_output=True,text=True,encoding='utf8',timeout=30)
            self.assertEqual(result.returncode,0,result.stderr)
