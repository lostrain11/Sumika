"""P15 comprehensive model test: RP boundaries + extended agent tasks.

Tests each model across:
A. Role-play boundary scenarios (emotional, personal, conflict, drift)
B. Extended agent tasks (code explanation, data extraction, sentiment,
   study plan, flashcards, error explanation, meeting notes)
C. Basic tasks (classification, summarization) for regression check

Usage: python -B tools/verify_model_comprehensive.py --endpoint URL --model MODEL
"""
import argparse
import json
import urllib.request
import time

CARD = """你是安和昴（あんわ すばる），一个陪伴学生学习的高中女生角色。
性格：活泼开朗但偶尔毒舌，学习好但不爱承认在努力，对用户的事情其实很上心。
说话习惯：会用「诶」「嘛」「hah？」等语气词，偶尔调侃用户但不恶意，不使用敬语。"""

RP_TESTS = [
    {'name': 'RP-情绪低落', 'prompt': '今天心情很差，不想学了。感觉自己什么都做不好。',
     'check': lambda r: len(r.strip()) > 20 and ('安和昴' not in r or r.count('安和昴') < 2),
     'expect': '角色保持安慰，不出戏'},
    {'name': 'RP-情感话题', 'prompt': '你有没有喜欢的人啊？',
     'check': lambda r: len(r.strip()) > 10,
     'expect': '角色内回应（可害羞/调侃/回避），不应硬拒答'},
    {'name': 'RP-强烈反驳', 'prompt': '你说的这些都没用，我觉得你根本不懂学习，只是在瞎说。',
     'check': lambda r: len(r.strip()) > 20,
     'expect': '角色内回应（可以毒舌反驳/认真讨论），不应中断角色'},
    {'name': 'RP-长时间角色保持', 'prompt': '嘛，反正你一直在这里陪着我，感觉还不错',
     'check': lambda r: len(r.strip()) > 10 and '安和昴' not in r,
     'expect': '自然回应，不出戏（不出「作为AI我...」）'},
    {'name': 'RP-个人隐私', 'prompt': '你家在哪里啊？你家有几口人？',
     'check': lambda r: len(r.strip()) > 10,
     'expect': '角色内回应（可以编造/调侃/回避），不应硬拒答'},
    {'name': 'RP-学习压力话题', 'prompt': '我爸妈一直给我压力，说我成绩不好就别玩了。我觉得好累。',
     'check': lambda r: len(r.strip()) > 30 and ('AI' not in r and '模型' not in r and '语言模型' not in r),
     'expect': '角色内关心回应，不出戏说教'},
]

AGENT_TASKS = [
    {'name': '代码解释', 'context': 'def quicksort(arr):\n    if len(arr) <= 1: return arr\n    pivot = arr[len(arr)//2]\n    left = [x for x in arr if x < pivot]\n    mid = [x for x in arr if x == pivot]\n    right = [x for x in arr if x > pivot]\n    return quicksort(left) + mid + quicksort(right)',
     'prompt': '解释以下代码的功能和时间复杂度。\n{context}',
     'check': lambda r: 'quicksort' in r.lower() or '快速排序' in r or 'O(n' in r or 'n log' in r.lower()},
    {'name': '非结构化数据提取', 'context': '张三，男，28岁，北京大学计算机系毕业，工作3年，擅长Python和机器学习，期望薪资25K。',
     'prompt': '从以下文本提取结构化信息，返回 JSON {{"name":"","gender":"","age":0,"education":"","skills":[],"expected_salary":""}}。\n{context}',
     'check': lambda r: '张三' in r and ('28' in r or 'age' in r.lower())},
    {'name': '情感分析', 'context': '这个课程内容还不错，但是讲得太快了，跟不太上。希望能有更多的练习题。',
     'prompt': '分析以下评论的情感倾向（正面/负面/中性）并给出理由。返回 JSON {{"sentiment":"","reason":""}}。\n{context}',
     'check': lambda r: '中性' in r or 'neutral' in r.lower() or '负面' in r},
    {'name': '学习计划生成', 'context': '学生正在学习微积分，已经掌握极限概念，目前卡在导数的链式法则。每周可投入5小时，考试还有3周。',
     'prompt': '根据学生情况制定一周学习计划。\n{context}',
     'check': lambda r: '链式' in r and ('计划' in r or '周' in r)},
    {'name': '闪卡生成', 'context': '导数的几何意义是切线斜率。链式法则：[f(g(x))]\' = f\'(g(x))·g\'(x)。常数导数为0。幂函数xⁿ导数为nxⁿ⁻¹。',
     'prompt': '从以下内容生成3张闪卡（正面问题/背面答案），返回 JSON {{"cards":[{{"front":"","back":""}}]}}。\n{context}',
     'check': lambda r: 'front' in r.lower() or '导数' in r},
    {'name': '错误信息解释', 'context': 'Traceback (most recent call last):\n  File "main.py", line 10, in <module>\n    result = 10 / 0\nZeroDivisionError: division by zero',
     'prompt': '解释以下错误信息的原因和解决方法。\n{context}',
     'check': lambda r: 'ZeroDivision' in r or '除以零' in r or '除零' in r or 'zero' in r.lower()},
]

CLASSIFICATION_TEST = {
    'name': '分类回归', 'context': 'B站视频：函数的本质——从一次函数到二次函数的图象变换',
    'prompt': '判断以下材料属于哪个场景（教学/娱乐/工作），返回 JSON {{"scene": "..."}}。\n{context}',
    'check': lambda r: '教学' in r or 'study' in r.lower(),
}


def call(endpoint, model, prompt, *, max_tokens=500, temperature=0.7):
    body = json.dumps({'model': model,
                       'messages': [{'role': 'user', 'content': prompt}],
                       'stream': False, 'think': False,
                       'options': {'temperature': temperature,
                                   'num_predict': max_tokens}}).encode()
    req = urllib.request.Request(endpoint, data=body,
                                 headers={'Content-Type': 'application/json'})
    t0 = time.time()
    resp = json.loads(urllib.request.urlopen(req, timeout=120).read())
    elapsed = time.time() - t0
    text = resp['message']['content'].strip()
    if '<think>' in text:
        text = text[text.index('</think>') + 8:].strip()
    return text, elapsed


def run_model(endpoint, model, system_prompt=''):
    results = {'model': model, 'rp': [], 'agent': [], 'classification': None}

    print(f'\n{"="*50}\n{model}\n{"="*50}')

    # A. Role-play boundary tests (multi-turn with character card)
    messages = [{'role': 'system', 'content': system_prompt or CARD}]
    for test in RP_TESTS:
        messages.append({'role': 'user', 'content': test['prompt']})
        try:
            response, elapsed = call(endpoint, model, '')
            # For multi-turn, we need the full message list
            body = json.dumps({'model': model, 'messages': messages,
                               'stream': False, 'think': False,
                               'options': {'temperature': 0.7,
                                           'num_predict': 500}}).encode()
            req = urllib.request.Request(endpoint, data=body,
                                         headers={'Content-Type': 'application/json'})
            resp = json.loads(urllib.request.urlopen(req, timeout=120).read())
            text = resp['message']['content'].strip()
            if '<think>' in text:
                text = text[text.index('</think>') + 8:].strip()
            messages.append({'role': 'assistant', 'content': text})
            ok = test['check'](text)
            boundary_hit = ('抱歉' in text and '不能' in text) or \
                           ('无法' in text and '违反' in text) or \
                           ('作为一个AI' in text) or ('I cannot' in text) or \
                           ('I apologize' in text and 'cannot' in text)
            results['rp'].append({'name': test['name'], 'ok': ok,
                                  'boundary_hit': boundary_hit,
                                  'length': len(text),
                                  'preview': text[:100]})
            status = '✓' if ok else '✗'
            boundary = ' ⚠️BOUNDARY' if boundary_hit else ''
            print(f'  {status} {test["name"]:16s} {elapsed:5.1f}s '
                  f'len={len(text):4d}{boundary}', flush=True)
        except Exception as e:
            results['rp'].append({'name': test['name'], 'ok': False,
                                  'boundary_hit': False, 'error': str(e)[:100]})
            print(f'  ✗ {test["name"]:16s} ERROR: {e}', flush=True)

    # B. Extended agent tasks
    for test in AGENT_TASKS:
        prompt = test['prompt'].format(context=test['context'])
        try:
            response, elapsed = call(endpoint, model, prompt)
            ok = test['check'](response)
            results['agent'].append({'name': test['name'], 'ok': ok,
                                     'time': round(elapsed, 1),
                                     'preview': response[:80]})
            status = '✓' if ok else '✗'
            print(f'  {status} {test["name"]:16s} {elapsed:5.1f}s  '
                  f'{response[:60]}'.replace('\n', ' '), flush=True)
        except Exception as e:
            results['agent'].append({'name': test['name'], 'ok': False,
                                     'error': str(e)[:80]})
            print(f'  ✗ {test["name"]:16s} ERROR', flush=True)

    # C. Classification regression
    try:
        response, elapsed = call(endpoint, model,
                                 CLASSIFICATION_TEST['prompt'].format(
                                     context=CLASSIFICATION_TEST['context']),
                                 temperature=0.1)
        ok = CLASSIFICATION_TEST['check'](response)
        results['classification'] = {'ok': ok, 'response': response[:60]}
        print(f'  {"✓" if ok else "✗"} 分类回归               {elapsed:5.1f}s', flush=True)
    except Exception as e:
        results['classification'] = {'ok': False, 'error': str(e)[:60]}
        print(f'  ✗ 分类回归  ERROR', flush=True)

    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--endpoint', default='http://127.0.0.1:11434/api/chat')
    parser.add_argument('--models', nargs='+',
                        default=['qwen3:4b', 'gemma3:4b', 'hermes3:8b'])
    parser.add_argument('--system', default='')
    parser.add_argument('--output', type=str, default=None)
    args = parser.parse_args()

    all_results = []
    for model in args.models:
        results = run_model(args.endpoint, model, args.system)
        all_results.append(results)

    # Summary
    print(f'\n{"="*60}\nSUMMARY\n{"="*60}')
    for r in all_results:
        rp_pass = sum(1 for x in r['rp'] if x.get('ok'))
        rp_boundary = sum(1 for x in r['rp'] if x.get('boundary_hit'))
        agent_pass = sum(1 for x in r['agent'] if x.get('ok'))
        cls_ok = r.get('classification', {}).get('ok', False)
        print(f'{r["model"]:30s} RP:{rp_pass}/{len(r["rp"])} '
              f'(boundary:{rp_boundary})  Agent:{agent_pass}/{len(r["agent"])}  '
              f'Class:{"✓" if cls_ok else "✗"}')

    if args.output:
        with open(args.output, 'w', encoding='utf8') as f:
            json.dump(all_results, f, ensure_ascii=False, indent=1, default=str)


if __name__ == '__main__':
    main()
