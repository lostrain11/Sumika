"""Actual isolated bridge process restart and HTTP boundary verification."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.request
import urllib.error
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from ui.server import Bridge


def main():
    base=ROOT/'.sumika-next'/('desktop-bridge-'+uuid.uuid4().hex)
    base.mkdir()
    settings=base/'settings.json'
    bridge=Bridge(settings,schedule_directory=base/'schedules')
    scope=bridge._chat_scope(bridge.settings())
    source=bridge.conversations.begin(scope,'fixture-session','隔离夹具：检查项目测试')
    bridge.conversations.complete(source,{'text':'隔离夹具回复，不是模型验收。'})
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    url=f'http://127.0.0.1:{port}'
    def request(path, payload=None, token=None):
        headers={'Content-Type':'application/json'}
        if token:headers['X-Sumika-CSRF']=token
        req=urllib.request.Request(url+path,headers=headers,data=None if payload is None else json.dumps(payload).encode())
        with urllib.request.urlopen(req,timeout=10) as response:return json.load(response)
    env={k:v for k,v in os.environ.items() if not k.endswith(('_API_KEY','_API_TOKEN'))}
    process=None;checks=[]
    try:
        for generation in range(2):
            process=subprocess.Popen([sys.executable,'-B','-m','ui.server','--settings',str(settings),'--port',str(port),
                '--capabilities',str(base/'capabilities.db'),'--schedules',str(base/'schedules')],cwd=ROOT,env=env,
                stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
            for _ in range(100):
                if process.poll() is not None:raise RuntimeError('isolated bridge exited')
                try:token=request('/api/manage/session')['csrf'];break
                except OSError:time.sleep(.1)
            else:raise RuntimeError('isolated bridge not ready')
            if generation==0:
                assert request('/api/settings/role-model')['enabled'] is False
                try:request('/api/lifecycle/shutdown',{})
                except urllib.error.HTTPError as e:assert e.code==403
                else:raise AssertionError('unprotected shutdown')
                draft=request('/api/manage/task-draft',{'action':'prepare','source_message_id':source+':user'},token)['draft']
                checks.append('disabled first run and protected HTTP shutdown')
            else:
                try:request('/api/lifecycle/shutdown',{},previous_token)
                except urllib.error.HTTPError as e:assert e.code==403
                else:raise AssertionError('previous instance token accepted')
                checks.append('previous bridge instance token rejected after restart')
                assert request('/api/role/chat/history?session=fixture-session')['messages'][0]['id']==source+':user'
                assert request('/api/manage/task-draft')['draft']['id']==draft['id']
                request('/api/manage/task-draft',{'action':'dismiss','id':draft['id']},token)
                assert request('/api/manage/task-draft')['draft'] is None
                checks.append('actual process restart preserves conversation and handoff; explicit dismissal persists')
            assert request('/api/lifecycle/shutdown',{},token)['stopping']
            previous_token=token
            process.wait(timeout=15)
            assert process.returncode==0
            process=None
        checks.append('authenticated graceful process exit twice; no port-based kill')
        report={'status':'passed','checks':checks,'model_requests':0,'personal_data_touched':False}
        (base/'report.json').write_text(json.dumps(report,indent=2),encoding='utf8')
        print(json.dumps({'directory':str(base),**report}))
    finally:
        if process and process.poll() is None:
            process.terminate();process.wait(timeout=15)

if __name__=='__main__':main()
