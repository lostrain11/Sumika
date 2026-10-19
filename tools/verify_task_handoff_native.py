"""Owned candidate Bridge + native DSH; synthetic local model only."""
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import uuid
sys.path.insert(0, str(Path.cwd()))

PRODUCT = Path.cwd()
SOURCE = Path(__file__).resolve().parents[1]
BASE = SOURCE/'.sumika-next/acceptance-20261017'/('task-handoff-'+uuid.uuid4().hex)
BASE.mkdir()
os.environ['SUMIKA_DATA_DIR'] = str(BASE/'personal')
os.environ.pop('SUMIKA_ROLE_STORE', None)
sys.path.append(str(SOURCE/'tests_next'))
from p2_fixture import ModelFixture
from extensions.models.settings import example, save
from ui.server import serve, BUILTIN_ROLES
from sumika_next.daily import default_home
from sumika_next.daily import create_workspace_session

settings = BASE/'personal/settings.json'
settings.parent.mkdir(parents=True)
save(example(BUILTIN_ROLES/'sampleA',BASE/'personal/memory.sqlite3'),settings)
report = {'passed':False, 'candidate':str(PRODUCT), 'external_model_calls':0,
          'synthetic_model':True, 'checks':{}, 'source_skin':False}
server = None
with ModelFixture() as model:
    home=default_home(PRODUCT)
    home.mkdir(parents=True)
    (home/'.env').write_text('DEEPSEEK_API_KEY=synthetic-loopback-only\n',encoding='utf8')
    (home/'cordis.patch.yml').write_text(json.dumps([
        {'id':'session-title-llm','disabled':True},
        {'id':'session-telemetry-otel','disabled':True},
        {'id':'llm-deepseek','config':{'baseURL':model.url}},
    ]),encoding='utf8')
    try:
        server=serve(settings,port=0,workbench_root=PRODUCT,
            capability_database=BASE/'personal/capabilities.sqlite3',
            schedule_directory=BASE/'personal/schedules')
        threading.Thread(target=server.serve_forever,daemon=True).start()
        bridge=server.sumika_bridge
        from extensions.models.settings import load
        config=load(settings)
        text='请检查验收项目的构建错误'
        turn=bridge.conversations.begin(bridge._chat_scope(config),'room-sampleA',text)
        bridge.conversations.complete(turn,{'text':'这是隔离验收回复','task_intent':{'kind':'task','confidence':'high','evidence':text}})
        bridge.workbench.start()
        adapter=bridge.workbench.adapter
        session=create_workspace_session(adapter, BASE, BASE/'launch.sqlite3')
        stream=adapter.stream('session/follow',{'address':{'kind':'session','sessionId':session}},timeout=40)
        try:
            next(stream)
            adapter._rpc('session/prompt',{'sessionId':session,'requestId':uuid.uuid4().hex,
                'mode':'queue','content':[{'type':'text','text':'Synthetic acceptance: reply briefly.'}]})
            events=[]
            for event in stream:
                events.append(event)
                if event.get('event',{}).get('type')=='turn/end':break
            else:raise AssertionError('native turn did not end')
        finally:stream.close()
        report['checks']['native_nonblank_session_completed']=True
        base=f'http://127.0.0.1:{server.server_port}'
        result=subprocess.run(['node',str(SOURCE/'tools/verify_task_handoff_ui.mjs'),base,str(BASE)],
            capture_output=True,text=True,encoding='utf8',timeout=100,cwd=PRODUCT)
        (BASE/'handoff-browser.log').write_text(result.stdout+'\n'+result.stderr,encoding='utf8')
        assert result.returncode==0,'handoff browser: '+str(BASE/'handoff-browser.log')
        report['checks']['persisted_source_handoff_composer']=True
        report['loopback_fixture_calls']=len(model.requests)
        assert len(model.requests)==1, 'handoff unexpectedly invoked model'
        report['passed']=True
    except BaseException as error:
        report['error']=str(error)
        raise
    finally:
        if server:
            process=getattr(server.sumika_bridge.workbench.adapter,'process',None)
            server.shutdown(); server.server_close()
            report['owned_dsh_stopped']=process is None or process.poll() is not None
        (BASE/'report.json').write_text(json.dumps(report,indent=2),encoding='utf8')
        print(json.dumps({'evidence':str(BASE),'report':report}),flush=True)
