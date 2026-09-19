"""Verify the owned daily plugin after an explicitly requested idle restart.

No model prompt or website submission. Refuse restart when native work is queued.
"""
import argparse
import http.cookiejar
import json
from pathlib import Path
import urllib.request
import uuid
import websocket


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--restart',action='store_true')
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[1]
    origin='http://127.0.0.1:8765'
    jar=http.cookiejar.CookieJar()
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),urllib.request.HTTPCookieProcessor(jar))
    def get(path):
        with opener.open(origin+path,timeout=40) as response:return json.load(response)
    token=get('/api/manage/session')['csrf']
    def post(path,data):
        req=urllib.request.Request(origin+path,data=json.dumps(data).encode(),headers={
            'Content-Type':'application/json','Origin':origin,'X-Sumika-CSRF':token})
        with opener.open(req,timeout=110) as response:return json.load(response)
    before=get('/api/workbench')
    assert before['running'] and before['url']=='http://127.0.0.1:5175'
    launch=get('/api/workbench/embed')['url']
    assert launch.startswith(before['url']+'/?token=')
    with opener.open(launch,timeout=15) as response:response.read()
    req=urllib.request.Request(before['url']+'/api/remote.mux');jar.add_cookie_header(req)
    ws=websocket.create_connection('ws://127.0.0.1:5175/api/remote.mux',
        cookie=req.get_header('Cookie'),origin=before['url'],timeout=15,http_no_proxy=['127.0.0.1'])
    try:
        sid=uuid.uuid4().hex
        ws.send(json.dumps({'type':'open','streamId':sid,'endpoint':'session/control','payload':{'args':{}}}))
        frame=json.loads(ws.recv())
        assert frame['streamId']==sid and frame['value']['type']=='baseline'
        baseline=frame['value']['value']
        assert not any(baseline['jobs'].values()), 'active native jobs; do not restart'
        assert not any(baseline['queues'].values()), 'queued native work; do not restart'
    finally:ws.close()
    if args.restart:
        result=post('/api/workbench/stop',{})
        assert result.get('stopped') is True,result
        assert get('/api/workbench')['running'] is False
        after=post('/api/workbench/start',{'workspace':str(root),'port':5175})
    else:after=before
    assert after['running'] and after['embed_ready']
    registered=any('Sumika web review: submit/result registered' in str(line)
                   for line in after.get('recent_log',[]))
    report={'running':True,'idle_sessions_checked':len(baseline['jobs']),
            'restarted':args.restart,'registered':registered,'external_messages':0,
            'paid_api_calls':0,'note':'Registry check, not a model-driven daily tool execution.'}
    path=root/'.sumika-next/web-review-acceptance/daily-registration.json'
    path.write_text(json.dumps(report,indent=2),encoding='utf8')
    print(json.dumps(report))
    assert registered, 'registration absent from startup log; inspect before claiming daily readiness'


if __name__=='__main__':main()
