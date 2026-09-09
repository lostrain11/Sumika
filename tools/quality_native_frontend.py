"""Relay only browser RPCs from production UI to an isolated acceptance Core."""
import json
import secrets
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def start_frontend(service, endpoint, stack, report):
    secret = secrets.token_hex(32)

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            if self.path != '/' or self.headers.get('X-Smoke-Token') != secret:
                self.send_error(403)
                return
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 100000:
                    raise ValueError('invalid length')
                payload = json.loads(self.rfile.read(length))
                if payload['method'] not in {'quality.browser.attach', 'quality.browser.poll', 'quality.browser.complete'}:
                    raise ValueError('unsupported method')
                result = service.rpc(payload['method'], payload.get('params', {}))
                body = json.dumps({'jsonrpc': '2.0', 'id': payload.get('id'), 'result': result}).encode()
            except Exception:
                self.send_error(400)
                return
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    server.daemon_threads = True
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    stack.callback(server.server_close)
    stack.callback(server.shutdown)
    process = subprocess.Popen(['node', str(Path(__file__).with_name('native_consultation_frontend.mjs'))],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                               text=True, encoding='utf-8', creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))

    def stop():
        try:
            output, _ = process.communicate('\n', timeout=15)
            rows = [json.loads(line) for line in output.splitlines() if line.strip()]
            if rows:
                report.update(rows[-1])
        except (subprocess.TimeoutExpired, ValueError):
            process.kill()
            process.communicate()
            report['cleanup_failed'] = True

    stack.callback(stop)
    process.stdin.write(json.dumps({'endpoint': endpoint, 'bridge': f'http://127.0.0.1:{server.server_port}/', 'token': secret}) + '\n')
    process.stdin.flush()
    ready = []
    reader = threading.Thread(target=lambda: ready.append(process.stdout.readline()), daemon=True)
    reader.start()
    reader.join(60)
    if not ready or not json.loads(ready[0]).get('ready'):
        raise RuntimeError('production-frontend-not-ready')
