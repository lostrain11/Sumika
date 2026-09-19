import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from extensions.desktop.browser_skill import BrowserSkillClient
from extensions.desktop.browser_consultation_bridge import BrowserConsultationBridge


class BindingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir='.sumika-next')
        self.addCleanup(self.temp.cleanup)
        self.client = BrowserSkillClient(registry=Path(self.temp.name)/'auth.json')
        self.client.set_enabled(True)
        self.client.authorize('chatgpt.com', 'personal', read=True, send=False)
        self.session = {'session_id':'s', 'browser_instance_id':'b', 'agent_window_id':9}
        self.tab = {'tab_id':7, 'scope':'agent', 'window_id':9, 'url':'https://chatgpt.com/'}
        self.sessions = patch.object(self.client, 'session_list', return_value=[self.session]).start()
        self.run = patch.object(BrowserConsultationBridge, '_run', return_value={'tabs':[self.tab]}).start()
        self.addCleanup(patch.stopall)

    def test_persists_identity_without_granting_send(self):
        binding = self.client.bind_session('chatgpt.com', 's', 7)
        fresh = BrowserSkillClient(registry=self.client.registry)
        self.assertEqual(fresh._read()['sites']['chatgpt.com']['binding'], binding)
        self.assertFalse(fresh.permission('chatgpt.com', 'send'))
        self.assertEqual(self.client.binding_status('chatgpt.com')['state'], 'ready')
        self.assertEqual(self.client.binding_status('chatgpt.com')['login'], 'unknown')

    @patch('extensions.desktop.browser_skill.subprocess.run')
    def test_master_disable_preserves_data_and_blocks_existing_client(self, run):
        self.client.bind_session('chatgpt.com','s',7)
        before=self.client._read()['sites']
        BrowserSkillClient(registry=self.client.registry).set_enabled(False)
        self.assertFalse(self.client.enabled)
        self.assertEqual(self.client._read()['sites'],before)
        self.assertEqual(self.client.status()['status'],'disabled')
        self.assertEqual(BrowserSkillClient(registry=self.client.registry).session_list(),[])
        with self.assertRaises(PermissionError):self.client.permission('chatgpt.com','read')
        with self.assertRaises(PermissionError):self.client.session_start()
        run.assert_not_called()

    def test_fresh_and_legacy_registry_default_disabled(self):
        fresh=BrowserSkillClient(registry=Path(self.temp.name)/'new.json')
        self.assertFalse(fresh.enabled)
        data=self.client._read();data.pop('enabled');self.client._write(data)
        self.assertFalse(self.client.enabled)
        with self.assertRaises(ValueError):self.client.set_enabled('true')

    @patch('extensions.desktop.browser_skill.subprocess.run')
    def test_open_site_checks_identity_and_preserves_permissions(self, run):
        run.return_value.returncode=0
        before=self.client.registry.read_bytes()
        for site,browser,window in [('evil.test','b',9),('chatgpt.com','other',9),('chatgpt.com','b',10)]:
            with self.assertRaises(PermissionError):self.client.open_site(site,'s',browser,window)
        run.assert_not_called()
        self.client.open_site('chatgpt.com','s','b',9)
        command=run.call_args.args[0]
        self.assertEqual(command[-2:],['--url','https://chatgpt.com'])
        self.assertEqual(self.client.registry.read_bytes(),before)
        run.return_value.returncode=1
        with self.assertRaisesRegex(RuntimeError,'unknown'):self.client.open_site('chatgpt.com','s','b',9)
        self.assertEqual(run.call_count,2)

    def test_stale_binding_requires_explicit_rebind(self):
        self.client.bind_session('chatgpt.com', 's', 7)
        self.sessions.return_value = []
        self.assertEqual(self.client.binding_status('chatgpt.com')['state'], 'stale')
        self.assertEqual(self.client._read()['sites']['chatgpt.com']['binding']['session_id'], 's')

    def test_identity_reuse_blocks_previously_resolved_bridge(self):
        self.client.bind_session('chatgpt.com', 's', 7)
        bridge = self.client.bound_bridge('chatgpt.com')
        self.sessions.return_value = [{**self.session, 'browser_instance_id':'other'}]
        self.run.reset_mock()
        with self.assertRaises(PermissionError): bridge.observe('chatgpt.com')
        self.run.assert_not_called()

    def test_wrong_origin_user_tab_and_wrong_window_do_not_persist(self):
        for change in ({'url':'https://evil.test/'}, {'scope':'user'}, {'window_id':10}):
            self.run.return_value = {'tabs':[{**self.tab, **change}]}
            with self.assertRaises(PermissionError): self.client.bind_session('chatgpt.com', 's', 7)
            self.assertNotIn('binding', self.client._read()['sites']['chatgpt.com'])

    def test_unavailable_inventory_is_unknown_not_empty_success(self):
        self.client.bind_session('chatgpt.com', 's', 7)
        self.sessions.side_effect = RuntimeError('offline')
        self.assertEqual(self.client.binding_status('chatgpt.com')['state'], 'unknown')

    def test_revoke_blocks_existing_bridge_and_profile_change_invalidates_binding(self):
        self.client.bind_session('chatgpt.com', 's', 7)
        bridge = self.client.bound_bridge('chatgpt.com')
        self.client.revoke('chatgpt.com')
        with self.assertRaises(PermissionError): bridge.observe('chatgpt.com')
        self.client.authorize('chatgpt.com', 'different', read=True)
        self.assertEqual(self.client.binding_status('chatgpt.com')['state'], 'unbound')

    def test_submission_is_bound_durable_and_not_repeated(self):
        self.client.authorize('chatgpt.com','personal',read=True,send=True)
        self.client.bind_session('chatgpt.com','s',7)
        bridge = self.client.bound_bridge('chatgpt.com')
        args = dict(request_id='test-request',prompt_selector='#prompt',submit_selector='#send',approved=True)
        self.run.reset_mock()
        self.run.side_effect = lambda args: ({'ok':True,'value':{'ok':True,'empty':True,'filled':True,'ready':True,'submitted':True}}
                                             if args[0]=='evaluate' else {'tabs':[self.tab]})
        self.assertEqual(bridge.submit('chatgpt.com','test',**args)['state'],'submitted')
        calls = list(self.run.call_args_list)
        self.assertEqual(sum(c.args[0][0]=='evaluate' and '"action": "submit"' in c.args[0][-1] for c in calls),1)
        bridge.submit('chatgpt.com','test',**args)
        self.assertEqual(self.run.call_args_list,calls)

    def test_disabled_control_wait_only_reads_then_clicks_once(self):
        import json
        self.client.authorize('chatgpt.com','personal',read=True,send=True)
        self.client.bind_session('chatgpt.com','s',7)
        bridge=self.client.bound_bridge('chatgpt.com')
        actions=[]
        def run(args):
            if args[0]!='evaluate': return {'tabs':[self.tab]}
            config=json.loads(args[-1].rsplit(')(',1)[1][:-1])
            action=config['action'];actions.append(action)
            return {'ok':True,'value':{'ok':True,'empty':True,'filled':True,
                'ready':actions.count('ready')>1,'submitted':True}}
        self.run.side_effect=run
        with patch('extensions.desktop.browser_consultation_bridge.time.sleep'):
            result=bridge.submit('chatgpt.com','test',request_id='wait',prompt_selector='#p',submit_selector='#s',approved=True)
        self.assertEqual(result['state'],'submitted')
        self.assertEqual(actions.count('fill'),1)
        self.assertEqual(actions.count('submit'),1)
        self.assertEqual(actions.count('ready'),2)
        self.assertEqual(result['steps'],['checking','filling','waiting_ready','clicking','acknowledged'])

    def test_submission_needs_explicit_approval_even_with_site_send_permission(self):
        self.client.authorize('chatgpt.com','personal',read=True,send=True)
        self.client.bind_session('chatgpt.com','s',7)
        bridge=self.client.bound_bridge('chatgpt.com')
        self.run.reset_mock()
        with self.assertRaises(PermissionError):
            bridge.submit('chatgpt.com','test',request_id='r',prompt_selector='#p',submit_selector='#s')
        self.run.assert_not_called()
