"""Actual EXE launch/reuse/conflict acceptance with an isolated data directory."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('product', type=Path)
    args = parser.parse_args()
    product = args.product.resolve(strict=True)
    # Verify using the installed product, including when no source checkout or
    # host Python exists in a clean Windows guest.
    sys.path.insert(0, str(product))
    from ui.bridge_probe import probe
    from sumika_next.runtime_ownership import process_identity
    base = product.parent/('exe-startup-'+uuid.uuid4().hex)
    base.mkdir()
    data = base/'personal data'
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    report = {'passed': False, 'checks': {}, 'scope': 'Actual EXE using current Windows host; no model calls'}
    identity = None

    def launch(label, target_port):
        result = subprocess.run([str(product/'Sumika.exe'), '-NoBrowser', '-Port', str(target_port),
                                 '-DataDirectory', str(data)], cwd=product, capture_output=True,
                                text=True, encoding='utf8', errors='replace', timeout=100)
        (base/(label+'.txt')).write_text(result.stdout+'\n'+result.stderr, encoding='utf8')
        return result.returncode

    try:
        for label in ('first', 'reuse'):
            code = launch(label, port)
            # Capture a verifiable owned instance even if launcher exit reporting fails.
            matched = probe(product, data/'role-model-settings.json', port) == 0
            if matched:
                with opener.open(f'http://127.0.0.1:{port}/api/instance') as response:
                    current = json.load(response)
                if identity is not None:
                    assert current == identity, 'relaunch replaced the instance'
                identity = current
            assert code == 0 and matched, (label, code, matched)
            report['checks'][label] = True

        class ForeignHandler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{"kind":"foreign-server"}')

        foreign = ThreadingHTTPServer(('127.0.0.1', 0), ForeignHandler)
        thread = threading.Thread(target=foreign.serve_forever, daemon=True)
        thread.start()
        try:
            assert launch('foreign-port', foreign.server_port) != 0
            with opener.open(f'http://127.0.0.1:{foreign.server_port}/') as response:
                assert response.status == 200
            report['checks']['foreign_http200_rejected_and_preserved'] = True
        finally:
            foreign.shutdown()
            foreign.server_close()
            thread.join()
        # Exercise the shipped authenticated lifecycle, not merely taskkill.
        with opener.open(f'http://127.0.0.1:{port}/api/manage/session', timeout=10) as response:
            token = json.load(response)['csrf']
        request = urllib.request.Request(f'http://127.0.0.1:{port}/api/lifecycle/shutdown',
            data=b'{}', headers={'Content-Type': 'application/json', 'X-Sumika-CSRF': token})
        with opener.open(request, timeout=15) as response:
            assert json.load(response) == {'stopping': True}
        deadline = time.monotonic() + 15
        while process_identity(identity['pid']) == identity['creation']:
            assert time.monotonic() < deadline, 'packaged bridge acknowledged stop but remained alive'
            time.sleep(.2)
        report['checks']['authenticated_shutdown_and_process_exit'] = True
        report['test_bridge_stopped'] = True
        report['passed'] = True
    finally:
        if identity is not None and process_identity(identity['pid']) == identity['creation']:
            result = subprocess.run(['taskkill', '/PID', str(identity['pid']), '/F'], capture_output=True)
            report['test_bridge_stopped'] = result.returncode == 0
            report['emergency_cleanup_required'] = True
        (base/'report.json').write_text(json.dumps(report, indent=2), encoding='utf8')
        print('ARTIFACT', base, json.dumps(report), flush=True)


if __name__ == '__main__':
    main()
