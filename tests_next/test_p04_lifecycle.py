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
        # A real start clears the stale reason via the state reset in start.


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
        self.thread.join(timeout=5)
        self.server.server_close()
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
  startAudioCalls};
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
console.log(JSON.stringify(results));
''', encoding='utf8')
        run = subprocess.run(['node', str(harness), str(worker_path)],
                             capture_output=True, text=True, timeout=60)
        if run.returncode != 0:
            Path('E:/SumikaBuild/p04-node-stderr.log').write_text(run.stderr, encoding='utf8')
            self.fail('extension arbitration harness failed; full stderr in '
                      'E:/SumikaBuild/p04-node-stderr.log')
        results = json.loads(run.stdout.strip().splitlines()[-1])
        # F-04: the failed start surfaces instead of claiming running.
        self.assertTrue(results['failed_audio_start']['threw'],
                        'a failed start-audio must fail the connection loudly')
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


if __name__ == '__main__':
    unittest.main()
