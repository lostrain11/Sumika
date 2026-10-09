"""Continuous study voice in the isolated runtime; PCM never crosses its pipe."""
import asyncio
from collections import deque
from datetime import datetime
import json
from pathlib import Path
import sys
import threading

from extensions.capabilities import CapabilityStore
from extensions.models.settings import load as load_settings
from extensions.roles.roles import load_role
from .contracts import ObservationBundle, PerceptionService
from .observation_scheduler import ObservationScheduler
from .qa import CompanionQuestionService


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


async def run_session(config, input_stream, emit):
    from extensions.companion.pipecat_voice import build_sapi_study_worker, run_microphone
    from extensions.companion.sapi_playback import DirectSapiPlayback
    from extensions.roles.chat import RoleChat
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
                if packet.get('action') in ('text_begin', 'text_end'):
                    if type(packet.get('request')) is not int or packet['request'] <= 0:
                        raise ValueError('positive voice control request required')
                    with mailbox_lock:
                        if len(mailbox['controls']) >= 2:
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

    def reply(prompt, **kwargs):
        require_configuration(config)
        return RoleChat(settings).reply(prompt, task_intent=False, memory_writes=False, **kwargs)
    service = CompanionQuestionService(reply,
        include_images=settings.get('multimodal', {}).get('enabled', False))
    service.update(initial)

    def playback_config(role_id):
        require_configuration(config)
        if role_id != config['role_id']:
            raise PermissionError('study voice role changed')
        return {'python':sys.executable, 'root':str(Path(config['root']).resolve()),
                'voice_name':settings['voice']['tts_voice'], 'voice_capability':config['selected']['voice'],
                'capabilities':config['capabilities']}
    playback = DirectSapiPlayback(Path(config['runtime_directory'])/'segments', playback_config)
    threading.Thread(target=receive, name='sumika-voice-control', daemon=True).start()
    running = turn = scheduler = None
    try:
        if closed.is_set():
            with mailbox_lock:
                if mailbox['error'] is not None:
                    raise mailbox['error']
            return
        discussion = config.get('proactive', {'enabled':True, 'interval_seconds':120})
        perception = PerceptionService(lambda target: service.latest)
        perception.select_target(initial.target)
        perception.start()
        def discuss(bundle):
            token = turn.start_discussion('请结合当前内容，用一句简短的话提出一个值得一起讨论的学习点；'
                '资料不足时不要猜测。')
            if token is not None:
                scheduler.playback_started(token)
        scheduler = ObservationScheduler(perception, on_proactive=discuss,
            on_error=lambda error: emit({'event':'error', 'reason':error['type'],
                                         'stage':'proactive_start', 'fatal':False}),
            proactive_interval=discussion['interval_seconds'], settled_seconds=3)
        # Start quietly and let the user establish the current learning context.
        scheduler.notify_user_activity(discussion['interval_seconds'])
        worker, turn = build_sapi_study_worker(model_path=config['model'], question_service=service,
            asr_provider=config['selected']['asr']['provider'],
            playback=playback, role_id=config['role_id'], approved=True,
            on_event=lambda name, detail: emit({'event':name, **detail}),
            on_delta=lambda value: emit({'event':'delta', **value}),
            observation_scheduler=scheduler)
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
            service.update(latest)
        running = asyncio.create_task(run_microphone(worker, approved=True,
            device=settings['voice']['input_device'], stop_event=stop,
            on_started=lambda: emit({'event':'listening', 'target':initial.target})))
        next_tick = asyncio.get_running_loop().time()
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
                else:
                    await turn.end_text_question()
                scheduler.notify_user_activity(discussion['interval_seconds'])
                emit({'event':'control_ack', 'request':control['request']})
            if latest is not None:
                if latest.target != initial.target or not latest.valid:
                    raise RuntimeError('study voice target changed or became invalid')
                service.update(latest)
            now = asyncio.get_running_loop().time()
            if discussion['enabled'] and now >= next_tick:
                # Suppress background analysis for the entire user turn,
                # including ASR/model generation before playback has begun.
                if turn.busy:
                    scheduler.notify_user_activity(1.1)
                scheduler.tick()
                next_tick = now + 1
            await asyncio.sleep(0.05)
        with mailbox_lock:
            if mailbox['error'] is not None:
                raise mailbox['error']
        if running is not None and running.done():
            await running
    finally:
        closed.set()
        stop.set()
        service.revoke()
        if scheduler is not None:
            scheduler.stop()
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
