"""Deterministic Chinese memory evaluation for the embedded provider."""
import argparse,json,tempfile,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from extensions.memory.embedded_memory import EmbeddedMemory

def evaluate(path):
 m=EmbeddedMemory(path); total=passed=0
 def check(ok):
  nonlocal total,passed;total+=1;passed+=bool(ok)
 m.add('用户喜欢中文界面和轻音乐',user_id='u',role_id='aoi',source='user')
 m.add('安和昴是乐队鼓手，喜欢游戏',user_id='u',role_id='aoi',source='role_card')
 check(bool(m.search('中文界面',user_id='u',role_id='aoi',source='user')))
 check(not m.search('中文界面',user_id='u',role_id='other'))
 m.add('偏好=爵士',user_id='u',role_id='aoi',fact_key='偏好');m.add('偏好=古典',user_id='u',role_id='aoi',fact_key='偏好')
 check(bool(m.search('古典',user_id='u',role_id='aoi')) and not m.search('爵士',user_id='u',role_id='aoi'))
 m.relate('昴','成员','乐队',user_id='u',role_id='aoi');m.relate('乐队','主唱','仁菜',user_id='u',role_id='aoi');check(len(m.related('昴',user_id='u',role_id='aoi',depth=2))==2)
 check(not m.search('游戏',user_id='u',role_id='other'))
 out=Path(path).with_suffix('.json');m.export_json(out);report=Path(path).with_suffix('.report.json');report.write_text(json.dumps({'provider':'EmbeddedMemory','passed':passed,'total':total,'score':passed/total,'export':str(out)},ensure_ascii=False,indent=2),encoding='utf8');m.close();return {'passed':passed,'total':total,'score':passed/total,'export':str(out),'report':str(report)}
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--db',required=True);a=p.parse_args();print(json.dumps(evaluate(a.db),ensure_ascii=False))
