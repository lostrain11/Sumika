"""Start the assembled bridge with its bundled Python and isolated personal data."""
import argparse
import json
import os
from pathlib import Path
import queue
import subprocess
import threading
import urllib.request
import uuid


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('product', type=Path)
    args = parser.parse_args()
    product = args.product.resolve(strict=True)
    evidence = product.parent/('startup-'+uuid.uuid4().hex)
    personal = evidence/'personal data'
    evidence.mkdir()
    report = {'passed': False, 'scope': 'bundled Python bridge startup, not EXE launch', 'checks': {}}
    env = dict(os.environ, SUMIKA_DATA_DIR=str(personal), PYTHONPATH='C:/must-not-use',
               PYTHONHOME='C:/must-not-use')
    env.pop('SUMIKA_ROLE_STORE', None)
    script = (
        'import json; from ui.server import serve; '
        's=serve(port=0); print(json.dumps({"port":s.server_port}),flush=True); s.serve_forever()'
    )
    process = None
    try:
        process = subprocess.Popen([str(product/'runtime/python/python.exe'), '-B', '-u', '-c', script],
                                   cwd=product, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   text=True, encoding='utf8', creationflags=subprocess.CREATE_NO_WINDOW)
        output = queue.Queue()
        def read():
            for line in process.stdout:
                output.put(line)
            output.put(None)
        threading.Thread(target=read, daemon=True).start()
        line = output.get(timeout=45)
        if line is None:
            raise RuntimeError('Bridge failed: ' + process.stderr.read()[-3000:])
        port = json.loads(line)['port']
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        for route in ('/', '/api/state'):
            with opener.open(f'http://127.0.0.1:{port}{route}', timeout=30) as response:
                body = response.read()
                assert response.status == 200
                if route == '/api/state':
                    assert isinstance(json.loads(body), dict)
                else:
                    assert b'<html' in body.lower()
        assert (personal/'role-model-settings.json').is_file()
        assert (personal/'role-conversations.sqlite3').is_file()
        assert not (product/'.sumika-next').exists()
        report['checks'] = {'bundled_python_imports_product': True, 'html_and_state': True,
                            'private_data_created_outside_install': True}
        report['passed'] = True
    finally:
        if process is not None:
            if process.poll() is None:
                process.terminate()
            process.wait(timeout=15)
            process.stdout.close()
            process.stderr.close()
            report['owned_bridge_stopped'] = process.poll() is not None
        (evidence/'report.json').write_text(json.dumps(report, indent=2), encoding='utf8')
        print('ARTIFACT', evidence, json.dumps(report))


if __name__ == '__main__':
    main()
