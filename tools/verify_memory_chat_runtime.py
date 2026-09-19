"""Real offline role-memory path through the daily interpreter; synthetic data only."""
import copy
import json
from pathlib import Path
import sys
import time
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tests_next.test_auto_extraction import _settings
from extensions.roles.chat import open_session,build_messages


def main():
    base=ROOT/'.sumika-next'/('memory-chat-runtime-'+uuid.uuid4().hex);base.mkdir()
    settings=_settings(base);settings['role']['memory_provider']='semantic'
    report={'provider':'semantic','external_model_calls':0,'checks':{}}
    start=time.monotonic()
    session=open_session(settings)
    try:
        session.request('remember',{'text':'用户对花生过敏，不能吃含花生的食物。','event_id':'fixture:user:allergy'})
        session.request('remember',{'text':'用户以前住在北京。','fact_key':'location','event_id':'fixture:user:old'})
        session.request('remember',{'text':'用户现在住在成都。','fact_key':'location','event_id':'fixture:user:new'})
    finally:session.close()
    session=open_session(settings)
    try:
        query='哪些食材是我不能吃的'
        ctx=session.request('context',{'user_content':query,'mode':'role'})
        system=build_messages({'role_context':ctx['role_context'],'original_user_content':query})[0]['content']
        assert '花生过敏' in system
        report['checks']['paraphrase_reaches_model_reference']=True
        rows=session.request('search',{'query':'我现在住在哪座城市'})
        assert any('成都' in r['text'] for r in rows)
        assert all('北京' not in r['text'] for r in rows)
        report['checks']['reopen_and_update']=True
    finally:session.close()
    other=copy.deepcopy(settings);other['role']['user_id']='other-user'
    session=open_session(other)
    try:
        assert not session.request('search',{'query':'花生'})
        report['checks']['scope_isolation']=True
    finally:session.close()
    report['elapsed_seconds']=round(time.monotonic()-start,2)
    (base/'report.json').write_text(json.dumps(report,indent=2),encoding='utf8')
    print(json.dumps(report));print('EVIDENCE',base/'report.json')


if __name__=='__main__':main()
