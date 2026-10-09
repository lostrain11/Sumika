"""Provider-neutral continuous voice coordinator for the companion.

Capture, ASR and TTS stay outside this module. The coordinator owns consent,
turn fencing and interruption so a late provider result cannot be played or
written into the current discussion.
"""
from dataclasses import dataclass
import threading
import time

from extensions.roles.realtime_voice import VoiceSession, VoiceState


@dataclass(frozen=True)
class AudioRoute:
    microphone: str
    application: str | None = None
    process_id: int | None = None

    def __post_init__(self):
        if not isinstance(self.microphone, str) or not self.microphone.strip():
            raise ValueError('microphone route required')
        if self.process_id is not None and (type(self.process_id) is not int or self.process_id <= 0):
            raise ValueError('process id must be positive')
        if self.process_id is None and self.application is not None:
            raise ValueError('application route requires process id')


class CompanionVoicePipeline:
    """Coordinate one active voice turn; providers call the explicit methods."""

    def __init__(self, *, asr, answer, tts, cancel=None, clock=time.monotonic,
                 on_event=None):
        for name, value in {'asr': asr, 'answer': answer, 'tts': tts}.items():
            if not callable(value):
                raise ValueError(f'{name} provider must be callable')
        self.asr, self.answer, self.tts = asr, answer, tts
        self.cancel_provider = cancel if callable(cancel) else lambda: None
        if on_event is not None and not callable(on_event):
            raise ValueError('voice event callback must be callable')
        self.on_event = on_event or (lambda event, token: None)
        self.clock = clock
        self.session = VoiceSession()
        self.route = None
        self._lock = threading.RLock()
        self._epoch = 0
        self._started = False

    def start(self, route: AudioRoute, *, approved=False):
        if approved is not True:
            raise PermissionError('explicit microphone and application audio consent required')
        with self._lock:
            if self._started:
                raise RuntimeError('voice pipeline is already running')
            self.route = route
            self.session = VoiceSession()
            self._epoch += 1
            self._started = True
            return {'status': 'started', 'route': route.__dict__, 'session': self.session.snapshot()}

    def begin_turn(self):
        with self._lock:
            self._require_started()
            if self.session.state == VoiceState.PLAYING:
                self.interrupt()
            self.session.start_listening()
            self.on_event('user_started', self._token())
            return self._token()

    def submit_audio(self, audio, *, token):
        if not isinstance(audio, (bytes, bytearray)) or not audio:
            raise ValueError('audio bytes required')
        with self._lock:
            self._check(token, VoiceState.LISTENING)
            self.session.audio_ready()
            epoch, turn = token
            route = self.route
        stage = 'speech recognition'
        try:
            text = self.asr(bytes(audio))
            with self._lock:
                self._check((epoch, turn), VoiceState.TRANSCRIBING)
                self.session.transcribed(text)
            stage = 'companion answer'
            response = self.answer(text, route=route)
            with self._lock:
                self._check((epoch, turn), VoiceState.RESPONDING)
                self.session.responded(response)
                self.on_event('playback_started', (epoch, turn))
        except Exception:
            with self._lock:
                if self._started and self._token() == (epoch, turn):
                    self.session.fail(f'{stage} failed')
                    self.on_event('failed', (epoch, turn))
            raise
        try:
            self.tts(response, token=(epoch, turn))
        except Exception:
            with self._lock:
                if self._token() == (epoch, turn):
                    self.session.fail('speech playback failed')
                self.on_event('playback_ended', (epoch, turn))
            raise
        with self._lock:
            self._check((epoch, turn), VoiceState.PLAYING)
            return self.session.snapshot()

    def playback_done(self, token):
        with self._lock:
            self._check(token, VoiceState.PLAYING)
            result = self.session.playback_done()
            self.on_event('playback_ended', token)
            return result

    def interrupt(self):
        with self._lock:
            if not self._started:
                return {'status': 'stopped'}
            token = self._token()
            self._epoch += 1
            result = self.session.cancel()
            try:
                self.cancel_provider()
            finally:
                self.on_event('interrupted', token)
            return {'status': 'interrupted', 'session': result}

    def stop(self):
        with self._lock:
            token = self._token()
            self._epoch += 1
            self._started = False
            result = self.session.cancel()
            try:
                self.cancel_provider()
            finally:
                self.on_event('stopped', token)
            return {'status': 'stopped', 'session': result}

    def _require_started(self):
        if not self._started:
            raise RuntimeError('voice pipeline is not started')

    def _token(self):
        return self._epoch, self.session.turn_id

    def _check(self, token, state):
        if token != self._token() or self.session.state != state:
            raise RuntimeError('voice turn was cancelled or superseded')
