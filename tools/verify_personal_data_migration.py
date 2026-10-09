"""Exercise packaged migration with isolated personal data; retain all evidence."""
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import time
import urllib.request
import urllib.error
import uuid


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('product', type=Path)
    args = parser.parse_args()
    product = args.product.resolve(strict=True)
    base = product.parent / ('data-migration-' + uuid.uuid4().hex)
    local = base / 'local'; local.mkdir(parents=True)
    source = local / 'Sumika'; source.mkdir()
    marker = source / 'migration-marker.txt'; marker.write_text('retained evidence')
    target = base / 'moved data'
    env = dict(os.environ, LOCALAPPDATA=str(local), SUMIKA_DATA_DIR=str(source))
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
    origin = f'http://127.0.0.1:{port}'
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    def request(path, payload=None, csrf=None):
        headers = {'Content-Type':'application/json'}
        if csrf: headers['X-Sumika-CSRF'] = csrf
        req = urllib.request.Request(origin+path, data=None if payload is None else json.dumps(payload).encode(), headers=headers)
        with opener.open(req, timeout=10) as response: return json.load(response)
    report = {'passed':False, 'scope':'isolated current-host migration; no user data or model requests'}
    try:
        launched = subprocess.run([str(product/'Sumika.exe'), '-NoBrowser', '-Port', str(port)],
            cwd=product, env=env, capture_output=True, timeout=100)
        (base/'launch.txt').write_bytes(launched.stdout+launched.stderr)
        assert launched.returncode == 0
        csrf = request('/api/manage/session')['csrf']
        try:
            request('/api/manage/personal-data/migrate', {'destination':str(target),'confirmed':True})
            raise AssertionError('unauthenticated migration accepted')
        except urllib.error.HTTPError as error:
            assert error.code == 403
            error.close()
        try:
            request('/api/manage/personal-data/migrate', {'destination':str(target)}, csrf)
            raise AssertionError('unconfirmed migration accepted')
        except urllib.error.HTTPError as error:
            assert error.code == 400
            error.close()
        prepared = request('/api/manage/personal-data/migrate', {'destination':str(target),'confirmed':True}, csrf)
        job = Path(prepared['job'])
        assert json.loads(job.read_text())['state'] == 'waiting_for_exit'
        assert request('/api/lifecycle/shutdown', {}, csrf)['stopping'] is True
        deadline = time.monotonic()+150
        while time.monotonic() < deadline:
            state = json.loads(job.read_text())
            assert state['state'] != 'failed_no_automatic_retry', state
            try:
                data = request('/api/manage/personal-data')
                if Path(data['directory']) == target: break
            except (OSError, urllib.error.URLError): pass
            time.sleep(.5)
        else: raise AssertionError('migrated server did not return')
        assert marker.read_text() == (target/marker.name).read_text()
        assert Path(json.loads((local/'Sumika-location.json').read_text())['directory']) == target
        assert state['state'] == 'complete'
        assert Path(state['result']['snapshot']).is_dir()
        report.update(passed=True, source_retained=True, snapshot_verified=True,
            restarted_on_same_port=True, unauthorized_rejected=True, confirmation_required=True)
    finally:
        try:
            token = request('/api/manage/session')['csrf']
            request('/api/lifecycle/shutdown', {}, token)
            report['shutdown_requested'] = True
        except OSError: pass
        (base/'report.json').write_text(json.dumps(report, indent=2))
        print(base, json.dumps(report), flush=True)


if __name__ == '__main__':
    main()
