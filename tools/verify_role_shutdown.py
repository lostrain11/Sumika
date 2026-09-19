"""Isolated real role HTTP transport/drain/recovery; deterministic local responses."""
import json
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import socket
import subprocess
import sys
import threading
import queue
import time
import urllib.request
import urllib.error
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from extensions.models.settings import example, save
from extensions.roles.roles import import_card
from ui.server import serve


def process_probe(base):
    """Crash only an owned fixture process while provider HTTP is outstanding."""
    entered, release = threading.Event(), threading.Event()
    calls = []

    class HoldingModel(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            calls.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
            entered.set()
            release.wait(30)
            self.close_connection = True

    model = ThreadingHTTPServer(('127.0.0.1', 0), HoldingModel)
    threading.Thread(target=model.serve_forever, daemon=True).start()
    settings_path = base / 'settings.json'
    settings = json.loads(settings_path.read_text(encoding='utf8'))
    settings['endpoint'] = f'http://127.0.0.1:{model.server_port}'
    save(settings, settings_path)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    process = None

    def launch():
        child = subprocess.Popen([sys.executable, '-B', str(Path(__file__).resolve()), '--child', str(settings_path)],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding='utf8',
            creationflags=subprocess.CREATE_NO_WINDOW)
        lines = queue.Queue()
        threading.Thread(target=lambda: lines.put(child.stdout.readline()), daemon=True).start()
        try:
            port = json.loads(lines.get(timeout=20))['port']
            return child, port
        except BaseException:
            child.kill()
            child.wait(timeout=10)
            raise

    def request(port, route, payload=None, token=None):
        req = urllib.request.Request(f'http://127.0.0.1:{port}{route}',
            data=None if payload is None else json.dumps(payload).encode(),
            headers={'Content-Type': 'application/json', **({'X-Sumika-CSRF': token} if token else {})})
        with opener.open(req, timeout=15) as response:
            return json.load(response)

    try:
        process, port = launch()
        first_pid = process.pid
        token = request(port, '/api/manage/session')['csrf']
        with ThreadPoolExecutor(1) as pool:
            response = pool.submit(request, port, '/api/role/chat',
                                   {'message': 'crash transport probe', 'session': 'crash-probe'}, token)
            try:
                assert entered.wait(10)
                before = request(port, '/api/role/chat/history?session=crash-probe')['messages']
                assert len(before) == 1 and before[0]['state'] == 'unknown'
            finally:
                # Simulate abrupt OS exit, using only the child handle just created.
                process.kill()
                process.wait(timeout=10)
                release.set()
            try:
                response.result(timeout=10)
                raise AssertionError('crashed request unexpectedly completed')
            except (OSError, urllib.error.URLError):
                pass
        process, port = launch()
        history = request(port, '/api/role/chat/history?session=crash-probe')['messages']
        assert history == before, 'unknown history changed during process restart'
        time.sleep(.5)
        assert len(calls) == 1, 'restart replayed request'
        token = request(port, '/api/manage/session')['csrf']
        assert request(port, '/api/lifecycle/shutdown', {}, token) == {'stopping': True}
        assert process.wait(timeout=10) == 0
        return {'passed': True, 'first_pid': first_pid, 'restart_pid': process.pid,
                'provider_requests': len(calls), 'unknown_history_unchanged': True,
                'normal_exit_after_restart': True}
    finally:
        release.set()
        if process is not None and process.poll() is None:
            process.kill()
            process.wait(timeout=10)
        model.shutdown()
        model.server_close()


def run_case(base, failure):
    base.mkdir()
    entered, release = threading.Event(), threading.Event()
    requests = []

    class Model(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            assert self.path == '/api/chat'
            requests.append(payload)
            entered.set()
            if not release.wait(20) or failure:
                self.connection.shutdown(socket.SHUT_RDWR)
                self.connection.close()
                return
            body = json.dumps({'message': {'content': 'Shutdown transport reply'}, 'done': True,
                               'prompt_eval_count': 10, 'eval_count': 5}).encode()
            self.send_response(200)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    model = ThreadingHTTPServer(('127.0.0.1', 0), Model)
    model_thread = threading.Thread(target=model.serve_forever, daemon=True)
    model_thread.start()
    card = base / 'card.json'
    card.write_text(json.dumps({'spec': 'chara_card_v2', 'data': {
        'name': 'Shutdown probe', 'description': 'Local transport acceptance character.'}}), encoding='utf8')
    role = import_card(card, base / 'roles', 'shutdown-probe')
    settings = example(role, base / 'memory.sqlite3')
    settings.update(enabled=True, provider='ollama', model='local-fixture',
                    endpoint=f'http://127.0.0.1:{model.server_port}', timeout_seconds=25)
    settings_path = base / 'settings.json'
    save(settings, settings_path)
    server = serve(settings_path, port=0, capability_database=base / 'capabilities.db',
                   schedule_directory=base / 'schedules')
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def request(server, route, payload=None, token=None):
        headers = {'Content-Type': 'application/json'}
        if token:
            headers['X-Sumika-CSRF'] = token
        req = urllib.request.Request(f'http://127.0.0.1:{server.server_port}{route}',
            data=None if payload is None else json.dumps(payload).encode(), headers=headers)
        try:
            response = opener.open(req, timeout=30)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            return response.status, json.load(response)

    restarted = None
    try:
        token = request(server, '/api/manage/session')[1]['csrf']
        with ThreadPoolExecutor(2) as pool:
            chat = pool.submit(request, server, '/api/role/chat',
                               {'message': 'admitted transport probe', 'session': 'shutdown-probe'}, token)
            try:
                assert entered.wait(10), 'provider was not called'
                before = server.sumika_bridge.transcript('shutdown-probe')
                assert len(before) == 1 and before[0]['state'] == 'unknown'
                stopping = pool.submit(request, server, '/api/lifecycle/shutdown', {}, token)
                assert server.sumika_bridge._shutdown_requested.wait(5)
                assert not stopping.done(), 'shutdown acknowledged before model settled'
                assert request(server, '/api/role/chat', {'message': 'must not send'}, token)[0] == 503
                assert len(requests) == 1
            finally:
                release.set()
            chat_status, result = chat.result(timeout=15)
            assert stopping.result(timeout=15) == (200, {'stopping': True})
        thread.join(timeout=5)
        assert not thread.is_alive()
        server.server_close()
        restarted = serve(settings_path, port=0, capability_database=base / 'capabilities.db',
                          schedule_directory=base / 'schedules')
        history = restarted.sumika_bridge.transcript('shutdown-probe')
        assert history[0]['id'] == before[0]['id']
        if failure:
            assert chat_status == 502 and result['status'] == 'unknown' and result['fallback_used'] is False
            assert len(history) == 1 and history[0]['state'] == 'unknown'
        else:
            assert chat_status == 200 and result['text'] == 'Shutdown transport reply'
            assert len(history) == 2 and all(row['state'] == 'completed' for row in history)
        assert len(requests) == 1, 'automatic replay occurred'
        return {'passed': True, 'provider_requests': len(requests), 'http_status': chat_status,
                'restored_state': history[0]['state'], 'stable_message_id': True,
                'restart_without_replay': True, 'new_write_rejected': True}
    finally:
        release.set()
        server.shutdown()
        server.server_close()
        if restarted:
            restarted.server_close()
        model.shutdown()
        model.server_close()
        model_thread.join(timeout=5)


def main():
    base = ROOT / '.sumika-next' / ('role-shutdown-' + uuid.uuid4().hex)
    base.mkdir()
    report = {'passed': False, 'boundary': 'Real RoleChat/Ollama HTTP/SQLite and bridge; deterministic local model, no DSH or voice process.'}
    try:
        for failure in (False, True):
            name = 'disconnect' if failure else 'completed'
            report[name] = run_case(base / name, failure)
        report['abrupt_process_restart'] = process_probe(base / 'disconnect')
        report['passed'] = True
    finally:
        (base / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf8')
        print('ARTIFACT', base)


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--child':
        settings_path = Path(sys.argv[2]).resolve(strict=True)
        server = serve(settings_path, port=0, capability_database=settings_path.parent / 'capabilities.db',
                       schedule_directory=settings_path.parent / 'schedules')
        print(json.dumps({'port': server.server_port}), flush=True)
        try:
            server.serve_forever()
        finally:
            server.server_close()
    else:
        main()
