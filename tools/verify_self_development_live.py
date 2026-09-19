"""Opt-in real DeepSeek development through DSH on a copied Sumika module.

Only an existing local credential is read; no key or HTTP bodies are logged.
The fixed-origin relay bounds calls and does not fall back to another model.
"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'tools')]
from sumika_next.dsh import Dsh
from sumika_next.runtime_ownership import ProfileLease
from verify_dsh_recovery import prompt, finish


def verified_test_result(events, command, expected_count):
    """Bind unittest evidence to the sole authorized native terminal call."""
    calls = [f['event']['data'] for f in events
             if f.get('event', {}).get('type') == 'tool/call']
    if len(calls) != 1:
        return False
    call = calls[0]
    try:
        arguments = json.loads(call.get('arguments', ''))
    except (TypeError, ValueError):
        return False
    if (call.get('name') != 'pwsh' or not isinstance(arguments, dict)
            or arguments.get('command') != command or not call.get('callId')):
        return False
    results = [f['event']['data'] for f in events
               if f.get('event', {}).get('type') == 'tool/result']
    if len(results) != 1:
        return False
    result = results[0]
    message = result.get('message', {})
    source = message.get('source', {})
    blocks = message.get('content', [])
    if (result.get('turn') != call.get('turn') or result.get('step') != call.get('step')
            or source.get('kind') != 'tool' or source.get('callId') != call['callId']
            or result.get('meta', {}).get('truncated')
            or len(blocks) != 1):
        return False
    block = blocks[0]
    if (block.get('type') != 'tool-result' or block.get('toolCallId') != call['callId']
            or block.get('isError') is not False):
        return False
    content = block.get('content', [])
    if not content or any(c.get('type') != 'text' or not isinstance(c.get('text'), str)
                          for c in content):
        return False
    output = '\n'.join(c['text'] for c in content).replace('\r\n', '\n')
    summaries = re.findall(r'^Ran (\d+) tests? in [\d.]+s$', output, re.MULTILINE)
    return (summaries == [str(expected_count)]
            and re.search(r'\nOK\s*\Z', output) is not None
            and '[exit code:' not in output
            and not re.search(r'^(?:FAILED|ERROR|FAIL)(?:\b|:)', output, re.MULTILINE))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-edit-phase', action='store_true', help='Make bounded real model calls; candidate code is not executed')
    parser.add_argument('--resume-reviewed', type=Path, help='Resume an existing reviewed candidate once, without editing')
    parser.add_argument('--continue-incomplete-edit', type=Path, help='Continue one terminal incomplete edit without executing candidate code')
    parser.add_argument('--task', choices=['windows-paths', 'audit-cli', 'installer-paths', 'restore-preflight'], default='windows-paths')
    parser.add_argument('--after-failed-test-review', action='store_true', help='One explicit second test after externally reviewed fixture correction')
    parser.add_argument('--after-deduplicated-probe', action='store_true', help='New request after verified zero-call duplicate probe')
    args = parser.parse_args()
    if sum(map(bool,(args.run_edit_phase,args.resume_reviewed,args.continue_incomplete_edit))) != 1:
        parser.error('choose exactly one explicit edit or reviewed resume action')
    if args.after_failed_test_review and not args.resume_reviewed:
        parser.error('fixture correction requires an existing reviewed resume')
    if args.after_deduplicated_probe and not args.after_failed_test_review:
        parser.error('deduplicated recovery requires reviewed fixture correction')
    _run_guarded_edit_phase(args.resume_reviewed or args.continue_incomplete_edit, args.task,
                            args.after_failed_test_review, args.after_deduplicated_probe,
                            edit_continuation=bool(args.continue_incomplete_edit))


def _run_guarded_edit_phase(resume=None, task='windows-paths', corrected_fixture=False, deduplicated=False, edit_continuation=False):
    credential = Path(os.environ['LOCALAPPDATA'])/'Sumika/env.ps1'
    match = re.search(r'''\$env:DEEPSEEK_API_KEY\s*=\s*(['"])([^'"\r\n]+)\1''',
                      credential.read_text(encoding='utf-8-sig'))
    if not match:
        raise RuntimeError('Existing DeepSeek credential not available')
    key = match[2]
    base = resume.resolve(strict=True) if resume else ROOT/'.sumika-next'/('self-development-live-'+uuid.uuid4().hex)
    if resume and (base.parent != ROOT/'.sumika-next' or not base.name.startswith('self-development-live-')):
        raise ValueError('resume must identify an existing isolated probe')
    home, work = base/'profile', base/'work'
    if not resume:
        home.mkdir(parents=True)
        work.mkdir()
    if resume and (base/'task.json').is_file():
        task = json.loads((base/'task.json').read_text(encoding='utf8'))['task']
    source = ROOT/('tools/backup_personal_data.py' if task == 'restore-preflight' else 'tools/audit_package_licenses.py' if task == 'audit-cli' else 'tools/verify_portable_staging.py')
    original = source.read_bytes()
    companion_sources = {'README.md': ROOT/'packaging/README.md',
                         'verify_portable_staging.py': ROOT/'tools/verify_portable_staging.py'} if task == 'audit-cli' else {}
    if task == 'installer-paths':
        companion_sources = {'install_sumika.ps1': ROOT/'packaging/install_sumika.ps1'}
    if task == 'restore-preflight':
        companion_sources = {'restore_preflight.py': ROOT/'tools/development_tasks/restore_preflight_seed.py',
                             'README.md': ROOT/'docs/project/backup-recovery.md'}
    companion_originals = {name: path.read_bytes() for name, path in companion_sources.items()}
    if not resume:
        (work/source.name).write_bytes(original)
        (work/'test_paths.py').write_text('''import unittest
from verify_portable_staging import safe_path
class Paths(unittest.TestCase):
    def test_reject_windows_names(self):
        for path in ('ui/CON', 'ui/con.txt', 'ui/aux.json', 'ui/LPT9.log',
                     'ui/a?.txt', 'ui/a*.js', 'ui/a|b', 'ui/a<b', 'ui/a>b',
                     'ui/a"b', 'ui/a\\x01b', 'ui/COM1.txt'):
            with self.subTest(path=path), self.assertRaises(ValueError):
                safe_path(path)
    def test_keep_valid_names(self):
        for path in ('ui/context.js', 'ui/auxiliary.py', 'tools/com10.py',
                     'ui/中文.png', 'runtime/node/node.exe'):
            self.assertEqual(safe_path(path), path)
if __name__ == '__main__': unittest.main()
''', encoding='utf8')
        if task == 'audit-cli':
            for name, content in companion_originals.items():
                (work/name).write_bytes(content)
            (work/'test_paths.py').write_bytes((ROOT/'tools/development_tasks/audit_cli_tests.py').read_bytes())
        if task == 'installer-paths':
            for name, content in companion_originals.items():
                (work/name).write_bytes(content)
            (work/'test_paths.py').write_bytes((ROOT/'tools/development_tasks/installer_paths_tests.py').read_bytes())
        if task == 'restore-preflight':
            for name, content in companion_originals.items():
                (work/name).write_bytes(content)
            # Test-only bootstrap uses existing real lock code; candidate imports
            # still resolve in work first, including CLI subprocesses.
            bootstrap='import os, sys\nsys.path.append('+repr(str(ROOT))+')\nos.environ["PYTHONPATH"]='+repr(str(ROOT))+'\n'
            (work/'test_paths.py').write_text(bootstrap+(ROOT/'tools/development_tasks/restore_preflight_tests.py').read_text(encoding='utf8'),encoding='utf8')
        (base/'task.json').write_text(json.dumps({'task': task}), encoding='utf8')
    report = {'passed': False, 'model': 'deepseek-flash', 'requests': 0,
              'scope': 'Real model modifies isolated copy of Sumika release verifier', 'checks': {}}
    test_original = (work/'test_paths.py').read_bytes()
    test_command = "& '"+sys.executable+"' -B -m unittest test_paths"
    policy = base/'review-policy.json'
    candidate_original = (work/source.name).read_bytes()
    file_names = [source.name, 'test_paths.py', *companion_sources]
    file_hashes = {name: hashlib.sha256((work/name).read_bytes()).hexdigest() for name in file_names}
    evidence = base
    if edit_continuation:
        old=json.loads((base/'report.json').read_text(encoding='utf8'))
        prior_policy=json.loads(policy.read_text(encoding='utf8'))
        if (task!='restore-preflight' or old.get('status')!='edit_phase_failed'
                or old.get('turn_reason')!='completed' or old.get('candidate_hashes')!=file_hashes
                or prior_policy.get('reviewedHashes',{}).get('test_paths.py')!=file_hashes['test_paths.py']):
            raise ValueError('requires terminal incomplete candidate with unchanged files and tests')
        evidence=base/'edit-continuation'
        evidence.mkdir()  # Never replay a prior/unknown continuation.
    elif resume:
        old = json.loads((base/'report.json').read_text(encoding='utf8'))
        review = json.loads((base/('review-after-fixture-correction.json' if corrected_fixture else 'review.json')).read_text(encoding='utf8'))
        prior_policy = json.loads(policy.read_text(encoding='utf8'))
        tests_match = prior_policy['reviewedHashes']['test_paths.py'] == hashlib.sha256(test_original).hexdigest()
        if corrected_fixture:
            previous = json.loads((base/'reviewed-resume/report.json').read_text(encoding='utf8'))
            revision = review.get('test_fixture_revision', {})
            if (previous.get('status') != 'reviewed_resume_failed' or previous.get('turn_reason') != 'completed'
                    or not previous.get('checks', {}).get('one_exact_test_call')
                    or previous.get('checks', {}).get('native_tests_passed') is not False
                    or (not deduplicated and revision.get('before') != prior_policy['reviewedHashes']['test_paths.py'])
                    or revision.get('after') != file_hashes['test_paths.py']):
                raise ValueError('no terminal failed test and reviewed fixture revision; do not replay')
            tests_match = True
            if deduplicated:
                duplicate = json.loads((base/'reviewed-resume-2/report.json').read_text(encoding='utf8'))
                observation = json.loads((base/'reviewed-resume-2/observation.json').read_text(encoding='utf8'))
                if (duplicate.get('requests') != 0 or not observation.get('new_test_not_executed')
                        or prior_policy.get('reviewedHashes') != file_hashes):
                    raise ValueError('deduplicated probe was not proven unexecuted; do not replay')
        candidate_hash = hashlib.sha256(candidate_original).hexdigest()
        revision = review.get('host_source_revision', {})
        preserved_source = base/'model-original-verifier.py'
        source_matches = candidate_hash == old.get('candidate_sha256')
        if not source_matches and task == 'installer-paths':
            source_matches = (revision.get('before') == old.get('candidate_sha256')
                and revision.get('after') == candidate_hash and preserved_source.is_file()
                and hashlib.sha256(preserved_source.read_bytes()).hexdigest() == revision['before'])
        if (not old.get('edit_phase_completed') or old.get('turn_reason') != 'completed'
                or not source_matches or candidate_hash != review.get('candidate_sha256')
                or review.get('status') != 'reviewed_and_focused_tests_passed_not_merged'
                or not tests_match):
            raise ValueError('candidate or tests differ from reviewed evidence')
        if task in ('audit-cli', 'installer-paths', 'restore-preflight') and review.get('reviewedHashes') != file_hashes:
            raise ValueError('multi-file candidate lacks matching external review hashes')
        evidence = base/('reviewed-resume-3' if deduplicated else 'reviewed-resume-2' if corrected_fixture else 'reviewed-resume')
        evidence.mkdir()  # Existing attempt, including unknown result, is never replayed.
    policy.write_text(json.dumps({'schema_version': 1, 'workspace': str(work.resolve()),
        'files': file_names, 'testCommand': test_command,
        'editableFiles': ([source.name, 'README.md'] if task == 'audit-cli' else
                          [source.name, 'restore_preflight.py', 'README.md'] if task == 'restore-preflight' else
                          [source.name, 'install_sumika.ps1'] if task == 'installer-paths' else [source.name]),
        'allowEdits': not bool(resume) or edit_continuation,
        'reviewedHashes': file_hashes}), encoding='utf8')
    if not resume:
        before = subprocess.run([sys.executable, '-B', '-m', 'unittest', 'test_paths'], cwd=work,
                            capture_output=True, text=True)
        (base/'before.txt').write_text(before.stdout+before.stderr, encoding='utf8')
        assert before.returncode != 0, 'expected actual baseline gap'
    lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            length = int(self.headers.get('Content-Length', '0'))
            if self.path != '/chat/completions' or not 0 < length <= 350000:
                self.send_error(400)
                return
            body = self.rfile.read(length)
            request = json.loads(body)
            with lock:
                if (request.get('model') != 'deepseek-flash' or report['requests'] >= (24 if task == 'restore-preflight' else 20 if task == 'installer-paths' else 16 if task == 'audit-cli' else 10)
                        or report.get('provider_error_type')):
                    self.send_error(403)
                    return
                report['requests'] += 1
            try:
                req = urllib.request.Request('https://api.deepseek.com/chat/completions', body,
                    {'Authorization': 'Bearer '+key, 'Content-Type': 'application/json'})
                with urllib.request.urlopen(req, timeout=120) as response:
                    self.send_response(response.status)
                    self.send_header('Content-Type', response.headers.get('Content-Type', 'text/event-stream'))
                    self.end_headers()
                    while block := response.read1(8192):
                        self.wfile.write(block)
                        self.wfile.flush()
            except Exception as error:
                report['provider_error_type'] = type(error).__name__
                if hasattr(error, 'code'):
                    report['provider_http_status'] = error.code
                self.close_connection = True

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    (home/'.env').write_text('DEEPSEEK_API_KEY=relay-placeholder-not-secret\n', encoding='utf8')
    (home/'cordis.patch.yml').write_text(json.dumps([
        {'id': 'session-title-llm', 'disabled': True},
        {'id': 'session-telemetry-otel', 'disabled': True},
        {'id': 'llm-deepseek', 'config': {'baseURL': f'http://127.0.0.1:{server.server_port}',
                                        'maxTokens': 4096, 'thinking': 'disabled'}},
        {'id': 'sandbox-policy', 'config': {'mode': 'workspace-write'}},
        {'id': 'approval', 'config': {'policy': 'never'}},
        {'id': 'permission', 'config': {'defaultPreset': 'bounded-test', 'presets': {
            'bounded-test': {'sandbox': 'workspace-write', 'approval': 'never'}}}},
        {'insert': [{'id': 'sumika-probe-guard', 'name': str(ROOT/'tools/development_probe_guard.mjs'),
                     'config': {'workspace': str(work), 'policyFile': str(policy)}}]},
    ]), encoding='utf8')
    adapter = Dsh(ROOT, home)
    lease = ProfileLease(home).acquire()
    try:
        adapter.start()
        lease.bind(adapter.process)
        sid = 'real-self-development'
        if resume:
            report['scope'] = 'Real model resumes reviewed candidate and runs one native test command'
            report.pop('edit_phase_completed', None)
            assert any(s['sessionId'] == sid for s in adapter.list_sessions()), 'original session missing'
        else:
            adapter._rpc('session/create', {'sessionId': sid, 'cwd': str(work)})
        stream = adapter.stream('session/follow', {'address': {'kind': 'session', 'sessionId': sid}}, timeout=180)
        try:
            next(stream)
            request = ('The host reviewed your candidate and pinned its hash. Resume this existing task: '
                       'use pwsh to run EXACTLY this command once: '+test_command+'. '
                       'Do not edit files, add flags, change working directory, or run any other command. '
                       'Report the actual test result briefly, then stop.') if resume and not edit_continuation else (
                   'Fix the Windows release-path validation gap in verify_portable_staging.py. '
                   'Read the source and test_paths.py, modify only the verifier. Reject Windows reserved device names and '
                   'invalid filename characters while retaining valid Unicode and existing release boundaries. '
                   'Do not edit tests, delete files, access outside this working directory, use the network, '
                   'install dependencies or spawn agents. This is the edit phase: do not execute modified code. '
                   'The host already ran the baseline tests. Use read and edit, then stop and report the candidate '
                   'ready for external review; tests will run only after review. Do not claim tests passed.')
            if not resume and task == 'audit-cli':
                report['scope'] = 'Real model improves shipped license-audit CLI and release documentation'
                request = (
                    'Implement a release-audit CI interface in audit_package_licenses.py and document it in README.md. '
                    'Read test_paths.py and existing code. Add optional --fail-on-findings: write the complete report first, '
                    'then return exit code 2 when any dependency findings exist; otherwise 0. Default invocation returns 0 '
                    'even with findings because it is an inventory, never legal clearance. main() returns the integer; '
                    'script entry must propagate it via SystemExit. Preserve exclusive output creation and no overwrite. '
                    'Document exact flag/exit meanings and review limitations, updating relevant existing section. '
                    'Only audit_package_licenses.py and README.md may be edited. Do not change tests or '
                    'verify_portable_staging.py. No execution, network, deletion, installation or agents in this edit phase. '
                    'Use read/edit, then report ready for external review without claiming tests passed.')
            request_id = 'development-probe-' + uuid.uuid4().hex
            if (not resume or edit_continuation) and task == 'restore-preflight':
                report['scope']='Real model implements readonly restore preflight across backup CLI, new module and recovery documentation'
                request=(
                    'Implement a read-only restore preflight using existing snapshot integrity checks. Read test_paths.py first. '
                    'In backup_personal_data.py extract verify_snapshot(snapshot) from restore, returning the verified manifest; '
                    'restore must reuse it and retain all existing destination, links, integrity and no-overwrite protections. '
                    'Implement restore_preflight.inspect_snapshot(snapshot): verify first, never create a lock/database/journal or mutate any data. '
                    'Return schema_version 1, integrity verified, status ready/needs_attention/unknown, dependencies and issues. '
                    'Inspect only role.role_dir (directory) and role.database (file) in snapshot data/role-model-settings.json. '
                    'Absent settings is valid unconfigured first launch. Absolute paths within manifest.source map to snapshot/data, '
                    'never inspect the original internal location. External absolute local paths are only stat-checked. '
                    'Dependencies contain field, scope internal/external/unknown and availability present/missing/unknown; '
                    'do not output raw settings, paths, secrets or exception text. Missing resource => needs_attention; '
                    'relative paths, UNC/network paths, malformed settings => unknown without network access. '
                    'Pending role-restore-state.json => needs_attention with issue role_rebind_pending; corrupt journal => unknown '
                    'with role_rebind_state_invalid. Integrity failure raises ValueError instead of pretending readiness. '
                    'Add --inspect --source SNAPSHOT CLI without destination; reject combinations with restore/rebind/resume, '
                    'retain required destination for other actions. Lazy import avoids circular imports; support both direct script and tools package use. '
                    'Document scope, statuses, private-data boundary and inability to certify other dependencies in README.md. '
                    'Only edit backup_personal_data.py, restore_preflight.py and README.md. Tests are read-only. '
                    'No code execution, deletion, network, installs or subagents during edit phase. '
                    'Use read/edit then stop for external review, do not claim tests passed.')
                if edit_continuation:
                    request += (
                        ' This is an explicit continuation of your terminal incomplete turn, not a new task. '
                        'Your backup_personal_data.py edits already exist; inspect before editing them again. '
                        'All FOUR files are in the current working directory: backup_personal_data.py, restore_preflight.py, '
                        'README.md and immutable test_paths.py. restore_preflight.py already exists as a stub: '
                        'read it, then use edit to replace the exact stub text. Do not use write, terminal, broad glob, '
                        'questions or outside paths; those operations remain unavailable. Read README.md then edit it. '
                        'The requested dependencies array has exactly two entries when role settings are present, '
                        'one for each named field; use scope/availability for classification. '
                        'Finish both missing implementation and documentation before reporting ready. '
                        'The host has NOT approved code execution; no tests may be run during this continuation.')
            if not resume and task == 'installer-paths':
                report['scope'] = 'Real model fixes pre-extraction path conflicts in Python verifier and PowerShell installer'
                request = (
                    'Fix release inventories that declare both a file and its descendant, e.g. ui/Asset and ui/asset/icon.png. '
                    'Read test_paths.py and both implementations. Add validate_inventory_paths(paths) in verify_portable_staging.py '
                    'and call it from verify before checking on-disk files. Validate each path via existing safe_path, reject '
                    'case-insensitive duplicates and file-ancestor conflicts in either ordering; shared directories are valid. '
                    'In install_sumika.ps1 reject equivalent conflicting manifest entries before creating any staging directory '
                    'or extracting anything. Preserve existing manifest, hash, path and no-overwrite protections. '
                    'Only modify verify_portable_staging.py and install_sumika.ps1. Tests are read-only. '
                    'Do not execute code, use network, delete files, install anything, or spawn agents. '
                    'Read/edit only, then stop for external review without claiming tests passed.')
            (evidence/'submission.json').write_text(json.dumps({'request_id': request_id,
                'session': sid, 'request_sha256': hashlib.sha256(request.encode()).hexdigest()}), encoding='utf8')
            assert adapter._rpc('session/prompt', {'sessionId': sid, 'requestId': request_id,
                'mode': 'queue', 'content': [{'type': 'text', 'text': request}]}) == {'accepted': True}
            events = finish(stream)
        finally:
            stream.close()
        (evidence/'events.json').write_text(json.dumps(events, ensure_ascii=False, indent=2), encoding='utf8')
        report['turn_reason'] = events[-1]['event']['data']['reason']['kind']
        report['checks'] = {
                            'tests_unchanged': (work/'test_paths.py').read_bytes() == test_original,
                            'copied_source_changed': (work/source.name).read_bytes() != original,
                            'original_source_unchanged': source.read_bytes() == original}
        if task == 'audit-cli':
            report['checks'].update(
                documentation_updated=(work/'README.md').read_bytes() != companion_originals['README.md'],
                helper_unchanged=(work/'verify_portable_staging.py').read_bytes() == companion_originals['verify_portable_staging.py'],
                original_companions_unchanged=all(path.read_bytes() == companion_originals[name] for name, path in companion_sources.items()))
            report['candidate_hashes'] = {name: hashlib.sha256((work/name).read_bytes()).hexdigest() for name in file_names}
        report['edit_phase_completed'] = all(report['checks'].values()) and report['turn_reason'] == 'completed'
        if task == 'installer-paths':
            report['checks'].update(
                installer_updated=(work/'install_sumika.ps1').read_bytes() != companion_originals['install_sumika.ps1'],
                original_companions_unchanged=all(path.read_bytes() == companion_originals[name] for name,path in companion_sources.items()))
            report['candidate_hashes'] = {name:hashlib.sha256((work/name).read_bytes()).hexdigest() for name in file_names}
            report['edit_phase_completed'] = all(report['checks'].values()) and report['turn_reason'] == 'completed'
        if task == 'restore-preflight':
            report['checks'].update(
                preflight_updated=(work/'restore_preflight.py').read_bytes()!=companion_originals['restore_preflight.py'],
                documentation_updated=(work/'README.md').read_bytes()!=companion_originals['README.md'],
                original_companions_unchanged=all(path.read_bytes()==companion_originals[name] for name,path in companion_sources.items()))
            report['candidate_hashes']={name:hashlib.sha256((work/name).read_bytes()).hexdigest() for name in file_names}
            report['edit_phase_completed']=all(report['checks'].values()) and report['turn_reason']=='completed'
        report['status'] = 'candidate_awaiting_review' if report['edit_phase_completed'] else 'edit_phase_failed'
        report['candidate_sha256'] = hashlib.sha256((work/source.name).read_bytes()).hexdigest()
        # Complete development acceptance still requires review, tests and merge.
        report['passed'] = False
        if resume and not edit_continuation:
            calls = [f['event']['data'] for f in events if f.get('event', {}).get('type') == 'tool/call']
            report['checks'].pop('copied_source_changed')
            report['checks'].pop('documentation_updated', None)
            report.pop('edit_phase_completed', None)
            report['checks'].update(candidate_unchanged=(work/source.name).read_bytes() == candidate_original,
                reviewed_inputs_unchanged=all(hashlib.sha256((work/name).read_bytes()).hexdigest() == digest
                                              for name, digest in file_hashes.items()),
                one_exact_test_call=len(calls) == 1 and calls[0]['name'] == 'pwsh'
                    and json.loads(calls[0]['arguments']).get('command') == test_command,
                native_tests_passed=verified_test_result(events, test_command,
                    13 if task == 'restore-preflight' else 4 if task in ('audit-cli', 'installer-paths') else 2),
                original_session_resumed=True)
            report['passed'] = all(report['checks'].values()) and report['turn_reason'] == 'completed'
            report['status'] = 'reviewed_native_test_completed' if report['passed'] else 'reviewed_resume_failed'
    finally:
        try:
            adapter.close()
            lease.release()
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
            (evidence/'report.json').write_text(json.dumps(report, indent=2), encoding='utf8')
            print('ARTIFACT', evidence, json.dumps(report), flush=True)


if __name__ == '__main__':
    main()
