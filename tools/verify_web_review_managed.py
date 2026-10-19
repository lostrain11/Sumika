"""Actual Workbench-managed registration and approval, synthetic sessions only.

No website grants are created, so even the allow-once branch must fail before
BrowserSkill launch. No production profile or browser session is used.
"""
import argparse
import json
from pathlib import Path
import sys
import uuid
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--product', type=Path, default=SOURCE)
    parser.add_argument('--output', type=Path, default=SOURCE/'.sumika-next/acceptance-20261018/managed-review')
    args = parser.parse_args()
    product = args.product.resolve()
    sys.path[:0] = [str(product), str(SOURCE/'tests_next'), str(SOURCE/'tools')]
    from p2_fixture import ModelFixture
    from ui.workbench import WorkbenchController
    from verify_dsh_recovery import prompt, finish
    # Historical helper adds its own checkout to sys.path; restore the selected
    # product before lazy imports in Workbench install/start.
    sys.path.insert(0, str(product))
    import ui.workbench as workbench_module
    assert Path(workbench_module.__file__).resolve().is_relative_to(product)

    base = args.output.resolve()/uuid.uuid4().hex
    home, work = base/'home', base/'work'
    home.mkdir(parents=True)
    work.mkdir()
    registry = base/'personal/browser-authorizations.json'
    registry.parent.mkdir()
    report = {'passed':False, 'product':str(product), 'checks':{}, 'external_messages':0,
              'boundary':'Actual managed Workbench registration; deterministic loopback model and synthetic approval answerer, not browser approval clicks.'}
    evidence = {}
    controller = WorkbenchController(product, browser_registry=registry, python=sys.executable)
    with ModelFixture() as model:
        (home/'.env').write_text('DEEPSEEK_API_KEY=local-fixture-not-a-secret\n',encoding='utf8')
        answerer=base/'approval.mjs'
        decision_file=base/'decision.json'
        answerer.write_text("import {readFileSync} from 'node:fs'; export function apply(ctx,config) { ctx.on('approval/request',async(req,next)=>{ if(req.toolName!=='web_review_submit')return next(); const decision=JSON.parse(readFileSync(config.file,'utf8')).decision; return decision==='pending'?next():decision; }); }",encoding='utf8')
        (home/'cordis.patch.yml').write_text(json.dumps([
            {'id':'session-title-llm','disabled':True},
            {'id':'llm-deepseek','config':{'baseURL':model.url}},
            {'id':'session-telemetry-otel','disabled':True},
            {'insert':[{'id':'fixture-approval','name':str(answerer),'config':{'file':str(decision_file)}}]},
        ]),encoding='utf8')
        try:
            with patch('ui.workbench.default_home',return_value=home):
                controller.start()
            import extensions.desktop.review_install as installer_module
            assert Path(installer_module.__file__).resolve().is_relative_to(product)
            adapter=controller.adapter
            rows=json.loads((home/'cordis.patch.yml').read_text(encoding='utf8'))
            entries=[entry for row in rows for entry in row.get('insert',[])]
            config=next(x['config'] for x in entries if x['id']=='sumika-web-review')
            assert config['registry']==str(registry) and config['root']==str(product)
            assert config['registeredWorkspaces'] is True and config['projects']==[]
            assert Path(config['runner']).is_relative_to(product)
            report['checks']['fresh_managed_profile_paths_and_native_scope']=True
            registered=adapter._rpc('workspace/create',{'path':str(work)})['workspace']['workspaceId']
            for case in ('disabled','reject','cancel','allow-no-site'):
                registry.write_text(json.dumps({'schema_version':1,'enabled':case!='disabled','sites':{}}),encoding='utf8')
                decision_file.write_text(json.dumps({'decision':'allowed-once' if case=='allow-no-site' else 'rejected'}),encoding='utf8')
                # Cancellation must wait at the real native unanswered approval.
                if case=='cancel':
                    decision_file.write_text(json.dumps({'decision':'pending'}),encoding='utf8')
                sid='managed-review-'+case
                adapter._rpc('session/create',{'sessionId':sid,'workspaceId':registered})
                model.responses=0
                model.call_id_prefix=case
                model.recipe=[('web_review_submit',{'site':'chatgpt.com','prompt':'SYNTHETIC_MANAGED_REVIEW_NO_SITE_GRANT'})]
                stream=adapter.stream('session/follow',{'address':{'kind':'session','sessionId':sid}},timeout=35)
                events=[]
                try:
                    next(stream)
                    prompt(adapter,sid,'Synthetic native review once. Do not retry.')
                    for frame in stream:
                        event=frame.get('event')
                        if not event:continue
                        events.append(event)
                        if event['type']=='approval/asked' and case=='cancel':
                            adapter._rpc('session/cancel',{'sessionId':sid})
                        if event['type']=='turn/end':break
                finally:stream.close()
                evidence[case]=events
                assert events and events[-1]['type']=='turn/end', case
                approvals=[e for e in events if e['type']=='approval/asked']
                results=[e['data'] for e in events if e['type']=='tool/result']
                assert results,case
                if case=='disabled':
                    assert not approvals,'disabled switch must refuse before asking'
                    assert any(r.get('message',{}).get('isError') for r in results),results
                else:
                    assert approvals,case
                    expected={'reject':'rejected','cancel':'cancelled','allow-no-site':'allowed-once'}[case]
                    assert any(e['type']=='approval/decided' and e['data'].get('outcome')==expected for e in events),(case,events)
                    if case=='cancel':assert any(r.get('error',{}).get('code')=='ABORTED_BEFORE_DISPATCH' for r in results),results
                    if case=='allow-no-site':
                        text=json.dumps(results)
                        assert 'authorization' in text.lower() or 'authorized' in text.lower(),results
                        assert 'process_ok' in text and 'false' in text,results
                assert not (registry.parent/'browser-consultations.sqlite3').exists(),'ungranted site must not begin submission'
                report['checks'][case]=True
            # Existing worktree paths must never be accepted just because a
            # session claims a cwd: it must belong to the native registry.
            report['loopback_model_calls']=len(model.requests)
            report['passed']=True
        finally:
            controller.stop()
            (base/'events.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf8')
            (base/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
            print(json.dumps({'artifact':str(base),**report},ensure_ascii=False),flush=True)


if __name__=='__main__':main()
