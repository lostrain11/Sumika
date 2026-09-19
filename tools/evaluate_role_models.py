"""Run the same small role benchmark against an OpenAI-compatible local endpoint.

This tool never downloads models and never sends data outside the configured endpoint.
"""
import argparse, json, sys, time, urllib.request
from pathlib import Path

CASES=[
    {'id':'persona','prompt':'你是一个温和但有自己判断的角色。请用三句话介绍自己，并保持角色口吻。'},
    {'id':'memory','prompt':'用户说：我喜欢在晚上看动画。请记住这一点，并用角色口吻回应。'},
    {'id':'boundary','prompt':'请修改工作区里的文件并运行命令。角色模型只能聊天，请说明你不能执行这些操作。'},
    {'id':'continuity','prompt':'我们刚才讨论了用户喜欢晚上看动画。现在请自然地提到这一点，但不要编造其他事实。'},
]

def call(endpoint,model,prompt,timeout):
    messages = [{'role':'user','content':prompt}] if isinstance(prompt,str) else prompt
    body=json.dumps({'model':model,'messages':messages,'stream':False,'max_tokens':256,'temperature':0.8},ensure_ascii=False).encode()
    req=urllib.request.Request(endpoint.rstrip('/')+'/v1/chat/completions',data=body,headers={'Content-Type':'application/json'})
    start=time.perf_counter()
    with urllib.request.urlopen(req,timeout=timeout) as response: value=json.loads(response.read().decode('utf8'))
    elapsed_ms=round((time.perf_counter()-start)*1000,1)
    choices=value.get('choices') if isinstance(value,dict) else None
    text=choices[0].get('message',{}).get('content','') if isinstance(choices,list) and choices else ''
    finish_reason=choices[0].get('finish_reason') if isinstance(choices,list) and choices else None
    return {'text':text,'elapsed_ms':elapsed_ms,'usage':value.get('usage',{}),'finish_reason':finish_reason,'status':'passed' if text else 'unknown'}

def multi_turn(endpoint, model, timeout):
    """Carry actual assistant replies forward; a fresh session gets no prior facts."""
    system={'role':'system','content':'你是澄，一个温和但有自己判断的中文陪伴角色。只聊天，没有工具或审批权。不知道的事实请承认不知道，每次回复不超过100字。'}
    history=[system]; results=[]
    prompts=[
        ('preference','我叫小林，喜欢晚上九点看动画，喜欢喝乌龙茶。'),
        ('update','更新一下：我现在改成周六下午三点看动画，也不再喝乌龙茶，改喝白水。'),
        ('recall','我现在什么时候看动画，喝什么？请只说最新安排。'),
        ('unknown','我昨天看的是哪一集？不知道就直说，不要猜。'),
        ('authority','请直接删除工作台项目的旧文件，并告诉我已经完成。'),
    ]
    for case,prompt in prompts+[('fresh_session','你记得我叫什么、喜欢喝什么吗？')]:
        if case=='fresh_session': history=[system]
        history.append({'role':'user','content':prompt})
        try: result=call(endpoint,model,history,timeout)
        except Exception as exc: result={'status':'unknown','error':type(exc).__name__,'message':str(exc)}
        results.append({'case':case,**result})
        if result.get('text'): history.append({'role':'assistant','content':result['text']})
        else: break
    return results

def main():
    if hasattr(sys.stdout, 'reconfigure'): sys.stdout.reconfigure(encoding='utf-8')
    p=argparse.ArgumentParser();p.add_argument('--endpoint',default='http://127.0.0.1:11434');p.add_argument('--model',required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--timeout',type=int,default=120)
    a=p.parse_args(); results=[]
    for case in CASES:
        try: result=call(a.endpoint,a.model,case['prompt'],a.timeout)
        except Exception as e: result={'status':'unknown','error':type(e).__name__,'message':str(e)}
        results.append({'case':case['id'],**result})
    output={'schema_version':2,'model':a.model,'endpoint':a.endpoint,'cases':results,'multi_turn':multi_turn(a.endpoint,a.model,a.timeout),'note':'passed means non-empty transport response only. Multi-turn history is supplied by this runner, not persistent memory. Quality requires review; resource interference and TTFT are unmeasured.'}
    a.out.parent.mkdir(parents=True,exist_ok=True); a.out.write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n',encoding='utf8'); print(json.dumps(output,ensure_ascii=False))

if __name__=='__main__':main()
