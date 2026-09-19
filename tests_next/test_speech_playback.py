import subprocess
import sys
import tempfile
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from extensions.capabilities import CapabilityStore
from extensions.roles.speech_playback import SpeechPlayback, worker


class SpeechPlaybackTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = CapabilityStore(self.root/'capabilities.sqlite3')
        self.store.configure('voice', 'windows-sapi')
        self.config = dict(capabilities=str(self.root/'capabilities.sqlite3'),
                           voice_capability=self.store.resolve('voice'), voice_name='selected voice',
                           text='你好', output=str(self.root/'speech.wav'))

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def test_selected_voice_synchronous_playback_without_microphone(self):
        with patch('extensions.roles.speech_playback.synthesize', return_value={'path':self.config['output']}) as synth, \
                patch('winsound.PlaySound') as play:
            result = worker(self.config)
        synth.assert_called_once_with('你好', self.config['output'], voice_name='selected voice')
        play.assert_called_once()
        import winsound
        self.assertTrue(play.call_args.args[1] & winsound.SND_NODEFAULT)
        self.assertFalse(play.call_args.args[1] & winsound.SND_ASYNC)
        self.assertEqual(result, {'text':'你好'})
        self.assertEqual([item['id'] for item in self.store.list()], ['voice'])

    def test_disable_during_synthesis_prevents_playback(self):
        def synth(*args, **kwargs):
            self.store.configure('voice','windows-sapi', enabled=False)
            return {'path':self.config['output']}
        with patch('extensions.roles.speech_playback.synthesize',side_effect=synth), patch('winsound.PlaySound') as play:
            with self.assertRaises(PermissionError):
                worker(self.config)
            play.assert_not_called()

    def test_provider_change_never_synthesizes_or_falls_back(self):
        self.store.configure('voice','other')
        with patch('extensions.roles.speech_playback.synthesize') as synth:
            with self.assertRaises(PermissionError):
                worker(self.config)
            synth.assert_not_called()

    def test_unapproved_or_invalid_text_never_spawns(self):
        spawn = Mock()
        service = SpeechPlayback(self.root/'jobs', lambda role: {}, spawn=spawn)
        with self.assertRaises(PermissionError):
            service.start('role',text='hello')
        for text in ('', 'x'*4001, None):
            with self.assertRaises(ValueError):
                service.start('role', text=text, approved=True)
        spawn.assert_not_called()
        service.close()

    def test_owned_playback_worker_can_be_cancelled(self):
        children=[]
        def spawn(argv, **kwargs):
            self.assertEqual(argv[5], 'extensions.roles.speech_playback')
            child=subprocess.Popen([sys.executable,'-c','import json,sys,time;json.load(sys.stdin);time.sleep(30)'], **kwargs)
            children.append(child)
            return child
        service=SpeechPlayback(self.root/'jobs',lambda role:dict(python=sys.executable,root=str(self.root)),spawn=spawn)
        try:
            request=service.start('role',text='hello',approved=True)
            self.assertEqual(request['state'],'processing')
            self.assertEqual(service.cancel(request['id'])['state'],'cancelled')
            service.thread.join(timeout=5)
            self.assertFalse(service.thread.is_alive())
            self.assertIsNotNone(children[0].poll())
        finally:
            service.close()
