"""Explicit local playback using the existing owned speech worker lifecycle."""
import json

from extensions.capabilities import CapabilityStore
from extensions.roles.speech_input import SpeechInput
from extensions.roles.voice import synthesize


class SpeechPlayback(SpeechInput):
    worker_module = 'extensions.roles.speech_playback'
    pending_state = 'processing'

    def start(self, role_id, *, text, approved=False):
        if not isinstance(text, str) or not text.strip() or len(text) > 4000:
            raise ValueError('playback requires 1 to 4000 characters')
        with self.lock:
            self._text = text
            return super().start(role_id, approved=approved)

    def worker_payload(self, config, directory):
        return {**config, 'text': self._text, 'output': str(directory/'speech.wav')}


def worker(config):
    store = CapabilityStore(config['capabilities'])
    try:
        selected = store.resolve('voice')
        if selected['provider'] != 'windows-sapi' or selected != config['voice_capability']:
            raise PermissionError('selected local voice unavailable or changed')
        result = synthesize(config['text'], config['output'], voice_name=config['voice_name'])
        if store.resolve('voice') != selected:
            raise PermissionError('voice capability changed before playback')
        import winsound
        # Synchronous playback keeps completion and cancellation owned by this worker.
        # NODEFAULT prevents an invalid file from playing a system fallback sound.
        winsound.PlaySound(result['path'], winsound.SND_FILENAME | winsound.SND_SYNC | winsound.SND_NODEFAULT)
        return {'text': config['text']}
    finally:
        store.close()


if __name__ == '__main__':
    import sys
    if sys.argv[1:] != ['--worker']:
        raise SystemExit('playback requires managed worker invocation')
    print(json.dumps(worker(json.load(sys.stdin)), ensure_ascii=False))
