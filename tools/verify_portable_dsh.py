"""Copy a physical DSH runtime and verify native tools in an isolated profile.

Uses the host Python/Node and deterministic loopback model. This is runtime
relocation acceptance, not complete product or clean-machine acceptance.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'tests_next'), str(ROOT/'tools')]
from p2_fixture import ModelFixture
from sumika_next.dsh import Dsh
from verify_dsh_recovery import prompt, finish


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('runtime', type=Path)
    args = parser.parse_args()
    source = args.runtime.resolve(strict=True)
    # Refuse links before copying, rather than expanding pnpm junction graphs.
    for directory, dirs, files in os.walk(source, followlinks=False):
        for name in dirs + files:
            path = Path(directory)/name
            if path.is_symlink() or path.is_junction():
                raise ValueError('runtime must have a physical dependency layout')
    base = ROOT/'.sumika-next/package'/('runtime-relocation-'+uuid.uuid4().hex)
    product, home, work = base/'product', base/'profile', base/'work'
    home.mkdir(parents=True)
    work.mkdir()
    report = {'passed': False, 'scope': 'DSH runtime relocation with host Python/Node',
              'external_model_calls': 0, 'checks': {}}
    adapter = None
    try:
        shutil.copytree(source, product/'runtime/dsh')
        subprocess.run(['git', 'init', '-q', str(work)], check=True)
        with ModelFixture() as model:
            (home/'.env').write_text('DEEPSEEK_API_KEY=relocation-fixture-not-a-secret\n', encoding='utf8')
            (home/'cordis.patch.yml').write_text(json.dumps([
                {'id': 'session-title-llm', 'disabled': True},
                {'id': 'llm-deepseek', 'config': {'baseURL': model.url}},
                {'id': 'session-telemetry-otel', 'disabled': True},
            ]), encoding='utf8')
            model.recipe = [
                ('write', {'file_path': 'value.txt', 'content': '41\n'}),
                ('edit', {'file_path': 'value.txt', 'old_string': '41', 'new_string': '42'}),
                ('read', {'file_path': 'value.txt'}),
                ('pwsh', {'command': "if ((Get-Content value.txt -Raw).Trim() -ne '42') { exit 1 }; 'passed' | Set-Content verified.txt",
                          'description': 'Check isolated fixture edit', 'timeoutMs': 5000}),
            ]
            adapter = Dsh(product, home)
            adapter.start()
            report['checks']['manifest_and_native_start'] = True
            sid = 'relocated-runtime'
            adapter._rpc('session/create', {'sessionId': sid, 'cwd': str(work)})
            stream = adapter.stream('session/follow', {'address': {'kind': 'session', 'sessionId': sid}}, timeout=60)
            try:
                next(stream)
                prompt(adapter, sid, 'Perform the local fixture sequence.')
                frames = finish(stream)
            finally:
                stream.close()
            events = [f['event'] for f in frames if f.get('event')]
            assert events[-1]['data']['reason']['kind'] == 'completed'
            assert (work/'value.txt').read_text().strip() == '42'
            assert (work/'verified.txt').read_text(encoding='utf-8-sig').strip() == 'passed'
            calls = [e['data']['name'] for e in events if e['type'] == 'tool/call']
            assert calls == ['write', 'edit', 'read', 'pwsh'], calls
            report['checks']['native_file_edit_and_terminal'] = True
            report['model_requests'] = len(model.requests)
            adapter.close()
            assert adapter.process.poll() is not None
            report['checks']['owned_process_stopped'] = True
            report['passed'] = True
    finally:
        try:
            if adapter is not None:
                adapter.close()
        finally:
            (base/'report.json').write_text(json.dumps(report, indent=2), encoding='utf8')
            print('ARTIFACT', base, json.dumps(report), flush=True)


if __name__ == '__main__':
    main()
