"""DSH rc.2 release acceptance with a local model fixture, never a paid model."""
import json
from pathlib import Path
import sys
import uuid
import time
import subprocess

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests_next'))
from p2_fixture import ModelFixture
from sumika_next.dsh import Dsh
from verify_dsh_recovery import snapshot, prompt, finish


def verify_terminal_lifecycle(adapter, model, work, base):
    evidence = {}
    for session, command, timeout, expected in [
        ('p2-exit', 'exit 7', 5000, '[exit code: 7]'),
        ('p2-timeout', "Start-Sleep -Seconds 3; 'late' | Set-Content timeout-late.txt", 300, '[exit code: 1]'),
    ]:
        model.responses = 0
        model.recipe = [('pwsh', {'command': command, 'description': 'Verify native terminal failure reporting', 'timeoutMs': timeout})]
        adapter._rpc('session/create', {'sessionId': session, 'cwd': str(work)})
        stream = adapter.stream('session/follow', {'address': {'kind': 'session', 'sessionId': session}}, timeout=30)
        next(stream)
        prompt(adapter, session, session)
        events = finish(stream)
        evidence[session] = events
        assert expected in json.dumps(events), (session, events)
    model.responses = 0
    model.recipe = [('pwsh', {
        'command': "$ErrorActionPreference='Stop'; 'started' | Set-Content started.txt; Start-Sleep -Seconds 6; 'late' | Set-Content cancel-late.txt",
        'description': 'Verify cancellation of active terminal work', 'timeoutMs': 15000})]
    session = 'p2-shell-cancel'
    adapter._rpc('session/create', {'sessionId': session, 'cwd': str(work)})
    prompt(adapter, session, session)
    deadline = time.monotonic() + 20
    while not (work/'started.txt').exists():
        assert time.monotonic() < deadline, 'terminal never started'
        time.sleep(.1)
    assert adapter._rpc('session/cancel', {'sessionId': session}) == {'accepted': True}
    time.sleep(7)
    assert not (work/'cancel-late.txt').exists(), 'cancelled command continued'
    assert not (work/'timeout-late.txt').exists(), 'timed out command continued'
    state = snapshot(adapter, session)
    evidence[session] = adapter._rpc('session/page', {'address': {'kind': 'session', 'sessionId': session}, 'throughSeq': state['cursor']})
    (base/'terminal-lifecycle.json').write_text(json.dumps(evidence, indent=2), encoding='utf-8')
    print('TERMINAL exit, timeout, active cancel verified', flush=True)


def main():
    with ModelFixture() as model:
        base = ROOT / '.sumika-next' / ('p2-' + uuid.uuid4().hex)
        base.mkdir()
        home = base/'home'
        work = base/'work'
        home.mkdir(); work.mkdir()
        subprocess.run(['git','init','-q',str(work)], check=True)
        skill = work/'.agents/skills/p2-local/SKILL.md'
        skill.parent.mkdir(parents=True)
        skill.write_text('---\nname: p2-local\ndescription: Local deterministic P2 skill fixture.\n---\nP2_SKILL_MARKER: read value.txt and report its exact content.\n', encoding='utf-8')
        model.recipe = [
            ('write', {'file_path':'value.txt','content':'41\n'}),
            ('read', {'file_path':'value.txt'}),
            ('edit', {'file_path':'value.txt','old_string':'41','new_string':'42'}),
            ('grep', {'pattern':'42','path':'.','include':'*.txt'}),
            ('glob', {'pattern':'*.txt'}),
            ('pwsh', {'command':"$ErrorActionPreference = 'Stop'; if ((Get-Content -LiteralPath 'value.txt' -Raw).Trim() -ne '42') { exit 1 }; 'verified' | Set-Content -LiteralPath 'test-result.txt'; Write-Output P2_TEST_PASS",'description':'Verify fixture file content using PowerShell','workdir':str(work)}),
            ('skill', {'name':'p2-local'}),
            ('subagent', {'description':'Check local fixture response','prompt':'P2_CHILD return P2_CHILD_DONE','run_in_background':False}),
            ('list_agents', {}),
            ('$mcp', {'text':'P2_MCP_CHALLENGE'}),
        ]
        (home/'.env').write_text('DEEPSEEK_API_KEY=p2-local-fixture-not-a-secret\n', encoding='utf-8')
        patches = [
            {'id':'session-title-llm','disabled':True},
            {'id':'llm-deepseek','config':{'baseURL':model.url}},
            {'id':'session-telemetry-otel','disabled':True},
            {'insert':[{'id':'p2-mcp','name':'@deepseek-ai/dsh-mcp-client','config':{'transport':'stdio','serverName':'p2','command':sys.executable,'args':['-u',str(ROOT/'tests_next/p2_mcp_server.py')],'failOnStartupError':True}}]},
        ]
        (home/'cordis.patch.yml').write_text(json.dumps(patches), encoding='utf-8')
        adapter = Dsh(ROOT, home)
        report = {'complete': False, 'checks': {}}
        try:
            adapter.start()
            adapter._rpc('session/create', {'sessionId':'p2-main','cwd':str(work)})
            frames = adapter.stream('session/follow', {'address':{'kind':'session','sessionId':'p2-main'}})
            collected = [next(frames)]
            print('OPENING cursor', collected[0]['cursor'], flush=True)
            print('PROMPT', adapter._rpc('session/prompt', {'sessionId':'p2-main','requestId':'p2-request','mode':'queue','content':[{'type':'text','text':'P2_FIXTURE integration test'}]}), flush=True)
            for frame in frames:
                collected.append(frame)
                kind=frame.get('event',{}).get('type',frame.get('type'))
                print('EVENT', kind, flush=True)
                if kind=='turn/end': break
            frames.close()
            (base/'events.json').write_text(json.dumps(collected,ensure_ascii=False,indent=2), encoding='utf-8')
            assert (work/'value.txt').read_text().strip()=='42'
            results = [f['event']['data']['message']['content'] for f in collected if f.get('event',{}).get('type')=='tool/result']
            assert len(results) == 10, 'expected all native tools to execute'
            assert all(not block.get('isError') for blocks in results for block in blocks), results
            assert 'P2_SKILL_MARKER' in json.dumps(results), 'skill missing'
            assert 'P2_MCP_CHALLENGE' in json.dumps(results), 'MCP missing'
            assert 'P2_CHILD_DONE' in json.dumps(results), 'subagent missing'
            assert 'P2_TEST_PASS' in json.dumps(results) and '[stderr]' not in json.dumps(results), 'terminal test failed'
            assert (work/'test-result.txt').read_text().strip() == 'verified'
            print('FILE_VERIFIED', flush=True)
            verify_terminal_lifecycle(adapter, model, work, base)
            report['checks'] = dict.fromkeys(['files', 'terminal_test', 'skills', 'subagent', 'mcp', 'terminal_exit_timeout_cancel'], True)
            report['complete'] = True
        finally:
            if not model.requests: print('STARTUP', list(adapter.startup_messages), flush=True)
            adapter.close()
            (base/'model-requests.json').write_text(json.dumps(model.requests,ensure_ascii=False,indent=2), encoding='utf-8')
            (base/'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
            print('ARTIFACT', base, 'MODEL_REQUESTS', len(model.requests), flush=True)


if __name__ == '__main__': main()
