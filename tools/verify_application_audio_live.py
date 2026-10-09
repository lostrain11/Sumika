"""Bounded real process-audio acceptance; PCM is measured in memory only."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from extensions.companion.application_audio import ApplicationAudioTrack
from extensions.companion.audio_providers import VoskPcmProvider
from extensions.desktop.process_audio import ProcessAudioCapture
from extensions.desktop.window_targets import list_window_targets


def bridge_acceptance(args, window):
    """Exercise product HTTP admission, worker pipe, fusion and withdrawal."""
    import os
    from urllib.request import Request, urlopen
    from extensions.models.settings import example, save
    from extensions.capabilities import CapabilityStore
    from ui.server import serve, BUILTIN_ROLES

    root = args.product_root.resolve()
    os.environ['SUMIKA_DESKTOP_PYTHON'] = str(root/'runtime/desktop/python.exe')
    os.environ['SUMIKA_VOICE_PYTHON'] = str(
        args.voice_python.resolve(strict=True) if args.voice_python else root/'runtime/voice/python.exe')
    os.environ['SUMIKA_PROCESS_AUDIO_HELPER'] = str(args.helper.resolve())
    settings = example(BUILTIN_ROLES/'sampleA', args.output/'memory.sqlite3')
    settings['enabled'] = False
    settings['memory']['enabled'] = False
    settings['voice']['enabled'] = True
    settings['voice']['asr_model'] = str(
        args.sensevoice_model.resolve() if args.sensevoice_model else args.model.resolve())
    save(settings, args.output/'settings.json')
    database = args.output/'capabilities.sqlite3'
    store = CapabilityStore(database)
    selected_provider = 'sherpa-onnx-sensevoice' if args.sensevoice_model else 'vosk'
    store.configure('asr', selected_provider)
    store.close()
    server = serve(args.output/'settings.json', port=0, capability_database=database,
        workbench_root=args.output/'workbench', schedule_directory=args.output/'schedule')
    threading.Thread(target=server.serve_forever, daemon=True).start()
    bridge = server.sumika_bridge
    origin = f'http://127.0.0.1:{server.server_port}'
    with urlopen(origin+'/api/manage/session') as response:
        token = json.load(response)['csrf']
    def post(path, value):
        request = Request(origin+path, data=json.dumps(value).encode('utf8'), method='POST',
            headers={'Content-Type':'application/json', 'X-Sumika-CSRF':token})
        try:
            with urlopen(request, timeout=45) as response:
                return json.load(response)
        except Exception as error:
            # Keep the bounded bridge reason in the acceptance report. Do not
            # persist response bodies beyond the short error string.
            body = getattr(error, 'read', lambda: b'')()
            try:
                detail = json.loads(body.decode('utf8')).get('error', '')
            except Exception:
                detail = ''
            raise RuntimeError(f'bridge request failed: {type(error).__name__}:{str(detail)[:256]}') from error
    report = {'passed': False, 'scope': 'Real Bilibili WGC + product HTTP audio admission '
              '+ ApplicationAudioProcess/worker + ContextFusion + withdrawal; no model/microphone',
              'target': window, 'transcripts': [], 'raw_audio_saved': False,
              'provider': selected_provider, 'voice_python': os.environ['SUMIKA_VOICE_PYTHON']}
    def context_status():
        current = bridge._companion.latest
        visual = bridge._fusion.current()
        return {'perception': bridge._perception.status(),
                'latest_present': current is not None,
                'latest_valid': current.valid if current is not None else None,
                'fusion_present': visual is not None,
                'fusion_valid': visual.valid if visual is not None else None}
    try:
        post('/api/companion/perception', dict(action='start', consent=True,
            handle=window['handle'], process_id=window['process_id'],
            process_creation=window['process_creation']))
        deadline = time.monotonic()+20
        while time.monotonic() < deadline:
            current = bridge._companion.latest
            if current is not None and current.valid:
                break
            time.sleep(.2)
        else:
            raise RuntimeError('product perception did not provide a valid frame')
        report['capture'] = {'valid': current.valid, 'source': current.source,
                             'text_chars': len(current.text), 'image_available': bool(current.image)}
        report['start'] = post('/api/companion/audio', dict(action='start', consent=True,
            process_id=window['process_id'], process_creation=window['process_creation']))
        print('READY', flush=True)
        deadline = time.monotonic()+args.seconds
        seen = set()
        while time.monotonic() < deadline:
            state = bridge._application_audio.status()
            if state['status'] != 'running':
                report['worker_failure'] = state
                raise RuntimeError('product audio worker stopped unexpectedly')
            current = bridge._companion.latest
            if current is not None:
                for item in current.metadata.get('application_audio', []):
                    identity = (item['observed_at'], item['text'])
                    if identity not in seen:
                        seen.add(identity)
                        report['transcripts'].append(item)
                if report['transcripts']:
                    report['fused_reference_present'] = 'Application audio reference' in current.text
            time.sleep(.1)
        report['stop'] = post('/api/companion/audio', {'action':'stop'})
        report['context_after_audio_stop'] = context_status()
        current = bridge._companion.latest
        report['audio_cleared'] = (current is not None and current.valid
            and not current.metadata.get('application_audio')
            and 'Application audio reference' not in current.text)
        time.sleep(.5)
        current = bridge._companion.latest
        report['context_after_settle'] = context_status()
        # Retaining a valid visual is required; disappearance is a failure,
        # rather than evidence that audio was successfully removed.
        report['late_audio_absent'] = (current is not None and current.valid
            and not current.metadata.get('application_audio'))
        post('/api/companion/revoke', {})
        report['all_revoked'] = (bridge._companion.latest is None
            and not bridge._perception.status()['alive']
            and not bridge._application_audio.status()['alive'])
        report['passed'] = (bool(report['transcripts']) and report.get('fused_reference_present')
            and report['stop']['status'] == 'stopped' and not report['stop']['alive']
            and report['audio_cleared'] and report['late_audio_absent'] and report['all_revoked'])
    except Exception as error:
        report['failure'] = {'type': type(error).__name__}
        # Preserve bounded supervisor diagnostics, not an arbitrary HTTP body
        # (which can contain learning content or configuration values).
        report['audio_status'] = bridge._application_audio.status()
        report['context_on_failure'] = context_status()
        raise
    finally:
        server.shutdown()
        server.server_close()
        (args.output/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')
        print(json.dumps({'passed':report['passed'], 'report':str(args.output/'report.json')}), flush=True)
    if not report['passed']:
        raise RuntimeError('product audio/fusion/withdrawal acceptance failed')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--title', required=True, help='Unique title of owned test browser')
    parser.add_argument('--helper', type=Path, required=True)
    parser.add_argument('--model', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--seconds', type=int, default=38)
    parser.add_argument('--sensevoice-model', type=Path)
    parser.add_argument('--asr-site', type=Path)
    parser.add_argument('--voice-python', type=Path,
                        help='Explicit isolated candidate runtime for product worker acceptance')
    parser.add_argument('--product-root', type=Path,
                        help='Use product HTTP bridge and packaged capability runtimes')
    args = parser.parse_args()
    if not 1 <= args.seconds <= 60:
        raise ValueError('bounded duration required')
    args.output.mkdir(parents=True, exist_ok=False)
    deadline = time.monotonic() + 10
    while True:
        windows = [w for w in list_window_targets()['windows'] if args.title in w['title']]
        if len(windows) == 1 or time.monotonic() >= deadline:
            break
        time.sleep(.2)
    if len(windows) != 1:
        raise RuntimeError('owned test window missing or ambiguous')
    window = windows[0]
    if args.product_root is not None:
        return bridge_acceptance(args, window)
    capture = ProcessAudioCapture(args.helper, process_id=window['process_id'],
        creation_time=window['process_creation'], approved=True)
    transcripts = []
    stats = {'bytes': 0, 'nonzero_samples': 0, 'peak': 0}
    lock = threading.Lock()
    comparison = []
    buffer = bytearray()
    sensevoice = None
    if args.sensevoice_model:
        if args.product_root:
            raise ValueError('comparison is an isolated probe, not product acceptance')
        if args.asr_site:
            sys.path.insert(0, str(args.asr_site.resolve(strict=True)))
        from extensions.companion.audio_providers import SenseVoicePcmProvider
        sensevoice = SenseVoicePcmProvider(args.sensevoice_model)
        sensevoice.load_model()
        comparison_vosk = VoskPcmProvider(args.model)
        comparison_vosk.load_model()

    def compare(pcm, offset):
        # One bounded memory segment is sent to both engines, not two captures.
        import threading
        row = {'end_offset_seconds': offset, 'duration_seconds': len(pcm)/32000}
        for name, provider in (('vosk', comparison_vosk), ('sensevoice', sensevoice)):
            started = time.monotonic()
            row[name] = {'text': provider._recognize(pcm, 16000, threading.Event()),
                         'decode_seconds': time.monotonic()-started}
        comparison.append(row)

    class MeasuredTrack(ApplicationAudioTrack):
        def _pcm(self, pcm):
            import numpy as np
            values = np.frombuffer(pcm, dtype='<i2').astype('int32')
            with lock:
                stats['bytes'] += len(pcm)
                stats['nonzero_samples'] += int(np.count_nonzero(values))
                stats['peak'] = max(stats['peak'], int(np.abs(values).max(initial=0)))
            super()._pcm(pcm)
            if sensevoice is not None:
                buffer.extend(pcm)
                while len(buffer) >= 160000:
                    segment = bytes(buffer[:160000])
                    del buffer[:160000]
                    compare(segment, stats['bytes']/32000-len(buffer)/32000)

    def received(bundle):
        item = asdict(bundle)
        item['observed_at'] = bundle.observed_at.isoformat()
        with lock:
            transcripts.append(item)

    track = MeasuredTrack(capture, VoskPcmProvider(args.model),
        target=f"window:{window['handle']}:pid:{window['process_id']}", on_transcript=received)
    report = {'passed': False, 'scope': 'Actual process loopback and local ASR; no microphone/model call/audio persistence',
              'target': window, 'transcripts': transcripts, 'pcm': stats,
              'same_pcm_comparison': comparison, 'raw_audio_saved': False}
    try:
        track.start()
        print('READY', flush=True)
        deadline = time.monotonic() + args.seconds
        while time.monotonic() < deadline:
            if track.status()['state'] != 'recording':
                raise RuntimeError('capture stopped unexpectedly')
            time.sleep(.2)
        report['capture_status'] = track.status()
        report['passed'] = stats['nonzero_samples'] > 0 and bool(transcripts)
    finally:
        track.stop()
        buffer.clear()
        report['stopped'] = track.status()['state'] == 'stopped'
        (args.output/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')
        print(json.dumps({'passed': report['passed'], 'report': str(args.output/'report.json')}), flush=True)
    if not report['passed']:
        raise RuntimeError('no actual speech transcript; inspect report')


if __name__ == '__main__':
    main()
