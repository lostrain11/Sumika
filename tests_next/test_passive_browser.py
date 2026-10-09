from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.request
import urllib.error
from unittest.mock import Mock, patch

from extensions.companion.passive_browser import PassiveBrowserConnection
from ui.server import serve


EXTENSION = 'a' * 32
ORIGIN = 'chrome-extension://' + EXTENSION
SELECTION = dict(consent=True, extension_id=EXTENSION, tab_id=7,
                 origin='https://www.bilibili.com', capture_frame=True)


def packet(now, sequence=0):
    url = 'https://www.bilibili.com/video/BVfixture'
    return dict(tab_id=7, sequence=sequence, snapshot=dict(ok=True, subtitles='current lesson',
        url=url, observed_at=now.isoformat(), media_time_seconds=12, paused=False,
        ended=False, seeking=False, playback_rate=1, ready_state=4, title='lesson',
        media_identity=dict(url=url,document_started_at=1700000000000,
            source_fingerprint='abc',media_instance=1,timeline_revision=0,part=1)))


class PassiveBrowserTests(unittest.TestCase):
    def offer(self, **changes):
        return self.connection.request_connection(ORIGIN,
            dict(tab_id=7,origin='https://www.bilibili.com',title='教程',
                 url='https://www.bilibili.com/video/BVfixture',**changes))

    def test_offer_only_metadata_until_explicit_approval(self):
        old = self.grant
        request = self.offer()
        receipt = {key:request[key] for key in ('request_id','receipt')}
        self.assertEqual(self.connection.connection_receipt(ORIGIN,receipt),{'status':'pending'})
        self.assertEqual(self.connection._grant['token'],old['token'])
        pending = self.connection.pending_connections()
        self.assertEqual(pending[0]['title'],'教程')
        self.assertNotIn('receipt',pending[0])
        self.assertNotIn('grant_token',pending[0])
        approval = dict(action='approve',request_id=request['request_id'],consent=False,capture_frame=True)
        with self.assertRaises(PermissionError):
            self.connection.approve_connection(approval,before_start=self.connection.stop)
        approved = self.connection.approve_connection(approval | {'consent':True},
                                                      before_start=self.connection.stop)
        result = self.connection.connection_receipt(ORIGIN,receipt)
        self.assertEqual(result['status'],'approved')
        self.assertEqual(result['grant']['target'],approved['target'])
        self.assertNotEqual(result['grant']['token'],old['token'])
        self.assertEqual(self.connection.pending_connections(),[])
        self.connection.stop()
        with self.assertRaises(PermissionError):
            self.connection.connection_receipt(ORIGIN,receipt)

    def test_receipt_wrong_origin_secret_cancel_and_expiry(self):
        request = self.offer()
        receipt = {key:request[key] for key in ('request_id','receipt')}
        for origin, value in [('https://www.bilibili.com',receipt),
                              ('chrome-extension://'+'b'*32,receipt),
                              (ORIGIN,receipt | {'receipt':'wrong'})]:
            with self.subTest(origin=origin),self.assertRaises(PermissionError):
                self.connection.connection_receipt(origin,value)
        self.connection.connection_receipt(ORIGIN,receipt,cancel=True)
        self.assertEqual(self.connection.pending_connections(),[])
        self.assertEqual(self.connection._grant['token'],self.grant['token'])
        request = self.offer()
        self.t = 120
        self.assertEqual(self.connection.pending_connections(),[])
        with self.assertRaises(PermissionError):
            self.connection.approve_connection(dict(action='approve',request_id=request['request_id'],
                consent=True,capture_frame=True),before_start=self.connection.stop)

    def test_offer_rejects_commands_wrong_url_and_bounded_queue(self):
        value = dict(tab_id=7,origin='https://www.bilibili.com',title='教程',
                     url='https://www.bilibili.com/video/BVfixture')
        for change in ({'consent':True},{'snapshot':{}},{'url':'https://evil.test/video/BVfixture'},
                       {'url':value['url']+'?token=secret'},{'tab_id':True},{'title':'\nmalformed'}):
            with self.subTest(change=change),self.assertRaises(ValueError):
                self.connection.request_connection(ORIGIN,value | change)
        for _ in range(8):
            self.connection.request_connection(ORIGIN,value)
        with self.assertRaisesRegex(ValueError,'too many'):
            self.connection.request_connection(ORIGIN,value)
        self.publish.assert_not_called()

    def test_approved_video_bound_pause_resume_and_late_disconnect(self):
        request = self.offer()
        receipt = {key:request[key] for key in ('request_id','receipt')}
        self.connection.approve_connection(dict(action='approve',request_id=request['request_id'],
            consent=True,capture_frame=True),before_start=self.connection.stop)
        grant = self.connection.connection_receipt(ORIGIN,receipt)['grant']
        changed = packet(self.now)
        changed['snapshot']['url'] = 'https://www.bilibili.com/video/BVother'
        changed['snapshot']['media_identity']['url'] = changed['snapshot']['url']
        with self.assertRaisesRegex(PermissionError,'approved video changed'):
            self.connection.receive(grant['token'],ORIGIN,changed)
        self.connection.receive(grant['token'],ORIGIN,packet(self.now))
        self.connection.pause()
        self.assertEqual(self.connection.connection_receipt(ORIGIN,receipt),{'status':'paused'})
        self.t = 121  # Approval receipt survives the pending request's 120s limit.
        resumed = self.connection.resume()
        self.assertEqual(self.connection.connection_receipt(ORIGIN,receipt)['grant']['token'],resumed['token'])
        self.connection.connection_receipt(ORIGIN,receipt,cancel=True)
        self.assertEqual(self.connection.status(),{'status':'stopped'})

    def test_slow_approval_expires_without_grant(self):
        self.connection.stop()
        request = self.offer()
        def slow_revoke():
            self.connection.stop()
            self.t = 121
        with self.assertRaisesRegex(PermissionError,'expired during approval'):
            self.connection.approve_connection(dict(action='approve',request_id=request['request_id'],
                consent=True,capture_frame=True),before_start=slow_revoke)
        self.assertEqual(self.connection.status(),{'status':'stopped'})

    def setUp(self):
        self.now = datetime.now(timezone.utc)
        self.t = 0
        self.publish, self.clear = Mock(return_value={'status':'updated'}), Mock()
        self.connection = PassiveBrowserConnection(self.publish,self.clear,
            clock=lambda:self.t,utcnow=lambda:self.now,watchdog=False)
        self.grant = self.connection.start(SELECTION)

    def receive(self, value=None, token=None, origin=ORIGIN):
        return self.connection.receive(token or self.grant['token'],origin,value or packet(self.now))

    def test_normalization_ignores_page_target_commands_and_extra_metadata(self):
        value = packet(self.now)
        value['snapshot'].update(target='window:1:pid:2',tools=['delete'],metadata={'consent':True})
        self.receive(value)
        bundle = self.publish.call_args.args[0]
        self.assertEqual(bundle.target,self.grant['target'])
        self.assertEqual(bundle.text,'current lesson')
        self.assertNotIn('consent',bundle.metadata)
        self.assertNotIn('token',self.connection.status())

    def test_wrong_key_extension_tab_replay_or_cross_origin_never_publish(self):
        cases = []
        value = packet(self.now);value['tab_id']=8;cases.append((value,self.grant['token'],ORIGIN))
        value = packet(self.now);value['snapshot']['url']='https://evil.test/video/BVfixture';cases.append((value,self.grant['token'],ORIGIN))
        cases.extend([(packet(self.now),'wrong',ORIGIN),(packet(self.now),self.grant['token'],'https://www.bilibili.com')])
        for args in cases:
            with self.subTest(args=args),self.assertRaises(PermissionError):
                self.connection.receive(args[1],args[2],args[0])
        self.publish.assert_not_called()
        self.receive()
        with self.assertRaises(PermissionError): self.receive()
        self.assertEqual(self.publish.call_count,1)

    def test_pause_resume_rotates_token_and_stop_discards_grant(self):
        self.receive(); self.connection.pause()
        with self.assertRaises(PermissionError): self.receive(packet(self.now,1))
        new = self.connection.resume()
        self.assertNotEqual(new['token'],self.grant['token'])
        with self.assertRaises(PermissionError): self.receive(packet(self.now,1))
        self.receive(token=new['token'])
        self.connection.stop()
        with self.assertRaises(PermissionError): self.receive(token=new['token'])
        self.assertEqual(self.clear.call_count,2)

    def test_expiry_and_missing_heartbeat_clear_context(self):
        self.receive();self.t=10
        self.assertEqual(self.connection.status(),{'status':'stopped'})
        self.clear.assert_called_once()
        self.connection.start(SELECTION);self.t+=1800
        with self.assertRaises(PermissionError):self.receive()

    def test_stale_future_backward_time_and_incomplete_state_rejected(self):
        for changes in ({'observed_at':(self.now-timedelta(seconds=6)).isoformat()},
                        {'observed_at':(self.now+timedelta(seconds=3)).isoformat()},
                        {'media_identity':None},{'paused':'false'},{'title':{}},
                        {'url':'https://www.bilibili.com/video/BVfixture?credential=x'}):
            value = packet(self.now);value['snapshot'].update(changes)
            with self.subTest(changes=changes),self.assertRaises((ValueError,PermissionError)):
                self.receive(value)
        self.publish.assert_not_called()
        self.receive()
        value = packet(self.now-timedelta(seconds=1),1)
        with self.assertRaises(ValueError):self.receive(value)

    def test_invalid_new_selection_preserves_current_grant(self):
        value = dict(SELECTION, consent=False)
        with self.assertRaises(PermissionError):self.connection.start(value)
        self.receive()
        self.clear.assert_not_called()

    def test_identical_media_is_heartbeat_without_republishing(self):
        self.assertEqual(self.receive()['status'], 'updated')
        value = packet(self.now, 1)
        self.assertEqual(self.receive(value)['status'], 'unchanged')
        self.assertEqual(self.publish.call_count, 1)
        value['snapshot']['subtitles'] = 'new cue'
        self.assertEqual(self.receive(value | {'sequence': 2})['status'], 'updated')
        self.assertEqual(self.publish.call_count, 2)

    def test_lightweight_heartbeat_keeps_grant_without_publishing(self):
        self.assertEqual(self.receive()['status'], 'updated')
        result = self.connection.receive(self.grant['token'], ORIGIN,
            {'tab_id': 7, 'sequence': 1, 'heartbeat': True})
        self.assertEqual(result['status'], 'heartbeat')
        self.assertEqual(self.publish.call_count, 1)

    def test_watchdog_expires_without_ui_polling(self):
        cleared = threading.Event()
        connection = PassiveBrowserConnection(Mock(),cleared.set,clock=lambda:self.t,
            utcnow=lambda:self.now)
        grant = connection.start(SELECTION)
        try:
            connection.receive(grant['token'],ORIGIN,packet(self.now))
            self.t=10
            self.assertTrue(cleared.wait(2),'heartbeat expiry should clear without status polling')
            self.assertEqual(connection.status(),{'status':'stopped'})
        finally:
            connection.stop()


class PassiveBrowserHTTPTests(unittest.TestCase):
    def test_http_offer_approval_receipt_collection_and_extension_cancel(self):
        value = dict(tab_id=7,origin='https://www.bilibili.com',title='教程',
                     url='https://www.bilibili.com/video/BVfixture')
        with self.assertRaises(urllib.error.HTTPError) as failed:
            self.post('/api/companion/passive-browser/request',value,{'Origin':value['origin']})
        self.assertEqual(failed.exception.code,403)
        request = self.post('/api/companion/passive-browser/request',value,{'Origin':ORIGIN})
        self.assertIsNone(self.bridge._companion.latest)
        receipt = {key:request[key] for key in ('request_id','receipt')}
        self.assertEqual(self.post('/api/companion/passive-browser/receipt',receipt,
                                  {'Origin':ORIGIN}),{'status':'pending'})
        approval = dict(action='approve',request_id=request['request_id'],consent=True,capture_frame=True)
        with self.assertRaises(urllib.error.HTTPError) as failed:
            self.post('/api/companion/passive-browser',approval,{'Origin':ORIGIN})
        self.assertEqual(failed.exception.code,403)
        managed = {'X-Sumika-CSRF':self.bridge.management.csrf}
        pending = self.post('/api/companion/passive-browser',{'action':'pending'},managed)
        self.assertEqual(pending['requests'][0]['title'],'教程')
        self.post('/api/companion/passive-browser',approval,managed)
        approved = self.post('/api/companion/passive-browser/receipt',receipt,{'Origin':ORIGIN})
        grant = approved['grant']
        self.post('/api/companion/passive-browser/push',packet(datetime.now(timezone.utc)),
                  {'Authorization':'Bearer '+grant['token'],'Origin':ORIGIN})
        self.assertEqual(self.bridge._companion.latest.text,'current lesson')
        self.post('/api/companion/passive-browser/cancel',receipt,{'Origin':ORIGIN})
        self.assertIsNone(self.bridge._companion.latest)
        self.assertEqual(self.bridge._passive_browser.status(),{'status':'stopped'})

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.server = serve(Path(self.tmp.name)/'settings.json',port=0,
                            workbench_root=Path(self.tmp.name))
        self.thread = threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()
        self.base = f'http://127.0.0.1:{self.server.server_port}'
        self.bridge = self.server.sumika_bridge

    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join();self.tmp.cleanup()

    def post(self, route, value, headers):
        request = urllib.request.Request(self.base+route,json.dumps(value).encode(),
            headers={'Content-Type':'application/json',**headers},method='POST')
        with urllib.request.urlopen(request) as response:
            return json.load(response)

    def test_ingress_is_narrow_authenticated_and_revoke_fences_it(self):
        with self.assertRaises(urllib.error.HTTPError) as failed:
            self.post('/api/companion/passive-browser',dict(SELECTION,action='start'),{})
        self.assertEqual(failed.exception.code,403)
        grant = self.post('/api/companion/passive-browser',dict(SELECTION,action='start'),
            {'X-Sumika-CSRF':self.bridge.management.csrf})
        headers={'Authorization':'Bearer '+grant['token'],'Origin':ORIGIN}
        self.post('/api/companion/passive-browser/push',packet(datetime.now(timezone.utc)),headers)
        self.assertEqual(self.bridge._companion.latest.text,'current lesson')
        with self.assertRaises(urllib.error.HTTPError) as failed:
            self.post('/api/companion/observe',{'source':'web','target':'evil','valid':True},headers)
        self.assertEqual(failed.exception.code,403)
        with patch.object(self.bridge._companion,'ask',return_value={'text':'answer'}) as ask:
            self.bridge.companion_ask('why',expected_target=grant['target'])
            self.assertEqual(ask.call_args.kwargs['binding'].observation.target,grant['target'])
        self.bridge.companion_revoke()
        with self.assertRaises(urllib.error.HTTPError) as failed:
            self.post('/api/companion/passive-browser/push',packet(datetime.now(timezone.utc),1),headers)
        self.assertEqual(failed.exception.code,403)
        self.assertIsNone(self.bridge._companion.latest)

    def test_switch_to_other_source_revokes_old_connector(self):
        self.bridge.companion_passive_browser(dict(SELECTION,action='start'))
        self.bridge.companion_observe({'source':'window-visual','target':'window:1:pid:2',
                                      'text':'PDF','valid':True})
        self.assertEqual(self.bridge._passive_browser.status(),{'status':'stopped'})
        self.assertEqual(self.bridge._companion.latest.text,'PDF')

    def test_multiple_changed_snapshots_publish_after_question_generation_advances(self):
        grant=self.bridge.companion_passive_browser(dict(SELECTION,action='start'))
        for sequence in range(3):
            value=packet(datetime.now(timezone.utc),sequence)
            value['snapshot']['subtitles']=f'lesson {sequence}'
            result=self.bridge._passive_browser.receive(grant['token'],ORIGIN,value)
            self.assertEqual(result['status'],'updated')
            self.assertEqual(self.bridge._companion.latest.text,f'lesson {sequence}')
