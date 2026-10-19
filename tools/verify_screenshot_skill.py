"""Real native skill -> configured OCR -> model context, synthetic file only."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import shutil
import sys
from unittest.mock import patch
import uuid

SOURCE=Path(__file__).resolve().parents[1]


def quote(value):
    return "'"+str(value).replace("'","''")+"'"


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--product',type=Path,default=SOURCE)
    parser.add_argument('--output',type=Path,default=SOURCE/'.sumika-next/acceptance-20261018/screenshot-skill')
    parser.add_argument('--repair-fixture-acl',action='store_true')
    args=parser.parse_args();product=args.product.resolve(strict=True)
    sys.path[:0]=[str(product),str(SOURCE/'tests_next'),str(SOURCE/'tools')]
    from p2_fixture import ModelFixture
    from verify_dsh_recovery import finish,prompt
    from extensions.capabilities import CapabilityStore
    from extensions.desktop.runtime import capability_python
    from ui.workbench import WorkbenchController
    base=args.output.resolve()/uuid.uuid4().hex
    home=base/'home';work=base/'work';home.mkdir(parents=True);work.mkdir()
    if args.repair_fixture_acl:
        from extensions.office.native import resource
        script=resource(product,'dsh-sandbox-windows-acl','assets/diagnose-windows-sandbox-acl/scripts/diagnose-windows-sandbox-acl.ps1')
        if script is None:raise RuntimeError('bundled ACL diagnosis script missing')
        repaired=subprocess.run([shutil.which('pwsh') or 'powershell','-NoProfile','-File',str(script),
            '-Path',str(work),'-AllowRoot',str(work),'-Out',str(base/'acl-recovery')],
            capture_output=True,text=True,encoding='utf8',timeout=60)
        (base/'acl-repair.txt').write_text(repaired.stdout+repaired.stderr,encoding='utf8')
        repaired.check_returncode()
    database=base/'capabilities.sqlite3';request=work/'ocr-request.json';image=work/'screenshot.png'
    store=CapabilityStore(database);store.configure('ocr','windows',enabled=False);store.close()
    desktop=capability_python('desktop',root=product)
    assert desktop,'selected desktop interpreter missing'
    subprocess.run([desktop,'-X','utf8','-B','-c',
        "from PIL import Image,ImageDraw,ImageFont; import sys; i=Image.new('RGB',(1000,160),'white'); ImageDraw.Draw(i).text((30,35),'Please save your work before closing.',font=ImageFont.truetype('C:/Windows/Fonts/msyh.ttc',40),fill='black'); i.save(sys.argv[1])",
        str(image)],check=True,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    request.write_text(json.dumps({'capability':'ocr','operation':'recognize','arguments':{'image':str(image),'language':'eng'}}),encoding='utf8')
    primary=product/'runtime/python/python.exe';primary=str(primary) if primary.is_file() else sys.executable
    command=f'& {quote(primary)} -X utf8 -B {quote(product/"tools/run_module.py")} extensions.desktop.service --store {quote(database)} --request {quote(request)}'
    report={'passed':False,'product':str(product),'external_model_calls':0,'device_capture':False,'checks':[]}
    controller=WorkbenchController(product,capability_database=database)
    events=[]
    with ModelFixture() as model:
        (home/'.env').write_text('DEEPSEEK_API_KEY=screenshot-local-fixture\n',encoding='utf8')
        (home/'cordis.patch.yml').write_text(json.dumps([
            {'id':'session-title-llm','disabled':True},
            {'id':'llm-deepseek','config':{'baseURL':model.url}},
            {'id':'session-telemetry-otel','disabled':True}]),encoding='utf8')
        try:
            with patch('ui.workbench.default_home',return_value=home):controller.start(port=0)
            skill=home/'skills/sumika-screenshot-translation/SKILL.md'
            assert skill.is_file(),'automatic managed-profile publication absent'
            assert str(database) in skill.read_text(encoding='utf8')
            report['checks'].append('real_workbench_start_publishes_skill_bound_to_registry')
            adapter=controller.adapter
            def run(session,recipe):
                model.recipe=recipe;model.responses=0
                adapter._rpc('session/create',{'sessionId':session,'cwd':str(work)})
                stream=adapter.stream('session/follow',{'address':{'kind':'session','sessionId':session}},timeout=90)
                next(stream);prompt(adapter,session,'Use sumika-screenshot-translation on the synthetic screenshot; target Chinese.')
                frames=finish(stream);events.extend(frames)
                messages=[f['event']['data']['message'] for f in frames if f.get('event',{}).get('type')=='tool/result']
                assert messages and all(not m.get('isError') for m in messages),messages
                assert any(f.get('event',{}).get('type')=='turn/end' and f['event']['data']['reason'].get('kind')=='completed' for f in frames),frames[-1]
                return messages
            disabled=command+"; if ($LASTEXITCODE -ne 2) { throw 'Disabled OCR must refuse' }; exit 0"
            messages=run('screenshot-disabled',[
                ('skill',{'name':'sumika-screenshot-translation'}),
                ('pwsh',{'command':disabled,'workdir':str(work),'description':'Check disabled OCR refuses synthetic image','timeoutMs':60000})])
            assert 'capability disabled' in json.dumps(messages,ensure_ascii=False),messages
            report['checks'].append('native_skill_loads_and_disabled_service_refuses')
            store=CapabilityStore(database);store.configure('ocr','windows',enabled=True);store.close()
            messages=run('screenshot-enabled',[
                ('skill',{'name':'sumika-screenshot-translation'}),
                ('pwsh',{'command':command+'; exit $LASTEXITCODE','workdir':str(work),'description':'Read generated screenshot through configured OCR','timeoutMs':60000})])
            assert 'Please save your work before closing.' in json.dumps(messages,ensure_ascii=False),messages
            assert 'Please save your work before closing.' in json.dumps(model.requests[-1],ensure_ascii=False)
            report['checks'].append('actual_ocr_text_reaches_native_work_model_context')
            report['local_fixture_calls']=len(model.requests)
            report['boundary']='Deterministic native transport acceptance; final fixture reply is not a real model translation-quality score. No screenshot captured or external model called.'
            report['passed']=True
        except Exception as error:
            report['error']=repr(error)
        finally:
            controller.stop();report['managed_dsh_stopped']=not controller.status()['running']
            (base/'events.json').write_text(json.dumps(events,ensure_ascii=False,indent=2),encoding='utf8')
            (base/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
            print(json.dumps({'report':str(base/'report.json'),**report},ensure_ascii=False))
    return 0 if report['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
