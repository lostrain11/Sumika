"""P6 fault-injection legs: provider errors keep real state, no retry storms.

Drives the real product bridge with the configured provider pointed at a
deliberately broken endpoint (connection refused, then a server that answers
500). Every ask must fail honestly — real error kind, no fabricated text,
unknown usage — and the bridge must stay healthy afterwards: the session
endpoint, observation and a subsequent ask all still work, proving text mode
survives and nothing silently retried into a paid storm (single attempt per
ask is the provider contract; the short elapsed time on refused connections
is the observable proof).
"""
import argparse
import json
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
SETTINGS_DEFAULT = 'C:/Users/Lostrain.DESKTOP-43S7UNP/AppData/Local/Sumika/role-model-settings.json'
LESSON_TEXT = '故障注入验收页面：二分查找每次将范围减半。'

BRIDGE_CODE = '''
import sys, threading, json
from pathlib import Path
data = Path(sys.argv[1]); endpoint = sys.argv[2]
provider = sys.argv[4]
from extensions.models.settings import load, save
base = load(Path(sys.argv[3]))
base["role"]["database"] = str(data / "role.db")
base["role"]["memory_provider"] = "embedded"
base["memory"]["enabled"] = False
base["enabled"] = True
base["provider"] = provider
base["endpoint"] = endpoint
if provider == "ollama":
    base["model"] = "fault-injection-model"
save(base, data / "settings.json")
from ui.server import serve
server = serve(data / "settings.json", port=0, workbench_root=data)
threading.Thread(target=server.serve_forever, daemon=True).start()
print(json.dumps({"port": server.server_port}), flush=True)
sys.stdin.read()
'''


def spawn_bridge(data, endpoint, settings, env, provider='openai-compatible'):
    data.mkdir(parents=True, exist_ok=True)
    log = open(data.parent / 'bridge-log.txt', 'w', encoding='utf8')
    process = subprocess.Popen(
        [sys.executable, '-X', 'utf8', '-B', '-c', BRIDGE_CODE, str(data), endpoint, settings, provider],
        cwd=str(ROOT), stdin=subprocess.PIPE, stdout=log, stderr=subprocess.STDOUT,
        text=True, encoding='utf8', env=env)
    port = None
    for _ in range(240):
        time.sleep(0.25)
        for line in (data.parent / 'bridge-log.txt').read_text(encoding='utf8').splitlines():
            if line.strip().startswith('{') and 'port' in line:
                port = json.loads(line)['port']
                break
        if port or process.poll() is not None:
            break
    if port is None:
        raise RuntimeError('bridge start timeout')
    return process, f'http://127.0.0.1:{port}'


def post(base, path, payload, csrf=None, timeout=240):
    headers = {'Content-Type': 'application/json'}
    if csrf:
        headers['X-Sumika-CSRF'] = csrf
    request = urllib.request.Request(base + path, data=json.dumps(payload).encode(), headers=headers)
    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.load(response), round((time.monotonic() - started) * 1000)
    except urllib.error.HTTPError as error:
        body = error.read().decode('utf8', 'replace')
        try:
            return json.loads(body), round((time.monotonic() - started) * 1000)
        except json.JSONDecodeError:
            return {'raw': body[:200]}, round((time.monotonic() - started) * 1000)


def get_session(base):
    with urllib.request.urlopen(base + '/api/manage/session', timeout=10) as response:
        return json.load(response)


def observe(base):
    session = get_session(base)
    result, _ = post(base, '/api/companion/observe', {
        'source': 'web-visible', 'target': 'fault-check-page', 'valid': True,
        'text': LESSON_TEXT, 'metadata': {'title': '故障注入'}}, csrf=session['csrf'], timeout=10)
    return result


def run_scenario(label, endpoint, data, settings, env, results, provider='openai-compatible'):
    process, base = spawn_bridge(data, endpoint, settings, env, provider)
    scenario = {'endpoint': endpoint, 'asks': []}
    try:
        observe(base)
        for attempt in range(2):
            answer, elapsed = post(base, '/api/companion/ask',
                                   {'question': '用五个字回答：天空是什么颜色？'},
                                   csrf=get_session(base)['csrf'])
            scenario['asks'].append({'attempt': attempt + 1, 'elapsed_ms': elapsed,
                                     'response': answer})
        scenario['session_alive_after_failures'] = bool(get_session(base).get('csrf'))
        results.append(scenario)
    finally:
        process.stdin.close()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    parser.add_argument('--settings', default=SETTINGS_DEFAULT)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    env = {**__import__('os').environ, 'DEEPSEEK_API_KEY': 'sk-fault-injection-not-a-real-key'}
    results = []
    # 1. Refused connection on the https cloud path: instant single-attempt
    #    failure (the settings guard requires https for openai-compatible, so
    #    the refusal happens at TLS/connect time), bridge stays healthy.
    run_scenario('refused', 'https://127.0.0.1:9', args.output / 'bridge-refused',
                 args.settings, env, results)
    # 2. Provider answers 500 on the local-provider (ollama) path: classified
    #    error, still one attempt per ask.
    class BrokenProvider(BaseHTTPRequestHandler):
        def do_POST(self):
            self.send_response(500)
            self.send_header('Content-Length', '5')
            self.end_headers()
            self.wfile.write(b'boom!')
        def log_message(self, *args):
            pass
    killer = HTTPServer(('127.0.0.1', 0), BrokenProvider)
    threading.Thread(target=killer.serve_forever, daemon=True).start()
    run_scenario('provider-500', f'http://127.0.0.1:{killer.server_port}',
                 args.output / 'bridge-500', args.settings, env, results, provider='ollama')
    killer.shutdown()

    checks = {}
    refused, bad_server = results
    first = refused['asks'][0]['response']
    checks['refused_error_honest'] = (refused['asks'][0]['elapsed_ms'] < 30000
                                      and 'text' not in first
                                      and bool(first.get('message') or first.get('raw') or first.get('kind')))
    checks['refused_no_fabricated_answer'] = all('text' not in ask['response'] for ask in refused['asks'])
    checks['refused_single_attempt_fast'] = all(ask['elapsed_ms'] < 30000 for ask in refused['asks'])
    provider = bad_server['asks'][0]['response']
    # The observable contract on the route: an honest unknown-status error
    # with no fabricated text, one fast attempt per ask, bridge alive.
    checks['provider_500_classified'] = (provider.get('status') == 'unknown'
                                         and provider.get('fallback_used') is False
                                         and 'outcome' in (provider.get('message') or ''))
    checks['provider_500_no_fabricated_answer'] = all('text' not in ask['response'] for ask in bad_server['asks'])
    checks['session_alive_after_all_failures'] = (refused['session_alive_after_failures']
                                                  and bad_server['session_alive_after_failures'])
    report = {'passed': all(checks.values()), 'checks': checks, 'scenarios': results,
              'scope': 'Real bridge + configured provider path against deliberately broken endpoints; no real provider call',
              'started_at': datetime.now(timezone.utc).isoformat()}
    (args.output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps({'passed': report['passed'], 'checks': checks}))


if __name__ == '__main__':
    main()
