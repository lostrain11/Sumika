"""Verify native DSH write confinement on owned fixtures, no cloud calls."""
import argparse
import hashlib
import json
import shutil
from pathlib import Path
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'tests_next'), str(ROOT/'tools')]
from p2_fixture import ModelFixture
from sumika_next.dsh import Dsh
from verify_dsh_recovery import prompt, finish, snapshot


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--probe-guard', action='store_true')
    parser.add_argument('--python-temp', action='store_true', help='Compare Python private temp ACL with ordinary workspace directories')
    parser.add_argument('--iteration', action='store_true', help='Exercise native multi-file edit/test/fix/restart without the narrow probe guard')
    parser.add_argument('--notice-tests', action='store_true', help='Run reviewed notice suite through native sandbox; retain fixtures')
    args = parser.parse_args()
    if sum((args.probe_guard, args.python_temp, args.iteration, args.notice_tests)) > 1:
        parser.error('select one probe mode')
    base = ROOT/'.sumika-next'/('development-sandbox-'+uuid.uuid4().hex)
    home, work = base/'profile', base/'work'
    home.mkdir(parents=True)
    work.mkdir()
    sentinel = base/'outside-workspace.txt'
    sentinel.write_text('preserve-owned-sentinel', encoding='utf8')
    report = {'passed': False, 'cloud_calls': 0, 'checks': {},
              'boundary': 'Windows native file-write confinement; not read/network isolation or a complete OS sandbox'}
    adapter = Dsh(ROOT, home)
    with ModelFixture() as model:
        (home/'.env').write_text('DEEPSEEK_API_KEY=local-fixture-not-secret\n', encoding='utf8')
        (home/'cordis.patch.yml').write_text(json.dumps([
            {'id': 'session-title-llm', 'disabled': True},
            {'id': 'session-telemetry-otel', 'disabled': True},
            {'id': 'llm-deepseek', 'config': {'baseURL': model.url}},
            {'id': 'sandbox-policy', 'config': {'mode': 'workspace-write'}},
            {'id': 'approval', 'config': {'policy': 'never'}},
            {'id': 'permission', 'config': {'defaultPreset': 'bounded-test', 'presets': {
                'bounded-test': {'sandbox': 'workspace-write', 'approval': 'never'}}}},
        ]), encoding='utf8')
        outside = str(sentinel).replace("'", "''")
        model.recipe = [
            ('write', {'file_path': 'inside.txt', 'content': 'allowed'}),
            ('pwsh', {'command': "Set-Content -LiteralPath 'inside-shell.txt' -Value 'allowed' -ErrorAction Stop",
                      'description': 'Write owned workspace fixture'}),
            ('write', {'file_path': str(sentinel), 'content': 'forbidden-fs'}),
            ('pwsh', {'command': "Set-Content -LiteralPath '"+outside+"' -Value 'forbidden-shell' -ErrorAction Stop",
                      'description': 'Verify rejection outside owned workspace'}),
            ('pwsh', {'command': "Set-Content -LiteralPath '"+outside+"' -Value 'forbidden-escalation' -ErrorAction Stop",
                      'description': 'Verify unattended escalation rejection',
                      'sandbox_permissions': 'danger-full-access', 'justification': 'Isolated rejection test'}),
        ]
        if args.probe_guard:
            module, tests = work/'module.py', work/'test_module.py'
            module.write_text('value = 1\n', encoding='utf8')
            test_body = 'import module\nassert module.value == 1\nprint("reviewed-test-ok")\n'
            tests.write_text(test_body, encoding='utf8')
            command = "& '"+sys.executable+"' -B test_module.py"
            policy = base/'review-policy.json'
            policy.write_text(json.dumps({'schema_version': 1, 'workspace': str(work.resolve()),
                'files': [module.name, tests.name], 'testCommand': command,
                'reviewedHashes': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (module, tests)}}), encoding='utf8')
            patch = home/'cordis.patch.yml'
            rows = json.loads(patch.read_text())
            rows.append({'insert': [{'id': 'sumika-probe-guard',
                'name': str(ROOT/'tools/development_probe_guard.mjs'),
                'config': {'workspace': str(work), 'policyFile': str(policy)}}]})
            patch.write_text(json.dumps(rows), encoding='utf8')
            model.recipe = [
                ('read', {'file_path': str(module)}),
                ('pwsh', {'command': command, 'description': 'Run reviewed test'}),
                ('read', {'file_path': str(policy)}),
                ('pwsh', {'command': "Set-Content unapproved.txt forbidden", 'description': 'Reject unapproved command'}),
                ('read', {'file_path': str(module)}),
                ('edit', {'file_path': str(module), 'old_string': 'value = 1', 'new_string': 'value = 2'}),
                ('pwsh', {'command': command, 'description': 'Reject execution of unreviewed code'}),
                ('write', {'file_path': str(tests), 'content': 'tamper'}),
            ]
        if args.python_temp:
            if args.probe_guard:
                raise ValueError('select one probe mode')
            probe = work/'directory_probe.py'
            probe.write_text('''import json,tempfile
from pathlib import Path
results={}
private=Path(tempfile.mkdtemp(dir=Path.cwd()))
ordinary=Path('ordinary-directory')
ordinary.mkdir()
for name,folder in [('private',private),('ordinary',ordinary)]:
    try:
        target=folder/'sentinel.txt'
        target.write_text('owned fixture',encoding='utf8')
        assert target.read_text(encoding='utf8')=='owned fixture'
        results[name]='read-write-ok'
    except PermissionError:
        results[name]='permission-denied'
Path('directory-results.json').write_text(json.dumps(results),encoding='utf8')
print(json.dumps(results))
''', encoding='utf8')
            model.recipe = [('pwsh', {'command': "& '"+sys.executable+"' -B directory_probe.py",
                                     'description': 'Compare owned workspace directory creation modes; no permission changes'})]
        if args.iteration:
            test_body = ('import unittest\nfrom presentation import describe\n'
                         'class Result(unittest.TestCase):\n'
                         '    def test_total(self):\n'
                         '        self.assertEqual(describe([2, 3]), "total=5")\n')
            (work/'test_iteration.py').write_text(test_body, encoding='utf8')
            command = "& '"+sys.executable+"' -B -m unittest test_iteration"
            model.recipe = [
                ('write', {'file_path': 'calculation.py', 'content': 'def total(values):\n    return sum(values) + 1\n'}),
                ('write', {'file_path': 'presentation.py', 'content': 'from calculation import total\ndef describe(values):\n    return "total=" + str(total(values))\n'}),
                ('pwsh', {'command': command, 'description': 'Run owned baseline test; expect failure'}),
                ('edit', {'file_path': 'calculation.py', 'old_string': 'sum(values) + 1', 'new_string': 'sum(values)'}),
                ('read', {'file_path': 'calculation.py'}),
                ('edit', {'file_path': 'calculation.py', 'old_string': 'sum(values) + 1', 'new_string': 'sum(values)'}),
                ('pwsh', {'command': command, 'description': 'Verify corrected two-module calculation'}),
                ('read', {'file_path': 'calculation.py'}),
                ('read', {'file_path': 'presentation.py'}),
            ]
            report['boundary'] = 'Deterministic native multi-file development transport and restart; not real-model intelligence or interactive approval acceptance'
        if args.notice_tests:
            selected = ['tools/audit_package_licenses.py', 'tools/verify_portable_staging.py',
                        'tests_next/test_dependency_notices.py']
            for relative in selected:
                target = work/relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT/relative, target)
            shutil.copytree(ROOT/'packaging/notices', work/'packaging/notices')
            input_hashes = {relative: hashlib.sha256((work/relative).read_bytes()).hexdigest()
                            for relative in selected}
            command = "& '"+sys.executable+"' -B -m unittest tests_next.test_dependency_notices"
            model.recipe = [('pwsh', {'command': command, 'description': 'Run reviewed notice suite with retained workspace fixtures'})]
            report['boundary'] = 'Native sandbox compatibility of unchanged reviewed suite; not real-model development acceptance'
        try:
            adapter.start()
            sid = 'native-write-confinement'
            adapter._rpc('session/create', {'sessionId': sid, 'cwd': str(work)})
            stream = adapter.stream('session/follow', {'address': {'kind': 'session', 'sessionId': sid}}, timeout=120)
            try:
                next(stream)
                prompt(adapter, sid, 'Run the synthetic confinement fixture once.')
                frames = finish(stream)
            finally:
                stream.close()
            (base/'events.json').write_text(json.dumps(frames, indent=2), encoding='utf8')
            state = snapshot(adapter, sid)
            (base/'snapshot.json').write_text(json.dumps(state, indent=2), encoding='utf8')
            results = [f['event']['data'] for f in frames if f.get('event', {}).get('type') == 'tool/result']
            by_step = {r['step']: r for r in results}
            shell_denial = json.dumps(by_step.get(4, {}))
            escalation = by_step.get(5, {}).get('message', {}).get('content', [])
            report['checks'] = {
                'all_five_tools_settled': len(results) == 5,
                'native_workspace_write': (work/'inside.txt').is_file() and (work/'inside.txt').read_text() == 'allowed',
                'shell_workspace_write': (work/'inside-shell.txt').is_file(),
                'outside_sentinel_unchanged': sentinel.read_text() == 'preserve-owned-sentinel',
                'native_fs_denial_code': by_step.get(3, {}).get('error', {}).get('code') == 'FS_SANDBOX_DENIED',
                'shell_denial_marker': '[sandbox: file access denied under workspace-write mode]' in shell_denial,
                'escalation_rejected': any(c.get('isError') and 'rejected escalating' in json.dumps(c) for c in escalation),
                'turn_completed': frames[-1]['event']['data']['reason']['kind'] == 'completed',
            }
            report['tool_results'] = results
            if args.probe_guard:
                def denied(step):
                    return 'SUMIKA_PROBE_SCOPE' in json.dumps(by_step.get(step, {}))
                report['checks'] = {
                    'all_tools_settled': len(results) == 8,
                    'approved_test_ran': 'reviewed-test-ok' in json.dumps(by_step.get(2, {})) and not denied(2),
                    'source_edit_allowed': module.read_text() == 'value = 2\n',
                    'policy_read_denied': denied(3),
                    'unapproved_command_denied': denied(4) and not (work/'unapproved.txt').exists(),
                    'unreviewed_code_execution_denied': denied(7),
                    'test_write_denied': denied(8) and tests.read_text() == test_body,
                }
            if args.python_temp:
                directories = json.loads((work/'directory-results.json').read_text(encoding='utf8'))
                report['directory_results'] = directories
                report['checks'] = {'one_native_tool': len(results) == 1,
                    'private_temp_denial_reproduced': directories['private'] == 'permission-denied',
                    'ordinary_workspace_directory_usable': directories['ordinary'] == 'read-write-ok',
                    'outside_sentinel_unchanged': sentinel.read_text() == 'preserve-owned-sentinel'}
            if args.iteration:
                from verify_self_development_live import verified_test_result
                def step_frames(step):
                    return [f for f in frames if f.get('event', {}).get('type') in ('tool/call', 'tool/result')
                            and f['event']['data'].get('step') == step]
                calls_before_restart = model.responses
                candidate_hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                    for p in work.glob('*.py')}
                adapter.close()
                adapter.start()
                recovered = snapshot(adapter, sid)
                (base/'recovered-snapshot.json').write_text(json.dumps(recovered, indent=2), encoding='utf8')
                recovered_text = json.dumps(recovered)
                call_ids = [f['event']['data']['callId'] for f in frames
                            if f.get('event', {}).get('type') == 'tool/call']
                report['checks'] = {
                    'nine_tools_settled': len(results) == 9,
                    'unread_edit_refused': by_step.get(4, {}).get('error', {}).get('code') == 'FS_STALE_VERSION',
                    'failed_test_observed': 'FAILED (failures=1)' in json.dumps(by_step.get(3, {}))
                        and not verified_test_result(step_frames(3), command, 1),
                    'corrected_test_passed': verified_test_result(step_frames(7), command, 1),
                    'immutable_test_unchanged': (work/'test_iteration.py').read_text(encoding='utf8') == test_body,
                    'source_fix_persisted': (work/'calculation.py').read_text() == 'def total(values):\n    return sum(values)\n',
                    'restart_files_unchanged': candidate_hashes == {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                                                  for p in work.glob('*.py')},
                    'restart_tool_history_preserved': len(call_ids) == 9 and all(cid in recovered_text for cid in call_ids),
                    'restart_no_model_replay': model.responses == calls_before_restart,
                    'outside_sentinel_unchanged': sentinel.read_text() == 'preserve-owned-sentinel',
                    'turn_completed': frames[-1]['event']['data']['reason']['kind'] == 'completed',
                }
            if args.notice_tests:
                from verify_self_development_live import verified_test_result
                report['checks'] = {
                    'one_native_test_call': len(results) == 1,
                    'fourteen_tests_passed': verified_test_result(frames, command, 14),
                    'reviewed_inputs_unchanged': all(hashlib.sha256((work/r).read_bytes()).hexdigest() == h
                                                   for r, h in input_hashes.items()),
                    'outside_sentinel_unchanged': sentinel.read_text() == 'preserve-owned-sentinel',
                    'turn_completed': frames[-1]['event']['data']['reason']['kind'] == 'completed',
                }
            report['passed'] = all(report['checks'].values())
        finally:
            adapter.close()
            report['owned_dsh_stopped'] = adapter.process is None or adapter.process.poll() is not None
            (base/'report.json').write_text(json.dumps(report, indent=2), encoding='utf8')
            print('ARTIFACT', base, 'passed', report['passed'], 'checks', report['checks'], flush=True)
    return 0 if report['passed'] and report['owned_dsh_stopped'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
