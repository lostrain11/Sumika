"""Offline retrieval comparison. A small regression set, not an AML benchmark."""
import argparse
import json
from pathlib import Path
import sys
import tempfile
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from extensions.memory.embedded_memory import EmbeddedMemory
from extensions.memory.semantic_memory import SemanticMemory

FACTS=[
    '用户对花生过敏，吃含花生的食物会身体不适。',
    '用户下周二下午三点预约了牙医，需要提前半小时出发。',
    '用户最近搬到了成都，以前居住在北京。',
    '用户每晚十点半睡觉，不希望深夜收到提醒。',
    '用户使用 Windows 电脑，项目保存在 D 盘。',
    '角色喜欢打鼓，是乐队的鼓手。',
]
CASES=[
    ('花生',0),('哪些食材是我不能吃的',0),
    ('牙医',1),('看牙的预约是什么时候',1),
    ('成都',2),('我现在住在哪座城市',2),
    ('深夜',3),('几点以后不要打扰我休息',3),
    ('Windows',4),('我的开发文件放在哪个磁盘',4),
    ('鼓手',5),('她在乐队负责什么乐器',5),
    ('银河系中心的黑洞质量是多少',None),
    ('明天彩票中奖号码是什么',None),
]


def evaluate(factory):
    with tempfile.TemporaryDirectory(prefix='sumika-quality-') as d:
        start=time.perf_counter();m=factory(Path(d)/'memory.db')
        try:
            for text in FACTS:m.add(text,user_id='test',role_id='role')
            results=[]
            for query,expected in CASES:
                t=time.perf_counter();rows=m.search(query,user_id='test',role_id='role',limit=1)
                ok=(not rows) if expected is None else bool(rows and rows[0]['text']==FACTS[expected])
                results.append(dict(query=query,passed=ok,expected=expected,retrieved=[r['text'] for r in rows],milliseconds=round((time.perf_counter()-t)*1000,2)))
            isolated=not m.search('花生',user_id='test',role_id='other')
            m.add('现在喜欢古典',fact_key='music',user_id='test',role_id='role')
            m.add('现在喜欢摇滚',fact_key='music',user_id='test',role_id='role')
            active=[r[0] for r in m.db.execute('SELECT text FROM memories WHERE fact_key=? AND active=1',('music',))]
            forgotten_id=m.add('只在测试期间记住的临时事实',user_id='test',role_id='role')['id']
            m.forget(forgotten_id)
            forgotten_rejected=not m.search('测试期间 临时事实',user_id='test',role_id='role')
            other_scope_clean=not m.search('花生',user_id='test',role_id='other')
            return dict(cases=results,passed=sum(r['passed'] for r in results),total=len(results),scope_isolated=isolated,update_correct=active==['现在喜欢摇滚'],forgotten_rejected=forgotten_rejected,other_scope_clean=other_scope_clean,elapsed_seconds=round(time.perf_counter()-start,2))
        finally:m.close()


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--cache',required=True);p.add_argument('--out',required=True);args=p.parse_args()
    report={'dataset':'sumika-chinese-regression-v1','boundary':'14 synthetic retrieval cases; not AML and not evidence of best provider; no answer model','keyword':evaluate(EmbeddedMemory),'semantic':evaluate(lambda db:SemanticMemory(db,cache_dir=args.cache))}
    Path(args.out).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({key:{k:v for k,v in report[key].items() if k!='cases'} for key in ('keyword','semantic')}))
