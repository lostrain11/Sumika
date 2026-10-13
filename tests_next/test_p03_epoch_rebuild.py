"""P03 acceptance: one recognizer per audio epoch, rebuilt with the current
full media identity (F-02). A seek must not lose the audio track: the old
worker is torn down, a fresh worker carries the post-seek identity, and its
transcripts are the ones the fusion accepts."""
import json
import sys
import tempfile
import threading
import time
import unittest
from base64 import b64encode
from pathlib import Path
import subprocess
from unittest.mock import patch

from extensions.companion.passive_browser_audio import (
    PACKET_BYTES, PassiveBrowserAudio)

GRANT = {'token': 'grant-token', 'extension_id': 'abcdefghijklmnopabcdefghijklmnop',
         'tab_id': 7, 'origin': 'https://www.bilibili.com', 'audio': True,
         'audio_epoch': 'epoch-1'}

WORKER_SCRIPT = (
    'import json,sys\n'
    'config=json.loads(sys.stdin.readline())\n'
    'print(json.dumps({"status":"running","target":config["target"]}),flush=True)\n'
    'while True:\n'
    '    line=sys.stdin.readline()\n'
    '    if not line: break\n'
    '    packet=json.loads(line)\n'
    '    if packet.get("action")=="stop": break\n'
    '    print(json.dumps({"observation":{"observed_at":"2026-10-12T12:00:00+00:00",'
    '"source":"application-audio-transcript","target":config["target"],"valid":True,'
    '"text":"lesson","metadata":{"media_identity":config["media_identity"]}}}),flush=True)\n')


def packet(sequence, epoch, identity):
    return {'tab_id': 7, 'audio_epoch': epoch, 'sequence': sequence,
            'media_identity': identity, 'sample_rate': 16000, 'channels': 1,
            'format': 'pcm_s16le', 'sample_offset': sequence * 1600,
            'pcm_base64': b64encode(bytes(PACKET_BYTES)).decode('ascii')}


class EpochRebuildTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        root = Path(self.folder.name)
        (root/'capabilities.sqlite').touch()
        from extensions.capabilities import CapabilityStore
        store = CapabilityStore(root/'capabilities.sqlite')
        try:
            store.configure('asr', 'vosk', options={})
            self.selected = store.resolve('asr')
        finally:
            store.close()
        self.spawn_configs = []
        self.observations = []
        self.interpreter = sys.executable
        self.real_popen = subprocess.Popen

    def _fake_spawn(self, arguments, **kwargs):
        process = self.real_popen(
            [self.interpreter, '-X', 'utf8', '-c', WORKER_SCRIPT],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, encoding='utf8')
        original = process.stdin.write
        def write(value):
            if isinstance(value, str) and 'media_identity' in value:
                self.spawn_configs.append(json.loads(value).get('media_identity'))
            return original(value)
        process.stdin.write = write
        return process

    def _identity(self, revision):
        return {'url': 'https://www.bilibili.com/video/BV1', 'part': 1,
                'source_fingerprint': 'aa', 'timeline_revision': revision}

    def _audio(self):
        audio = PassiveBrowserAudio(root=Path(self.folder.name),
            on_observation=self.observations.append, on_clear=lambda: None)
        self.addCleanup(lambda: audio.stop() if audio._process else None)
        return audio

    def test_rotate_rebuilds_worker_with_post_seek_identity(self):
        audio = self._audio()
        identity_a, identity_b = self._identity(0), self._identity(1)
        with patch('extensions.companion.passive_browser_audio.capability_python',
                   return_value=self.interpreter), \
             patch('extensions.companion.passive_browser_audio.subprocess.Popen',
                   side_effect=self._fake_spawn):
            status = audio.start(target='browser-passive:test:tab:7',
                identity=identity_a, model=self.folder.name,
                capabilities=str(Path(self.folder.name)/'capabilities.sqlite'),
                asr=self.selected, audio_epoch='epoch-1')
            self.assertEqual(status['status'], 'running')
            grant = dict(GRANT)
            for sequence in range(2):
                audio.receive(grant['token'],
                    'chrome-extension://'+grant['extension_id'],
                    packet(sequence, 'epoch-1', identity_a), grant=grant)
            # R3: the seek rebuilds the recognizer with the post-seek identity.
            audio.rotate_epoch('epoch-2', identity=identity_b)
            self.assertEqual(len(self.spawn_configs), 2)
            self.assertEqual(self.spawn_configs[-1], identity_b)
            grant['audio_epoch'] = 'epoch-2'
            for sequence in range(3):
                audio.receive(grant['token'],
                    'chrome-extension://'+grant['extension_id'],
                    packet(sequence, 'epoch-2', identity_b), grant=grant)
            # Wait for the REBUILT worker's transcripts BEFORE stopping: the
            # transcript dicts carry media_identity at the top level.
            self.assertTrue(observations_ready(self.observations, minimum=1),
                            'the rebuilt worker must produce transcripts')
            audio.stop()
        for value in self.observations:
            identity = value['metadata']['media_identity']
            self.assertEqual(identity['timeline_revision'], 1,
                             'post-seek transcripts carry the post-seek identity')

    def test_rotate_rejects_packets_outside_the_new_epoch(self):
        audio = self._audio()
        identity_a = self._identity(0)
        with patch('extensions.companion.passive_browser_audio.capability_python',
                   return_value=self.interpreter), \
             patch('extensions.companion.passive_browser_audio.subprocess.Popen',
                   side_effect=self._fake_spawn):
            audio.start(target='browser-passive:test:tab:7',
                identity=identity_a, model=self.folder.name,
                capabilities=str(Path(self.folder.name)/'capabilities.sqlite'),
                asr=self.selected, audio_epoch='epoch-1')
            audio.rotate_epoch('epoch-2', identity=self._identity(1))
            grant = dict(GRANT)
            grant['audio_epoch'] = 'epoch-2'
            with self.assertRaisesRegex(ValueError, 'outside the active epoch'):
                audio.receive(grant['token'],
                    'chrome-extension://'+grant['extension_id'],
                    packet(0, 'epoch-1', identity_a), grant=grant)
            audio.receive(grant['token'], 'chrome-extension://'+grant['extension_id'],
                          packet(0, 'epoch-2', self._identity(1)), grant=grant)
            audio.stop()

    def test_old_worker_death_does_not_stop_the_new_track(self):
        audio = self._audio()
        with patch('extensions.companion.passive_browser_audio.capability_python',
                   return_value=self.interpreter), \
             patch('extensions.companion.passive_browser_audio.subprocess.Popen',
                   side_effect=self._fake_spawn):
            audio.start(target='browser-passive:test:tab:7',
                identity=self._identity(0), model=self.folder.name,
                capabilities=str(Path(self.folder.name)/'capabilities.sqlite'),
                asr=self.selected, audio_epoch='epoch-1')
            old_reader_epoch = audio._epoch
            audio.rotate_epoch('epoch-2', identity=self._identity(1))
            # The old reader's pipe died with the killed worker; its failure
            # path must return quietly instead of failing the new track.
            fake_old = type('P', (), {'stdout': None})()
            audio._read(fake_old, old_reader_epoch)
            self.assertEqual(audio.status()['status'], 'running')
            audio.stop()

    def test_starting_state_buffers_packets_across_model_load(self):
        # P05: while the recognizer is starting, packets buffer generously
        # (model load takes seconds); the 20-packet bound applies when running.
        from extensions.companion.passive_browser_audio import QUEUE_LIMIT
        audio = self._audio()
        audio._state = 'starting'
        audio._audio_epoch = 'epoch-1'
        audio._identity = self._identity(0)
        audio._next_sequence = 0
        audio._consented = True
        self.audio_receive = audio.receive
        grant = dict(GRANT)
        accepted = 0
        for sequence in range(100):
            try:
                audio.receive(grant['token'],
                    'chrome-extension://'+grant['extension_id'],
                    packet(sequence, 'epoch-1', self._identity(0)), grant=grant)
                accepted += 1
            except (PermissionError, RuntimeError):
                break
        self.assertGreater(accepted, QUEUE_LIMIT,
                           'starting-state buffering must exceed the running bound')

    def test_rotation_failure_stops_cleanly(self):
        audio = self._audio()
        with patch('extensions.companion.passive_browser_audio.capability_python',
                   return_value=self.interpreter), \
             patch('extensions.companion.passive_browser_audio.subprocess.Popen',
                   side_effect=self._fake_spawn):
            audio.start(target='browser-passive:test:tab:7',
                identity=self._identity(0), model=self.folder.name,
                capabilities=str(Path(self.folder.name)/'capabilities.sqlite'),
                asr=self.selected, audio_epoch='epoch-1')
        with patch('extensions.companion.passive_browser_audio.capability_python',
                   return_value=None):
            with self.assertRaises(RuntimeError):
                audio.rotate_epoch('epoch-2', identity=self._identity(1))
        self.assertEqual(audio.status()['status'], 'stopped')


def observations_ready(observations, minimum=1):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and len(observations) < minimum:
        time.sleep(0.05)
    return len(observations) >= minimum


if __name__ == '__main__':
    unittest.main()
