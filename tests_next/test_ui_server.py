import json
import os
import sqlite3
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

from extensions.models.settings import example, save as save_settings, load as load_settings
from extensions.roles.roles import import_card
from ui.server import serve


def _role_dir(root):
    card = root / "card.json"
    card.write_text(json.dumps({"spec": "chara_card_v2", "data": {
        "name": "安和昴", "description": "人格",
        "extensions": {"sumika": {"language_policy": "默认简体中文，不出现日文假名。",
                                  "name_map": {"桃香さん": "桃香"}}},
        "character_book": {"entries": []}}}, ensure_ascii=False), encoding="utf8")
    return import_card(card, root / "store", "ui-role")


class UIServerTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.settings_path = root / "settings.json"
        capability_path = root / "capabilities.db"
        self.schedule_directory = root / "schedules"
        connection = sqlite3.connect(capability_path)
        connection.execute("CREATE TABLE capabilities (id TEXT PRIMARY KEY, position INTEGER, enabled INTEGER, provider TEXT, options TEXT)")
        connection.execute("INSERT INTO capabilities VALUES ('memory',0,1,'embedded','{}')")
        connection.commit()
        connection.close()
        settings = example(_role_dir(root), root / "sumika.db")
        save_settings(settings, self.settings_path)
        self.server = serve(self.settings_path, port=0, capability_database=capability_path,
                            schedule_directory=self.schedule_directory)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self._tmp.cleanup()

    def request(self, path, *, method="GET", body=None):
        headers = {"Content-Type": "application/json"}
        if method not in ('GET', 'HEAD'):
            _, session = self.request('/api/manage/session')
            headers['X-Sumika-CSRF'] = session['csrf']
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}", method=method,
            data=None if body is None else json.dumps(body, ensure_ascii=False).encode("utf8"),
            headers=headers)
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read().decode("utf8"))

    def test_state_settings_and_modules_are_real(self):
        status, state = self.request("/api/state")
        self.assertEqual(status, 200)
        self.assertEqual(state["schema_version"], 1)
        self.assertEqual(state["modules"][0]["id"], "memory")
        _, catalogue = self.request("/api/modules")
        self.assertEqual(catalogue["modules"][0]["label"], "长期记忆")
        self.assertEqual(catalogue["modules"][0]["purpose"], "角色事实与关系的本地存储")
        self.assertEqual(catalogue["modules"][0]["id"], "memory")
        self.assertEqual(state["role"]["language_policy_source"], "card")
        _, settings = self.request("/api/settings/role-model")
        self.assertFalse(settings["enabled"])
        self.assertNotIn("key", json.dumps(settings["language"]))
        _, roles = self.request("/api/roles")
        ids = {role["id"] for role in roles["roles"]}
        self.assertIn("sampleA", ids)
        sample = next(role for role in roles["roles"] if role["id"] == "sampleA")
        self.assertEqual(sample["verified"], "ok")
        self.assertTrue(sample["has_model_3d"])
        self.assertNotIn("D:\\", json.dumps(roles, ensure_ascii=False))

    def test_all_old_write_routes_require_the_same_authorization(self):
        paths = ['/api/memory/reset', '/api/memory/forget', '/api/roles/remove',
                 '/api/roles/import', '/api/roles/select', '/api/roles/attach',
                 '/api/workbench/start', '/api/workbench/stop', '/api/workbench/session',
                 '/api/role/chat', '/api/schedule/toggle', '/api/capabilities/toggle']
        for path in paths:
            with self.subTest(path=path):
                req = urllib.request.Request(f'http://127.0.0.1:{self.port}{path}', data=b'{}',
                                             headers={'Content-Type':'application/json'})
                with self.assertRaises(urllib.error.HTTPError) as caught:
                    urllib.request.urlopen(req)
                self.assertEqual(caught.exception.code, 403)
        _, session = self.request('/api/manage/session')
        for headers in ({'Origin':'http://127.0.0.1:9999'}, {'Origin':'https://evil.test'},
                        {'Sec-Fetch-Site':'cross-site'}, {'Host':'attacker.test'}):
            req = urllib.request.Request(f'http://127.0.0.1:{self.port}/api/settings/role-model',
                method='PUT', data=b'{}', headers={**headers,'X-Sumika-CSRF':session['csrf']})
            with self.assertRaises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(req)
            self.assertEqual(caught.exception.code, 403)

    def test_foreign_loopback_cannot_read_session_token(self):
        req=urllib.request.Request(f'http://127.0.0.1:{self.port}/api/manage/session',
                                   headers={'Origin':'http://localhost:9999'})
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(req)
        self.assertEqual(caught.exception.code, 403)
        self.assertIsNone(caught.exception.headers.get('Access-Control-Allow-Origin'))

    def test_native_origin_tokens_are_bound_to_live_owned_instance(self):
        bridge = self.server.sumika_bridge
        origin = 'http://127.0.0.1:5175'
        def request(route, token=None, method='GET'):
            req = urllib.request.Request(f'http://127.0.0.1:{self.port}{route}', method=method,
                headers={'Origin':origin, 'X-Sumika-CSRF':token or ''},
                data=b'{}' if method == 'POST' else None)
            return urllib.request.urlopen(req, timeout=5)
        with patch.object(bridge.workbench, 'browser_binding', return_value=(origin,'first')) as binding:
            with request('/api/manage/session') as response:
                token = json.load(response)['csrf']
                self.assertEqual(response.headers['Access-Control-Allow-Origin'], origin)
            self.assertNotEqual(token, bridge.management.csrf)
            # The generic bridge token cannot authorize native-origin writes.
            with self.assertRaises(urllib.error.HTTPError) as caught:
                request('/api/workbench/stop', bridge.management.csrf, 'POST')
            self.assertEqual(caught.exception.code, 403)
            with request('/api/workbench/stop', token, 'POST') as response:
                self.assertEqual(response.status, 200)
            binding.return_value = (origin, 'second')
            with self.assertRaises(urllib.error.HTTPError) as caught:
                request('/api/workbench/stop', token, 'POST')
            self.assertEqual(caught.exception.code, 403)
            binding.return_value = None
            with self.assertRaises(urllib.error.HTTPError) as caught:
                request('/api/manage/session')
            self.assertEqual(caught.exception.code, 403)

    def test_closing_rejects_queued_writes_without_starting_or_saving(self):
        bridge = self.server.sumika_bridge
        before = self.settings_path.read_bytes()
        with patch.object(bridge.workbench, 'start') as start:
            bridge._closing = True
            for route, method in [('/api/workbench/start', 'POST'),
                                  ('/api/manage/task-draft', 'POST'),
                                  ('/api/role/chat', 'POST'),
                                  ('/api/settings/role-model', 'PUT')]:
                with self.assertRaises(urllib.error.HTTPError) as caught:
                    self.request(route, method=method, body={})
                self.assertEqual(caught.exception.code, 503)
            start.assert_not_called()
        self.assertEqual(self.settings_path.read_bytes(), before)

    def test_voice_input_disabled_and_unapproved_do_not_spawn(self):
        bridge = self.server.sumika_bridge
        with patch.object(bridge.speech, 'spawn') as spawn:
            for body in ({'role_id':'ui-role'}, {'role_id':'ui-role','approved':True}):
                with self.assertRaises(urllib.error.HTTPError) as denied:
                    self.request('/api/voice/input/start', method='POST', body=body)
                self.assertEqual(denied.exception.code, 403)
            spawn.assert_not_called()

    def test_voice_output_disabled_and_unapproved_do_not_spawn(self):
        bridge = self.server.sumika_bridge
        with patch.object(bridge.playback, 'spawn') as spawn:
            for approved in (False, True):
                with self.assertRaises(urllib.error.HTTPError) as denied:
                    self.request('/api/voice/output/start', method='POST',
                                 body={'role_id':'ui-role','text':'hello','approved':approved})
                self.assertEqual(denied.exception.code, 403)
            spawn.assert_not_called()

    def test_output_only_voice_needs_no_microphone_but_recording_stays_denied(self):
        import sys
        from extensions.capabilities import CapabilityStore
        bridge = self.server.sumika_bridge
        settings = load_settings(self.settings_path)
        settings['voice'].update(enabled=True, input_device=None)
        save_settings(settings, self.settings_path)
        store = CapabilityStore(bridge.capability_database)
        try:
            store.configure('voice', 'windows-sapi')
            store.configure('microphone', 'sounddevice', enabled=False)
        finally:
            store.close()
        with patch('extensions.desktop.audio_devices.env_python', return_value=sys.executable):
            configured = bridge.playback_configuration('ui-role')
        self.assertEqual(configured['voice_name'], settings['voice']['tts_voice'])
        self.assertNotIn('device', configured)
        with patch.object(bridge.speech, 'spawn') as spawn:
            with self.assertRaises(urllib.error.HTTPError) as denied:
                self.request('/api/voice/input/start', method='POST',
                             body={'role_id':'ui-role', 'approved':True})
            self.assertEqual(denied.exception.code,403)
            spawn.assert_not_called()

    def test_shutdown_attempts_playback_stop_even_when_input_stop_fails(self):
        from ui.workbench import WorkbenchError
        bridge = self.server.sumika_bridge
        with patch.object(bridge.speech, 'close', side_effect=RuntimeError('unknown')), \
                patch.object(bridge.playback, 'close') as playback, \
                patch.object(bridge.workbench, 'stop') as workbench:
            with self.assertRaises(WorkbenchError):
                bridge.shutdown()
            playback.assert_called_once()
            workbench.assert_not_called()
        self.assertTrue(bridge._shutdown_requested.is_set())
        self.assertFalse(bridge._closing)

    def test_both_module_write_routes_keep_disable_and_report_stop_unknown(self):
        from extensions.capabilities import CapabilityStore
        bridge = self.server.sumika_bridge
        for route in ('/api/capabilities/toggle', '/api/manage/modules/toggle'):
            store=CapabilityStore(bridge.capability_database)
            try: store.configure('voice','windows-sapi',enabled=True)
            finally: store.close()
            body={'id':'voice','enabled':False}
            if '/manage/' in route:
                body['expected_revision']=bridge.management.modules()['revision']
            with patch.object(bridge.speech,'cancel_active',side_effect=RuntimeError('unknown')), \
                    patch.object(bridge.playback,'cancel_active') as playback:
                with self.assertRaises(urllib.error.HTTPError) as failed:
                    self.request(route, method='POST', body=body)
                self.assertEqual(failed.exception.code,502)
                self.assertEqual(json.load(failed.exception)['status'],'unknown')
                playback.assert_called_once()
            store=CapabilityStore(bridge.capability_database)
            try:self.assertFalse(next(r for r in store.list() if r['id']=='voice')['enabled'])
            finally:store.close()

    def test_failed_shutdown_keeps_service_open_and_reports_unknown(self):
        from ui.workbench import WorkbenchError
        bridge = self.server.sumika_bridge
        with patch.object(bridge.workbench, 'stop', side_effect=WorkbenchError('still running')):
            with self.assertRaises(urllib.error.HTTPError) as caught:
                self.request('/api/lifecycle/shutdown', method='POST', body={})
        self.assertEqual(caught.exception.code, 502)
        self.assertEqual(json.load(caught.exception)['status'], 'unknown')
        self.assertFalse(bridge._closing)
        self.assertEqual(self.request('/api/state')[0], 200)
        self.assertTrue(bridge._shutdown_requested.is_set())
        with self.assertRaises(urllib.error.HTTPError) as denied:
            self.request('/api/workbench/start', method='POST', body={})
        self.assertEqual(denied.exception.code, 503)
        with patch.object(bridge.workbench, 'stop') as stop:
            self.assertEqual(self.request('/api/lifecycle/shutdown', method='POST', body={})[0], 200)
            stop.assert_called_once()

    def test_http_shutdown_fences_new_writes_while_chat_drains(self):
        from concurrent.futures import ThreadPoolExecutor
        from unittest.mock import Mock
        bridge = self.server.sumika_bridge
        entered, release = threading.Event(), threading.Event()
        def reply(*args, **kwargs):
            entered.set()
            if not release.wait(8):
                raise RuntimeError('chat release timed out')
            return {'text': 'saved before exit'}
        chat = Mock(histories={}, history_limit=12)
        chat.reply.side_effect = reply
        with patch.object(bridge, '_role_chat', return_value=chat), \
                patch.object(bridge.workbench, 'stop') as stop, ThreadPoolExecutor(3) as pool:
            response = pool.submit(bridge.chat, 'admitted')
            try:
                self.assertTrue(entered.wait(5))
                shutdown = pool.submit(self.request, '/api/lifecycle/shutdown', method='POST', body={})
                self.assertTrue(bridge._shutdown_requested.wait(5))
                self.assertFalse(shutdown.done())
                stop.assert_not_called()
                for route, method in [('/api/role/chat','POST'), ('/api/settings/role-model','PUT')]:
                    with self.assertRaises(urllib.error.HTTPError) as denied:
                        self.request(route, method=method, body={})
                    self.assertEqual(denied.exception.code, 503)
            finally:
                release.set()
            response.result(timeout=5)
            self.assertEqual(shutdown.result(timeout=5)[0], 200)
            stop.assert_called_once()
        self.assertEqual(bridge.transcript('ui-role-chat')[-1]['text'], 'saved before exit')
        self.assertEqual(chat.reply.call_count, 1)

    def test_server_close_failure_retains_data_lease(self):
        from ui.data_lease import DataLease
        from ui.workbench import WorkbenchError
        bridge = self.server.sumika_bridge
        with patch.object(bridge.workbench, 'stop', side_effect=WorkbenchError('unknown stop')):
            with self.assertRaises(WorkbenchError):
                self.server.server_close()
        with self.assertRaises(OSError):
            DataLease(self.settings_path.parent).acquire()
        self.assertTrue(bridge._shutdown_requested.is_set())

    def test_shutdown_waits_for_admitted_chat_to_persist(self):
        from concurrent.futures import ThreadPoolExecutor
        from unittest.mock import Mock
        bridge = self.server.sumika_bridge
        entered, release, stopping = threading.Event(), threading.Event(), threading.Event()
        def reply(*args, **kwargs):
            entered.set()
            if not release.wait(5):
                raise RuntimeError('test did not release chat')
            return {'text': '已落盘的回复'}
        chat = Mock(histories={}, history_limit=12)
        chat.reply.side_effect = reply
        def stop():
            stopping.set()
            bridge.shutdown()
        with patch.object(bridge, '_role_chat', return_value=chat), \
                patch.object(bridge.workbench, 'stop'), ThreadPoolExecutor(2) as pool:
            response = pool.submit(bridge.chat, '等待保存')
            try:
                self.assertTrue(entered.wait(5))
                shutdown = pool.submit(stop)
                self.assertTrue(stopping.wait(5))
                self.assertFalse(shutdown.done())
            finally:
                release.set()
            response.result(timeout=5)
            shutdown.result(timeout=5)
        self.assertTrue(bridge._closing)
        self.assertEqual(bridge.transcript('ui-role-chat')[-1]['text'], '已落盘的回复')

    def test_first_launch_initializes_disabled_settings_without_role_setup(self):
        from ui.server import Bridge
        path = Path(self._tmp.name) / 'new-user' / 'settings.json'
        with patch('extensions.roles.chat.RoleChat._provider') as provider:
            bridge = Bridge(path)
            self.assertFalse(bridge.settings()['enabled'])
            self.assertEqual(bridge.chat('你好')['disabled'], True)
            provider.assert_not_called()
        before=path.read_bytes()
        Bridge(path)
        self.assertEqual(path.read_bytes(), before)

    def test_clear_room_requires_role_and_only_clears_current_conversation(self):
        bridge=self.server.sumika_bridge
        scope=bridge._chat_scope(load_settings(self.settings_path))
        turn=bridge.conversations.begin(scope,'room-ui-role','fixture')
        bridge.conversations.complete(turn,{'text':'fixture reply'})
        _, page=self.request('/api/role/chat/history?session=room-ui-role&role_id=ui-role&limit=3')
        self.assertTrue(page['supports_clear'])
        with self.assertRaises(urllib.error.HTTPError):
            self.request('/api/role/chat/clear',method='POST',body={'role_id':'other','session':'room-ui-role'})
        self.assertEqual(len(bridge.conversations.messages(scope,'room-ui-role')),2)
        _,result=self.request('/api/role/chat/clear',method='POST',body={'role_id':'ui-role','session':'room-ui-role'})
        self.assertTrue(result['cleared'])
        self.assertEqual(bridge.conversations.context(scope,'room-ui-role'),[])

    def test_history_rejects_stale_role_even_without_pagination(self):
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.request('/api/role/chat/history?session=room-ui-role&role_id=stale-role')
        self.assertEqual(caught.exception.code, 400)

    def test_role_asset_serving_and_capability_toggle(self):
        request = urllib.request.Request(f"http://127.0.0.1:{self.port}/api/roles/sampleA/asset/model_3d")
        with urllib.request.urlopen(request, timeout=30) as response:
            self.assertEqual(response.status, 200)
            self.assertEqual(response.headers["Content-Type"], "model/gltf-binary")
            self.assertGreater(len(response.read(64)), 0)
        for target in ("/api/roles/nope/asset/model_3d", "/api/roles/sampleA/asset/voice"):
            with self.assertRaises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(f"http://127.0.0.1:{self.port}{target}", timeout=10)
            self.assertEqual(caught.exception.code, 404)
        status, toggled = self.request("/api/capabilities/toggle", method="POST",
                                       body={"id": "memory", "enabled": False})
        self.assertEqual(status, 200)
        self.assertEqual(toggled, {"id": "memory", "enabled": False, "provider": "embedded"})
        _, modules = self.request("/api/modules")
        self.assertFalse(modules["modules"][0]["enabled"])
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.request("/api/capabilities/toggle", method="POST", body={"id": "missing", "enabled": True})
        self.assertEqual(caught.exception.code, 400)

    def test_role_selection_switches_the_active_role(self):
        _, roles = self.request("/api/roles")
        self.assertIn("active", roles)
        target = next(role for role in roles["roles"] if role["id"] == "sampleA")
        self.assertTrue(target["assets"], "sampleA carries a 3D model")
        status, selected = self.request("/api/roles/select", method="POST", body={"id": "sampleA"})
        self.assertEqual(status, 200)
        self.assertEqual(selected["selected"], "sampleA")
        settings = load_settings(self.settings_path)
        self.assertTrue(settings["role"]["role_dir"].endswith("sampleA"))
        _, after = self.request("/api/roles")
        self.assertEqual(after["active"]["id"], "sampleA")
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.request("/api/roles/select", method="POST", body={"id": "missing-role"})
        self.assertEqual(caught.exception.code, 400)
        self.assertEqual(load_settings(self.settings_path)["role"]["role_dir"],
                         settings["role"]["role_dir"], "a failed switch must not change the active role")

    def test_settings_save_roundtrip_and_secret_rejection(self):
        _, settings = self.request("/api/settings/role-model")
        payload = {k: v for k, v in settings.items() if k not in ("path", "configured", "language_policy_preview")}
        payload["enabled"] = True
        payload["language"] = {**payload["language"], "policy": "用户策略：只用简体中文。"}
        status, saved = self.request("/api/settings/role-model", method="PUT", body=payload)
        self.assertEqual(status, 200)
        self.assertEqual(saved["language_policy_preview"]["source"], "user")
        self.assertTrue(load_settings(self.settings_path)["enabled"])
        before = self.settings_path.read_text(encoding="utf8")
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.request("/api/settings/role-model", method="PUT",
                         body={**payload, "model": "sk-abcdef1234567890"})
        self.assertEqual(caught.exception.code, 400)
        self.assertEqual(self.settings_path.read_text(encoding="utf8"), before)
        self.request("/api/settings/role-model", method="PUT",
                     body={**payload, "language": {**payload["language"], "policy": None}})
        _, cleared = self.request("/api/settings/role-model")
        self.assertEqual(cleared["language_policy_preview"]["source"], "card")

    def test_disabled_chat_makes_no_request_and_unknown_route_is_json(self):
        with patch("extensions.roles.chat.CloudProvider") as provider:
            status, result = self.request("/api/role/chat", method="POST", body={"message": "你好"})
            provider.assert_not_called()
        self.assertEqual(status, 200)
        self.assertTrue(result['disabled'])
        self.assertFalse(result['model_started'])
        self.assertTrue(result['source_message_id'].endswith(':user'))
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.request("/api/not-a-route")
        self.assertEqual(caught.exception.code, 404)
        self.assertEqual(json.loads(caught.exception.read().decode("utf8")), {"error": "unknown endpoint"})

    def test_provider_failure_returns_unknown_without_fallback(self):
        _, settings = self.request("/api/settings/role-model")
        payload = {k: v for k, v in settings.items() if k not in ("path", "configured", "language_policy_preview")}
        payload["enabled"] = True
        self.request("/api/settings/role-model", method="PUT", body=payload)
        from extensions.models.cloud import CloudError
        with patch("extensions.roles.chat.CloudProvider") as provider, \
                patch.dict(os.environ, {"DEEPSEEK_API_KEY": "unit-test-placeholder"}):
            provider.return_value.generate.side_effect = CloudError("auth", "provider returned HTTP 401")
            with self.assertRaises(urllib.error.HTTPError) as caught:
                self.request("/api/role/chat", method="POST", body={"message": "你好"})
        self.assertEqual(caught.exception.code, 502)
        body = json.loads(caught.exception.read().decode("utf8"))
        self.assertEqual(body["status"], "unknown")
        self.assertFalse(body["fallback_used"])

    def test_static_serving_blocks_path_traversal(self):
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.request("/../AGENTS.md")
        self.assertIn(caught.exception.code, (403, 404))

    def test_schedule_endpoints_over_http(self):
        from extensions.desktop.scheduler import Schedule
        from ui.schedule import ScheduleController
        controller = ScheduleController(self.schedule_directory)
        controller.store.upsert(Schedule(id="s1", kind="daily", expression="08:00",
                                        action="提醒喝水", mode="reminder",
                                        timezone_name="Asia/Shanghai"))
        status, state = self.request("/api/schedule")
        self.assertEqual(status, 200)
        self.assertEqual([i["id"] for i in state["definitions"]], ["s1"])
        self.assertEqual(state["status"]["enabled"], True)
        self.request("/api/schedule/toggle", method="POST", body={"id": "s1", "enabled": False})
        _, after = self.request("/api/schedule")
        self.assertFalse(after["definitions"][0]["enabled"])
        self.request("/api/schedule/remove", method="POST", body={"id": "s1"})
        _, empty = self.request("/api/schedule")
        self.assertEqual(empty["definitions"], [])
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.request("/api/schedule/toggle", method="POST", body={"id": "s1", "enabled": True})
        self.assertEqual(caught.exception.code, 400)

    def test_memory_search_relations_forget_and_reset(self):
        from extensions.roles.chat import open_session
        settings = load_settings(self.settings_path)
        session = open_session(settings)
        try:
            session.request("remember", {"text": "小林喜欢晚上九点看动画", "fact_key": "user.anime"})
            session.request("relate", {"subject": "小林", "predicate": "关系", "object": "朋友"})
        finally:
            session.close()
        status, value = self.request("/api/memory?q=%E5%8A%A8%E7%94%BB")
        self.assertEqual(status, 200)
        self.assertEqual(value["provider"], "embedded")
        self.assertEqual(value["sources"], [{"source": "user", "count": 1}])
        self.assertTrue(value["results"])
        found = value["results"][0]
        self.assertIn("动画", found["text"])
        self.assertEqual([(r["subject"], r["predicate"], r["object"]) for r in value["relations"]],
                         [("小林", "关系", "朋友")])
        _, empty = self.request("/api/memory")
        self.assertEqual(empty["results"], [])
        self.request("/api/memory/forget", method="POST", body={"id": found["id"]})
        _, after = self.request("/api/memory?q=%E5%8A%A8%E7%94%BB")
        self.assertEqual(after["results"], [])
        self.request("/api/memory/reset", method="POST", body={})
        _, reset = self.request("/api/memory")
        self.assertEqual(reset["relations"], [])
        # Reset restores the role card itself as a memory, so provenance is kept.
        self.assertEqual(reset["sources"], [{"source": "role_card", "count": 1}])
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.request("/api/memory/forget", method="POST", body={"id": 0})
        self.assertEqual(caught.exception.code, 400)
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.request("/api/memory?limit=999")
        self.assertEqual(caught.exception.code, 400)


if __name__ == "__main__":
    unittest.main()
