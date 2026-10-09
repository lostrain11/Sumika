"""Direct SAPI playback using the existing owned speech worker lifecycle."""
import asyncio
import json
import time

from extensions.capabilities import CapabilityStore
from extensions.roles.speech_playback import SpeechPlayback


class DirectSapiPlayback(SpeechPlayback):
    worker_module = 'extensions.companion.sapi_playback'

    def worker_payload(self, config, directory):
        return {**config, 'text': self._text}


class SapiPlaybackProvider:
    """Async segment provider; cancellation returns after the child is reclaimed."""

    def __init__(self, playback, role_id):
        self.playback = playback
        self.role_id = role_id
        self._request = None

    async def play_segment(self, text):
        if self._request is not None:
            raise RuntimeError('SAPI segment is already active')
        # Start and publish ownership without yielding, so stop cannot miss a
        # child that has been launched but not yet assigned to this provider.
        request = self.playback.start(self.role_id, text=text, approved=True)
        self._request = request['id']
        try:
            while True:
                state = self.playback.status(request['id'])['state']
                if state == 'completed':
                    await self._join()
                    return
                if state != 'processing':
                    raise RuntimeError(f'SAPI playback ended with {state}')
                await asyncio.sleep(0.02)
        finally:
            await self.stop()

    async def _join(self):
        thread = self.playback.thread
        if thread is not None:
            await asyncio.to_thread(thread.join, 6)
            if thread.is_alive():
                raise RuntimeError('SAPI playback worker did not settle')

    async def stop(self):
        request = self._request
        if request is None:
            return
        task = asyncio.create_task(asyncio.to_thread(self.playback.cancel, request))
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            await asyncio.shield(task)
            raise
        finally:
            await self._join()
            self._request = None


def worker(config):
    import pythoncom
    import win32com.client
    text = config.get('text')
    if not isinstance(text, str) or not text.strip() or len(text) > 4000:
        raise ValueError('valid bounded speech text required')
    store = CapabilityStore(config['capabilities'])
    pythoncom.CoInitialize()
    speaker = None
    try:
        selected = store.resolve('voice')
        if selected['provider'] != 'windows-sapi' or selected != config['voice_capability']:
            raise PermissionError('selected voice unavailable or changed')
        speaker = win32com.client.Dispatch('SAPI.SpVoice')
        voices = [voice for voice in speaker.GetVoices()
                  if voice.GetDescription() == config['voice_name']]
        if len(voices) != 1:
            raise ValueError('configured SAPI voice unavailable; no fallback')
        speaker.Voice = voices[0]
        if store.resolve('voice') != selected:
            raise PermissionError('voice capability changed before playback')
        speaker.Speak(text, 1 | 16)  # Async, literal text rather than SSML.
        deadline = time.monotonic() + 55
        while not speaker.WaitUntilDone(20):
            if store.resolve('voice') != selected:
                raise PermissionError('voice capability changed during playback')
            if time.monotonic() >= deadline:
                raise TimeoutError('SAPI playback timed out')
            pythoncom.PumpWaitingMessages()
        return {'text': text}
    finally:
        try:
            if speaker is not None:
                speaker.Speak('', 1 | 2)  # Purge the exclusive worker's queue.
        finally:
            speaker = None
            pythoncom.CoUninitialize()
            store.close()


if __name__ == '__main__':
    import sys
    if sys.argv[1:] != ['--worker']:
        raise SystemExit('SAPI playback requires owned worker invocation')
    print(json.dumps(worker(json.load(sys.stdin)), ensure_ascii=False))
