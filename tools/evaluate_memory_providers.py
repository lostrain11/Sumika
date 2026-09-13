"""Run the same deterministic cases against any memory provider adapter."""
import argparse, json, tempfile, sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from extensions.memory.embedded_memory import EmbeddedMemory

def run(provider_factory, root):
    m=provider_factory(Path(root)); total=passed=0; cases=[]
    def check(name, ok):
        nonlocal total, passed
        total += 1; passed += bool(ok); cases.append({'name':name,'passed':bool(ok)})
    m.add('用户偏好中文界面和轻音乐',user_id='u',role_id='r',source='user')
    m.add('角色喜欢游戏',user_id='u',role_id='r',source='role_card')
    check('fact_recall', bool(m.search('中文界面',user_id='u',role_id='r')))
    check('scope_isolation', not m.search('中文界面',user_id='u',role_id='other'))
    m.add('偏好=爵士',user_id='u',role_id='r',fact_key='偏好')
    m.add('偏好=古典',user_id='u',role_id='r',fact_key='偏好')
    check('fact_update', bool(m.search('古典',user_id='u',role_id='r')))
    m.close()
    return {'provider':type(m).__name__,'passed':passed,'total':total,'score':passed/total,'cases':cases}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--db',required=True);p.add_argument('--out',required=True);a=p.parse_args()
    result=run(EmbeddedMemory,a.db);Path(a.out).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8');print(json.dumps(result,ensure_ascii=False))
