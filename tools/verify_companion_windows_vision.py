"""Owned Edge WGC -> companion HTTP -> TLS vision fixture acceptance."""
import base64
from datetime import datetime
import io
import json
import os
from pathlib import Path
import sqlite3
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from PIL import Image
import numpy as np
from pywinauto import Desktop
from extensions.models.settings import example, save
from ui.server import serve


def verify_question_loop(base, window, openssl, *, model_delay=2.5, observe_seconds=0):
    received = []
    errors = []
    active_request, release_request = threading.Event(), threading.Event()
    target = f'window:{window.handle}:pid:{window.process_id()}'

    class Fixture(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            try:
                assert self.path == '/chat/completions'
                assert self.headers.get('Authorization') == 'Bearer local-fixture-only'
                payload = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                assert payload['model'] == 'vision-fixture'
                parts = payload['messages'][-1]['content']
                assert [p['type'] for p in parts] == ['text', 'image_url']
                prompt = parts[0]['text']
                assert '[观察目标] '+target in prompt
                assert '[观察来源] window-visual' in prompt
                assert '[用户问题]' in prompt and '[参考内容开始]' in prompt
                encoded = parts[1]['image_url']['url']
                prefix = 'data:image/jpeg;base64,'
                assert encoded.startswith(prefix)
                with Image.open(io.BytesIO(base64.b64decode(encoded[len(prefix):], validate=True))) as bitmap:
                    assert bitmap.format == 'JPEG'
                    pixels = np.asarray(bitmap.convert('RGB')).astype(np.int16)
                    width, height = bitmap.size
                assert 100 < width <= 1600 and 100 < height <= 1600
                red = (pixels[:, :, 0] > 170) & (pixels[:, :, 1] < 90) & (pixels[:, :, 2] < 90)
                green = (pixels[:, :, 1] > 150) & (pixels[:, :, 0] < 90) & (pixels[:, :, 2] < 90)
                assert int(red.sum()) > 1000 and int(green.sum()) > 1000, 'wrong or blank lesson frame'
                received.append({'width': width, 'height': height, 'red_pixels': int(red.sum()),
                                 'green_pixels': int(green.sum()), 'target_bound': True})
                if payload['stream']:
                    self.send_response(200)
                    self.send_header('Content-Type', 'text/event-stream')
                    self.send_header('Connection', 'close')
                    self.end_headers()
                    self.close_connection = True
                    for fragment in ('本地流式', '夹具回复。'):
                        value = {'choices':[{'delta':{'content':fragment}}]}
                        self.wfile.write(('data: '+json.dumps(value,ensure_ascii=False)+'\n\n').encode())
                        self.wfile.flush()
                        time.sleep(.6)
                    self.wfile.write(b'data: {"choices": [{"delta": {}, "finish_reason": "stop"}]}\n\ndata: [DONE]\n\n')
                    self.wfile.flush()
                    return
                time.sleep(model_delay)
                if len(received) == 3:
                    active_request.set()
                    assert release_request.wait(10), 'active request fixture timed out'
                response = {'choices': [{'message': {'content': '这是本地格式夹具回复，未验证图像理解质量。'},
                                         'finish_reason': 'stop'}], 'model': 'vision-fixture'}
                code = 200
            except Exception as error:
                errors.append(f'{type(error).__name__}: {error}')
                response, code = {'error': 'fixture assertion failed'}, 400
            body = json.dumps(response).encode()
            self.send_response(code)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, ssl.SSLError):
                if not release_request.is_set():
                    raise

    bridge = model = None
    with tempfile.TemporaryDirectory(prefix='sumika-vision-tls-') as certificate_directory:
        certificate = Path(certificate_directory)/'certificate.pem'
        key = Path(certificate_directory)/'key.pem'
        subprocess.run([openssl, 'req', '-x509', '-newkey', 'rsa:2048', '-nodes',
            '-keyout', str(key), '-out', str(certificate), '-days', '1', '-subj', '/CN=127.0.0.1',
            '-addext', 'subjectAltName=IP:127.0.0.1'], check=True, capture_output=True)
        server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        server_context.load_cert_chain(certificate, key)
        client_context = ssl.create_default_context(cafile=str(certificate))
        assert client_context.check_hostname and client_context.verify_mode == ssl.CERT_REQUIRED
        model = ThreadingHTTPServer(('127.0.0.1', 0), Fixture)
        model.socket = server_context.wrap_socket(model.socket, server_side=True)
        threading.Thread(target=model.serve_forever, daemon=True).start()
        try:
            settings = example(ROOT/'extensions/roles/defaults/sampleA', base/'memory.sqlite3')
            settings.update(enabled=True, model='vision-fixture', provider='openai-compatible',
                            endpoint=f'https://127.0.0.1:{model.server_port}', key_env='SUMIKA_VISION_FIXTURE_KEY')
            settings['multimodal']['enabled'] = True
            settings['memory'].update(auto_extract=True, model_proposals=True)
            path = base/'settings.json'
            save(settings, path)
            bridge = serve(path, port=0, capability_database=base/'capabilities.sqlite3',
                           schedule_directory=base/'schedules')
            threading.Thread(target=bridge.serve_forever, daemon=True).start()
            url = f'http://127.0.0.1:{bridge.server_port}'
            with urllib.request.urlopen(url+'/api/manage/session') as response:
                token = json.load(response)['csrf']

            def post(route, payload):
                request = urllib.request.Request(url+route, data=json.dumps(payload).encode(),
                    headers={'Content-Type': 'application/json', 'X-Sumika-CSRF': token})
                with urllib.request.urlopen(request, timeout=30) as response:
                    return json.load(response)

            # urllib caches its opener, so supply scoped fixture trust explicitly.
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}),
                urllib.request.HTTPSHandler(context=client_context))
            with patch.dict(os.environ, {'SUMIKA_VISION_FIXTURE_KEY': 'local-fixture-only'}), \
                    patch('urllib.request._opener', opener):
                observed = post('/api/companion/capture', {'consent': True,
                    'handle': window.handle, 'process_id': window.process_id()})
                assert observed['valid'] and observed['target'] == target, observed
                started = post('/api/companion/perception', {'action': 'start', 'consent': True,
                    'handle': window.handle, 'process_id': window.process_id()})
                assert started['alive'], started
                deadline = time.monotonic()+15
                while time.monotonic() < deadline:
                    state = post('/api/companion/perception', {'action': 'status'})
                    if state['observations'] >= 2: break
                    assert state['status'] != 'error', state
                    time.sleep(.2)
                assert state['observations'] >= 2, state
                stability_started = time.monotonic()
                previous_count = state['observations']
                while time.monotonic()-stability_started < observe_seconds:
                    time.sleep(max(0, min(5, observe_seconds-(time.monotonic()-stability_started))))
                    state = post('/api/companion/perception', {'action': 'status'})
                    assert state['status'] == 'running' and state['alive'], state
                    assert state['observations'] > previous_count, state
                    previous_count = state['observations']
                stable_observations = state['observations']
                answer = post('/api/companion/ask', {'question': '请解释图中的两个颜色区域。'})
                after_answer = post('/api/companion/perception', {'action': 'status'})
                assert after_answer['observations'] > state['observations'], 'no concurrent observation during model request'
                observations_before_answer = state['observations']
                assert answer.get('status') != 'stale_response', answer
                assert answer['images_used'] == 1 and answer['observation_target'] == target, answer
                assert answer['observation_source'] == 'window-visual'
                assert answer['memory_proposals'] == 0 and not answer['auto_extracted']
                assert answer['role_tools'] == 0 and answer['task_intent'] is None
                assert len(received) == 1 and not errors, errors
                request = urllib.request.Request(url+'/api/companion/ask-stream',
                    data=json.dumps({'question':'流式解释图像'}).encode(),
                    headers={'Content-Type':'application/json', 'X-Sumika-CSRF':token})
                stream_started = time.monotonic()
                with urllib.request.urlopen(request, timeout=10) as response:
                    first_event = json.loads(response.readline())
                    first_delta_seconds = time.monotonic()-stream_started
                    stream_events = [first_event] + [json.loads(line) for line in response]
                assert first_event['event'] == 'delta' and first_delta_seconds < 1, stream_events
                assert ''.join(e['text'] for e in stream_events if e['event']=='delta') == '本地流式夹具回复。'
                assert stream_events[-1]['event']=='complete' and stream_events[-1]['images_used']==1, stream_events
                paused = post('/api/companion/perception', {'action': 'pause'})
                assert paused['status'] == 'paused' and not paused['alive'], paused
                resumed = post('/api/companion/perception', {'action': 'resume'})
                assert resumed['alive'], resumed
                deadline = time.monotonic()+15
                while time.monotonic() < deadline:
                    state = post('/api/companion/perception', {'action': 'status'})
                    if state['observations'] >= 1: break
                    assert state['status'] != 'error', state
                    time.sleep(.2)
                assert state['observations'] >= 1, state
                late_answers, late_errors = [], []
                def active_question():
                    try:
                        late_answers.append(post('/api/companion/ask', {'question':'撤销测试问题'}))
                    except Exception as error:
                        late_errors.append(type(error).__name__)
                active_thread = threading.Thread(target=active_question)
                active_thread.start()
                try:
                    assert active_request.wait(8), 'model request never became active'
                    revoke_started = time.monotonic()
                    assert post('/api/companion/revoke', {})['status'] == 'revoked'
                    revoke_seconds = time.monotonic()-revoke_started
                    active_thread.join(2)
                    assert not active_thread.is_alive(), 'companion request did not return after cancellation'
                finally:
                    release_request.set()
                    active_thread.join(10)
                assert not active_thread.is_alive() and not late_errors, late_errors
                assert late_answers[0]['status'] == 'stale_response' and 'text' not in late_answers[0], late_answers
                stopped = post('/api/companion/perception', {'action': 'status'})
                assert stopped['status'] == 'stopped' and not stopped['alive'], stopped
                try:
                    post('/api/companion/ask', {'question': '继续解释刚才的画面。'})
                except urllib.error.HTTPError as error:
                    assert error.code == 400
                    assert 'no observation' in json.load(error)['error']
                else:
                    raise AssertionError('revoked visual context was still usable')
                assert len(received) == 3, 'revoke caused a provider call'
            with sqlite3.connect(base/'memory.sqlite3') as database:
                assert database.execute('SELECT count(*) FROM memories').fetchone()[0] == 0
            with sqlite3.connect(base/'role-conversations.sqlite3') as database:
                persisted = '\n'.join(database.iterdump())
                assert target not in persisted and 'data:image/' not in persisted
            # The browser profile can contain its own static extension icons. The
            # product capture path must not create media beside the settings DB.
            assert not any(p.suffix.lower() in ('.png', '.jpg', '.jpeg', '.webp', '.wav')
                           for p in base.iterdir() if p.is_file())
            return {'capture_ask_http': True, 'tls_certificate_and_hostname_verified': True,
                    'model_delay_seconds': model_delay,
                    'streaming_first_delta_seconds': round(first_delta_seconds,3),
                    'streaming_completed': True,
                    'continuous_duration_seconds': observe_seconds,
                    'continuous_observations': stable_observations,
                    'observations_before_answer': observations_before_answer,
                    'observations_after_answer': after_answer['observations'],
                    'model_requests': len(received), 'image_metadata': received,
                    'screen_memory_writes': 0, 'screen_chat_persistence': False,
                    'raw_frame_files': 0, 'revoke_blocks_question': True,
                    'revoke_during_active_model': True, 'revoke_seconds': round(revoke_seconds, 3),
                    'late_reply_discarded': True, 'provider_request_cancelled': True,
                    'remote_cancellation_confirmed': False,
                    'real_model_quality_verified': False, 'fixture_errors': errors}
        finally:
            if bridge is not None:
                bridge.shutdown()
                bridge.server_close()
            if model is not None:
                model.shutdown()
                model.server_close()


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--openssl', default='D:/Tools/Git/usr/bin/openssl.exe')
    parser.add_argument('--observe-seconds', type=float, default=0)
    parser.add_argument('--output-root', type=Path, default=ROOT/'.sumika-next')
    args = parser.parse_args()
    assert Path(args.openssl).is_file(), 'OpenSSL fixture tool not found'
    base = args.output_root.resolve()/('companion-vision-'+uuid.uuid4().hex)
    base.mkdir(parents=True)
    title = 'SumikaVisionFixture-'+uuid.uuid4().hex
    page = base/'lesson.html'
    page.write_text(f'''<!doctype html><meta charset="utf-8"><title>{title}</title>
<body style="background:white;font:24px Arial;padding:24px"><h1>Owned vision lesson fixture</h1>
<p>This generated page contains no user screen data.</p>
<div style="display:flex;gap:32px"><div style="width:220px;height:220px;background:#ed2020"></div>
<div style="width:220px;height:220px;background:#20d020"></div></div></body>''', encoding='utf8')
    child = subprocess.Popen(['C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
        '--user-data-dir='+str(base/'profile'), '--no-first-run', '--disable-sync',
        '--force-renderer-accessibility', '--app='+page.as_uri()],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    report = {'passed': False, 'started_at': datetime.now().astimezone().isoformat(),
              'scope': 'Owned Edge HWND -> real WGC worker -> HTTP -> TLS OpenAI-format fixture; no paid model',
              'real_model_quality_verified': False}
    window = None
    try:
        deadline = time.monotonic()+25
        while time.monotonic() < deadline:
            matches = [w for w in Desktop(backend='uia').windows() if title in w.window_text()]
            if len(matches) == 1:
                window = matches[0]
                break
            time.sleep(.2)
        assert window is not None, 'owned Edge fixture window missing'
        time.sleep(1)
        report.update(verify_question_loop(base, window, args.openssl,
                                          observe_seconds=args.observe_seconds))
        report['passed'] = True
    except Exception as error:
        report['failure'] = f'{type(error).__name__}: {error}'
        raise
    finally:
        if window is not None:
            window.close()
        try:
            child.wait(timeout=10)
        except subprocess.TimeoutExpired:
            child.terminate()
            child.wait(timeout=5)
        path = base/'report.json'
        path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf8')
        print(json.dumps({**report, 'evidence': str(path)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
