"""Stop a real owned workbench during a native shell tool; inspect restart.

No cloud model, daily profile, or user task. This measures current behavior,
and does not label forced process termination as graceful cancellation.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'tests_next'), str(ROOT/'tools')]
from p2_fixture import ModelFixture
from verify_dsh_recovery import prompt, snapshot
from sumika_next.daily import default_home
from sumika_next.runtime_ownership import process_identity
from ui.workbench import WorkbenchController


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--queued', action='store_true')
    args = parser.parse_args()
    base = ROOT/'.sumika-next'/('active-stop-'+uuid.uuid4().hex)
    data, work = base/'data', base/'work'
    work.mkdir(parents=True)
    previous = os.environ.get('SUMIKA_DATA_DIR')
    os.environ['SUMIKA_DATA_DIR'] = str(data)
    controller = WorkbenchController(ROOT)
    child = None
    report = {'passed': False, 'cloud_calls': 0, 'checks': {},
              'queued_scenario': args.queued,
              'boundary': 'Forced stop and restart of owned fixtures; not graceful draining or concurrent-submission acceptance'}
    try:
        home = default_home(ROOT)
        home.mkdir(parents=True)
        with ModelFixture() as model:
            (home/'.env').write_text('DEEPSEEK_API_KEY=local-fixture-not-secret\n', encoding='utf8')
            (home/'cordis.patch.yml').write_text(json.dumps([
                {'id': 'session-title-llm', 'disabled': True},
                {'id': 'session-telemetry-otel', 'disabled': True},
                {'id': 'llm-deepseek', 'config': {'baseURL': model.url}},
            ]), encoding='utf8')
            model.recipe = [('pwsh', {'command': "$PID | Set-Content -LiteralPath 'child.pid'; Start-Sleep -Seconds 45; 'late' | Set-Content -LiteralPath 'late.txt'",
                                      'description': 'Owned active-stop fixture', 'timeoutMs': 60000})]
            controller.start()
            adapter = controller.adapter
            sid = 'active-shell-stop'
            adapter._rpc('session/create', {'sessionId': sid, 'cwd': str(work)})
            prompt(adapter, sid, 'Run the isolated active-stop fixture.')
            deadline = time.monotonic()+30
            marker = work/'child.pid'
            while not marker.exists():
                if time.monotonic() >= deadline:
                    raise RuntimeError('native shell did not start')
                time.sleep(.1)
            pid = int(marker.read_text(encoding='utf-8-sig').strip())
            identity = process_identity(pid)
            if identity is None:
                raise RuntimeError('native shell ended before test')
            child = (pid, identity)
            report['checks']['owned_shell_observed_running'] = True
            queued_text = 'Queued task must survive shutdown without automatic execution.'
            if args.queued:
                prompt(adapter, sid, queued_text)
                control = adapter.stream('session/control', {}, timeout=10)
                try:
                    initial = next(control)
                finally:
                    control.close()
                assert initial['type'] == 'baseline'
                assert queued_text in json.dumps(initial['value']['queues'].get(sid, []))
                report['checks']['queued_prompt_observed_before_stop'] = True
            count = len(model.requests)
            report['stop'] = controller.stop()
            deadline = time.monotonic()+8
            while process_identity(pid) == identity and time.monotonic() < deadline:
                time.sleep(.1)
            report['checks']['active_shell_exited'] = process_identity(pid) != identity
            report['checks']['late_write_absent'] = not (work/'late.txt').exists()
            controller.start()
            restored = snapshot(controller.adapter, sid)
            page = controller.adapter._rpc('session/page', {'address': {'kind': 'session', 'sessionId': sid},
                                                           'throughSeq': restored['cursor']})
            (base/'restored-page.json').write_text(json.dumps(page, indent=2), encoding='utf8')
            time.sleep(1)
            report['checks']['no_model_replay_on_restart'] = len(model.requests) == count
            report['checks']['original_prompt_preserved'] = 'Run the isolated active-stop fixture.' in json.dumps(page)
            events = [r.get('event', {}) for r in page['records']]
            report['checks']['native_interrupted_outcome'] = any(e.get('type') == 'turn/end' and
                e.get('data', {}).get('reason', {}).get('kind') == 'interrupted' for e in events)
            report['checks']['tool_outcome_unknown'] = 'Its outcome is unknown' in json.dumps(page)
            if args.queued:
                control = controller.adapter.stream('session/control', {}, timeout=10)
                try:
                    current = next(control)
                finally:
                    control.close()
                (base/'restored-control.json').write_text(json.dumps(current, indent=2), encoding='utf8')
                report['checks']['queued_text_preserved'] = queued_text in json.dumps(page) + json.dumps(current)
                report['queued_after_restart'] = len(current['value']['queues'].get(sid, []))
                report['checks']['queue_still_pending'] = report['queued_after_restart'] == 1
            report['restored_running'] = next(s['running'] for s in controller.adapter.list_sessions() if s['sessionId'] == sid)
            controller.stop()
            report['passed'] = all(report['checks'].values())
    finally:
        try:
            controller.stop()
            if child and process_identity(child[0]) == child[1]:
                report['orphan_fixture_cleanup'] = subprocess.run(['taskkill','/PID',str(child[0]),'/F'],capture_output=True).returncode
        finally:
            if previous is None:
                os.environ.pop('SUMIKA_DATA_DIR', None)
            else:
                os.environ['SUMIKA_DATA_DIR'] = previous
            (base/'report.json').write_text(json.dumps(report, indent=2), encoding='utf8')
            print('ARTIFACT', base, json.dumps(report), flush=True)


if __name__ == '__main__':
    main()
