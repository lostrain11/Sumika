"""Opt-in ordinary development through the installed Sumika managed workbench.

Uses the existing DeepSeek credential in memory and an isolated copied project.
No execution guard replacing native tools; native workspace-write policy stays
active. Approval requests are left to the native UI. Nothing is auto-merged.
"""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import threading
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--product', type=Path, required=True)
    parser.add_argument('--run', action='store_true')
    parser.add_argument('--resume', type=Path, help='Explicit new feedback turn in a verified terminal existing session')
    parser.add_argument('--feedback', type=Path)
    parser.add_argument('--preflight-failure', help='Explicit inspected continuation with no admitted request')
    parser.add_argument('--patch-task', action='store_true', help='New native patch-verifier robustness task; never replay old license task')
    parser.add_argument('--terminal-continuation', help='Explicit latest continuation directory with a native terminal event')
    parser.add_argument('--max-output-tokens', type=int, default=8192)
    parser.add_argument('--source-bundle-pro-task', action='store_true', help='One explicitly authorized Pro source bundle task, maximum 40 calls')
    parser.add_argument('--reasoning-effort', choices=['low', 'high', 'max'])
    args = parser.parse_args()
    if not args.run:
        parser.error('--run explicitly admits one new real task; never use to resume unknown work')
    if bool(args.resume) != bool(args.feedback):
        parser.error('--resume and --feedback must be supplied together')
    if args.patch_task and args.resume:
        parser.error('--patch-task starts a distinct task; cannot resume old work')
    if args.source_bundle_pro_task and (args.resume or args.patch_task):
        parser.error('Pro acceptance is a separate one-shot task')
    selected_model = 'deepseek-v4-pro' if args.source_bundle_pro_task else 'deepseek-flash'
    product = args.product.resolve(strict=True)
    base = args.resume.resolve(strict=True) if args.resume else ROOT/'.sumika-next'/('product-development-'+uuid.uuid4().hex)
    work, personal = base/'project', base/'personal'
    if args.resume:
        if base.parent != ROOT/'.sumika-next' or not base.name.startswith('product-development-'):
            raise ValueError('Resume must identify an existing isolated acceptance run')
        previous = json.loads((base/'report.json').read_text(encoding='utf8'))
        if previous.get('product') != str(product) or not previous.get('turn_end'):
            raise ValueError('Unverified product or nonterminal request; inspect without resending')
        continuations = list(base.glob('continuation-*'))
        if continuations:
            if len(continuations) != 1 or continuations[0].name not in (args.preflight_failure, args.terminal_continuation):
                raise ValueError('Existing continuation requires separate inspection; no replay')
            failed = continuations[0]
            state = json.loads((failed/'report.json').read_text(encoding='utf8'))
            if args.terminal_continuation:
                if (not state.get('turn_end') or state.get('product') != str(product)
                        or state.get('session_id') != previous.get('session_id')):
                    raise ValueError('Continuation has no verified terminal identity; no replay')
                previous = state
            elif (state.get('status') != 'prepared' or state.get('provider_requests') != 0
                    or state.get('session_id') or (failed/'request.json').exists()
                    or (failed/'events.jsonl').exists()):
                raise ValueError('Continuation may have been admitted; inspect without resending')
        selected_model = previous['model']
        evidence = base/('continuation-'+uuid.uuid4().hex); evidence.mkdir()
    else:
        work.mkdir(parents=True); personal.mkdir(); evidence = base
    selected = ['tools/audit_package_licenses.py', 'tools/verify_portable_staging.py',
                'tests_next/test_dependency_notices.py', 'packaging/README.md']
    if args.patch_task:
        selected = ['tools/verify_native_source_patches.py', 'packaging/README.md']
    if args.source_bundle_pro_task:
        selected = ['tools/build_native_source_materials.py', 'packaging/README.md']
    if args.resume:
        selected = list(previous['original_hashes'])
    originals = previous['original_hashes'] if args.resume else {}
    if not args.resume:
        for relative in selected:
            target = work/relative; target.parent.mkdir(parents=True, exist_ok=True)
            raw = (ROOT/relative).read_bytes(); target.write_bytes(raw)
            originals[relative] = hashlib.sha256(raw).hexdigest()
        shutil.copytree(ROOT/'packaging/notices', work/'packaging/notices')
    credential = Path(os.environ['LOCALAPPDATA'])/'Sumika/env.ps1'
    match = re.search(r'''\$env:DEEPSEEK_API_KEY\s*=\s*(['"])([^'"\r\n]+)\1''',
                      credential.read_text(encoding='utf-8-sig'))
    if not match:
        raise RuntimeError('Configured DeepSeek credential unavailable; no fallback')
    key = match[2]
    prior_requests = previous.get('prior_provider_requests', 0) + previous['provider_requests'] if args.resume else 0
    request_limit = 40-prior_requests if selected_model == 'deepseek-v4-pro' else (60 if args.resume or args.patch_task else 40)
    if request_limit <= 0: raise ValueError('Authorized provider budget already consumed')
    report = {'status':'prepared', 'passed':False, 'product':str(product),
              'model':selected_model, 'provider_requests':0, 'original_hashes':originals,
              'prior_provider_requests': prior_requests, 'provider_request_limit': request_limit,
              'boundary':'Ordinary native tools in isolated workspace; no automatic adoption or release claim'}
    def save():
        (evidence/'report.json').write_text(json.dumps(report, indent=2), encoding='utf8')
    save()
    gate = threading.Lock()
    class Relay(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def do_POST(self):
            size = int(self.headers.get('Content-Length', '0'))
            if self.path != '/chat/completions' or not 0 < size <= 1500000:
                self.send_error(400); return
            body = self.rfile.read(size)
            request = json.loads(body)
            with gate:
                if (request.get('model') != selected_model
                        or report['provider_requests'] >= request_limit or report.get('provider_error')):
                    report['local_relay_refusal'] = 'model_mismatch_or_request_limit_or_previous_error'
                    save()
                    self.send_error(403); return
                report['provider_requests'] += 1
            try:
                outbound = urllib.request.Request('https://api.deepseek.com/chat/completions', body,
                    {'Authorization':'Bearer '+key, 'Content-Type':'application/json'})
                with urllib.request.urlopen(outbound, timeout=120) as response:
                    self.send_response(response.status)
                    self.send_header('Content-Type', response.headers.get('Content-Type', 'text/event-stream'))
                    self.end_headers()
                    while chunk := response.read1(8192):
                        self.wfile.write(chunk); self.wfile.flush()
            except Exception as error:
                report['provider_error'] = type(error).__name__
                report['provider_http_status'] = getattr(error, 'code', None)
                self.close_connection = True
            finally: save()
    relay = ThreadingHTTPServer(('127.0.0.1',0), Relay)
    threading.Thread(target=relay.serve_forever, daemon=True).start()
    os.environ['SUMIKA_DATA_DIR'] = str(personal)
    sys.path.insert(0, str(product))
    from sumika_next.daily import default_home
    from ui.server import serve
    home = default_home(product); home.mkdir(parents=True, exist_ok=True)
    (home/'.env').write_text('DEEPSEEK_API_KEY=local-relay-placeholder\n', encoding='utf8')
    (home/'cordis.patch.yml').write_text(json.dumps([
        {'id':'session-title-llm','disabled':True},
        {'id':'session-telemetry-otel','disabled':True},
        {'id':'llm-deepseek','config':{'baseURL':f'http://127.0.0.1:{relay.server_port}', 'maxTokens':args.max_output_tokens}},
        {'id':'sandbox-policy','config':{'mode':'workspace-write'}},
        {'id':'approval','config':{'policy':'ask'}},
        {'id':'permission','config':{'defaultPreset':'acceptance','presets':{
            'acceptance':{'sandbox':'workspace-write','approval':'ask'}}}},
    ]), encoding='utf8')
    shell = serve(personal/'role-model-settings.json', port=0,
                  workbench_root=product, schedule_directory=base/'schedules')
    threading.Thread(target=shell.serve_forever, daemon=True).start()
    stream = None
    try:
        shell.sumika_bridge.workbench.start()
        adapter = shell.sumika_bridge.workbench.adapter
        if args.resume:
            sid = previous['session_id']
            assert any(s['sessionId']==sid for s in adapter.list_sessions()), 'original session missing'
            report['resumed_existing_session'] = True
        else:
            workspace = adapter._rpc('workspace/create',{'path':str(work)})['workspace']['workspaceId']
            sid = 'ordinary-development-'+uuid.uuid4().hex
            adapter._rpc('session/create',{'sessionId':sid,'workspaceId':workspace})
        if selected_model == 'deepseek-v4-pro':
            selection = adapter._rpc('session/selectModel', {'sessionId': sid,
                'provider': 'deepseek-official', 'model': selected_model,
                **({'reasoningEffort': args.reasoning_effort} if args.reasoning_effort else {})})
            report['native_model_selection'] = selection
        report.update(status='running', session_id=sid, profile=str(home),
                      ui_url=f'http://127.0.0.1:{shell.server_port}/#board')
        request_id = uuid.uuid4().hex
        prompt = (
            'Improve the actual license auditor in this isolated Sumika project. Currently it flags every '
            'README containing MIT text for review even when the exact README and complete verbatim '
            'copyright/permission/disclaimer excerpt were already reviewed and preserved in '
            'packaging/notices/sources.json. Inspect the existing implementation and records. Implement '
            'narrow evidence-based recognition: bind package name/version/manifest hash, exact README path '
            'and current hash, and intact supplemental excerpt actually present in the README. A generic '
            'license file or a verification prose string alone must not waive a finding. Unknown, changed, '
            'tampered, partial or mismatched evidence stays flagged. Preserve native/copyleft and unresolved '
            'findings and existing CLI behavior. Use an explicit review-kind field for previously reviewed '
            'records if appropriate. Update audit code, add meaningful positive/negative tests, and update '
            'the relevant documentation. Plan briefly, implement, run tests, review your diff and fix defects '
            'before reporting actual results. This is ordinary iterative development, not an edit-only phase. '
            'Work only inside this project. No file deletion, network tools, dependency installation, agents, '
            'credentials or access to other projects. Do not change native/DSH code or weaken approvals or sandbox. '
            'Do not claim full license compliance. Existing host development Python is '+sys.executable+
            '; use it with -B for tests. Existing baseline command: -m unittest tests_next.test_dependency_notices. '
            'No git repository is required. The main agent will independently review all changes before adoption.')
        if args.resume:
            prompt = args.feedback.read_text(encoding='utf8')
        if args.patch_task:
            prompt = (
                'Improve tools/verify_native_source_patches.py in this isolated Sumika project. '
                'This is a NEW ordinary implementation task. The existing tool verifies source hashes '
                'and patch application but trusts recipe archive bytes and can exit without a useful '
                'failure report. Add explicit --recipe-materials JSON input using the existing '
                'packaging/notices/native-patch-materials.json archive file/sha256 bindings; verify BOTH '
                'recipe archive hashes before reading or using their contents. Missing, duplicate, '
                'unexpected, malformed or mismatched archive identities must fail closed. Never infer '
                'trust from the archive own directory name. On every failure after creation of the '
                'unique output directory, preserve report.json with passed=false, a precise failure '
                'stage/reason and any completed component evidence. Never overwrite a previous run. '
                'Preserve current patch selection and zero-fuzz rules, no compilation or legal claims. '
                'Add meaningful unit tests with SMALL synthetic archives, no external source archive '
                'downloads needed. Test successful validation, tampering, malformed/duplicate/missing '
                'bindings, and report preservation on setup/checksum/patch failure. Mock patch subprocess '
                'only as appropriate; tests must prove behavior rather than mirror strings. Update '
                'existing packaging/README.md relevant section. Plan briefly, implement, test, review '
                'diff, fix issues and report results. Use '+sys.executable+' -B -m unittest '
                'discover -s tests_next -p test_native_source_patches.py. No git repo is required. '
                'Critical known Windows compatibility: do NOT use tempfile/mkdtemp/TemporaryDirectory. '
                'Use Path(__file__).resolve().parents[1]/".test-evidence"/uuid.uuid4().hex with mkdir '
                'and retain directories. No cleanup, unlink, rmtree, deletion, chmod, ACL or permission '
                'changes. If any tool denies access, report it and stop that action; do not change '
                'wrappers or paths to evade it. No network, installs, agents, credentials, other projects '
                'or changes to DSH. Work only in this workspace. No automatic merge; main agent reviews.')
        if args.source_bundle_pro_task:
            prompt = (
                'Complete a real development task in this isolated Sumika workspace. Improve the existing '
                'tools/build_native_source_materials.py, which builds an internal source-material ZIP. '
                'It currently leaves a partial ZIP without failure evidence when a later input hash fails. '
                'Make success/failure explicit: preserve a sidecar report with passed=false, exact stage, '
                'reason and entries already written on any build/verification failure after claiming a '
                'new output. A previous ZIP or report must never be overwritten; reject either existing '
                'artifact before changing anything. Retain partial output, never delete it. Validate the '
                'three existing metadata ledgers before copying bytes: their expected list/object shapes, '
                'required safe names and SHA256 fields, and duplicate destination identities. Do not '
                'make legal clearance claims or change source selection. Refactor locally as needed. '
                'Add meaningful tests using tiny synthetic source inputs and small metadata ledgers; '
                'mock ROOT to a private fixture containing packaging/notices, never use real downloads. '
                'Test success, invalid/duplicate/missing metadata, an early and a LATER checksum failure '
                'with retained partial evidence, corrupt output verification if practical, and existing '
                'ZIP/report refusal without overwriting. Update only the relevant existing packaging '
                'README section. Implement, run tests, inspect the diff and fix failures before reporting. '
                'Use '+sys.executable+' -B -m unittest discover -s tests_next -p test_native_source_materials.py. '
                'IMPORTANT: no tempfile/mkdtemp/TemporaryDirectory on Windows. Use unique directories '
                'under Path(__file__).resolve().parents[1]/".test-evidence"/uuid.uuid4().hex and retain '
                'all fixtures. No deletion, cleanup, unlink, rmtree, ACL/chmod or sandbox changes. '
                'No network tools, dependency installs, agents, credentials or other projects. Stop on '
                'permission denial; never evade it. Stay within this project and native tools. No git '
                'repository needed. Avoid broad tree dumps and repeated whole-file rewrites. Main agent '
                'will independently review and run the actual source archive acceptance. You have up to '
                '40 provider requests for this task; finish within this bounded run. Do not create a '
                'parallel implementation or docs system. Existing script and notices are the assets.')
        (evidence/'request.json').write_text(json.dumps({'request_id':request_id,'prompt':prompt},indent=2),encoding='utf8')
        stream = adapter.stream('session/follow',{'address':{'kind':'session','sessionId':sid}},timeout=1800)
        next(stream)
        assert adapter._rpc('session/prompt',{'sessionId':sid,'requestId':request_id,'mode':'queue',
                    'content':[{'type':'text','text':prompt}]}) == {'accepted':True}
        save(); print('RUN',base,'UI',report['ui_url'],flush=True)
        with (evidence/'events.jsonl').open('x',encoding='utf8') as log:
            for frame in stream:
                log.write(json.dumps(frame,ensure_ascii=False)+'\n');log.flush()
                event=frame.get('event',{});kind=event.get('type')
                if kind in ('tool/call','tool/result','approval/asked','approval/decided','turn/end'):
                    data = event.get('data', {})
                    print('EVENT',kind,data.get('name', ''),
                          str(data.get('arguments', ''))[:220] if kind == 'tool/call' else '',flush=True)
                if kind=='turn/end':
                    report['turn_end']=event;report['status']='turn_terminal_awaiting_main_review';save();break
        if report['status']=='running': report['status']='unknown_do_not_resubmit'
        report['source_originals_unchanged']=all(hashlib.sha256((ROOT/r).read_bytes()).hexdigest()==h for r,h in originals.items())
        report['candidate_hashes']={r:hashlib.sha256((work/r).read_bytes()).hexdigest() for r in selected}
    finally:
        if stream: stream.close()
        shell.shutdown(); shell.server_close()
        relay.shutdown(); relay.server_close()
        save(); print('REPORT',evidence/'report.json',flush=True)


if __name__=='__main__':main()
