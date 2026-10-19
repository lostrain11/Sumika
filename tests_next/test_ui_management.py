import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from extensions.models.settings import example, save, load
from extensions.roles.roles import import_card
from ui.management import Management, Conflict
from ui.schedule import ScheduleController
from ui.server import Bridge


class ManagementTests(unittest.TestCase):
    def test_role_context_edit_roundtrip_consumption_budget_and_isolation(self):
        from extensions.roles.roles import load_role
        from extensions.roles.service import RoleSession
        role=Path(self.roles['a'])
        original=(role/'card/original-card.json').read_bytes()
        state=self.manager.resources('a')
        changes={'background':'synthetic school background','worldbook':[
            {'content':'secret garden','keys':['garden'],'secondary_keys':['blue'],
             'selective':True,'enabled':True,'extensions':{'preserved':'yes'}},
            {'content':'constant fact','keys':[],'constant':True},
            {'content':'disabled fact','keys':['garden'],'enabled':False}],
            'theme':{'accent':'#123456','soft':'#abcdef'}}
        result=self.manager.resources('a','edit-context',{'expected_revision':state['revision'],'changes':changes})
        self.assertTrue(Path(result['backup']).is_file())
        self.assertEqual(result['worldbook'],changes['worldbook'])
        self.assertEqual((role/'card/original-card.json').read_bytes(),original)
        self.assertEqual(load_role(role)['verified']['status'],'ok')
        with self.assertRaises(Conflict):
            self.manager.resources('a','edit-context',{'expected_revision':state['revision'],'changes':changes})
        for card_enabled in (True,False):
            session=RoleSession(role,self.root/'edit-memory.sqlite3',user_id='u',project_id='p',
                work_model='w',role_model='r',card_context_enabled=card_enabled)
            try:
                out=session.request('context',{'user_content':'garden blue','mode':'role'})
                text=json.dumps(out['role_context'])
                self.assertIn('secret garden',text);self.assertIn('constant fact',text)
                self.assertNotIn('disabled fact',text)
                self.assertIn('synthetic school background',text)
                self.assertNotIn('secret garden',json.dumps(session.request('context',{'user_content':'garden'})['role_context']))
                self.assertEqual(out['context']['original_user_content'],'garden blue')
                if card_enabled:self.assertLessEqual(out['selection']['used_chars'],out['selection']['budget_chars'])
            finally:session.close()
        self.assertEqual(self.manager.memory('a')['memories'],[])
        self.assertEqual(self.manager.resources('b')['background'],'')

    def test_role_context_invalid_and_builtin_edits_do_not_write(self):
        import copy
        state=self.manager.resources('a')
        initial=(Path(self.roles['a'])/'role.json').read_bytes()
        changes={key:state[key] for key in ('background','worldbook','theme')}
        for bad in ({'theme':{'accent':'red'}},{'worldbook':[{'keys':[12]}]},
                    {'worldbook':[{'enabled':'yes'}]},{'background':None}):
            with self.assertRaises(ValueError):
                self.manager.resources('a','edit-context',{'expected_revision':state['revision'],'changes':{**copy.deepcopy(changes),**bad}})
            self.assertEqual((Path(self.roles['a'])/'role.json').read_bytes(),initial)
        self.assertFalse((self.root/'backups/roles').exists())
        self.bridge._role_kinds=lambda:{'a':'builtin'}
        with self.assertRaisesRegex(ValueError,'read-only'):
            self.manager.resources('a','edit-context',{'expected_revision':state['revision'],'changes':changes})

    def test_receive_handoff_uses_native_target_and_ignores_browser_context(self):
        from extensions.roles.conversations import Conversations
        settings = load(self.bridge.settings_path)
        store = Conversations(self.root/'conversations.sqlite3')
        turn = store.begin('scope', 'room', '请检查测试项目')
        store.complete(turn, {'text': '收到'})
        draft = store.prepare(settings['role']['user_id'], 'scope', turn+':user')
        self.bridge.conversations = store
        context = {'project': {'id': 'native', 'name': 'Real'}, 'session_id': 's', 'provenance': 'host_verified'}
        self.bridge.workbench.handoff_context = Mock(return_value=context)
        result = self.manager.dispatch('POST', '/api/manage/task-draft', {
            'action': 'receive', 'id': draft['id'], 'workspace_id': 'native', 'session_id': 's',
            'projects': [{'id': 'forged', 'name': 'Invented'}], 'receipts': [{'status': 'verified'}]})
        self.bridge.workbench.handoff_context.assert_called_once_with('native', 's')
        self.assertEqual(result['handoff']['context'], context)
        self.assertIsNone(store.draft(settings['role']['user_id']))

    def setUp(self):
        root = Path('.sumika-next/test-ui-management')
        root.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=root)
        self.root = Path(self.temp.name)
        card = self.root / 'card.json'
        card.write_text(json.dumps({'spec':'chara_card_v2','data':{'name':'Test','description':'test persona'}}),encoding='utf8')
        self.roles = {r:str(import_card(card,self.root/'roles',r)) for r in ('a','b')}
        path = self.root/'settings.json'
        save(example(self.roles['a'],self.root/'memory.sqlite3'),path)
        self.bridge=SimpleNamespace(settings_path=path, _role_paths=lambda:self.roles,
            workbench=SimpleNamespace(browser_binding=lambda:None),
            startup_state=Mock(return_value={'registry_present':False}),apply_startup=Mock(),stop_speech=Mock(),
            schedule=ScheduleController(self.root/'schedules'))
        self.manager=Management(self.bridge)
        self.bridge._role_kinds=lambda:{'a':'user','b':'user'}

    def tearDown(self):
        self.temp.cleanup()

    def test_settings_preserve_private_fields_and_reject_stale_edit(self):
        initial=self.manager.settings()
        out=self.manager.update_settings({'expected_revision':initial['revision'],'changes':{'memory':{'auto_extract':True}}})
        self.assertEqual(out['data']['role'], initial['data']['role'])
        self.assertTrue(out['data']['memory']['auto_extract'])
        self.bridge.apply_startup.assert_not_called()
        with self.assertRaises(Conflict):
            self.manager.update_settings({'expected_revision':initial['revision'],'changes':{'enabled':True}})
        with self.assertRaises(ValueError):
            self.manager.update_settings({'expected_revision':out['revision'],'changes':{'role':{'database':'other'}}})

    def test_tunnel_settings_merge_partial_and_preserve_auxiliary(self):
        initial = self.manager.settings()
        out = self.manager.update_settings({
            'expected_revision': initial['revision'],
            'changes': {'auxiliary': {
                'enabled': True, 'provider': 'ollama',
                'endpoint': 'http://127.0.0.1:18114',
                'model': 'qwen2.5:7b-instruct-q4_K_M',
                'tunnel': {'enabled': True, 'host': '192.168.31.227',
                           'user': 'lostrain'}}}})
        tunnel = out['data']['auxiliary']['tunnel']
        self.assertEqual(tunnel['remote_port'], 11434)
        self.assertEqual(tunnel['ssh_port'], 22)
        self.assertEqual(out['data']['auxiliary']['model'], 'qwen2.5:7b-instruct-q4_K_M')
        current = self.manager.settings()
        out = self.manager.update_settings({
            'expected_revision': current['revision'],
            'changes': {'auxiliary': {'tunnel': {'host': '192.168.31.228'}}}})
        tunnel = out['data']['auxiliary']['tunnel']
        self.assertEqual(tunnel['host'], '192.168.31.228')
        self.assertEqual(tunnel['user'], 'lostrain')
        self.assertEqual(tunnel['remote_port'], 11434)

    def test_voice_settings_change_stops_audio_but_memory_change_does_not(self):
        initial=self.manager.settings()
        self.manager.update_settings({'expected_revision':initial['revision'],
                                     'changes':{'memory':{'auto_extract':True}}})
        self.bridge.stop_speech.assert_not_called()
        current=self.manager.settings()
        self.manager.update_settings({'expected_revision':current['revision'],
                                     'changes':{'voice':{'tts_voice':'another explicit voice'}}})
        self.bridge.stop_speech.assert_called_once()

    def test_disable_persists_even_when_audio_stop_is_unknown(self):
        initial=self.manager.settings()
        self.manager.update_settings({'expected_revision':initial['revision'],'changes':{'voice':{'enabled':True,'input_device':1}}})
        current=self.manager.settings()
        self.bridge.stop_speech.side_effect=RuntimeError('stop unknown')
        with self.assertRaises(RuntimeError):
            self.manager.update_settings({'expected_revision':current['revision'],'changes':{'voice':{'enabled':False}}})
        self.assertFalse(self.manager.settings()['data']['voice']['enabled'])

    def test_model_proposals_require_confirmation_and_preserve_scope(self):
        from extensions.memory.write_policy import MemoryWriter
        session=self.manager.role_session('a')
        try:MemoryWriter(session.memory,session.scope).record(origin='model',event_id='m:user:0',text='用户喜欢茶。')
        finally:session.close()
        state=self.manager.memory('a')
        self.assertEqual(state['memories'],[])
        self.assertEqual(len(state['proposals']),1)
        self.assertEqual(self.manager.memory('b')['proposals'],[])
        payload={'expected_revision':state['revision'],'event_id':'m:user:0'}
        with self.assertRaises(ValueError):self.manager.memory('a','accept_proposal',payload)
        result=self.manager.memory('a','accept_proposal',{**payload,'confirmed':True})
        self.assertEqual(result['proposals'][0]['status'],'accepted')
        self.assertEqual(result['memories'][0]['source'],'user-confirmed')
        with self.assertRaises(Conflict):self.manager.memory('a','reject_proposal',{**payload,'confirmed':True})

    def test_memory_is_bound_to_role_and_restore_rejects_foreign_scope(self):
        state=self.manager.memory('a')
        state=self.manager.memory('a','remember',{'expected_revision':state['revision'],'text':'a secret', 'request_id':'one'})
        other=self.manager.memory('b')
        self.assertEqual(other['memories'],[])
        exported=self.manager.memory('a','export',{'expected_revision':state['revision']})
        with self.assertRaisesRegex(ValueError,'another memory scope'):
            self.manager.memory('b','restore',{'expected_revision':other['revision'],'data':exported['data'],'confirmed':True})
        self.assertEqual(self.manager.memory('a')['memories'][0]['text'],'a secret')
        self.assertEqual(self.manager.memory('b')['memories'],[])
        stale=state['revision']
        state=self.manager.memory('a','relate',{'expected_revision':stale,'subject':'user','predicate':'likes','object':'tea'})
        with self.assertRaises(Conflict):
            self.manager.memory('a','reset',{'expected_revision':stale,'confirmed':True})
        state=self.manager.memory('a','reset',{'expected_revision':state['revision'],'confirmed':True})
        self.assertEqual(state['relations'],[])
        self.assertTrue(list((self.root/'backups'/'memory').glob('*.json')))

    def test_memory_correction_management_requires_confirmation_and_host_scope(self):
        state = self.manager.memory('a')
        state = self.manager.memory('a', 'remember', {
            'expected_revision': state['revision'], 'text': 'likes tea', 'request_id': 'initial'})
        old = state['memories'][0]
        payload = {'expected_revision': state['revision'], 'record_id': old['record_id'],
                   'text': 'likes coffee', 'request_id': 'correct-1'}
        with self.assertRaisesRegex(ValueError, 'confirmation'):
            self.manager.memory('a', 'correct', payload)
        other = self.manager.memory('b')
        with self.assertRaises(Conflict):
            self.manager.memory('b', 'correct', {**payload, 'expected_revision': other['revision'], 'confirmed': True})
        result = self.manager.memory('a', 'correct', {**payload, 'confirmed': True,
            'scope': other['scope']})
        self.assertEqual([m['text'] for m in result['memories']], ['likes coffee'])
        self.assertNotEqual(result['memories'][0]['record_id'], old['record_id'])
        with self.assertRaises(Conflict):
            self.manager.memory('a', 'correct', {**payload, 'confirmed': True})
        self.assertEqual(self.manager.memory('b')['memories'], [])

    def test_memory_management_forget_passes_record_cas_after_state_read(self):
        state = self.manager.memory('a')
        state = self.manager.memory('a', 'remember', {
            'expected_revision': state['revision'], 'text': 'tea', 'request_id': 'initial'})
        row = state['memories'][0]
        session = self.manager.role_session('a')
        original_request = session.request
        def racing_request(operation, data):
            if operation == 'forget':
                original_request('correct', {'record_id': row['record_id'], 'text': 'coffee',
                    'expected_revision': row['revision'], 'event_id': 'race-correct'})
            return original_request(operation, data)
        session.request = racing_request
        with patch.object(self.manager, 'role_session', return_value=session):
            with self.assertRaisesRegex(ValueError, 'revision conflict'):
                self.manager.memory('a', 'forget', {'expected_revision': state['revision'],
                    'id': row['id'], 'confirmed': True})
        self.assertEqual([m['text'] for m in self.manager.memory('a')['memories']], ['coffee'])

    def test_relation_management_uses_single_identity_and_cas(self):
        state = self.manager.memory('a')
        for _ in range(2):
            state = self.manager.memory('a', 'relate', {'expected_revision': state['revision'],
                'subject': 'user', 'predicate': 'likes', 'object': 'tea'})
        row = state['relations'][0]
        result = self.manager.memory('a', 'edit_relation', {**row,
            'expected_revision': state['revision'], 'new_object': 'coffee'})
        self.assertEqual([r['object'] for r in result['relations']], ['coffee', 'tea'])
        session = self.manager.role_session('a')
        original = session.request
        def racing_request(operation, data):
            if operation == 'delete_relation':
                session.memory.mutate_relation(row['record_id'], expected_revision=row['revision'] + 1,
                    new_object='water', **session.scope)
            return original(operation, data)
        session.request = racing_request
        with patch.object(self.manager, 'role_session', return_value=session):
            with self.assertRaisesRegex(ValueError, 'revision conflict'):
                self.manager.memory('a', 'delete_relation', {**result['relations'][0],
                    'expected_revision': result['revision'], 'confirmed': True})
        self.assertEqual([r['object'] for r in self.manager.memory('a')['relations']], ['water', 'tea'])

    def test_origin_and_csrf(self):
        handler=SimpleNamespace(server=SimpleNamespace(server_port=1234),headers={'Host':'127.0.0.1:1234','Origin':'http://evil.test','X-Sumika-CSRF':self.manager.csrf})
        with self.assertRaises(PermissionError):self.manager.authorize(handler,True)
        handler.headers['Origin']='http://127.0.0.1:1234'
        handler.headers['X-Sumika-CSRF']='wrong'
        with self.assertRaises(PermissionError):self.manager.authorize(handler,True)
        handler.headers['X-Sumika-CSRF']=self.manager.csrf
        self.manager.authorize(handler,True)

    def test_schedule_edits_do_not_enable_execution_and_reject_conflict(self):
        state=self.manager.schedules()
        definition={'id':'test','kind':'daily','expression':'09:00','action':'test','mode':'execute','enabled':False,'timezone_name':'UTC'}
        saved=self.manager.update_schedule('save',{'expected_revision':state['revision'],'definition':definition})
        self.assertFalse(saved['definitions'][0]['enabled'])
        with self.assertRaises(Conflict):
            self.manager.update_schedule('remove',{'expected_revision':state['revision'],'id':'test','confirmed':True})

    def test_removed_module_stays_removed_after_bootstrap_and_readd_is_disabled(self):
        self.bridge.capability_database=self.root/'capabilities.sqlite3'
        self.bridge.workbench=SimpleNamespace(root=self.root)
        candidates=[{'id':'ocr','provider':'rapidocr','enabled':True,'options':{}}]
        with patch('ui.server.service_capabilities',return_value=candidates), patch('ui.management.service_capabilities',return_value=candidates):
            Bridge.capability_bootstrap(self.bridge)
            initial=self.manager.modules()
            removed=self.manager.modules('remove',{'expected_revision':initial['revision'],'id':'ocr','confirmed':True})
            Bridge.capability_bootstrap(self.bridge)
            self.assertEqual(self.manager.modules()['modules'],[])
            with self.assertRaises(Conflict):
                self.manager.modules('add',{'expected_revision':initial['revision'],'id':'ocr','provider':'rapidocr'})
            restored=self.manager.modules('add',{'expected_revision':removed['revision'],'id':'ocr','provider':'rapidocr'})
            self.assertFalse(restored['modules'][0]['enabled'])
            self.assertEqual(restored['removed'],[])

    def test_sensevoice_can_be_selected_without_overwriting_existing_configuration(self):
        from extensions.capabilities import CapabilityStore
        self.bridge.capability_database = self.root/'capabilities.sqlite3'
        self.bridge.workbench = SimpleNamespace(root=self.root.resolve())
        model = self.root/'sensevoice'
        model.mkdir()
        (model/'tokens.txt').touch()
        (model/'model.int8.onnx').touch()
        settings = load(self.bridge.settings_path)
        settings['voice']['asr_model'] = str(model.resolve())
        save(settings, self.bridge.settings_path)
        store = CapabilityStore(self.bridge.capability_database)
        store.configure('asr', 'vosk', enabled=False, options={'model':'retained-vosk'})
        store.close()
        with patch('ui.readiness._voice_resolve', side_effect=lambda root, names: (list(names), 'fixture')):
            Bridge.capability_bootstrap(self.bridge)
            initial = self.manager.modules()
            old = next(row for row in initial['modules'] if row['id']=='asr')
            self.assertEqual(old['provider'], 'vosk')
            self.assertFalse(old['enabled'])
            self.assertEqual(old['options']['model'], 'retained-vosk')
            result = self.manager.modules('configure', {'expected_revision':initial['revision'],
                'id':'asr', 'provider':'sherpa-onnx-sensevoice'})
            chosen = next(row for row in result['modules'] if row['id']=='asr')
            self.assertEqual(chosen['provider'], 'sherpa-onnx-sensevoice')
            self.assertEqual(chosen['options']['model'], str(model.resolve()))
            self.assertFalse(chosen['enabled'])
            self.bridge.stop_speech.assert_called_once()

    def test_browser_auth_is_explicit_and_never_reports_login(self):
        with self.assertRaises(ValueError):
            self.manager.browsers('authorize',{'site':'chat.deepseek.com','profile':'test','read':True})
        self.manager.browsers('toggle',{'enabled':True,'confirmed':True})
        result=self.manager.browsers('authorize',{'site':'chat.deepseek.com','profile':'test','read':True,'send':False,'confirmed':True})
        deepseek=next(s for s in result['sites'] if s['id']=='chat.deepseek.com')
        self.assertTrue(deepseek['read'])
        self.assertFalse(deepseek['send'])
        self.assertEqual(deepseek['login'],'unknown')
        self.manager.browsers('revoke',{'site':'chat.deepseek.com','confirmed':True})
        deepseek=next(s for s in self.manager.browsers()['sites'] if s['id']=='chat.deepseek.com')
        self.assertFalse(deepseek.get('read',False))

    def test_semantic_preflight_failure_preserves_existing_settings(self):
        initial=self.manager.settings()
        before=self.bridge.settings_path.read_bytes()
        with patch('extensions.memory.embedding_runtime.installed_runtime',side_effect=ValueError('missing offline runtime')):
            with self.assertRaisesRegex(ValueError,'missing offline'):
                self.manager.update_settings({'expected_revision':initial['revision'],
                                              'changes':{'role':{'memory_provider':'semantic'}}})
        self.assertEqual(self.bridge.settings_path.read_bytes(),before)

    def test_resource_rename_keeps_card_and_backup_and_blocks_stale_mutation(self):
        state=self.manager.resources('a')
        role=Path(self.roles['a'])
        card_files={p.relative_to(role).as_posix():p.read_bytes() for p in role.rglob('*') if p.is_file()}
        renamed=self.manager.resources('a','rename',{'expected_revision':state['revision'],'name':'新显示名'})
        self.assertEqual(renamed['name'],'新显示名')
        with zipfile.ZipFile(renamed['backup']) as archive:
            for name,content in card_files.items():
                if name!='checksums.json':self.assertEqual(archive.read(name),content)
        with self.assertRaises(Conflict):
            self.manager.resources('a','rename',{'expected_revision':state['revision'],'name':'过期'})
        with self.assertRaises(ValueError):
            self.manager.resources('a','archive',{'expected_revision':renamed['revision'],'confirmed':True})
        b=self.manager.resources('b')
        result=self.manager.resources('b','archive',{'expected_revision':b['revision'],'confirmed':True})
        self.assertFalse(Path(self.roles['b']).exists())
        self.assertTrue((Path(result['path'])/'role.json').is_file())

    def test_enhancement_switch_is_typed_and_preserved(self):
        current=self.manager.settings()
        with self.assertRaises(ValueError):
            self.manager.update_settings({'expected_revision':current['revision'],'changes':{'prompt_enhancement':{'enabled':'false'}}})
        saved=self.manager.update_settings({'expected_revision':current['revision'],'changes':{'prompt_enhancement':{'enabled':False}}})
        self.assertFalse(saved['data']['prompt_enhancement']['enabled'])

    def test_package_restore_and_invalid_package_never_publish_or_overwrite(self):
        state=self.manager.resources('b')
        exported=self.manager.resources('b','export',{'expected_revision':state['revision']})
        target=self.root/'restored'
        with patch('ui.server.user_role_store',return_value=target):
            with self.assertRaisesRegex(ValueError,'同名角色'):
                self.manager.import_resources({'path':exported['path'],'confirmed':True})
            self.bridge._role_paths=lambda:{'a':self.roles['a']}
            result=self.manager.import_resources({'path':exported['path'],'confirmed':True})
            self.assertEqual(result['id'],'b')
            original=(target/'b'/'role.json').read_bytes()
            with self.assertRaises(ValueError):
                self.manager.import_resources({'path':exported['path'],'confirmed':True})
            self.assertEqual((target/'b'/'role.json').read_bytes(),original)
            invalid=self.root/'invalid.zip'
            with zipfile.ZipFile(invalid,'w') as package:
                package.writestr('role.json',json.dumps({'schema_version':1,'id':'invalid','name':'Broken','assets':{'card':'card/missing.json'}}))
            with self.assertRaises(ValueError):
                self.manager.import_resources({'path':str(invalid),'confirmed':True})
            self.assertFalse((target/'invalid').exists())
            self.assertEqual(list((target.parent/'role-import-staging').iterdir()),[])


if __name__=='__main__':unittest.main()
