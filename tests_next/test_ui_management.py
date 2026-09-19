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
