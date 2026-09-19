"""Real isolated DSH approval/cancellation probe. No website messages or paid models."""
import json
import argparse
from pathlib import Path
import sys
import uuid
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tests_next'),str(ROOT/'tools')]
from p2_fixture import ModelFixture
from sumika_next.dsh import Dsh
from verify_dsh_recovery import prompt,snapshot
from extensions.diagnostics.dsh import project_page

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--decision', choices=['cancel','reject'], default='cancel')
    decision=parser.parse_args().decision
    base=ROOT/'.sumika-next'/('web-review-native-'+uuid.uuid4().hex)
    home=base/'home';work=base/'work'
    home.mkdir(parents=True);work.mkdir()
    report={'passed':False,'external_messages':0,'production_changed':False,'decision':decision,
            'boundary':'Native approval service test; synthetic answerer is not a browser click acceptance.'}
    # Even if the approval gate fails, this isolated worker cannot send externally.
    worker=base/'extensions/desktop/review_service.py'
    worker.parent.mkdir(parents=True)
    worker.write_text("from pathlib import Path\nPath('worker-executed').write_text('unexpected dispatch')\nraise SystemExit(1)\n",encoding='utf8')
    answerer=base/'reject.mjs'
    answerer.write_text("export function apply(ctx) { ctx.on('approval/request', async (req, next) => req.toolName === 'web_review_submit' ? 'rejected' : next()); }",encoding='utf8')
    events=[]
    with ModelFixture() as model:
        model.recipe=[('web_review_submit',{'site':'chatgpt.com','prompt':'Synthetic local approval probe. Do not send.'})]
        (home/'.env').write_text('DEEPSEEK_API_KEY=local-fixture-not-a-secret\n',encoding='utf8')
        config=dict(enabled=True,projects=[str(work)],workPresets=['standard'],root=str(base),
                    python=sys.executable,registry=str(base/'auth.json'),
                    runtimeEntry=str((ROOT/'runtime/dsh/node_modules/@deepseek-ai/dsh/package.json').resolve()))
        patches=[
            {'id':'session-title-llm','disabled':True},
            {'id':'llm-deepseek','config':{'baseURL':model.url}},
            {'id':'session-telemetry-otel','disabled':True},
            {'insert':[{'id':'sumika-web-review','name':str(ROOT/'extensions/desktop/review_dsh.mjs'),'config':config}]}
        ]
        if decision=='reject':
            patches.append({'insert':[{'id':'local-test-rejection','name':str(answerer)}]})
        (home/'cordis.patch.yml').write_text(json.dumps(patches),encoding='utf8')
        adapter=Dsh(ROOT,home)
        try:
            adapter.start()
            sid='web-review-approval'
            adapter._rpc('session/create',{'sessionId':sid,'cwd':str(work)})
            stream=adapter.stream('session/follow',{'address':{'kind':'session','sessionId':sid}},timeout=30)
            first=next(stream)
            (base/'initial.json').write_text(json.dumps(first),encoding='utf8')
            prompt(adapter,sid,'Run the synthetic approval probe once; do not retry.')
            try:
                for frame in stream:
                    event=frame.get('event',{})
                    if event:events.append(event)
                    typ=event.get('type','')
                    if typ=='approval/asked' and not report.get('cancel_requested'):
                        print('APPROVAL_EVENT',typ,flush=True)
                        report['approval_event']=typ
                        if decision=='cancel':
                            adapter._rpc('session/cancel',{'sessionId':sid})
                            report['cancel_requested']=True
                        continue
                    if typ=='turn/end':break
            finally:stream.close()
            assert report.get('approval_event'), 'native approval event absent; inspect isolated evidence'
            assert not (base/'browser-consultations.sqlite3').exists(), 'worker ran before approval'
            assert not (base/'worker-executed').exists(), 'tool execution bypassed approval'
            report['post_cancel_events']=[e['type'] for e in events if 'approval' in e['type'] or e['type']=='tool/result']
            expected='cancelled' if decision=='cancel' else 'rejected'
            assert any(e['type']=='approval/decided' and e['data'].get('outcome')==expected for e in events), 'expected approval decision absent'
            errors=[e['data'].get('error',{}).get('code') for e in events if e['type']=='tool/result']
            report['tool_error_codes']=errors
            if decision=='cancel':
                assert 'ABORTED_BEFORE_DISPATCH' in errors, 'tool body may have run'
            else:
                blocks=[b for e in events if e['type']=='tool/result'
                        for b in e['data'].get('message',{}).get('content',[])]
                assert any(b.get('isError') is True for b in blocks), 'rejected tool must report isError'
            projected=project_page({'hasMore':False,'records':[{'type':'event','event':e} for e in events]},
                                   session=sid,version='0.1.5-rc.2',through_seq=events[-1]['seq'])
            asked=next(e for e in projected['events'] if e['kind']=='approval/asked')
            decided=next(e for e in projected['events'] if e['kind']=='approval/decided')
            assert asked['approval_id']==decided['approval_id']
            assert decided['approval_outcome']==expected
            assert any(e['kind']=='tool/result' and e['status']=='error' and
                       set(e['call_ids']) & set(asked['call_ids']) for e in projected['events'])
            (base/'diagnostics.json').write_text(json.dumps(projected,indent=2),encoding='utf8')
            report['passed']=True
        finally:
            adapter.close()
            (base/'events.json').write_text(json.dumps(events,ensure_ascii=False,indent=2),encoding='utf8')
            (base/'report.json').write_text(json.dumps(report,indent=2),encoding='utf8')
            print('ARTIFACT',base,'REPORT',json.dumps(report),flush=True)

if __name__=='__main__':main()
