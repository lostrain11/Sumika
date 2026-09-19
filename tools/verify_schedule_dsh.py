"""Real DSH scheduled prompt, restart dedup and native cancellation; local model."""
import json
from pathlib import Path
import sys
import uuid
import time
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tests_next')]
from p2_fixture import ModelFixture
from sumika_next.dsh import Dsh
from extensions.desktop.scheduler import Schedule
from extensions.desktop.schedule_service import ScheduleService
from extensions.desktop.schedule_dsh import DshScheduleBridge
from verify_dsh_recovery import finish,snapshot

base=ROOT/'.sumika-next'/('schedule-'+uuid.uuid4().hex);base.mkdir()
home=base/'home';home.mkdir();work=base/'work';work.mkdir()
with ModelFixture() as model:
    model.block=True
    (home/'.env').write_text('DEEPSEEK_API_KEY=local-fixture-not-a-secret\n')
    (home/'cordis.patch.yml').write_text(json.dumps([{'id':'session-title-llm','disabled':True},{'id':'llm-deepseek','config':{'baseURL':model.url}},{'id':'session-telemetry-otel','disabled':True}]),encoding='utf8')
    adapter=Dsh(ROOT,home);service=None
    try:
        adapter.start()
        bridge=DshScheduleBridge(adapter,{'test':dict(enabled=True,workspace=str(work),action='Return a short scheduled test result.')})
        service=ScheduleService(work/'schedules.json',work/'history.db',bridge=bridge)
        service.store.upsert(Schedule('test','once','2026-01-01T00:00:00+00:00','Return a short scheduled test result.','execute'))
        service.store.upsert(Schedule('reminder','once','2026-01-01T00:00:00+00:00','Local reminder only'))
        results=service.tick(datetime.now(timezone.utc))
        execution=next(r for r in results if r['id']=='test')
        assert execution['state']=='submitted',results
        stream=adapter.stream('session/follow',{'address':{'kind':'session','sessionId':execution['receipt']}},timeout=45)
        next(stream);model.hold.set();events=finish(stream)
        assert any(f.get('event',{}).get('type')=='turn/end' for f in events)
        assert len(service.reminders())==1
        cancelled=service.cancel('test',execution['due']);assert cancelled['status']=='cancel_requested'
        model.hold.clear();model.waiting.clear()
        bridge.bindings['active']=dict(enabled=True,workspace=str(work),action='Wait for cancellation test.')
        service.store.upsert(Schedule('active','once','2026-01-01T00:00:00+00:00','Wait for cancellation test.','execute'))
        active=next(r for r in service.tick(datetime.now(timezone.utc)) if r['id']=='active')
        assert model.waiting.wait(10),'model did not start'
        service.cancel('active',active['due'])
        model.hold.set()
        deadline=time.monotonic()+25
        while True:
            snap=snapshot(adapter,active['receipt'])
            records=adapter._rpc('session/page',{'address':{'kind':'session','sessionId':active['receipt']},'throughSeq':snap['cursor']})['records']
            observed=[r['event'] for r in records if r.get('type')=='event']
            if observed and observed[-1]['type']=='step/end':break
            assert time.monotonic()<deadline,'cancellation not persisted'
            time.sleep(.2)
        assert not any(e['type'] in ('tool/call','assistant/message') for e in observed)
        request_count=len(model.requests);time.sleep(.5)
        assert len(model.requests)==request_count
        reason='native step ended without tool or assistant output'
        service.close();service=ScheduleService(work/'schedules.json',work/'history.db',bridge=bridge)
        assert service.tick(datetime.now(timezone.utc))==[]
        report=dict(passed=True,scheduled_prompt=True,reminder_local=True,restart_no_replay=True,cancel_request_accepted=True,cancel_test='active model request and idle completed session',cancel_reason=reason,external_model_calls=0,artifact=str(base))
        (ROOT/'docs/project/schedule-dsh-evidence.json').write_text(json.dumps(report,indent=2),encoding='utf8')
        print(json.dumps(report))
    finally:
        model.hold.set()
        if service:service.close()
        adapter.close()
