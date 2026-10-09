"""Real native plugin auto-injection, original-text integrity and disabled state."""
import json
import sys
import uuid
import argparse
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser()
parser.add_argument('--runtime', type=Path)
args=parser.parse_args()
sys.path[:0]=[str(ROOT),str(ROOT/'tests_next')]
from p2_fixture import ModelFixture
from sumika_next.dsh import Dsh
from extensions.memory.embedded_memory import EmbeddedMemory
from verify_dsh_recovery import finish,prompt

base=ROOT/'.sumika-next'/('role-plugin-'+uuid.uuid4().hex);base.mkdir()
home=base/'home';home.mkdir();work=base/'work';work.mkdir();role=base/'role';role.mkdir()
(role/'role.json').write_text(json.dumps(dict(id='test-role',name='Synthetic Role',persona='Fixture persona',worldbook=[],assets={})),encoding='utf8')
database=base/'memory.db';memory=EmbeddedMemory(database);memory.add('remembered-token is a synthetic fact',user_id='u',role_id='test-role',project_id='p');memory.close()
config=base/'role-config.json';config.write_text(json.dumps(dict(role_dir=str(role),database=str(database),user_id='u',project_id='p',work_model='work',role_model='role',enabled=True)),encoding='utf8')
original='记住[fixture]：auto-memory-token\n```diff\n+ original unchanged\n```'
with ModelFixture() as model:
    (home/'.env').write_text('DEEPSEEK_API_KEY=local-fixture-not-a-secret\n')
    runtime=(args.runtime or ROOT/'runtime/dsh').resolve()
    patches=[{'id':'session-title-llm','disabled':True},{'id':'llm-deepseek','config':{'baseURL':model.url}},{'id':'session-telemetry-otel','disabled':True},{'insert':[{'id':'sumika-roles','name':str(ROOT/'extensions/roles/dsh.mjs'),'config':dict(enabled=True,memoryWrites=True,memoryNamespace='isolated-fixture',projects={str(work):str(config)},python=sys.executable,core=str(ROOT/'extensions/roles/bridge.py'),runtimeEntry=str(runtime/'node_modules/@deepseek-ai/dsh/package.json'))}]}]
    patch=home/'cordis.patch.yml';patch.write_text(json.dumps(patches),encoding='utf8')
    adapter=Dsh(ROOT,home,runtime=runtime)
    def turn(session,text=original):
        adapter._rpc('session/create',{'sessionId':session,'cwd':str(work)})
        stream=adapter.stream('session/follow',{'address':{'kind':'session','sessionId':session}},timeout=45)
        try:
            next(stream);prompt(adapter,session,text)
            events=finish(stream)
            (base/(session+'-events.json')).write_text(json.dumps(events,ensure_ascii=False),encoding='utf8')
            errors=[e['event']['data'] for e in events if e.get('event',{}).get('type')=='turn/end'
                    and e['event']['data']['reason'].get('kind')!='completed']
            assert not errors, errors
        finally:stream.close()
    try:
        adapter.start();turn('role-enabled')
        wire=json.dumps(model.requests[-1],ensure_ascii=False)
        messages=model.requests[-1]['messages']
        assert json.dumps(messages,ensure_ascii=False).count('SUMIKA_ROLE_CONTEXT')==1
        memory=EmbeddedMemory(database)
        try:
            found=memory.search('auto-memory-token',user_id='u',role_id='test-role',project_id='p')
            assert len(found)==1 and found[0]['source']=='user'
            count=memory.db.execute('SELECT count(*) FROM memories').fetchone()[0]
        finally:memory.close()
        messages=model.requests[-1]['messages']
        assert any(original in (m['content'] if isinstance(m.get('content'),str) else
                   '\n'.join(b.get('text','') for b in m.get('content',[]) if b.get('type')=='text'))
                   for m in messages)
        turn('role-recall','auto-memory-token')
        assert '+ original unchanged' in json.dumps(model.requests[-1])
        adapter.close();adapter.start()
        turn('role-after-restart','auto-memory-token')
        assert '+ original unchanged' in json.dumps(model.requests[-1])
        # Keep role context on while disabling only automatic writes.
        adapter.close();patches[-1]['insert'][0]['config']['memoryWrites']=False;patch.write_text(json.dumps(patches),encoding='utf8')
        adapter.start();turn('write-disabled','记住：must-not-store-token')
        memory=EmbeddedMemory(database)
        try:
            assert memory.db.execute('SELECT count(*) FROM memories').fetchone()[0]==count
            assert not memory.search('must-not-store-token',user_id='u',role_id='test-role',project_id='p')
        finally:memory.close()
        adapter.close();patches[-1]['insert'][0]['config']['enabled']=False;patch.write_text(json.dumps(patches),encoding='utf8')
        adapter.start();turn('role-disabled')
        assert 'SUMIKA_ROLE_CONTEXT' not in json.dumps(model.requests[-1])
        report=dict(passed=True,runtime=str(runtime),auto_injection=True,explicit_memory_write=True,cross_session_recall=True,restart_recall=True,write_switch_independent=True,original_unchanged=True,disabled_no_injection=True,external_model_calls=0,artifact=str(base))
        (base/'report.json').write_text(json.dumps(report,indent=2),encoding='utf8')
        if args.runtime is None:
            (ROOT/'docs/project/role-plugin-evidence.json').write_text(json.dumps(report,indent=2),encoding='utf8')
        print(json.dumps(report))
    except Exception:
        print('\n'.join(adapter.startup_messages),file=sys.stderr)
        raise
    finally:adapter.close()
