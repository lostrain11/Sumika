"""Isolated rc.2 root-slot feasibility probe. Never modifies the daily profile."""
import json
from pathlib import Path
import subprocess
import sys
import uuid
import threading
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from sumika_next.dsh import Dsh
from sumika_next.daily import create_workspace_session
from ui.server import serve

CLIENT = r"""
window.__ModuleLoader__.load({id:'sumika-layout-probe',factory:require=>({inject:['slots'],apply(ctx){
const React=require('react'),h=React.createElement,listeners=new Set();
let info=Object.freeze({activePanelId:null}),navigation=new AbortController();
const layout={getPanelInfo:()=>info,selectPanel:id=>{navigation.abort();info=Object.freeze({activePanelId:id});listeners.forEach(f=>f());},
beginNavigation:()=>{navigation.abort();navigation=new AbortController();return navigation.signal;}};
ctx.effect(()=>{
 if(ctx.reflect.get('layout',false)!==undefined)throw new Error('layout ownership conflict');
 const root=ctx.slots.provideRoot({hooks:{panelInfo:{getSnapshot:()=>info,subscribe:f=>{listeners.add(f);return()=>listeners.delete(f);}}}});
 const service=ctx.reflect.provide('layout',layout);
 return()=>{navigation.abort();root();service();};
});
function Frame({renderSlot,usePanelInfo}){
 const [screen,setScreen]=React.useState('board');
 const panel=usePanelInfo(s=>s.activePanelId);
 return h('div',{'data-layout-probe':'',style:{height:'100vh',display:'flex',flexDirection:'column'}},
 h('nav',{},...['room','board','shelf','settings'].map(id=>h('button',{key:id,onClick:()=>setScreen(id),'data-probe-page':id},id))),
 h('div',{'data-probe-board':'',style:{display:screen==='board'?'flex':'none',flex:1,minHeight:0}},
 h('aside',{style:{width:280,overflow:'auto'}},renderSlot('sidebar',{collapsed:false,width:280})),
 h('main',{style:{flex:1,minWidth:0,overflow:'hidden'}},renderSlot('main',{}, {entryKey:panel??'conversation'})),
 h('aside',{},renderSlot('rightbar',{width:380,viewportWidth:1280,canShow:true}))),
 screen!=='board'?h('p',{},'Isolated slot probe: '+screen):null,
 renderSlot('shell.overlay',{}));
}
ctx.effect(()=>ctx.slots.register({name:'root',children:{sidebar:{kind:'single',scope:'root'},main:{kind:'keyed',scope:'root'},rightbar:{kind:'single',scope:'root'},'shell.overlay':{kind:'list',scope:'root'}}},Frame));
}})});
"""


def main():
    base=ROOT/'.sumika-next'/('layout-probe-'+uuid.uuid4().hex)
    package=base/'plugin';package.mkdir(parents=True)
    home=base/'home';home.mkdir()
    (package/'package.json').write_text(json.dumps({'name':'sumika-layout-probe','version':'0.0.0','type':'module','main':'index.mjs',
        'exports':{'.':'./index.mjs','./client':'./client.js','./package.json':'./package.json'},
        'dsh':{'client':{'inject':['@deepseek-ai/dsh-client-ui-slots'],'platform':'web','immediately':True}}}),encoding='utf8')
    (package/'index.mjs').write_text('export function apply() {}',encoding='utf8')
    (package/'client.js').write_text(CLIENT,encoding='utf8')
    (home/'cordis.patch.yml').write_text(json.dumps([{'id':'ui-layout','disabled':True},
        {'id':'session-title-llm','disabled':True},{'id':'session-telemetry-otel','disabled':True},
        {'insert':[{'id':'sumika-layout-probe','name':str(package/'index.mjs')}]}]),encoding='utf8')
    bridge=serve(base/'settings.json',port=0,capability_database=base/'capabilities.db',schedule_directory=base/'schedules')
    thread=threading.Thread(target=bridge.serve_forever,daemon=True);thread.start()
    controller=bridge.sumika_bridge.workbench
    result={'status':'failed','external_model_calls':0,'production_changed':False}
    try:
        with patch('ui.workbench.default_home',return_value=home):
            controller.start()
        adapter=controller.adapter
        work=base/'workspace';work.mkdir()
        create_workspace_session(adapter,work,base/'launch.sqlite3')
        run=subprocess.run(['D:/Tools/nodejs/node.exe',str(ROOT/'tools/verify_native_layout.mjs')],
                           input=json.dumps({'url':adapter._browser_url,'directory':str(base),
                                             'bridge':f'http://127.0.0.1:{bridge.server_port}'}),text=True,encoding='utf8',capture_output=True,timeout=110)
        print(run.stdout)
        if run.returncode: raise RuntimeError('browser slot probe failed; see isolated report')
        result['status']='passed'
    except Exception as error:
        result['error']=type(error).__name__
    finally:
        controller.stop()
        bridge.shutdown();bridge.server_close();thread.join(timeout=5)
        (base/'result.json').write_text(json.dumps(result,indent=2),encoding='utf8')
        print(json.dumps({'directory':str(base),**result}))
    return 0 if result['status']=='passed' else 1

if __name__=='__main__':sys.exit(main())
