"""Real native approval buttons and protocol, deterministic model, no external sends.

Reuses the product web-review approval adapter; its worker is replaced only inside
an isolated test root by a local sentinel writer. No synthetic approval answerer.
"""
import json
import argparse
import os
import queue
import hashlib
import shutil
from pathlib import Path
import subprocess
import sys
import time
import threading
import uuid
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1]
ROOT = Path(os.environ.get('SUMIKA_TEST_CANDIDATE', str(SOURCE))).resolve(strict=True)
sys.path[:0] = [str(ROOT), str(SOURCE / 'tests_next'), str(SOURCE / 'tools')]
from p2_fixture import ModelFixture
from sumika_next.dsh import Dsh
from verify_dsh_recovery import prompt, snapshot, finish
# Historical helpers prepend their own checkout; package imports must win.
sys.path.insert(0, str(ROOT))


def verify_file_evidence(home, payload, requests, state):
    data=payload.encode('utf8')
    digest=hashlib.sha256(data).hexdigest()
    saved=home/'attachments/v1/files'/digest[:2]/digest/'submitted-note.txt'
    original=home/'attachments/v1/file-objects'/digest[:2]/digest
    assert saved.read_bytes()==original.read_bytes()==data, 'stored attachment bytes changed'
    def objects(value):
        yield value
        if isinstance(value,dict):
            for child in value.values(): yield from objects(child)
        elif isinstance(value,list):
            for child in value: yield from objects(child)
    refs=[v for v in objects(state) if isinstance(v,dict) and v.get('attachmentId')=='sha256:'+digest]
    assert any(v.get('bytes')==len(data) and v.get('name')=='submitted-note.txt' for v in refs), 'durable attachment reference missing'
    texts=[v for v in objects(requests) if isinstance(v,str) and 'verbatim read-only copy saved at' in v and 'submitted-note.txt' in v]
    assert any(f'{len(data)} bytes, sha256:{digest[:8]}' in v and json.dumps(str(saved),ensure_ascii=False) in v for v in texts), 'provider file handle mismatch'
    return {'sha256':digest,'bytes':len(data),'stored_bytes_match':True,'durable_reference_matches':True,'provider_received_readonly_handle':True}


def verify_questions(adapter, model, shell, workspace, base, report):
    """Native model tool -> actual question composer -> correlated result."""
    if shell is None:
        raise ValueError('question acceptance requires --sumika-shell')
    for decision in ('option', 'custom', 'cancel'):
        directory = base/('question-'+decision)
        directory.mkdir()
        sid = 'question-ui-'+decision
        title = 'Approval UI question '+decision
        question = '本机隔离验收：请选择输出形式（'+decision+'）'
        answer = '使用合成选项' if decision == 'option' else '自定义验收回答_原文保留'
        adapter._rpc('session/create', {'sessionId':sid, 'workspaceId':workspace})
        adapter._rpc('session/rename', {'sessionId':sid, 'title':title})
        model.responses = 0
        model.recipe = [('ask_user_question', {'questions':[{
            'id':'format-choice', 'question':question,
            'options':[{'label':'使用合成选项'}, {'label':'另一合成选项'}]}]})]
        stream = adapter.stream('session/follow', {'address':{'kind':'session','sessionId':sid}}, timeout=100)
        next(stream)
        frames, received = [], queue.Queue()
        def drain():
            try:
                for frame in stream:
                    received.put(frame)
                    if frame.get('event',{}).get('type') == 'turn/end':
                        break
            except Exception as error:
                received.put(error)
            finally:
                received.put(None)
        reader = threading.Thread(target=drain, daemon=True)
        reader.start()
        browser = None
        try:
            prompt(adapter,sid,'Ask one synthetic question; never retry.')
            browser = subprocess.Popen(['node',str(SOURCE/'tools/verify_native_approval_ui.mjs')],
                stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                text=True,encoding='utf8')
            browser.stdin.write(json.dumps(dict(url=f'http://127.0.0.1:{shell.server_port}/#board',
                shell=True,title=title,mode='question',decision=decision,question=question,
                answer=answer,directory=str(directory))))
            browser.stdin.close()
            if decision == 'cancel':
                deadline = time.monotonic()+60
                while not (directory/'ready.json').exists():
                    assert browser.poll() is None, 'question browser exited before cancellation readiness'
                    assert time.monotonic()<deadline, 'question readiness timeout'
                    time.sleep(.1)
                adapter._rpc('session/cancel', {'sessionId':sid})
            assert browser.wait(timeout=90)==0, 'question browser failed; inspect browser.json'
            while True:
                value = received.get(timeout=40)
                if isinstance(value,Exception):
                    raise value
                if value is None:
                    break
                frames.append(value)
            events = [f['event'] for f in frames if 'event' in f]
            assert events[-1]['type']=='turn/end', 'question turn did not end'
            results = [e['data']['message'] for e in events if e['type']=='tool/result']
            assert len(results)==1
            assert results[0]['source']['callId']=='call-0'
            if decision!='cancel':
                assert not results[0].get('isError',False)
                result = json.loads(results[0]['content'][0]['text'])
                expected = {'id':'format-choice','selected':[answer]} if decision=='option' else {
                    'id':'format-choice','selected':[],'custom':answer}
                assert result['answers']==[expected], result
            else:
                assert results[0].get('isError') is True, 'cancelled question reported success'
            report['checks']['question_'+decision] = {
                'browser':json.loads((directory/'browser.json').read_text(encoding='utf8')),
                'correlated_result':True, 'turn_ended':True}
        finally:
            if browser is not None and browser.poll() is None:
                browser.kill();browser.wait(timeout=10)
            reader.join(timeout=5)
            if reader.is_alive():
                adapter.close();reader.join(timeout=5)
            if not reader.is_alive():
                stream.close()
            (directory/'events.json').write_text(json.dumps(frames,ensure_ascii=False,indent=2),encoding='utf8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sumika-shell', action='store_true', help='Exercise actual Sumika shell, managed profile and iframe')
    parser.add_argument('--approvals-only', action='store_true', help='Only approval decisions; omit additional attachment acceptance')
    parser.add_argument('--questions-only', action='store_true', help='Exercise native question option/custom/cancel, requires shell')
    args = parser.parse_args()
    base = SOURCE / '.sumika-next' / ('native-approval-ui-' + uuid.uuid4().hex)
    home, work = base / 'home', base / 'approval-ui-project'
    home.mkdir(parents=True)
    work.mkdir()
    previous_data = os.environ.get('SUMIKA_DATA_DIR')
    shell = None
    shell_thread = None
    if args.sumika_shell:
        from sumika_next.daily import default_home
        from ui.server import serve
        import ui.server as server_module
        assert Path(server_module.__file__).resolve().is_relative_to(ROOT), 'wrong Bridge import root'
        os.environ['SUMIKA_DATA_DIR'] = str(base/'personal-data')
        home = default_home(ROOT)
        home.mkdir(parents=True)
        shell = serve(base/'personal-data/role-model-settings.json', port=0, workbench_root=ROOT,
                      schedule_directory=base/'schedules')
        shell_thread = threading.Thread(target=shell.serve_forever, daemon=True)
        shell_thread.start()
    worker = base / 'extensions/desktop/review_service.py'
    worker.parent.mkdir(parents=True)
    # A normal host interpreter resolves the isolated sentinel package from cwd.
    # Bundled Python deliberately pins product imports through its _pth file.
    for directory in (worker.parent, worker.parent.parent):
        (directory/'__init__.py').write_text('', encoding='utf8')
    worker_python = os.environ.get('SUMIKA_FIXTURE_PYTHON') or shutil.which('python')
    if not worker_python:
        raise RuntimeError('host Python required for isolated approval sentinel')
    worker.write_text(
        "import json,sys\nfrom pathlib import Path\n"
        "request=json.load(sys.stdin)\n"
        f"with Path({str(base / 'worker-executed')!r}).open('a',encoding='utf8') as f: f.write(request['request_id']+'\\n')\n"
        "print(json.dumps({'state':'completed','response':'LOCAL_ONLY'}))\n", encoding='utf8')
    report = {'passed': False, 'external_messages': 0, 'checks': {}, 'candidate': str(ROOT),
              'boundary': 'Native DSH UI/protocol plus product approval adapter; isolated local worker only.'}
    if shell:
        report['bridge_module'] = str(Path(server_module.__file__).resolve())
    report['sentinel_python'] = worker_python
    adapter = Dsh(ROOT, home)
    with ModelFixture() as model:
        (home / '.env').write_text('DEEPSEEK_API_KEY=local-fixture-not-a-secret\n', encoding='utf8')
        config = dict(enabled=True, projects=[str(work)], workPresets=['standard'], root=str(base),
                      python=worker_python, registry=str(base / 'auth.json'),
                      runtimeEntry=str((ROOT / 'runtime/dsh/node_modules/@deepseek-ai/dsh/package.json').resolve()))
        # This is an isolated local approval test. The product correctly keeps
        # external review disabled until its user setting explicitly enables it.
        review_settings = json.dumps({
            'schema_version': 1, 'enabled': True,
            # Approval transport is tested with a local sentinel, no website
            # authorization or binding is granted by this fixture.
            'sites': {}
        })
        Path(config['registry']).write_text(review_settings, encoding='utf8')
        # The managed shell adapter migrates the plugin to its own personal
        # data registry; initialize that isolated user setting as well.
        (base / 'personal-data' / 'browser-authorizations.json').write_text(
            review_settings, encoding='utf8')
        (home / 'cordis.patch.yml').write_text(json.dumps([
            {'id': 'session-title-llm', 'disabled': True},
            {'id': 'llm-deepseek', 'config': {'baseURL': model.url}},
            {'id': 'session-telemetry-otel', 'disabled': True},
            {'insert': [{'id': 'sumika-web-review', 'name': str(ROOT / 'extensions/desktop/review_dsh.mjs'), 'config': config}]},
        ]), encoding='utf8')
        try:
            if shell:
                # Managed installation refreshes transport paths by design.
                # Substitute ONLY the child worker in this isolated profile,
                # after the real installer ran and before DSH starts. Product
                # plugin code, pre-execution scope and approval gate stay real.
                from extensions.desktop.review_install import install
                def install_sentinel(profile_home, **kwargs):
                    assert Path(profile_home).resolve() == home.resolve()
                    assert Path(kwargs['registry']).resolve().is_relative_to(base)
                    result = install(profile_home, **kwargs)
                    profile_patch = Path(profile_home) / 'cordis.patch.yml'
                    rows = json.loads(profile_patch.read_text(encoding='utf8'))
                    entries = [entry for row in rows for entry in row.get('insert', [])
                               if entry.get('id') == 'sumika-web-review']
                    assert len(entries) == 1
                    entries[0]['config']['python'] = worker_python
                    entries[0]['config']['runner'] = str(worker)
                    profile_patch.write_text(json.dumps(rows), encoding='utf8')
                    return result
                with patch('extensions.desktop.review_install.install', side_effect=install_sentinel):
                    shell.sumika_bridge.workbench.start()
                adapter = shell.sumika_bridge.workbench.adapter
                report['worker_boundary'] = 'Test-only post-install runner substitution in isolated profile; real product plugin and UI approval, no BrowserSkill or site grants.'
                report['boundary'] = 'Actual Sumika shell, skin and managed DSH approval UI; local deterministic model/worker only.'
            else:
                adapter.start()
            workspace = adapter._rpc('workspace/create', {'path': str(work)})['workspace']['workspaceId']
            for decision in ([] if args.questions_only else ['reject', 'cancel', 'allow']):
                directory = base / decision
                directory.mkdir()
                sid = 'approval-ui-' + decision
                title = 'Approval UI ' + decision
                adapter._rpc('session/create', {'sessionId': sid, 'workspaceId': workspace})
                adapter._rpc('session/rename', {'sessionId': sid, 'title': title})
                model.responses = 0
                model.recipe = [('web_review_submit', {'site': 'chatgpt.com', 'prompt': 'LOCAL_ONLY approval acceptance'})]
                events = []
                stream = adapter.stream('session/follow', {'address': {'kind': 'session', 'sessionId': sid}}, timeout=100)
                next(stream)
                received = queue.Queue()
                def drain():
                    try:
                        for frame in stream:
                            received.put(frame)
                            if frame.get('event', {}).get('type') == 'turn/end':
                                break
                    except Exception as error:
                        received.put(error)
                    finally:
                        received.put(None)
                reader = threading.Thread(target=drain, daemon=True)
                reader.start()
                try:
                    prompt(adapter, sid, 'Run one local approval probe; do not retry.')
                    while True:
                        frame = received.get(timeout=100)
                        if isinstance(frame, Exception):
                            raise frame
                        if frame is None:
                            raise RuntimeError('event stream ended before terminal evidence')
                        event = frame.get('event', {})
                        if not event:
                            continue
                        events.append(event)
                        if event['type'] == 'approval/asked':
                            assert not (base / 'worker-executed').exists(), 'worker ran before permission'
                            browser = subprocess.Popen(['node', str(SOURCE / 'tools/verify_native_approval_ui.mjs')],
                                stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                text=True, encoding='utf8')
                            try:
                                url = f'http://127.0.0.1:{shell.server_port}/#board' if shell else adapter._browser_url
                                browser.stdin.write(json.dumps(dict(url=url, shell=bool(shell), title=title, decision=decision, approvalsOnly=args.approvals_only, directory=str(directory))))
                                browser.stdin.close()
                                if decision == 'cancel':
                                    deadline = time.monotonic() + 60
                                    while not (directory / 'ready.json').exists():
                                        assert browser.poll() is None, 'browser exited before cancellation was ready'
                                        assert time.monotonic() < deadline, 'approval UI readiness timed out'
                                        time.sleep(.1)
                                    adapter._rpc('session/cancel', {'sessionId': sid})
                                assert browser.wait(timeout=90) == 0, 'browser failed; inspect browser.json and screenshot'
                            finally:
                                if browser.poll() is None:
                                    browser.kill()
                                    browser.wait(timeout=10)
                        if event['type'] == 'turn/end':
                            break
                finally:
                    reader.join(timeout=5)
                    if reader.is_alive():
                        adapter.close()
                        reader.join(timeout=5)
                    if not reader.is_alive():
                        stream.close()
                    (directory / 'events.json').write_text(json.dumps(events, ensure_ascii=False, indent=2), encoding='utf8')
                asked = [e for e in events if e['type'] == 'approval/asked']
                decided = [e for e in events if e['type'] == 'approval/decided']
                assert len(asked) == len(decided) == 1
                outcome = decided[0]['data']['outcome']
                assert asked[0]['data']['id'] == decided[0]['data']['id'], 'decision belongs to another approval'
                results = [e for e in events if e['type'] == 'tool/result']
                assert len(results) == 1
                result_data = results[0]['data']
                if decision != 'cancel':
                    assert result_data['message']['source']['callId'] == asked[0]['data']['callId']
                    message = result_data['message']
                    blocks = message['content']
                    assert len(blocks) == 1
                    # 0.2 uses standard message-level isError and text blocks;
                    # retain the old nested result contract for older runtimes.
                    assert message.get('isError', blocks[0].get('isError', False)) is (decision == 'reject')
                    if decision == 'allow':
                        value = json.loads(blocks[0]['text'] if blocks[0].get('type') == 'text'
                                           else blocks[0]['content'][0]['text'])
                        assert value['state'] == 'completed' and value['process_ok'] is True
                        assert value['response'] == 'LOCAL_ONLY'
                        assert (base / 'worker-executed').read_text(encoding='utf8').splitlines() == [value['request_id']]
                report['checks'][decision] = {'outcome': outcome, 'browser': json.loads((directory / 'browser.json').read_text(encoding='utf8')),
                                             'approval_correlated': True, 'tool_results': len(results)}
                if decision in ('reject', 'cancel'):
                    assert outcome == ('rejected' if decision == 'reject' else 'cancelled')
                    assert not (base / 'worker-executed').exists()
                    if decision == 'cancel':
                        assert results[0]['data'].get('error', {}).get('code') == 'ABORTED_BEFORE_DISPATCH'
                else:
                    assert outcome == 'allowed-once', outcome
                    assert len((base / 'worker-executed').read_text(encoding='utf8').splitlines()) == 1
                assert events[-1]['type'] == 'turn/end'
            if args.questions_only:
                verify_questions(adapter,model,shell,workspace,base,report)
            if shell and not args.approvals_only and not args.questions_only:
                second = base/'attachment-second-project'
                second.mkdir()
                other_workspace = adapter._rpc('workspace/create', {'path':str(second)})['workspace']['workspaceId']
                adapter._rpc('session/create', {'sessionId':'attachment-other','workspaceId':other_workspace})
                adapter._rpc('session/rename', {'sessionId':'attachment-other','title':'Other project session'})
                # Native navigation intentionally hides non-current blank sessions.
                other_stream=adapter.stream('session/follow',{'address':{'kind':'session','sessionId':'attachment-other'}})
                next(other_stream)
                prompt(adapter,'attachment-other','LOCAL_OTHER_PROJECT: navigation fixture only.')
                finish(other_stream)
                directory=base/'attachment-send'
                directory.mkdir()
                payload='LOCAL_FILE_CONTENT_中文_7dd26c: exact attachment bytes.'
                digest=hashlib.sha256(payload.encode('utf8')).hexdigest()
                saved=home/'attachments/v1/files'/digest[:2]/digest/'submitted-note.txt'
                # Preserve indices: this session already contains call-0 from approval.
                # Reusing a tool-call ID creates an invalid multi-turn history.
                model.recipe=[('$unused',{})]*model.responses+[('read',{'file_path':str(saved)})]
                before=len(model.requests)
                browser=subprocess.run(['node',str(SOURCE/'tools/verify_native_approval_ui.mjs')],
                    input=json.dumps(dict(url=f'http://127.0.0.1:{shell.server_port}/#board',shell=True,
                        title='Approval UI allow',mode='attachment-send',payload=payload,directory=str(directory))),
                    text=True,encoding='utf8',stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=120)
                report['attachment_submission']={'browser':json.loads((directory/'browser.json').read_text(encoding='utf8'))}
                new_requests=model.requests[before:]
                (directory/'model-requests.json').write_text(json.dumps(new_requests,ensure_ascii=False,indent=2),encoding='utf8')
                state=snapshot(adapter,'approval-ui-allow')
                (directory/'snapshot.json').write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding='utf8')
                assert browser.returncode==0, 'attachment browser failed; inspect evidence'
                assert len(new_requests)==2, 'expected attachment request and one tool-result continuation'
                assert 'submitted-note.txt' in json.dumps(new_requests), 'attachment reference missing from model request'
                tool_messages=[m for m in new_requests[-1].get('messages',[]) if m.get('role')=='tool']
                assert any(payload in json.dumps(m,ensure_ascii=False) for m in tool_messages), 'attachment bytes did not reach model through read tool'
                report['attachment_submission']['one_submission_two_model_requests_with_read_result']=True
                report['attachment_submission']['integrity']=verify_file_evidence(home,payload,new_requests,state)
                old_process=adapter.process
                shell.sumika_bridge.workbench.stop()
                assert old_process.poll() is not None, 'old managed instance still running'
                shell.sumika_bridge.workbench.start()
                adapter=shell.sumika_bridge.workbench.adapter
                restored=snapshot(adapter,'approval-ui-allow')
                (directory/'restarted-snapshot.json').write_text(json.dumps(restored,ensure_ascii=False,indent=2),encoding='utf8')
                verify_file_evidence(home,payload,new_requests,restored)
                assert len(model.requests)==before+2, 'restart replayed model request'
                report['attachment_submission']['server_restart_restored_attachment_without_replay']=True
            report['loopback_model_calls'] = len(model.requests)
            report['external_model_calls'] = 0
            report['passed'] = True
        finally:
            if shell:
                shell.shutdown()
                shell.server_close()
                shell_thread.join(timeout=5)
                if previous_data is None:
                    os.environ.pop('SUMIKA_DATA_DIR',None)
                else:
                    os.environ['SUMIKA_DATA_DIR']=previous_data
            else:
                adapter.close()
            report['owned_process_stopped'] = adapter.process is None or adapter.process.poll() is not None
            (base / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf8')
            print('ARTIFACT', base, flush=True)


if __name__ == '__main__':
    main()
