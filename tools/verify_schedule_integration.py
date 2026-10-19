"""Exercise Sumika human-command scheduling with real DSH and a loopback model."""
import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import subprocess
import threading
import time
import uuid
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--product',type=Path,default=SOURCE)
    parser.add_argument('--output',type=Path,default=SOURCE/'.sumika-next/acceptance-20261018/schedule-integration')
    parser.add_argument('--browser',action='store_true')
    args=parser.parse_args()
    product=args.product.resolve()
    sys.path[:0]=[str(product),str(SOURCE/'tests_next'),str(SOURCE/'tools')]
    from p2_fixture import ModelFixture
    from ui.workbench import WorkbenchController
    from verify_dsh_recovery import snapshot
    sys.path.insert(0,str(product))
    base=args.output.resolve()/uuid.uuid4().hex
    home,work=base/'home',base/'work'
    home.mkdir(parents=True);work.mkdir()
    report={'passed':False,'product':str(product),'checks':{},'external_calls':0}
    controller=WorkbenchController(product)
    with ModelFixture() as model:
        (home/'.env').write_text('DEEPSEEK_API_KEY=local-fixture-not-a-secret\n',encoding='utf8')
        (home/'cordis.patch.yml').write_text(json.dumps([
            {'id':'session-title-llm','disabled':True},
            {'id':'llm-deepseek','config':{'baseURL':model.url}},
            {'id':'session-telemetry-otel','disabled':True}]),encoding='utf8')
        try:
            with patch('ui.workbench.default_home',return_value=home):controller.start()
            adapter=controller.adapter
            workspace=adapter._rpc('workspace/create',{'path':str(work)})['workspace']['workspaceId']
            sid='sumika-schedule-integration'
            adapter._rpc('session/create',{'sessionId':sid,'workspaceId':workspace})
            targets=controller.schedule_targets()
            assert any(p['id']==workspace and sid in p['sessions'] for p in targets['projects']),targets
            report['checks']['live_targets']=True
            created=[]
            payloads=[]
            for kind,expression in [('daily','09:00'),('weekly','6 23:50'),('once',(datetime.now(timezone.utc)+timedelta(seconds=35)).isoformat())]:
                rid=uuid.uuid4().hex
                payload={'request_id':rid,'confirmed':True,'workspace_id':workspace,'session_id':sid,
                         'definition':{'id':rid,'kind':kind,'expression':expression,'action':'SYNTHETIC_SUMIKA_'+kind,'mode':'execute','enabled':True,'timezone_name':'Asia/Shanghai'}}
                result=controller.create_native_schedule(payload)
                assert result.get('state')=='created',result
                created.append(result['record']);payloads.append(payload)
                repeated=controller.create_native_schedule(payload)
                assert repeated==result,(repeated,result)
            assert len(adapter._rpc('schedule/list',{'sessionId':sid}))==3
            assert not model.requests,model.requests
            report['checks']['three_rules_and_idempotency_without_model']=True
            try:controller.create_native_schedule({**payloads[0],'workspace_id':'forged'})
            except ValueError:pass
            else:raise AssertionError('forged workspace accepted')
            report['checks']['forged_target_refused']=True
            for record in created[:2]:
                assert adapter._rpc('schedule/delete',{'sessionId':sid,'id':record['id']})['deleted']
            controller.stop()
            with patch('ui.workbench.default_home',return_value=home):controller.start()
            adapter=controller.adapter
            assert controller.create_native_schedule(payloads[0])['record']['id']==created[0]['id']
            assert len(adapter._rpc('schedule/list',{'sessionId':sid}))==1
            assert not model.requests
            report['checks']['restart_no_recreation_of_deleted_task']=True
            deadline=time.monotonic()+80
            delivery_history={}
            while time.monotonic()<deadline:
                delivery_history=adapter._rpc('schedule/history',{'sessionId':sid,'id':created[2]['id'],'limit':10})
                if delivery_history.get('records'):break
                time.sleep(.2)
            assert delivery_history.get('records'),delivery_history
            # A command also emits turn/end, so a generic first-event wait can
            # accidentally accept an old command completion before due time.
            deadline=time.monotonic()+20
            while not model.requests and time.monotonic()<deadline:time.sleep(.2)
            assert model.requests and 'SYNTHETIC_SUMIKA_once' in json.dumps(model.requests), 'due task did not activate original-session model'
            deadline=time.monotonic()+20
            while True:
                current=snapshot(adapter,sid)
                page=adapter._rpc('session/page',{'address':{'kind':'session','sessionId':sid},'throughSeq':current['cursor']})
                events=[x['event'] for x in page['records'] if x.get('type')=='event']
                if events and events[-1]['type']=='turn/end':break
                assert time.monotonic()<deadline,'due model turn did not finish'
                time.sleep(.2)
            (base/'delivery.json').write_text(json.dumps(delivery_history,ensure_ascii=False,indent=2),encoding='utf8')
            report['checks']['native_due_delivery_after_restart']=True
            report['model_requests_after_due']=len(model.requests)
            if args.browser:
                from extensions.models.settings import example,save
                from ui.server import serve,BUILTIN_ROLES
                save(example(BUILTIN_ROLES/'sampleA',base/'personal/memory.sqlite3'),base/'personal/settings.json')
                server=serve(base/'personal/settings.json',port=0,workbench_root=product,
                    capability_database=base/'personal/capabilities.sqlite3',schedule_directory=base/'personal/schedules')
                server.sumika_bridge.workbench=controller
                threading.Thread(target=server.serve_forever,daemon=True).start()
                try:
                    subprocess.run(['node',str(SOURCE/'tools/verify_schedule_integration_ui.mjs')],
                        input=json.dumps({'base':'http://127.0.0.1:'+str(server.server_port),'output':str(base),'workspace':workspace,'session':sid}),
                        text=True,check=True,timeout=100)
                    report['checks']['real_bridge_browser_create_and_native_navigation']=True
                finally:server.shutdown();server.server_close()
            report['loopback_model_calls']=len(model.requests)
            report['passed']=True
        finally:
            controller.stop()
            (base/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
            print(json.dumps({'report':str(base/'report.json'),**report},ensure_ascii=False))


if __name__=='__main__':main()
