"""Isolated voice-runtime worker; only bounded transcripts cross the parent pipe."""
from dataclasses import asdict
import json
import sys
import threading
import os

from .application_audio import ApplicationAudioTrack
from extensions.capabilities import CapabilityStore


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
        track = ApplicationAudioTrack.configured(helper=config['helper'],
            process_id=config['process_id'], creation_time=config['creation'],
            model_path=config['model'], target=config['target'], approved=True,
            on_transcript=observation,
            provider=config.get('asr', {}).get('provider', 'vosk'),
            media_time_seconds=config.get('media_time_seconds'),
            playback_rate=config.get('playback_rate', 1.0))
        # Load native dependencies before the blocking stdin owner watcher.
        if config.get('asr', {}).get('provider') == 'sherpa-onnx-sensevoice':
            track.prepare()
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


if __name__ == '__main__':
    raise SystemExit(run(sys.stdin, sys.stdout))
