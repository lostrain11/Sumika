import asyncio
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from extensions.companion.sapi_playback import DirectSapiPlayback, SapiPlaybackProvider


class SapiPlaybackTests(unittest.IsolatedAsyncioTestCase):
    async def test_cancel_reclaims_child_and_no_audio_file(self):
        children = []
        def spawn(argv, **kwargs):
            child = subprocess.Popen([sys.executable, '-c',
                'import json,sys,time;json.load(sys.stdin);time.sleep(30)'], **kwargs)
            children.append(child)
            return child
        with tempfile.TemporaryDirectory() as folder:
            playback = DirectSapiPlayback(Path(folder),
                lambda role: dict(python=sys.executable, root=folder), spawn=spawn)
            provider = SapiPlaybackProvider(playback, 'role')
            task = asyncio.create_task(provider.play_segment('hello'))
            try:
                for _ in range(100):
                    if children: break
                    await asyncio.sleep(0.01)
                self.assertTrue(children)
                task.cancel()
                with self.assertRaises(asyncio.CancelledError): await task
                self.assertIsNotNone(children[0].poll())
                self.assertFalse(playback.thread.is_alive())
                self.assertIsNone(provider._request)
                self.assertEqual(list(Path(folder).rglob('*.wav')), [])
            finally:
                playback.close()

    async def test_completed_segment_returns_after_worker_exit(self):
        def spawn(argv, **kwargs):
            return subprocess.Popen([sys.executable, '-c',
                'import json,sys;p=json.load(sys.stdin);print(json.dumps({"text":p["text"]}))'], **kwargs)
        with tempfile.TemporaryDirectory() as folder:
            playback = DirectSapiPlayback(Path(folder),
                lambda role: dict(python=sys.executable, root=folder), spawn=spawn)
            provider = SapiPlaybackProvider(playback, 'role')
            try:
                await provider.play_segment('hello')
                self.assertFalse(playback.thread.is_alive())
                await provider.play_segment('next')
                self.assertIsNone(provider._request)
            finally:
                playback.close()
