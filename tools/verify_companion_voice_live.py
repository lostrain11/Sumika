"""P6 hardware acceptance: 30+ real voice turns on real microphone and speakers.

Drives the real product bridge (ui.server.serve) with the packaged voice
interpreter and the user's actual microphone and playback device. The user
speaks; every VAD turn is recorded from the product's own event stream to
compute the frozen latency decomposition (stop-speak -> ASR done -> first
char -> first audio) plus barge-in behavior. Nothing replays audio and no
turn is fabricated: the report only counts what really happened. The
transcript texts are the user's own spoken acceptance inputs, kept in the
local report only.

Usage:
  python tools/verify_companion_voice_live.py <output-dir> [options]
  --turns N           completed turns required (default 30)
  --max-seconds N     overall watchdog (default 1500)
  --device INDEX      input device index (default: system default input)
  --model             use the configured cloud provider when its key is in
                      the environment; otherwise the reply is a local fixture
                      and the report says model latency was not measured
  --voice-python PATH packaged voice interpreter (defaults to the P8 candidate)
  --vosk-model PATH   ASR model directory
"""
import argparse
import json
import statistics
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

VOICE_PYTHON_DEFAULT = 'E:/SumikaBuild/product-candidate-20261008-s/runtime/voice/python.exe'
VOSK_DEFAULT = 'E:/Models/Speech/sumika/vosk-model-small-cn-0.22'
SETTINGS_DEFAULT = 'C:/Users/Lostrain.DESKTOP-43S7UNP/AppData/Local/Sumika/role-model-settings.json'
LESSON_TEXT = ('这是语音硬件验收页面。第一段：二分查找每次把范围减半，'
               '所以一千个有序元素最多十步就能找到目标。'
               '第二段：哈希表用键直接计算存储位置，平均查找是一步，但不保序。')

BRIDGE_CODE = '''
import sys, threading, json
from pathlib import Path
data = Path(sys.argv[1]); device = int(sys.argv[2]); vosk_model = sys.argv[3]
allow_model = sys.argv[4] == 'model'
from extensions.models.settings import load, save
base = load(Path(sys.argv[5]))
base['role']['database'] = str(data / 'role.db')
base['role']['memory_provider'] = 'embedded'
base['memory']['enabled'] = False
# Voice preflight requires an enabled model configuration even when the
# acceptance replaces the chat with a local fixture reply (mode is recorded).
base['enabled'] = True
base.setdefault('voice', {}).update({'enabled': True, 'input_device': device,
    'sample_rate': 16000, 'asr_model': vosk_model})
save(base, data / 'settings.json')
from extensions.capabilities import CapabilityStore
store = CapabilityStore(data / 'capabilities.sqlite3')
store.configure('microphone', 'sounddevice', options={'user_authorized': True})
store.configure('asr', 'vosk', options={})
store.configure('voice', 'windows-sapi', options={})
store.close()
from ui.server import serve
server = serve(data / 'settings.json', port=0, workbench_root=data,
               capability_database=data / 'capabilities.sqlite3')
if not allow_model:
    server.sumika_bridge._coordinator._service._role_chat = (
        lambda prompt, **kwargs: {'text': '这是语音验收的固定回答，用来测量本地语音链路延迟。' * 2})
threading.Thread(target=server.serve_forever, daemon=True).start()
print(json.dumps({'port': server.server_port}), flush=True)
try:
    sys.stdin.read()
finally:
    server.shutdown(); server.server_close()
'''


def http_json(base, path, payload=None, csrf=None, timeout=30):
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {'Content-Type': 'application/json'}
    if csrf:
        headers['X-Sumika-CSRF'] = csrf
    request = urllib.request.Request(base + path, data=data, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        body = error.read().decode('utf8', 'replace')[:300]
        raise RuntimeError(f'{path} -> HTTP {error.code}: {body}') from error


def pick_device(preferred):
    from extensions.desktop.audio_devices import list_input_devices
    listing = list_input_devices()
    devices = listing.get('devices') or []
    index = preferred if preferred is not None else listing.get('default_input')
    name = None
    for item in devices:
        if item.get('index') == index:
            name = item.get('name')
    if index is None:
        raise RuntimeError('no input device found: ' + json.dumps(listing, ensure_ascii=False))
    return {'index': index, 'name': name, 'devices': devices,
            'default_input': listing.get('default_input')}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    parser.add_argument('--turns', type=int, default=30)
    parser.add_argument('--max-seconds', type=int, default=1500)
    parser.add_argument('--device', type=int, default=None)
    parser.add_argument('--model', action='store_true',
                        help='use the configured cloud provider when its key is present')
    parser.add_argument('--voice-python', default=VOICE_PYTHON_DEFAULT)
    parser.add_argument('--vosk-model', default=VOSK_DEFAULT)
    parser.add_argument('--settings', default=SETTINGS_DEFAULT)
    parser.add_argument('--status-file', type=Path, default=None,
                        help='write live progress JSON here for the operator')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    device = pick_device(args.device)
    if not Path(args.voice_python).is_file():
        raise RuntimeError('voice interpreter missing: ' + args.voice_python)
    if not Path(args.vosk_model).is_dir():
        raise RuntimeError('vosk model missing: ' + args.vosk_model)

    (args.output / 'bridge-data').mkdir(parents=True, exist_ok=True)
    bridge_log = open(args.output / 'bridge-log.txt', 'w', encoding='utf8')
    bridge = subprocess.Popen(
        [sys.executable, '-X', 'utf8', '-B', '-c', BRIDGE_CODE,
         str(args.output / 'bridge-data'), str(device['index']),
         str(args.vosk_model), 'model' if args.model else 'fixture', args.settings],
        cwd=str(ROOT), stdin=subprocess.PIPE, stdout=bridge_log,
        stderr=subprocess.STDOUT,
        text=True, encoding='utf8', env={**__import__('os').environ,
                                         'SUMIKA_VOICE_PYTHON': args.voice_python,
                                         'SUMIKA_MIC_WORKER_LOG': str(args.output / 'worker-stderr.log')})
    ready = None
    for _ in range(600):
        time.sleep(0.25)
        bridge_log.flush()
        lines = (Path(args.output / 'bridge-log.txt').read_text(encoding='utf8')
                 .splitlines())
        for line in lines:
            line = line.strip()
            if line.startswith('{') and 'port' in line:
                ready = json.loads(line)
                break
        if ready is not None:
            break
        if bridge.poll() is not None:
            raise RuntimeError('bridge exited: ' + '\n'.join(lines[-15:]))
    if ready is None:
        raise RuntimeError('bridge start timeout: ' + '\n'.join(lines[-15:]))
    base = f'http://127.0.0.1:{ready["port"]}'
    try:
        session = http_json(base, '/api/manage/session')
    except BaseException as error:
        try:
            bridge.stdin.close(); bridge.wait(timeout=5)
        except Exception:
            bridge.kill()
        tail = (args.output / 'bridge-log.txt').read_text(encoding='utf8')[-1200:]
        raise RuntimeError(f'session GET failed ({error}); bridge alive='
                           f'{bridge.poll() is None}; log tail:\n{tail}') from error

    report = {'passed': False, 'scope': 'Real product bridge + packaged voice '
              'interpreter + real microphone/speakers; the user speaks real turns.',
              'mode': 'real-model' if args.model else 'fixture-reply',
              'device': {'index': device['index'], 'name': device['name']},
              'voice_interpreter': args.voice_python,
              'started_at': datetime.now(timezone.utc).isoformat(),
              'events': [], 'turns': [], 'barge_ins': [], 'errors': []}
    status_path = args.status_file or (args.output / 'status.json')

    def save_status(**extra):
        snapshot = {'turns_completed': len(report['turns']),
                    'barge_ins': len(report['barge_ins']),
                    'listening': report.get('listening', False), **extra}
        status_path.write_text(json.dumps(snapshot), encoding='utf8')

    save_status(phase='publishing observation')
    http_json(base, '/api/companion/observe', {
        'source': 'web-visible', 'target': 'voice-acceptance-page',
        'valid': True, 'text': LESSON_TEXT,
        'metadata': {'title': '语音硬件验收', 'url': 'local://voice-acceptance'},
        'observed_at': datetime.now(timezone.utc).isoformat()}, csrf=session['csrf'])

    save_status(phase='starting voice')
    http_json(base, '/api/companion/microphone', {
        'action': 'start', 'microphone_consent': True, 'playback_consent': True,
        'proactive': {'enabled': False, 'interval_seconds': 120}}, csrf=session['csrf'])

    cursor = 0
    current = None
    started = time.monotonic()
    try:
        while time.monotonic() - started < args.max_seconds:
            time.sleep(0.25)
            try:
                status = http_json(base, '/api/companion/microphone',
                                   {'action': 'status', 'after': cursor},
                                   csrf=session['csrf'])
            except (urllib.error.URLError, OSError) as error:
                report['errors'].append({'at': time.monotonic() - started,
                                         'error': type(error).__name__})
                continue
            cursor = status.get('cursor', cursor)
            for event in status.get('events') or []:
                event['_local_t'] = round(time.monotonic() - started, 3)
                report['events'].append(event)
                name = event.get('event')
                if name == 'listening':
                    report['listening'] = True
                elif name == 'user_started':
                    current = {'turn': event.get('turn'),
                               'user_started': event['_local_t'],
                               'speech_seconds': None, 'asr_ms': None,
                               'first_char_ms': None, 'first_audio_ms': None,
                               'total_ms': None, 'transcript': ''}
                    report['_open'] = True
                elif name == 'user_stopped' and current is not None:
                    current['user_stopped'] = event['_local_t']
                    current['speech_seconds'] = round(
                        event['_local_t'] - current['user_started'], 2)
                elif name == 'transcribed' and current is not None:
                    current['transcribed'] = event['_local_t']
                    current['transcript'] = (event.get('text') or '')[:200]
                    if current.get('user_stopped') is not None:
                        current['asr_ms'] = round(
                            (event['_local_t'] - current['user_stopped']) * 1000)
                elif name == 'delta' and current is not None:
                    if current.get('first_char_ms') is None and current.get('transcribed') is not None:
                        current['first_char_ms'] = round(
                            (event['_local_t'] - current['transcribed']) * 1000)
                elif name == 'playback_started' and current is not None:
                    current['playback_started'] = event['_local_t']
                    if current.get('transcribed') is not None and current.get('first_audio_ms') is None:
                        current['first_audio_ms'] = round(
                            (event['_local_t'] - current['transcribed']) * 1000)
                elif name == 'playback_ended' and current is not None:
                    current['total_ms'] = round(
                        (event['_local_t'] - current['user_started']) * 1000)
                    report['turns'].append(current)
                    current = None
                    report['_open'] = False
                elif name == 'interrupted':
                    report['barge_ins'].append({'at': event['_local_t'],
                                                'turn': event.get('turn')})
                    if current is not None:
                        current['interrupted'] = True
                        # A barge-in IS the user moving on: close the turn
                        # with the latencies observed up to the interrupt.
                        current['total_ms'] = round(
                            (event['_local_t'] - current['user_started']) * 1000)
                        report['turns'].append(current)
                        current = None
                        report['_open'] = False
                elif name in ('error', 'answer_error', 'coordinator_failed'):
                    report['errors'].append({'at': event['_local_t'],
                                             'event': name,
                                             'reason': event.get('reason') or event.get('error')})
                save_status()
            if len(report['turns']) >= args.turns and current is None:
                break
    finally:
        report['_open'] = False
        save_status(phase='stopping voice')
        try:
            http_json(base, '/api/companion/microphone',
                      {'action': 'stop'}, csrf=session['csrf'], timeout=10)
        except Exception:
            pass
        save_status(phase='closing bridge')
        bridge.stdin.close()
        try:
            bridge.wait(timeout=10)
        except subprocess.TimeoutExpired:
            bridge.kill()
        report['closed_at'] = datetime.now(timezone.utc).isoformat()

    turns = report['turns']
    completed = [t for t in turns
                 if t.get('total_ms') is not None and t.get('transcript')]
    body = completed[1:] if len(completed) > 1 else []
    def pct(values, q):
        if not values:
            return None
        ordered = sorted(values)
        return ordered[min(len(ordered) - 1, max(0, int(round(q * len(ordered) + 0.5) - 1)))]
    def lat(name, pool):
        values = [t[name] for t in pool if t.get(name) is not None]
        return {'n': len(values), 'median_ms': round(statistics.median(values)) if values else None,
                'p95_ms': pct(values, .95)}
    report['latency'] = {
        'cold_start': {k: completed[0].get(k) for k in
                       ('speech_plus_asr_ms', 'first_char_ms', 'first_audio_ms', 'total_ms')} if completed else None,
        'steady': {name: lat(name, body) for name in
                   ('speech_plus_asr_ms', 'first_char_ms', 'first_audio_ms', 'total_ms')}}
    report['model_latency_measured'] = bool(args.model)
    report['transcript_chars'] = sum(len(t['transcript']) for t in turns)
    report['empty_or_lost_turns'] = len(turns) - len(completed)
    # Audible late playback means the INTERRUPTED answer resumed audibly:
    # a playback_started (or segment_started) for a turn that had already
    # been interrupted, before that turn number is used again by a new
    # question. Streaming deltas of later answers are not late playback.
    interrupted_turns = set()
    audible_late = 0
    for event in report['events']:
        if event['event'] == 'interrupted':
            interrupted_turns.add(event.get('turn'))
        elif (event['event'] in ('playback_started', 'segment_started')
              and event.get('turn') in interrupted_turns):
            audible_late += 1
    report['late_playback_after_barge_in'] = audible_late
    # Combined speech+ASR latency: the packaged voice runtime does not yet
    # emit the stop-speech boundary, so user_started -> transcribed covers
    # the spoken sentence plus recognition (recorded as one honest figure).
    for turn in report['turns']:
        if turn.get('transcribed') is not None:
            turn['speech_plus_asr_ms'] = round(
                (turn['transcribed'] - turn['user_started']) * 1000)
    report['turns_completed'] = len(completed)
    report['passed'] = (len(completed) >= args.turns and late_playback == 0
                        and not report['errors'])
    (args.output / 'report.json').write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps({'passed': report['passed'],
                      'turns_completed': len(completed),
                      'barge_ins': len(report['barge_ins']),
                      'late_playback': late_playback,
                      'errors': report['errors'][:5],
                      'latency': report['latency']}))
    save_status(phase='done', passed=report['passed'])


if __name__ == '__main__':
    main()
