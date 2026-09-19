"""Real DSH role preset routing, no tools, work-default isolation; local models."""
import json
import sys
import uuid
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tests_next')]
from p2_fixture import ModelFixture
from sumika_next.dsh import Dsh
from extensions.roles.preset import install
from verify_dsh_recovery import finish,prompt

base=ROOT/'.sumika-next'/('role-model-'+uuid.uuid4().hex);base.mkdir()
home=base/'home';home.mkdir();work=base/'work';work.mkdir();role=base/'role';role.mkdir()
(role/'role.json').write_text(json.dumps(dict(id='fixture',name='Fixture',persona='Synthetic companion',worldbook=[],assets={})),encoding='utf8')
config=base/'role.json';config.write_text(json.dumps(dict(role_dir=str(role),database=str(base/'memory.db'),user_id='fixture',project_id='fixture',work_model='deepseek-chat',role_model='deepseek-v4-pro')),encoding='utf8')
preset_args=dict(model='deepseek-v4-pro',runtime_entry=ROOT/'runtime/dsh/node_modules/@deepseek-ai/dsh/package.json',role_config=config,workspace=work,python=sys.executable)
install(base/'presets'/'sumika-role',provider='deepseek-official',**preset_args)
install(base/'presets'/'sumika-disabled',provider='deepseek-official',enabled=False,**preset_args)
install(base/'presets'/'sumika-unavailable',provider='missing-fixture-provider',**preset_args)
with ModelFixture() as model:
    (home/'.env').write_text('DEEPSEEK_API_KEY=local-fixture-not-a-secret\n')
    patches=[{'id':'session-title-llm','disabled':True},{'id':'llm-deepseek','config':{'baseURL':model.url}},{'id':'session-telemetry-otel','disabled':True},{'id':'agent-presets','config':{'default':'standard','roots':[{'path':str(base/'presets'),'trust':'user'}]}}]
    (home/'cordis.patch.yml').write_text(json.dumps(patches),encoding='utf8')
    adapter=Dsh(ROOT,home)
    def turn(session,preset_id=None,expected_error=None):
        count=len(model.requests)
        args=dict(sessionId=session,cwd=str(work))
        if preset_id:args['agentPreset']=preset_id
        adapter._rpc('session/create',args)
        stream=adapter.stream('session/follow',{'address':{'kind':'session','sessionId':session}},timeout=45)
        try:
            next(stream);prompt(adapter,session,'original fixture text');events=finish(stream)
        finally:stream.close()
        if expected_error:
            assert len(model.requests)==count
            assert expected_error in json.dumps(events,ensure_ascii=False)
            return
        assert len(model.requests)>count,json.dumps(events,ensure_ascii=False)
        return model.requests[-1]
    try:
        adapter.start()
        before=turn('work-before')
        companion=turn('role','sumika-role')
        turn('disabled','sumika-disabled','role model disabled')
        turn('unavailable','sumika-unavailable','NO_ADAPTER')
        after=turn('work-after')
        assert before['model']==after['model'],(before['model'],after['model'])
        assert companion['model']=='deepseek-v4-pro',companion['model']
        assert not companion.get('tools'),'role preset unexpectedly exposes tools'
        assert 'SUMIKA_ROLE_CONTEXT' in json.dumps(companion)
        assert 'SUMIKA_ROLE_CONTEXT' not in json.dumps(before)+json.dumps(after)
        assert 'original fixture text' in json.dumps(companion)
        evidence=dict(passed=True,role_model=companion['model'],work_model=before['model'],work_default_unchanged=True,disabled_no_request=True,unavailable_no_fallback=True,role_tools=0,separate_sessions=True,external_model_calls=0,artifact=str(base))
        (ROOT/'docs/project/role-model-evidence.json').write_text(json.dumps(evidence,indent=2),encoding='utf8')
        print(json.dumps(evidence))
    except Exception:
        print('\n'.join(adapter.startup_messages),file=sys.stderr)
        raise
    finally:adapter.close()

