"""DSH rc.2 release acceptance with a local model fixture, never a paid model."""
import json
from pathlib import Path
import sys
import tempfile
import time
import subprocess

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests_next'))
from p2_fixture import ModelFixture
from sumika_next.dsh import Dsh


def main():
    with ModelFixture() as model:
        base = Path(tempfile.mkdtemp(prefix='p2-', dir=ROOT/'.sumika-next'))
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
            ('pwsh', {'command':f"$ErrorActionPreference = 'Stop'; if ((Get-Content '{str(work / 'value.txt').replace(chr(92), chr(92)+chr(92))}' -Raw).Trim() -ne '42') {{ exit 1 }}; Write-Output P2_TEST_PASS",'description':'Verify fixture file content using PowerShell','workdir':str(work)}),
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
            assert all(not block.get('isError') for blocks in results for block in blocks), results
            assert 'P2_SKILL_MARKER' in json.dumps(results), 'skill missing'
            assert 'P2_MCP_CHALLENGE' in json.dumps(results), 'MCP missing'
            assert 'P2_TEST_PASS' in json.dumps(results) and '[stderr]' not in json.dumps(results), 'terminal test failed'
            print('FILE_VERIFIED', flush=True)
        finally:
            if not model.requests: print('STARTUP', list(adapter.startup_messages), flush=True)
            adapter.close()
            (base/'model-requests.json').write_text(json.dumps(model.requests,ensure_ascii=False,indent=2), encoding='utf-8')
            print('ARTIFACT', base, 'MODEL_REQUESTS', len(model.requests), flush=True)


if __name__ == '__main__': main()
