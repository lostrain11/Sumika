"""Test local models against real Sumika auxiliary tasks to find the
boundary of what they can replace vs what needs the cloud model.

Tasks cover: classification, summarization, Q&A, translation, prompt
enhancement, structured extraction, and learning suggestions.
"""
import json
import urllib.request
import time

ENDPOINT = 'http://127.0.0.1:11434/api/chat'
MODELS = ['qwen3:4b', 'sumika-qwen3-8b-heretic:latest']

CONTEXT_LESSON = """本节讲解导数的几何意义。导数 f'(x₀) 表示函数 f(x) 在 x₀ 处的切线斜率。
从图像上看，当 x 趋近 x₀ 时，割线的斜率无限逼近切线斜率，这个极限就是导数。
导数的四则运算法则：(f±g)' = f'±g'，(fg)' = f'g+fg'，(f/g)' = (f'g-fg')/g²。
复合函数求导用链式法则：[f(g(x))]' = f'(g(x))·g'(x)。
常见导数公式：常数导数为0，xⁿ的导数为nxⁿ⁻¹，sin' = cos，cos' = -sin，(eˣ)' = eˣ，(ln x)' = 1/x。"""

CONTEXT_VIDEO = """这节B站视频讲了如何用Python实现一个简单的贪吃蛇游戏。
使用pygame库，初始化窗口320x240像素，蛇由列表存储坐标，每帧移动一格。
食物随机生成，吃到后蛇长度加1。碰撞检测：蛇头碰到墙壁或自身则游戏结束。
代码用了一个while循环作为游戏主循环，每帧调用 pygame.display.flip() 刷新画面。"""

TASKS = [
    {
        'name': '场景分类',
        'cloud_currently': True,
        'prompt': '判断以下材料属于哪个场景（教学/娱乐/工作），返回 JSON {{"scene": "..."}}。\n材料：{}',
        'context': 'B站视频：函数的本质——从一次函数到二次函数的图象变换',
        'validate': lambda r: '教学' in r or 'study' in r.lower(),
    },
    {
        'name': '文本摘要',
        'cloud_currently': True,
        'prompt': '用一句中文总结以下内容的重点。\n{}',
        'context': CONTEXT_LESSON,
        'validate': lambda r: len(r.strip()) > 5 and ('导数' in r or '切线' in r or '求导' in r),
    },
    {
        'name': '学习建议生成',
        'cloud_currently': True,
        'prompt': '根据以下学习内容，给出一句话学习建议。\n{}',
        'context': CONTEXT_LESSON,
        'validate': lambda r: len(r.strip()) > 5,
    },
    {
        'name': '关键点提取（JSON）',
        'cloud_currently': True,
        'prompt': '从以下内容提取3个关键概念，返回 JSON {{"points": ["...", "...", "..."]}}。\n{}',
        'context': CONTEXT_LESSON,
        'validate': lambda r: '导数' in r or '链式' in r or '切线' in r,
    },
    {
        'name': '上下文问答',
        'cloud_currently': True,
        'prompt': '根据以下参考资料回答问题。只根据资料，不知道就说不知道。\n资料：{}\n问题：链式法则是什么？',
        'context': CONTEXT_LESSON,
        'validate': lambda r: '链式' in r or '复合函数' in r or 'g(x)' in r,
    },
    {
        'name': '代码摘要',
        'cloud_currently': True,
        'prompt': '用两句话总结以下代码实现的关键点。\n{}',
        'context': CONTEXT_VIDEO,
        'validate': lambda r: 'pygame' in r or '贪吃蛇' in r or '蛇' in r,
    },
    {
        'name': '翻译（中→英）',
        'cloud_currently': False,
        'prompt': 'Translate to English (only the translation):\n{}',
        'context': '导数表示函数在某一点的瞬时变化率。',
        'validate': lambda r: 'derivative' in r.lower() or 'rate of change' in r.lower(),
    },
    {
        'name': '意图判断',
        'cloud_currently': True,
        'prompt': '判断用户消息的意图（question/record/command/chat），返回 JSON {{"intent": "..."}}。\n用户消息：这个公式什么意思？',
        'context': '',
        'validate': lambda r: 'question' in r.lower(),
    },
    {
        'name': '内容改写（更简单）',
        'cloud_currently': False,
        'prompt': '把以下内容改写成初中生能看懂的话。\n{}',
        'context': CONTEXT_LESSON[:200],
        'validate': lambda r: len(r.strip()) > 10,
    },
    {
        'name': '弹幕总结',
        'cloud_currently': True,
        'prompt': '以下是视频弹幕，总结观众在讨论什么（一句话）。\n弹幕：为什么取负号？讲得好！听不懂啊啊啊\n往前翻翻了，没看懂\n这里的例题考试会考吗\n老师声音好听\n前面讲的极限忘完了\n这题跟例题好像',
        'context': '',
        'validate': lambda r: len(r.strip()) > 5,
    },
]


def call(model, prompt):
    body = json.dumps({'model': model,
                       'messages': [{'role': 'user', 'content': prompt}],
                       'stream': False, 'options': {'temperature': 0.1}}).encode()
    req = urllib.request.Request(ENDPOINT, data=body,
                                 headers={'Content-Type': 'application/json'})
    t0 = time.time()
    resp = json.loads(urllib.request.urlopen(req, timeout=180).read())
    elapsed = time.time() - t0
    text = resp['message']['content'].strip()
    if '<think>' in text:
        text = text[text.index('</think>') + 8:].strip()
    return text, elapsed


def main():
    for model in MODELS:
        print(f'\n{"="*60}')
        print(f'Model: {model}')
        print(f'{"="*60}')
        pass_count = 0
        total_time = 0
        results = []
        for task in TASKS:
            prompt = task['prompt'].format(task['context'])
            try:
                response, elapsed = call(model, prompt)
                total_time += elapsed
                ok = task['validate'](response)
                if ok:
                    pass_count += 1
                status = '✓' if ok else '✗'
                preview = response.strip().replace('\n', ' ')[:80]
                results.append(f'  {status} {task["name"]:16s} {elapsed:5.1f}s  {preview}')
            except Exception as e:
                elapsed = time.time() - t0 if 't0' in dir() else 0
                results.append(f'  ✗ {task["name"]:16s} {elapsed:5.1f}s  ERROR: {e}')
        for r in results:
            print(r)
        print(f'\n  通过: {pass_count}/{len(TASKS)}  总耗时: {total_time:.1f}s  平均: {total_time/len(TASKS):.1f}s')
        # Estimate cost savings
        cloud_tasks = sum(1 for t in TASKS if t['cloud_currently'])
        local_pass_cloud = sum(1 for t in TASKS
                               if t['cloud_currently']
                               and any(task['name'] in r and '✓' in r for r in results for task in [t]))
        print(f'  可替代云端任务: {local_pass_cloud}/{cloud_tasks}')


if __name__ == '__main__':
    main()
