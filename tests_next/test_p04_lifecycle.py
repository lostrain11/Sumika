"""P04 acceptance: audio lifecycle — stop clears, errors persist, no auto-retry.

F-03: stopping the tab-audio track immediately clears the fused audio
context (on_clear), keeps the structured failure reason visible until an
explicit start, stops the track on a sequence gap, and is idempotent.
F-04: the extension surfaces a failed audio start instead of claiming
running, and transport rejections stop the track instead of auto-rotating
(only seek/rate/pause — player_changed — auto-recovers under standing
consent). Window start and bridge shutdown explicitly stop browser audio.
"""
import json
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from extensions.companion.passive_browser_audio import (
    PACKET_BYTES, PassiveBrowserAudio)

GRANT = {'token': 'grant-token', 'extension_id': 'abcdefghijklmnopabcdefghijklmnop',
         'tab_id': 7, 'origin': 'https://www.bilibili.com', 'audio': True,
         'audio_epoch': 'epoch-1'}
IDENTITY = {'url': 'https://www.bilibili.com/video/BV1', 'part': 1}


def packet(sequence, epoch='epoch-1'):
    from base64 import b64encode
    return {'tab_id': 7, 'audio_epoch': epoch, 'sequence': sequence,
            'media_identity': IDENTITY, 'sample_rate': 16000, 'channels': 1,
            'format': 'pcm_s16le', 'sample_offset': sequence * 1600,
            'pcm_base64': b64encode(bytes(PACKET_BYTES)).decode('ascii')}


class ActiveTrack(PassiveBrowserAudio):
    def __init__(self, on_clear):
        super().__init__(root=Path('.'), on_observation=lambda value: None,
                         on_clear=on_clear)
        self._state = 'running'
        self._target = 'browser-passive:test:tab:7'
        self._identity = IDENTITY
        self._audio_epoch = 'epoch-1'
        self._next_sequence = 0
        self._consented = True


class HostLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.clears = 0
        self.audio = ActiveTrack(on_clear=lambda: setattr(self, 'clears', self.clears + 1))

    def test_sequence_gap_stops_track_persists_error_and_clears(self):
        self.audio.receive(GRANT['token'], 'chrome-extension://'+GRANT['extension_id'],
                           packet(0), grant=GRANT)
        with self.assertRaisesRegex(PermissionError, 'sequence gap'):
            self.audio.receive(GRANT['token'], 'chrome-extension://'+GRANT['extension_id'],
                               packet(3), grant=GRANT)
        status = self.audio.status()
        self.assertEqual(status['status'], 'stopped',
                         'a sequence gap must stop the track explicitly')
        self.assertIn('sequence gap', status['error'] or '')
        self.assertEqual(self.clears, 1, 'stop must clear the fused audio context')
        # The reason stays visible after the stop (until an explicit start).
        status = self.audio.status()
        self.assertIn('sequence gap', status['error'] or '')
        # A second stop is idempotent: no double clear, error stays.
        self.audio.stop()
        self.assertEqual(self.clears, 1)

    def test_normal_stop_calls_clear_once_and_keeps_clean_state(self):
        self.audio.receive(GRANT['token'], 'chrome-extension://'+GRANT['extension_id'],
                           packet(0), grant=GRANT)
        result = self.audio.stop()
        self.assertEqual(self.clears, 1)
        self.assertIsNone(result['error'])
        self.audio.stop()
        self.assertEqual(self.clears, 1, 'repeated stop must be idempotent')

    def test_start_clears_a_previous_failure_reason(self):
        self.audio._fail('browser audio queue overflow')
        self.assertIn('queue overflow', self.audio.status()['error'] or '')
        self.audio._state = 'stopped'
        with patch('extensions.companion.passive_browser_audio.capability_python',
                   return_value=None):
            with self.assertRaises(RuntimeError):
                self.audio.start(target='browser-passive:test:tab:7',
                    identity=IDENTITY, model=Path('.'), asr='vosk',
                    audio_epoch='epoch-1')
        # start() resets the state before spawning; the new failure is returned
        # through the exception, and the previous queue-overflow string must not
        # survive as the track's current error.
        status = self.audio.status()
        self.assertEqual(status['status'], 'stopped')
        self.assertIsNone(status.get('error'))


class BridgeLifecycleTests(unittest.TestCase):
    def setUp(self):
        import sqlite3
        import tempfile
        from extensions.models.settings import example, save as save_settings
        from ui.server import serve
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.settings_path = root / 'settings.json'
        capability_path = root / 'capabilities.db'
        connection = sqlite3.connect(capability_path)
        connection.execute("CREATE TABLE capabilities (id TEXT PRIMARY KEY, position INTEGER, enabled INTEGER, provider TEXT, options TEXT)")
        connection.commit()
        connection.close()
        save_settings(example(root / 'role', root / 'sumika.db'), self.settings_path)
        self.server = serve(self.settings_path, port=0,
                            capability_database=capability_path,
                            schedule_directory=root / 'schedules')
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.bridge = self.server.sumika_bridge

    def tearDown(self):
        if self.thread.is_alive():
            self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self._tmp.cleanup()

    def test_perception_start_stops_browser_audio(self):
        bridge = self.bridge
        stopped = []
        with patch.object(bridge._browser_audio, 'stop',
                          side_effect=lambda: stopped.append(True)), \
             patch.object(bridge._browser_audio, 'status',
                          return_value={'status': 'running', 'alive': True,
                                        'target': 'browser-passive:x:tab:7'}), \
             patch('extensions.desktop.windows_capture._identity',
                   return_value='identity-7'), \
             patch('sumika_next.runtime_ownership.process_identity',
                   return_value='7'), \
             patch.object(bridge._perception, 'start',
                          return_value={'status': 'running'}):
            bridge.companion_perception({'action': 'start', 'handle': 123,
                'process_id': 42, 'process_creation': '7', 'consent': True})
        self.assertEqual(stopped, [True],
                         'a window capture start must stop the tab-audio track')

    def test_shutdown_stops_browser_audio(self):
        bridge = self.bridge
        stopped = []
        with patch.object(bridge._browser_audio, 'stop',
                          side_effect=lambda: stopped.append(True)), \
             patch.object(bridge._pet_host, 'stop'), \
             patch.object(bridge.workbench, 'stop'):
            bridge.shutdown()
        self.assertEqual(stopped, [True])

    def test_old_audio_transition_cannot_clear_newer_transition(self):
        bridge = self.bridge
        first = bridge._begin_browser_audio_transition()
        second = bridge._begin_browser_audio_transition()

        bridge._finish_browser_audio_transition(first)
        self.assertTrue(bridge._browser_audio_starting,
                        'a stale lazy-start completion must not release a newer rebuild')

        bridge._finish_browser_audio_transition(second)
        self.assertFalse(bridge._browser_audio_starting,
                         'the current transition owner releases the start fence')


    def test_revoke_stops_approved_passive_connection(self):
        bridge = self.bridge
        with patch.object(bridge._passive_browser, 'start',
                          return_value={'status': 'running'}),              patch.object(bridge._passive_browser, 'status',
                          side_effect=[{'status': 'running'},
                                       {'status': 'stopped'}]),              patch.object(bridge._passive_browser, 'stop') as stop:
            bridge.companion_revoke()
        self.assertEqual(stop.call_count, 1,
                         'companion_revoke must stop the passive connection')


class ExtensionArbitrationTests(unittest.TestCase):
    def test_browser_audio_seek_drops_pcm_then_keeps_capture_and_adopts_timeline(self):
        repo = Path(__file__).resolve().parents[1]
        harness = Path(tempfile.mkdtemp(prefix='p04-audio-seek-'))/'seek.mjs'
        harness.write_text('''
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import vm from 'node:vm';
const source=await readFile(process.argv[2],'utf8');
let seeking=false, revision=0, sourceFingerprint='one', timerFn=null, workletNode=null, stoppedTracks=0;
const listeners=new Map(), forwarded=[];
const video={isConnected:true,ended:false,
  getBoundingClientRect:()=>({width:640,height:360,bottom:360,right:640,top:0,left:0}),
  captureStream:()=>{const track={addEventListener(){},stop(){stoppedTracks++;}};
    return {getAudioTracks:()=>[track],getVideoTracks:()=>[],getTracks:()=>[track]};},
  addEventListener(name,fn){listeners.set(name,fn);},
  removeEventListener(name,fn){if(listeners.get(name)===fn)listeners.delete(name);}};
class AudioContext {
  constructor(){this.sampleRate=16000;this.state='running';this.destination={};
    this.audioWorklet={addModule:async()=>{}};}
  createMediaStreamSource(){return {connect(){},disconnect(){}};}
  createGain(){return {gain:{value:1},connect(){},disconnect(){}};}
  async resume(){}
  async close(){this.state='closed';}
}
class AudioWorkletNode {
  constructor(){this.port={onmessage:null};workletNode=this;}
  connect(){}
  disconnect(){}
}
const context=vm.createContext({location:{origin:'https://www.bilibili.com'},
  document:{querySelectorAll:()=>[video]},getComputedStyle:()=>({visibility:'visible',display:'block'}),
  innerHeight:900,innerWidth:1600,AudioContext,AudioWorkletNode,
  MediaStream:class{constructor(tracks){this.tracks=tracks;}},
  setInterval(fn){timerFn=fn;return 1;},clearInterval(){}});
const create=vm.runInContext('('+source+')',context);
const capture=create({consent:true,origin:'https://www.bilibili.com',workletUrl:'worklet.js',
  readSnapshot:()=>({ok:true,paused:false,seeking,ended:false,playback_rate:1,
    media_identity:{source_fingerprint:sourceFingerprint,timeline_revision:revision}}),onPcm:packet=>forwarded.push(packet)});
await capture.start();
assert.equal(capture.status().state,'recording');
seeking=true;revision++;
listeners.get('seeking')();
workletNode.port.onmessage({data:new ArrayBuffer(3200)});
timerFn();
assert.equal(capture.status().state,'recording','seeking must not tear down capture');
assert.equal(forwarded.length,0,'PCM observed during the seek must be discarded');
seeking=false;
listeners.get('seeked')();
await new Promise(resolve=>setImmediate(resolve));
assert.equal(capture.status().state,'recording','seeked must keep the media-element capture alive');
assert.equal(capture.status().reason,null);
assert.equal(stoppedTracks,0);
// The adapter runs in a separate vm realm; its `instanceof ArrayBuffer`
// check must see a buffer created by that realm, not the Node realm.
workletNode.port.onmessage({data:vm.runInContext('new ArrayBuffer(3200)',context)});
await new Promise(resolve=>setTimeout(resolve,0));
assert.equal(forwarded.length,1,'post-seek PCM must be forwarded under the new timeline');
await capture.stop();
assert.equal(stoppedTracks,1);
await capture.start();
seeking=true;listeners.get('seeking')();sourceFingerprint='another-source';
timerFn();
await new Promise(resolve=>setImmediate(resolve));
assert.equal(capture.status().state,'unavailable','source changes must still stop during seeking');
assert.equal(stoppedTracks,2);
''', encoding='utf8')
        run = subprocess.run(['node', str(harness),
                              str(repo/'extensions/companion/browser_audio_capture.js')],
                             capture_output=True, text=True, timeout=30)
        self.assertEqual(run.returncode, 0, run.stderr)

    def test_paused_capture_waits_for_player_and_stop_removes_listener(self):
        repo = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix='p04-resume-') as directory:
            fixture = Path(directory)
            build = subprocess.run(['node', str(repo/'tools/build_companion_extension.mjs'),
                                    str(fixture/'extension')], capture_output=True,
                                   text=True, timeout=60)
            self.assertEqual(build.returncode, 0, build.stderr)
            harness = fixture/'resume.mjs'
            harness.write_text('''
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import vm from 'node:vm';
const code=await readFile(process.argv[2],'utf8');
let listener, paused=true, seeking=false;
const events=new Map(), messages=[];
const video={isConnected:true,ended:false,
  addEventListener(name,fn){events.set(name,fn);},
  removeEventListener(name,fn){if(events.get(name)===fn)events.delete(name);}};
// Exercise the actual generated content lifecycle, using a fixed collector
// fixture because no page pixels/audio are needed for this waiting boundary.
const source=code.replace(/const collect=[\\s\\S]*?;\\nconst createAudio=/,
  'const collect=()=>fixtureSnapshot();\\nconst createAudio=');
const context=vm.createContext({console,URL,
  location:{origin:'https://www.bilibili.com'},
  fixtureSnapshot:()=>({ok:true,paused,seeking,ended:false}),
  document:{querySelectorAll:()=>[video]},
  chrome:{runtime:{id:'test',getURL:x=>x,
    sendMessage:async message=>{messages.push(message);return {};},
    onMessage:{addListener:fn=>{listener=fn;}}}}});
vm.runInContext(source,context);
const request=message=>new Promise(resolve=>listener(message,{id:'test'},resolve));
let result=await request({type:'start-audio',consent:true,audio_epoch:'one'});
assert.equal(result.started,false);assert.equal(result.waiting,true);
assert.ok(events.has('playing'));assert.equal(messages.length,0);
paused=false;events.get('playing')();await Promise.resolve();
assert.equal(messages.length,1);assert.equal(messages[0].reason,'player_changed');
assert.equal(events.size,0);
paused=true;
await request({type:'start-audio',consent:true,audio_epoch:'two'});
const stale=events.get('playing');
await request({type:'stop-audio'});
assert.equal(events.size,0);stale();await Promise.resolve();
assert.equal(messages.length,1);
paused=false;seeking=true;
result=await request({type:'start-audio',consent:true,audio_epoch:'three'});
assert.equal(result.waiting,true);assert.ok(events.has('seeked'));
seeking=false;events.get('seeked')();await Promise.resolve();
assert.equal(messages.length,2);assert.equal(events.size,0);
''', encoding='utf8')
            run = subprocess.run(['node', str(harness), str(fixture/'extension/content.js')],
                                 capture_output=True, text=True, timeout=60)
            self.assertEqual(run.returncode, 0, run.stderr)

    def test_worker_arbitration_policy(self):
        repo = Path(__file__).resolve().parents[1]
        fixture = Path(tempfile.mkdtemp(prefix='p04-ext-'))
        build = subprocess.run(
            ['node', str(repo/'tools'/'build_companion_extension.mjs'), str(fixture)],
            capture_output=True, text=True, timeout=60)
        self.assertEqual(build.returncode, 0, build.stderr)
        worker_path = fixture/'worker.js'
        harness = Path(tempfile.mkdtemp(prefix='p04-ext-test-'))/'arbitration.mjs'
        harness.write_text('''
import {readFile} from 'node:fs/promises';
import vm from 'node:vm';
const worker = await readFile(process.argv[2], 'utf8');
const id = 'abcdefghijklmnopabcdefghijklmnop';
let listener = null;
let epochCalls = 0, startAudioCalls = 0, startAudioReply = {started: true};
let audioPosts = [];
const context = vm.createContext({URL, AbortSignal, Date, console,
  setTimeout(fn) { return setTimeout(fn, 0); },
  setInterval() {}, clearTimeout() {},
  chrome: {runtime: {id,
      onMessage: {addListener(fn) { listener = fn; }}},
    tabs: {onRemoved: {addListener() {}}, onUpdated: {addListener() {}},
      async get() { return {id: 7, url: 'https://www.bilibili.com/video/BVtest', title: 't'}; },
      async sendMessage(tab, msg) {
        if (msg.type === 'start-audio') {
          startAudioCalls++;
          return startAudioReply;
        }
        return {started: true};
      }}},
  async fetch(url, options) {
    if (url.endsWith('/audio-epoch')) epochCalls++;
    if (url.endsWith('/passive-browser/audio')) {
      audioPosts.push(JSON.parse(options.body).sequence);
      return {ok: true, async json() { return {status: 'accepted', queued: 0}; }};
    }
    return {ok: true, async json() { return {audio_epoch: 'fresh'}; }};
  }});
vm.runInContext(worker, context);
const grant = {extension_id: id, tab_id: 7, origin: 'https://www.bilibili.com',
               audio: true, audio_epoch: 'old', capture_frame: true};
context.fixtureGrant = grant;
vm.runInContext("requestedConnection={base:'http://127.0.0.1:9999'}", context);
const sender = {id, tab: {id: 7}, frameId: 0, url: 'https://www.bilibili.com/video/BVtest'};
const results = {};
// F-04: a failed audio start must not claim running.
startAudioReply = {started: false, error: 'player audio track unavailable'};
let threw = null;
try {
  await vm.runInContext("startConnection({base:'http://127.0.0.1:9999',grant:fixtureGrant})", context);
} catch (error) { threw = error.message; }
results.failed_audio_start = {threw, audioActive: vm.runInContext('audioActive', context),
  startAudioCalls, error: vm.runInContext('lastAudioError', context)};
// Recovery: the retry succeeds and the connection goes live.
startAudioReply = {started: true};
await vm.runInContext("startConnection({base:'http://127.0.0.1:9999',grant:fixtureGrant})", context);
results.live_connection = {audioActive: vm.runInContext('audioActive', context)};
// F-03: transport rejection (host_rejected) stops and does NOT auto-rotate.
let before = epochCalls;
const rejected = await listener({type: 'audio-stopped', reason: 'host_rejected'}, sender,
  () => {});
results.transport_rejection = {epoch_requests: epochCalls - before,
  verdict: rejected};
before = epochCalls;
await listener({type: 'audio-stopped', reason: 'send_failed'}, sender, () => {});
results.send_failed = {epoch_requests: epochCalls - before};
// Only seek/rate/pause (player_changed) auto-recovers under standing consent.
const rotated = await listener({type: 'audio-stopped', reason: 'player_changed'},
  sender, () => {});
results.player_changed = {epoch_requests: epochCalls - before,
  verdict: rotated};
// R3/P07: queued PCM under a rotated epoch is dropped, never posted under
// the new one (the old sequence would trip the server's sequence fence).
await listener({type: 'audio-packet', sequence: 0, sample_offset: 0,
  media_identity: {}, pcm_base64: 'AAAA'}, sender, () => {});
await listener({type: 'audio-packet', sequence: 1, sample_offset: 1600,
  media_identity: {}, pcm_base64: 'AAAA'}, sender, () => {});
await new Promise(resolve => setTimeout(resolve, 80));  // drain settles
before = epochCalls;
await listener({type: 'audio-stopped', reason: 'player_changed'}, sender, () => {});
await new Promise(resolve => setTimeout(resolve, 50));
await listener({type: 'audio-packet', sequence: 0, sample_offset: 0,
  media_identity: {}, pcm_base64: 'AAAA'}, sender, () => {});
await new Promise(resolve => setTimeout(resolve, 120));
results.stale_epoch_fencing = {posted_sequences: audioPosts,
  epoch_requests: epochCalls - before};
// A paused player refuses an immediate capture restart. Never report audio
// active merely because the host recognizer has a fresh epoch.
startAudioReply = {started: false, waiting: true, error: 'player_paused_or_seeking'};
const pauseReply = await new Promise(resolve => listener(
  {type: 'audio-stopped', reason: 'player_changed'}, sender, resolve));
results.paused_restart = {reply: pauseReply,
  audioActive: vm.runInContext('audioActive', context),
  error: vm.runInContext('lastAudioError', context)};
startAudioReply = {started: true};
await new Promise(resolve => listener(
  {type: 'audio-stopped', reason: 'player_changed'}, sender, resolve));
results.resumed_restart = {audioActive: vm.runInContext('audioActive', context),
  error: vm.runInContext('lastAudioError', context)};
console.log(JSON.stringify(results));
''', encoding='utf8')
        run = subprocess.run(['node', str(harness), str(worker_path)],
                             capture_output=True, text=True, timeout=60)
        if run.returncode != 0:
            Path('E:/SumikaBuild/p04-node-stderr.log').write_text(run.stderr, encoding='utf8')
            self.fail('extension arbitration harness failed; full stderr in '
                      'E:/SumikaBuild/p04-node-stderr.log')
        results = json.loads(run.stdout.strip().splitlines()[-1])
        # Keep video available, but report the bounded audio start failure.
        self.assertIsNone(results['failed_audio_start']['threw'])
        self.assertEqual(results['failed_audio_start']['startAudioCalls'], 4)
        self.assertEqual(results['failed_audio_start']['error'], 'player audio track unavailable')
        self.assertFalse(results['failed_audio_start']['audioActive'])
        # F-03: transport rejections stop without auto-rotation.
        self.assertEqual(results['transport_rejection']['epoch_requests'], 0)
        self.assertEqual(results['send_failed']['epoch_requests'], 0)
        # Only player lifecycle changes auto-rotate.
        self.assertEqual(results['player_changed']['epoch_requests'], 1)
        # R3: rotation clears stale queued packets; only the fresh epoch's
        # sequence reaches the host.
        self.assertEqual(results['stale_epoch_fencing']['posted_sequences'], [0, 0])
        self.assertEqual(results['stale_epoch_fencing']['epoch_requests'], 1)
        self.assertFalse(results['paused_restart']['audioActive'])
        self.assertFalse(results['paused_restart']['reply']['restarted'])
        self.assertEqual(results['paused_restart']['error'], 'player_paused_or_seeking')
        self.assertTrue(results['resumed_restart']['audioActive'])
        self.assertIsNone(results['resumed_restart']['error'])


if __name__ == '__main__':
    unittest.main()
