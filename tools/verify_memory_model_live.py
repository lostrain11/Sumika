"""Owned local Ollama process and synthetic role; no cloud or personal data writes."""
import argparse,json,os,subprocess,sys,time,urllib.request,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tests_next.test_auto_extraction import _settings
from extensions.roles.chat import RoleChat,open_session
from extensions.memory.model_proposer import list_proposals,resolve

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--model',default='sumika-minicpm5-2b')
parser.add_argument('--limit',type=int,default=3)
args=parser.parse_args()
base=ROOT/'.sumika-next'/('memory-model-live-'+uuid.uuid4().hex)
base.mkdir()
env=dict(os.environ,OLLAMA_HOST='127.0.0.1:11439',OLLAMA_MODELS='E:/AI/OllamaModels',OLLAMA_NO_CLOUD='1')
exe=Path(os.environ['LOCALAPPDATA'])/'Programs/Ollama/ollama.exe'
op=urllib.request.build_opener(urllib.request.ProxyHandler({}))
log=(base/'runtime.log').open('w',encoding='utf8')
process=subprocess.Popen([str(exe),'serve'],env=env,stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)
report={'model':args.model,'cloud_calls':0,'personal_data_touched':False,'cases':[]}
try:
    for _ in range(40):
        if process.poll() is not None:raise RuntimeError('owned Ollama exited')
        try:
            with op.open('http://127.0.0.1:11439/api/tags',timeout=1) as r:models=json.load(r)
            break
        except OSError:time.sleep(.25)
    else:raise RuntimeError('owned Ollama unavailable')
    assert any(m['name'].split(':')[0]==report['model'] for m in models['models']), 'model not installed; no download'
    settings=_settings(base)
    settings.update(provider='ollama',endpoint='http://127.0.0.1:11439',model=report['model'],max_tokens=700,
                    context_length=2048,temperature=0,timeout_seconds=300)
    settings['memory']['model_proposals']=True
    class EvidenceChat(RoleChat):
        def _generate(self,*args,**kwargs):
            result=super()._generate(*args,**kwargs)
            self.synthetic_output=result['text']
            return result
    for i,text in enumerate(('我喜欢绿茶，平时最常喝绿茶。','如果我喜欢咖啡，你会推荐什么？','小说里的主角说：“我住在成都。”')[:args.limit]):
        chat=EvidenceChat(settings)
        result=chat.reply(text,source_message_id=f'live-{i}:user',task_intent=True)
        session=open_session(settings)
        try:
            proposals=list_proposals(session)
            fresh=[p for p in proposals if p.get('message_id')==f'live-{i}:user']
            assert session.request('search',{'query':'绿茶'})==[], 'pending became retrievable'
            report['cases'].append({'input':text,'reply':result['text'],'synthetic_raw_output':chat.synthetic_output,'proposals':fresh,'intent':result['task_intent']})
        finally:session.close()
    session=open_session(settings)
    try:
        candidates=[p for p in list_proposals(session) if p.get('message_id')=='live-0:user']
        report['positive_proposal_generated']=bool(candidates)
        if candidates:
            resolve(session,candidates[0]['event_id'],True)
            report['confirmed_recalled']=bool(session.request('search',{'query':'绿茶'}))
        report['negative_cases_clean']=all(not c['proposals'] for c in report['cases'][1:]) if len(report['cases'])==3 else None
    finally:session.close()
finally:
    # Windows terminate() alone leaves the inference runner alive, retaining GPU RAM.
    # This PID comes from our still-live Popen handle, never a port search.
    if process.poll() is None:
        subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],check=True,
                       stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                       creationflags=subprocess.CREATE_NO_WINDOW)
    process.wait(timeout=20)
    log.close()
    (base/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print(base/'report.json')
assert report.get('positive_proposal_generated') and report.get('confirmed_recalled'), 'positive proposal/confirmation failed'
if args.limit==3:
    assert report.get('negative_cases_clean') is True, 'hypothesis or quotation proposed as user fact'
