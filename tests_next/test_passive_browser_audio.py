"""Bounded browser tab audio transport discipline (delivery package P3)."""
import json
import sys
from base64 import b64encode
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch

from extensions.companion.passive_browser_audio import (
    PACKET_BYTES, PassiveBrowserAudio, QUEUE_LIMIT)

GRANT = {'token': 'grant-token', 'extension_id': 'abcdefghijklmnopabcdefghijklmnop',
         'tab_id': 7, 'origin': 'https://www.bilibili.com', 'audio': True,
         'audio_epoch': 'epoch-1'}
IDENTITY = {'url': 'https://www.bilibili.com/video/BV1Lf4y1M72V', 'part': 1}


def packet(sequence=0, *, epoch='epoch-1', identity=IDENTITY, pcm=None):
    return {'tab_id': 7, 'audio_epoch': epoch, 'sequence': sequence,
            'media_identity': identity, 'sample_rate': 16000, 'channels': 1,
            'format': 'pcm_s16le', 'sample_offset': sequence * 1600,
            'pcm_base64': b64encode(pcm or bytes(PACKET_BYTES)).decode('ascii')}


class ActiveAudio(PassiveBrowserAudio):
    """A transport driven into the running state without spawning a child."""

    def __init__(self):
        super().__init__(root=Path('.'), on_observation=lambda value: None,
                         on_clear=lambda: None)
        self._state = 'running'
        self._target = 'browser-passive:test:tab:7'
        self._identity = IDENTITY
        self._audio_epoch = 'epoch-1'
        self._next_sequence = 0
        self._consented = True


class PassiveBrowserAudioTests(unittest.TestCase):
    def setUp(self):
        self.audio = ActiveAudio()

    def test_strict_sequence_and_epoch_binding(self):
        grant = dict(GRANT)
        first = self.audio.receive(GRANT['token'], 'chrome-extension://'+GRANT['extension_id'],
                                   packet(0), grant=grant)
        self.assertEqual(first['sequence'], 0)
        self.audio.receive(GRANT['token'], 'chrome-extension://'+GRANT['extension_id'],
                           packet(1), grant=grant)
        with self.assertRaisesRegex(PermissionError, 'sequence gap'):
            self.audio.receive(GRANT['token'], 'chrome-extension://'+GRANT['extension_id'],
                               packet(3), grant=grant)
        with self.assertRaisesRegex(ValueError, 'outside the active epoch'):
            self.audio.receive(GRANT['token'], 'chrome-extension://'+GRANT['extension_id'],
                               packet(2, epoch='epoch-2'), grant=grant)

    def test_grant_token_tab_origin_and_audio_consent_bound(self):
        grant = dict(GRANT)
        with self.assertRaises(PermissionError):
            self.audio.receive('wrong-token', 'chrome-extension://'+GRANT['extension_id'],
                               packet(0), grant=grant)
        with self.assertRaises(PermissionError):
            self.audio.receive(GRANT['token'], 'chrome-extension://'+GRANT['extension_id'],
                               packet(0), grant={**grant, 'audio': False})
        with self.assertRaises(PermissionError):
            self.audio.receive(GRANT['token'], 'chrome-extension://'+GRANT['extension_id'],
                               {**packet(0), 'tab_id': 8}, grant=grant)

    def test_identity_change_and_packet_shape_fail_closed(self):
        grant = dict(GRANT)
        self.audio.receive(GRANT['token'], 'chrome-extension://'+GRANT['extension_id'],
                           packet(0), grant=grant)
        with self.assertRaisesRegex(PermissionError, 'identity changed'):
            self.audio.receive(GRANT['token'], 'chrome-extension://'+GRANT['extension_id'],
                               packet(1, identity={'url': 'https://www.bilibili.com/video/BVother'}),
                               grant=grant)
        with self.assertRaises(ValueError):
            self.audio.receive(GRANT['token'], 'chrome-extension://'+GRANT['extension_id'],
                               packet(1, pcm=bytes(100)), grant=grant)
        with self.assertRaises(ValueError):
            broken = packet(1)
            broken['pcm_base64'] = 'not base64!!'
            self.audio.receive(GRANT['token'], 'chrome-extension://'+GRANT['extension_id'],
                               broken, grant=grant)

    def test_queue_overflow_stops_track_explicitly(self):
        grant = dict(GRANT)
        for sequence in range(QUEUE_LIMIT):
            self.audio.receive(GRANT['token'], 'chrome-extension://'+GRANT['extension_id'],
                               packet(sequence), grant=grant)
        with self.assertRaisesRegex(RuntimeError, 'queue overflow'):
            self.audio.receive(GRANT['token'], 'chrome-extension://'+GRANT['extension_id'],
                               packet(QUEUE_LIMIT), grant=grant)
        self.assertEqual(self.audio.status()['status'], 'stopped')

    def test_inactive_session_rejects_packets(self):
        idle = PassiveBrowserAudio(root=Path('.'), on_observation=lambda value: None,
                                   on_clear=lambda: None)
        with self.assertRaises(PermissionError):
            idle.receive(GRANT['token'], 'chrome-extension://'+GRANT['extension_id'],
                         packet(0), grant=dict(GRANT))


class WorkerPipeModeTests(unittest.TestCase):
    """The relayed tab audio reaches a real interpreter via the pipe source."""

    def test_pipe_worker_confirms_running_and_consumes_packets(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        root = Path(folder.name)
        (root/'capabilities.sqlite').touch()
        from extensions.capabilities import CapabilityStore
        store = CapabilityStore(root/'capabilities.sqlite')
        try:
            store.configure('asr', 'vosk', options={})
            selected = store.resolve('asr')
        finally:
            store.close()
        script = (
            'import json,sys\n'
            'config=json.loads(sys.stdin.readline())\n'
            'assert config["source"]=="pipe" and config["consent"] is True\n'
            'print(json.dumps({"status":"running","target":config["target"]}),flush=True)\n'
            'packets=0\n'
            'while True:\n'
            '    line=sys.stdin.readline()\n'
            '    if not line: break\n'
            '    packet=json.loads(line)\n'
            '    if packet.get("action")=="stop": break\n'
            '    packets+=1\n'
            '    if packets==3:\n'
            '        print(json.dumps({"observation":{"observed_at":"2026-10-09T12:00:00+00:00",'
            '"source":"application-audio-transcript","target":config["target"],"valid":True,'
            '"text":"学习点","packets":packets}}),flush=True)\n')
        interpreter = sys.executable
        observations = []
        ready = threading.Event()
        real_popen = subprocess.Popen
        def fake_spawn(arguments, **kwargs):
            process = real_popen([interpreter, '-X', 'utf8', '-c', script],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                text=True, encoding='utf8')
            original = process.stdout.readline
            def readline(size=-1):
                value = original(size)
                if value and '"running"' in value:
                    ready.set()
                return value
            process.stdout.readline = readline
            return process
        audio = PassiveBrowserAudio(root=root, on_observation=observations.append,
                                    on_clear=lambda: None)
        with patch('extensions.companion.passive_browser_audio.capability_python',
                   return_value=interpreter), \
             patch('extensions.companion.passive_browser_audio.subprocess.Popen',
                   side_effect=fake_spawn):
            status = audio.start(target='browser-passive:test:tab:7', identity=IDENTITY,
                model=root, capabilities=str(root/'capabilities.sqlite'), asr=selected,
                audio_epoch='epoch-1')
            self.assertEqual(status['status'], 'running')
            self.assertTrue(ready.wait(5))
            grant = dict(GRANT)
            for sequence in range(3):
                self.audio_receive(audio, grant, sequence)
            deadline = __import__('time').monotonic() + 5
            while not observations and __import__('time').monotonic() < deadline:
                __import__('time').sleep(0.05)
            audio.stop()
        self.assertEqual(len(observations), 1)
        self.assertEqual(observations[0]['text'], '学习点')

    @staticmethod
    def audio_receive(audio, grant, sequence):
        audio.receive(grant['token'], 'chrome-extension://'+GRANT['extension_id'],
                      packet(sequence), grant=grant)


if __name__ == '__main__':
    unittest.main()
