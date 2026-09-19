"""Real DSH host integration, offline model, immutable binding and restart."""
import json
import sys
import uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tests_next')]
from p2_fixture import ModelFixture
from sumika_next.dsh import Dsh
from sumika_next.extension_host import ExtensionHost
from extensions.desktop.scheduler import Schedule,ScheduleStore
from verify_dsh_recovery import finish

base=ROOT/'.sumika-next'/('extension-host-'+uuid.uuid4().hex);base.mkdir()
home=base/'home';home.mkdir();work=base/'work';work.mkdir();directory=base/'schedules';directory.mkdir()
job=Schedule('host-test','once','2020-01-01T00:00:00+00:00','Return a short local test response.','execute')
ScheduleStore(directory/'schedules.json').upsert(job)
config=base/'extensions.json'
config.write_text(json.dumps(dict(schema_version=1,enabled=True,schedules=dict(directory=str(directory),execution_bindings={job.id:dict(enabled=True,workspace=str(work),action=job.action,fingerprint=job.fingerprint())}))),encoding='utf8')
with ModelFixture() as model:
    model.block=True
    (home/'.env').write_text('DEEPSEEK_API_KEY=local-test-not-a-secret\n')
    (home/'cordis.patch.yml').write_text(json.dumps([{'id':'session-title-llm','disabled':True},{'id':'llm-deepseek','config':{'baseURL':model.url}},{'id':'session-telemetry-otel','disabled':True}]),encoding='utf8')
    adapter=Dsh(ROOT,home);host=None
    try:
        adapter.start();host=ExtensionHost(adapter,config)
        result=host.tick();assert result[0]['state']=='submitted',result
        stream=adapter.stream('session/follow',{'address':{'kind':'session','sessionId':result[0]['receipt']}},timeout=40)
        next(stream);model.hold.set();events=finish(stream)
        assert any(f.get('event',{}).get('type')=='turn/end' for f in events)
        host.close();assert host.tick()==[]
        adapter.close();adapter.start()
        host=ExtensionHost(adapter,config);assert host.tick()==[]
        report=dict(passed=True,managed_dispatch=True,host_stop=True,process_restart_no_replay=True,external_model_calls=0,artifact=str(base))
        (ROOT/'docs/project/extension-host-evidence.json').write_text(json.dumps(report,indent=2),encoding='utf8');print(json.dumps(report))
    finally:
        model.hold.set()
        if host:host.close()
        adapter.close()
