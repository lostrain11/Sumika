"""Isolated voice-runtime worker; only bounded transcripts cross the parent pipe."""
from dataclasses import asdict
from base64 import b64decode
import json
import sys
import threading
import os

from .application_audio import (
    ApplicationAudioTrack, PipePcmCapture, SegmentedApplicationAudioTrack,
    SileroSpeechDetector)
from .audio_providers import SenseVoicePcmProvider, VoskPcmProvider
from extensions.capabilities import CapabilityStore

_module_probe = os.environ.get("SUMIKA_BROWSER_AUDIO_CHILD_LOG")
if _module_probe:
    with open(_module_probe, "a", encoding="utf8") as _out:
        _out.write(f"[import] worker={__file__} pid={os.getpid()}" + "\n")


def snapshot_media_identity(value):
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError('media identity must be an object')
    encoded = json.dumps(value, allow_nan=False)
    if len(encoded) > 4096:
        raise ValueError('media identity exceeds budget')
    return json.loads(encoded)


def require_asr(config):
    selected = config.get('asr')
    if not isinstance(selected, dict) or selected.get('provider') not in ('vosk', 'sherpa-onnx-sensevoice'):
        raise PermissionError('selected application ASR required')
    store = CapabilityStore(config['capabilities'])
    try:
        if store.resolve('asr') != selected:
            raise PermissionError('application ASR configuration changed')
    finally:
        store.close()


def build_track(config, observation):
    """Construct the recognizer for the configured source; no fallback."""
    provider_name = config.get('asr', {}).get('provider', 'vosk')
    model_path = config['model']
    if config.get('source') == 'pipe':
        capture = PipePcmCapture()
        if provider_name == 'sherpa-onnx-sensevoice':
            return SegmentedApplicationAudioTrack(capture, SenseVoicePcmProvider(model_path),
                target=config['target'], on_transcript=observation,
                speech_detector=SileroSpeechDetector())
        return ApplicationAudioTrack(capture, VoskPcmProvider(model_path),
            target=config['target'], on_transcript=observation)
    track = ApplicationAudioTrack.configured(helper=config['helper'],
        process_id=config['process_id'], creation_time=config['creation'],
        model_path=model_path, target=config['target'], approved=True,
        on_transcript=observation, provider=provider_name,
        media_time_seconds=config.get('media_time_seconds'),
        playback_rate=config.get('playback_rate', 1.0))
    return track


def run(input_stream, output_stream):
    diagnostic = None
    if os.environ.get('SUMIKA_ASR_STACK_REPORT'):
        import faulthandler
        diagnostic = open(os.environ['SUMIKA_ASR_STACK_REPORT'], 'w', encoding='utf8')
        faulthandler.dump_traceback_later(8, repeat=True, file=diagnostic)
    stop = threading.Event()
    writing = threading.Lock()
    track = None
    def emit(value):
        with writing:
            output_stream.write(json.dumps(value) + '\n')
            output_stream.flush()
    try:
        line = input_stream.readline(16001)
        if not line.endswith('\n') or len(line) > 16000:
            raise ValueError('bounded worker configuration required')
        config = json.loads(line)
        if config.get('consent') is not True:
            raise PermissionError('explicit application audio consent required')
        require_asr(config)
        media_identity = snapshot_media_identity(config.get('media_identity'))
        def observation(bundle):
            if stop.is_set():
                return
            require_asr(config)
            value = asdict(bundle)
            if media_identity is not None:
                value['metadata']['media_identity'] = snapshot_media_identity(media_identity)
            value['observed_at'] = bundle.observed_at.isoformat()
            emit({'observation': value})
        track = build_track(config, observation)
        # Load native dependencies before the blocking stdin owner watcher.
        if config.get('asr', {}).get('provider') == 'sherpa-onnx-sensevoice':
            track.prepare()
        if config.get('source') == 'pipe':
            run_pipe(input_stream, track, stop, emit, config)
            return 0
        def owner_closed():
            # Any subsequent input or EOF revokes this worker's entire session.
            input_stream.read(1)
            stop.set()
        threading.Thread(target=owner_closed, daemon=True).start()
        if stop.is_set():
            return 0
        track.start()
        require_asr(config)
        if not stop.is_set():
            emit({'status': 'running', 'target': config['target']})
        while not stop.wait(0.1):
            require_asr(config)
            state = track.status()
            if state['state'] != 'recording':
                reason = state.get('error')
                emit({'error': 'application_capture_failed',
                      'reason': reason[:128] if isinstance(reason, str) else None,
                      'progress': {key: state.get(key) for key in
                          ('capture_seconds', 'decoded_seconds', 'pending_segments', 'decode_elapsed_seconds')}})
                return 1
        return 0
    except Exception as error:
        if not stop.is_set():
            emit({'error': type(error).__name__})
        return 1
    finally:
        stop.set()
        if track is not None:
            track.stop()
        if diagnostic is not None:
            faulthandler.cancel_dump_traceback_later()
            diagnostic.close()


def run_pipe(input_stream, track, stop, emit, config):
    """Feed relayed browser tab PCM into the recognizer until stop or EOF.

    Each line is one bounded base64 packet; any gap, malformed packet or EOF
    stops the whole track instead of silently dropping tutorial speech.
    """
    diagnostic = os.environ.get('SUMIKA_BROWSER_AUDIO_CHILD_LOG')
    def note(message):
        if diagnostic:
            with open(diagnostic, 'a', encoding='utf8') as out:
                out.write(f'[run_pipe] {message}\n')
        else:
            # The stderr redirect lands in the same diagnostic file.
            print(f'[run_pipe] {message}', file=sys.stderr, flush=True)
    note(f'start interpreter={sys.executable} worker={__file__} env_log={bool(diagnostic)}')
    track.start()
    require_asr(config)
    emit({'status': 'running', 'target': config['target']})
    try:
        while not stop.is_set():
            line = input_stream.readline(8001)
            if not line:
                note('stdin eof')
                stop.set()
                break
            if len(line) > 8000 or not line.endswith('\n'):
                note(f'oversized line {len(line)}')
                raise ValueError('bounded browser audio packet required')
            packet = json.loads(line)
            action = packet.get('action')
            if action == 'stop':
                note('stop action')
                stop.set()
                break
            if action is not None:
                note(f'unknown action {action}')
                raise ValueError('unknown browser audio control')
            pcm = b64decode(packet.get('pcm', ''), validate=True)
            if len(pcm) > 64000 or len(pcm) % 2:
                note(f'bad packet size {len(pcm)}')
                raise ValueError('bounded 16kHz mono PCM required')
            track.capture.feed(pcm)
        note('clean exit')
        return 0
    except Exception as error:
        note(f'exception {type(error).__name__}: {error}')
        raise


if __name__ == '__main__':
    raise SystemExit(run(sys.stdin, sys.stdout))
