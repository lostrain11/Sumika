"""Continuous study voice in the isolated runtime; PCM never crosses its pipe.

The worker owns only VAD, local ASR and segmented SAPI playback. Questions,
proactive discussion and the model live in the host-side session coordinator:
the worker reports speech/playback states and receives generated answers over
the pipe, so text questioning works without any microphone.
"""
import asyncio
from collections import deque
from datetime import datetime
import json
from pathlib import Path
import sys
import threading

from extensions.capabilities import CapabilityStore
from extensions.models.settings import load as load_settings
from extensions.models.cancellation import CancellationToken
from extensions.roles.roles import load_role
from .contracts import ObservationBundle


def require_configuration(config):
    if config.get('microphone_consent') is not True or config.get('playback_consent') is not True:
        raise PermissionError('explicit microphone and playback consent required')
    discussion = config.get('proactive', {'enabled':True, 'interval_seconds':120})
    if (not isinstance(discussion, dict) or type(discussion.get('enabled')) is not bool
            or type(discussion.get('interval_seconds')) not in (int, float)
            or not 120 <= discussion['interval_seconds'] <= 86400):
        raise ValueError('explicit discussion mode and interval of at least 120 seconds required')
    settings = load_settings(config['settings_path'])
    if settings != config['settings']:
        raise PermissionError('study voice settings changed')
    voice = settings['voice']
    if (not settings['enabled'] or not voice['enabled'] or voice['sample_rate'] != 16000
            or type(voice['input_device']) is not int):
        raise PermissionError('enabled model and selected 16kHz microphone required')
    selected = config['selected']
    store = CapabilityStore(config['capabilities'])
    try:
        for kind, providers in (('microphone', ('sounddevice',)),
                                ('asr', ('vosk', 'sherpa-onnx-sensevoice')),
                                ('voice', ('windows-sapi',))):
            entry = store.resolve(kind)
            if entry != selected[kind] or entry['provider'] not in providers:
                raise PermissionError('study voice capability changed')
        if selected['microphone']['options'].get('user_authorized') is not True:
            raise PermissionError('microphone capability authorization required')
    finally:
        store.close()
    if load_role(settings['role']['role_dir'])['id'] != config['role_id']:
        raise PermissionError('study voice role changed')
    return settings


def observation(value):
    return ObservationBundle(observed_at=datetime.fromisoformat(value['observed_at']),
        source=value['source'], target=value['target'], valid=value['valid'],
        text=value.get('text',''), image=value.get('image'),
        media_time_seconds=value.get('media_time_seconds'), metadata=value.get('metadata') or {})


class _PipeBinding:
    """Opaque provenance marker; the host freezes the real binding on speech."""


class PipeQuestionService:
    """Companion question service surface backed by the host coordinator.

    The host owns history, bindings and the model. ``ask`` reports the request
    over the pipe and blocks until the host streams a verdict; deltas are
    delivered from the pipe reader thread exactly like local model deltas.
    """

    def __init__(self, send_event):
        self._send_event = send_event
        self._lock = threading.Lock()
        self._pending = {}
        self._invalidation = None
        self._sequence = 0

    def bind_question(self):
        return _PipeBinding()

    def watch_binding(self, binding, token):
        """Cancel the watched token when the host invalidates this playback."""
        def invalidated():
            token.cancel()
        with self._lock:
            self._invalidation = invalidated
        def remove():
            with self._lock:
                if self._invalidation is invalidated:
                    self._invalidation = None
        return remove

    def host_action(self, packet):
        """Deliver one host answer action; called on the pipe reader thread."""
        action = packet.get('action')
        request = packet.get('request')
        if action not in ('answer_delta', 'answer_done', 'answer_error',
                          'answer_invalidated') or type(request) is not int:
            raise ValueError('unknown study voice host action')
        if action == 'answer_invalidated':
            with self._lock:
                callback = self._invalidation
            if callback is not None:
                callback()
            return
        with self._lock:
            entry = self._pending.get(request)
        if entry is None:
            return
        if action == 'answer_delta':
            text = packet.get('text')
            if not isinstance(text, str) or len(text) > 4096:
                raise ValueError('invalid host answer delta')
            callback = entry.get('on_delta')
            if callback is not None:
                callback({'text': text})
        else:
            entry['verdict'] = (action, packet)
            entry['done'].set()

    def ask(self, text, *, session_id, binding, cancellation_token=None,
            on_delta=None, record_history=True, **kwargs):
        if not isinstance(text, str) or not text.strip():
            raise ValueError('voice question text required')
        done = threading.Event()
        with self._lock:
            self._sequence += 1
            request = self._sequence
            self._pending[request] = {'done': done, 'verdict': None,
                                      'on_delta': on_delta, 'invalidation': None}
        def cancelled():
            self._send_event({'event': 'answer_cancel', 'request': request})
            done.set()
        unregister = None
        if cancellation_token is not None:
            unregister = cancellation_token.register(cancelled)
        self._send_event({'event': 'answer_request', 'request': request,
                          'text': text, 'record_history': bool(record_history)})
        try:
            if not done.wait(300):
                raise RuntimeError('host answer did not complete')
        finally:
            with self._lock:
                entry = self._pending.pop(request, None)
            if unregister is not None:
                unregister()
        if entry is None:
            raise RuntimeError('host answer entry missing')
        action, packet = entry['verdict'] or ('answer_error', {'reason': 'cancelled'})
        if action == 'answer_error':
            raise RuntimeError('voice answer failed: ' + str(packet.get('reason')))
        return {'text': packet.get('text'), 'status': 'completed'}


async def run_session(config, input_stream, emit):
    from extensions.companion.pipecat_voice import build_sapi_study_worker, run_microphone
    from extensions.companion.sapi_playback import DirectSapiPlayback
    settings = require_configuration(config)
    initial = observation(config['observation'])
    if not initial.valid:
        raise ValueError('valid learning observation required')
    stop = asyncio.Event()
    closed = threading.Event()
    mailbox = {'observation': None, 'error': None, 'controls': deque()}
    mailbox_lock = threading.Lock()

    def receive():
        try:
            while True:
                line = input_stream.readline(8_000_001)
                if not line:
                    break
                if len(line) > 8_000_000 or not line.endswith('\n'):
                    raise ValueError('voice observation exceeds pipe limit')
                packet = json.loads(line)
                if packet.get('action') in ('stop','pause','revoke'):
                    break
                if packet.get('action') == 'discuss':
                    with mailbox_lock:
                        mailbox['controls'].append({'action':'discuss', 'packet':packet})
                    continue
                if packet.get('action') in ('answer_delta', 'answer_done',
                                            'answer_error', 'answer_invalidated'):
                    service.host_action(packet)
                    continue
                if packet.get('action') in ('text_begin', 'text_end'):
                    if type(packet.get('request')) is not int or packet['request'] <= 0:
                        raise ValueError('positive voice control request required')
                    with mailbox_lock:
                        if len(mailbox['controls']) >= 8:
                            raise ValueError('voice control queue exceeded')
                        mailbox['controls'].append(packet)
                    continue
                if packet.get('action') != 'observe':
                    raise ValueError('unknown study voice control')
                latest = observation(packet['observation'])
                if latest.target != initial.target or not latest.valid:
                    raise RuntimeError('study voice target changed or became invalid')
                with mailbox_lock:
                    mailbox['observation'] = latest
        except Exception as error:
            with mailbox_lock:
                mailbox['error'] = error
        finally:
            closed.set()

    def playback_config(role_id):
        require_configuration(config)
        if role_id != config['role_id']:
            raise PermissionError('study voice role changed')
        return {'python':sys.executable, 'root':str(Path(config['root']).resolve()),
                'voice_name':settings['voice']['tts_voice'], 'voice_capability':config['selected']['voice'],
                'capabilities':config['capabilities']}

    writing = threading.Lock()
    def send_event(packet):
        with writing:
            emit(packet)
    service = PipeQuestionService(send_event)
    playback = DirectSapiPlayback(Path(config['runtime_directory'])/'segments', playback_config)
    threading.Thread(target=receive, name='sumika-voice-control', daemon=True).start()
    running = turn = None
    try:
        if closed.is_set():
            with mailbox_lock:
                if mailbox['error'] is not None:
                    raise mailbox['error']
            return
        worker, turn = build_sapi_study_worker(model_path=config['model'], question_service=service,
            asr_provider=config['selected']['asr']['provider'],
            playback=playback, role_id=config['role_id'], approved=True,
            on_event=lambda name, detail: send_event({'event':name, **detail}),
            on_delta=lambda value: send_event({'event':'delta', **value}))
        # Model loading is synchronous; an owner withdrawal during loading must
        # still prevent opening a device once the factory returns.
        require_configuration(config)
        with mailbox_lock:
            if mailbox['error'] is not None:
                raise mailbox['error']
            latest, mailbox['observation'] = mailbox['observation'], None
        if closed.is_set():
            return
        if latest is not None:
            if latest.target != initial.target or not latest.valid:
                raise RuntimeError('study voice target changed or became invalid')
        running = asyncio.create_task(run_microphone(worker, approved=True,
            device=settings['voice']['input_device'], stop_event=stop,
            on_started=lambda: send_event({'event':'listening', 'target':initial.target})))
        while not closed.is_set() and not running.done():
            require_configuration(config)
            with mailbox_lock:
                latest, mailbox['observation'] = mailbox['observation'], None
                failure = mailbox['error']
                controls = list(mailbox['controls'])
                mailbox['controls'].clear()
            if failure is not None:
                raise failure
            for control in controls:
                if control['action'] == 'text_begin':
                    await turn.begin_text_question()
                    send_event({'event':'control_ack', 'request':control['request']})
                elif control['action'] == 'text_end':
                    await turn.end_text_question()
                    send_event({'event':'control_ack', 'request':control['request']})
                elif control['action'] == 'discuss':
                    text = control['packet'].get('text')
                    if not isinstance(text, str) or not text.strip() or len(text) > 500:
                        raise ValueError('bounded discussion text required')
                    token = turn.start_discussion(text)
                    if token is None:
                        send_event({'event':'discuss_rejected',
                                    'request':control['packet'].get('request')})
                    else:
                        send_event({'event':'discuss_started',
                                    'request':control['packet'].get('request'), 'turn':token})
                else:
                    raise ValueError('unknown study voice control')
            await asyncio.sleep(0.05)
        with mailbox_lock:
            if mailbox['error'] is not None:
                raise mailbox['error']
        if running is not None and running.done():
            await running
    finally:
        closed.set()
        stop.set()
        try:
            if running is not None:
                await running
            elif turn is not None:
                await turn.cleanup()
        finally:
            await asyncio.to_thread(playback.close)


def main():
    writing = threading.Lock()
    def emit(packet):
        with writing:
            print(json.dumps(packet), flush=True)
    try:
        line = sys.stdin.readline(8_000_001)
        if len(line) > 8_000_000 or not line.endswith('\n'):
            raise ValueError('bounded voice configuration required')
        asyncio.run(run_session(json.loads(line), sys.stdin, emit))
        return 0
    except Exception as error:
        emit({'event':'error', 'reason':type(error).__name__, 'fatal':True})
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
