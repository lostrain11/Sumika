"""One-shot acceptance of explicitly approved text. Never rerun a partial attempt.

Approval is read from the reviewed local manifest, not model/browser output.
Runs real native DSH tools against BrowserSkill, using a local deterministic LLM.
"""
import hashlib
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'tests_next'), str(ROOT/'tools')]
from p2_fixture import ModelFixture
from sumika_next.dsh import Dsh
from verify_dsh_recovery import prompt, finish
from extensions.desktop.browser_skill import BrowserSkillClient
from extensions.desktop.consultation_sites import capture_response, collect_response


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--resume-preflight',action='store_true',help='Skip all admitted requests; resume only never-admitted sites after inspecting live tabs')
    parser.add_argument('--readback-only',action='store_true',help='Never submit; collect saved request IDs and verify native readback and restart')
    parser.add_argument('--manifest',default='pending.json',help='Approved manifest filename within acceptance directory')
    parser.add_argument('--run-id',default='live',help='Unique receipt directory; never reuse for new submissions')
    parser.add_argument('--session',help='Explicit existing browser session, preserving selected site modes')
    options=parser.parse_args()
    if options.readback_only: options.resume_preflight=True
    directory = ROOT/'.sumika-next/web-review-acceptance'
    for value in (options.manifest,options.run_id):
        assert value not in ('.','..') and Path(value).name==value and '/' not in value and '\\' not in value
    plan = json.loads((directory/options.manifest).read_text(encoding='utf8'))
    assert plan['status'] == 'approved'
    assert hashlib.sha256(plan['prompt'].encode()).hexdigest() == plan['sha256']
    base = directory/options.run_id
    if not options.resume_preflight:
        base.mkdir()  # Exclusive receipt: no second run after any partial outcome.
    home, work = base/'home', base/'work'
    home.mkdir(exist_ok=options.resume_preflight); work.mkdir(exist_ok=options.resume_preflight)
    client = BrowserSkillClient()
    original = client.registry.read_bytes()
    backup = client.registry.parent/'backups'/('browser-auth-'+uuid.uuid4().hex+'.json')
    backup.parent.mkdir(exist_ok=True); backup.write_bytes(original)
    assert backup.read_bytes() == original
    report = {'status':'running', 'sites':{}, 'paid_api_calls':0, 'prompt_hash':plan['sha256']}
    if options.resume_preflight:
        report=json.loads((base/'report.json').read_text(encoding='utf8'))
        assert report['prompt_hash']==plan['sha256']

    def save():
        (base/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')

    def bsk(*args):
        out = subprocess.run([client.executable,*args,'--json'], capture_output=True, text=True, encoding='utf8', timeout=35, check=True)
        return json.loads(out.stdout)

    # Restart/rebinding authorization was explicitly granted earlier in this task.
    sessions = client.session_list()
    if options.resume_preflight:
        session=report['browser_session']
        assert any(all(s.get(k)==session[k] for k in ('session_id','agent_window_id','browser_instance_id')) for s in sessions), 'original browser identity unavailable'
    elif options.session:
        matches=[s for s in sessions if s.get('session_id')==options.session]
        assert len(matches)==1, 'selected session unavailable'
        session=matches[0]
    elif sessions:
        raise RuntimeError('active sessions exist; inspect rather than guess ownership')
    else:
        browsers = client.status().get('raw',{}).get('browsers',[])
        assert len(browsers) == 1, 'select a specific browser before continuing'
        session = client.session_start(browser=browsers[0]['instance_id'])
    report['browser_session'] = session
    save()
    with ModelFixture() as model:
        (home/'.env').write_text('DEEPSEEK_API_KEY=local-fixture-not-a-secret\n',encoding='utf8')
        config = dict(enabled=True,projects=[str(work)],workPresets=['standard'],root=str(ROOT),
                      python=sys.executable,registry=str(client.registry),
                      runtimeEntry=str((ROOT/'runtime/dsh/node_modules/@deepseek-ai/dsh/package.json').resolve()))
        (home/'cordis.patch.yml').write_text(json.dumps([
            {'id':'session-title-llm','disabled':True},
            {'id':'llm-deepseek','config':{'baseURL':model.url}},
            {'id':'session-telemetry-otel','disabled':True},
            {'insert':[{'id':'sumika-web-review','name':str(ROOT/'extensions/desktop/review_dsh.mjs'),'config':config}]}
        ]),encoding='utf8')
        adapter = Dsh(ROOT,home)

        def native_turn(sid, name, args, label, approve=False):
            model.responses=0; model.recipe=[(name,args)]
            model.call_id_prefix='review-'+uuid.uuid4().hex
            follow=adapter.stream('session/follow',{'address':{'kind':'session','sessionId':sid}},timeout=150)
            next(follow)
            approvals=None
            try:
                if approve:
                    approvals=adapter.stream('$events',{},timeout=45)
                    ready=next(approvals)
                prompt(adapter,sid,label+'-'+uuid.uuid4().hex)
                if approve:
                    for event in approvals:
                        if event.get('type')!='waterfall': continue
                        assert event['event']=='approval/request' and event['agentId']==sid
                        assert event['request']['toolName']=='web_review_submit' and event['request']['callId']==model.call_id_prefix+'-0'
                        assert args == {'site':current_site,'prompt':plan['prompt']}
                        # User approved exactly this site/text once. Native audit
                        # still owns the approval request and allowed-once grant.
                        adapter._rpc('$events/result',{'clientId':ready['clientId'],'eventId':event['eventId'],
                                                      'outcome':{'kind':'result','value':'allowed-once'}})
                        break
                frames=finish(follow)
                (base/(label+'.json')).write_text(json.dumps(frames,ensure_ascii=False),encoding='utf8')
                for frame in frames:
                    e=frame.get('event',{})
                    if e.get('type')=='tool/result':
                        if e['data'].get('error'): raise RuntimeError('native tool failed: '+json.dumps(e['data']['error']))
                        blocks=e['data']['message']['content'][0]['content']
                        return json.loads(''.join(b.get('text','') for b in blocks))
                raise RuntimeError('native result missing; do not resend')
            finally:
                follow.close()
                if approvals: approvals.close()

        try:
            adapter.start()
            if options.readback_only:
                for index,current_site in enumerate(plan['sites']):
                    entry=report['sites'][current_site]
                    request_id=entry['submission']['request_id']
                    result=collect_response(client,request_id)
                    entry['collection']=result;entry['state']=result['state'];save()
                    assert result['state']=='completed', 'response still unconfirmed; do not send again'
                    returned=native_turn(entry['native_session'],'web_review_result',{'request_id':request_id,'action':'status'},'readback-only-'+str(index))
                    assert returned['response']['response_hash']==result['response']['response_hash']
                    entry['native_readback']=True;save()
                    print(current_site,'NATIVE_READBACK completed',flush=True)
                count=len(model.requests)
                adapter.close();adapter.start()
                assert len(model.requests)==count, 'restart replayed model work'
                for entry in report['sites'].values():
                    restored=collect_response(client,entry['submission']['request_id'])
                    assert restored['response']['response_hash']==entry['collection']['response']['response_hash']
                report['restart_no_replay']=True
                report['status']='three_site_readback_verified' if len(plan['sites'])==3 else 'selected_sites_readback_verified'
                save()
                return
            for index,current_site in enumerate(plan['sites']):
                previous=report['sites'].get(current_site)
                if previous and previous['state']!='preparing':
                    print(current_site,'SKIPPED already admitted',flush=True)
                    continue
                entry=report['sites'][current_site]={**(previous or {}),'state':'preparing'};save()
                existing=[t for t in client.session_tabs(session['session_id']) if t.get('url','').startswith('https://'+current_site+'/')]
                if previous or options.session:
                    assert len(existing)==1, 'ambiguous preflight page; inspect before resuming'
                    tab=existing[0]
                    bsk('tab','select',str(tab['tab_id']),'--session',session['session_id'])
                else:
                    tab=bsk('tab','create','--session',session['session_id'],'--url','https://'+current_site+'/')
                entry['tab_id']=tab['tab_id'];save()
                deadline=time.monotonic()+20
                while True:
                    current=[t for t in client.session_tabs(session['session_id']) if t.get('tab_id')==tab['tab_id']]
                    if len(current)==1 and current[0].get('url','').startswith('https://'+current_site+'/'):break
                    if time.monotonic()>deadline:raise RuntimeError('tab URL not ready; no send admitted')
                    time.sleep(.2)
                client.bind_session(current_site,session['session_id'],tab['tab_id'])
                deadline=time.monotonic()+20
                while True:
                    try:
                        snap=capture_response(client.bound_bridge(current_site),current_site)
                        assert not snap['turns'], 'new page contains existing messages'
                        break
                    except RuntimeError:
                        if time.monotonic()>deadline: raise
                        time.sleep(.5)
                sid='live-web-review-'+str(index)
                if not previous or not previous.get('native_session'):
                    adapter._rpc('session/create',{'sessionId':sid,'cwd':str(work)})
                entry.update(state='admitted_once',native_session=sid,tab_id=tab['tab_id']);save()
                result=native_turn(sid,'web_review_submit',{'site':current_site,'prompt':plan['prompt']},'submit-'+str(index),approve=True)
                entry['submission']=result;save()
                print(current_site,'SUBMISSION',result.get('state'),flush=True)
                if not result.get('process_ok') or result.get('state') not in ('submitted','unknown'):
                    entry['state']='unconfirmed';save();continue
                request_id=result['request_id'];deadline=time.monotonic()+120
                while time.monotonic()<deadline:
                    result=collect_response(client,request_id)
                    entry['collection']=result;save()
                    if result['state']=='completed':break
                    time.sleep(1)
                entry['state']=result['state'];save()
                if result['state']=='completed':
                    returned=native_turn(sid,'web_review_result',{'request_id':request_id,'action':'status'},'readback-'+str(index))
                    assert returned['response']['response_hash']==result['response']['response_hash']
                    entry['native_readback']=True;save()
                print(current_site,'RESULT',entry['state'],flush=True)
            report['status']='tested';save()
        finally:
            adapter.close();save()
            print('REPORT',base/'report.json',flush=True)


if __name__=='__main__':main()
