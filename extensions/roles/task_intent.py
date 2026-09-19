"""One-response intent metadata, advisory only; never grants tool authority."""
import json


def instruction(marker):
    return (
        '\n回复正文保持角色自然对话。正文结束后另起一行追加机器标记：'
        + marker + '{"kind":"chat","confidence":"high","evidence":""}。'
        'kind仅可为chat、discussion、task、unknown。只判断本次用户原文：'
        '明确要求执行具体工作才是task；讨论、假设、引用、否定不是任务；'
        '指代不明用unknown。confidence仅high或low。task的evidence必须逐字摘录'
        '本次用户提出具体任务的完整语句，否则留空。不推断项目或授权，不宣称执行。'
        '标记不属于角色正文，不要在正文解释标记。'
    )


def parse(text, marker, original):
    unknown = {'kind': 'unknown', 'confidence': 'low', 'evidence': ''}
    if marker not in text:
        return text, unknown
    body, raw = text.split(marker, 1)
    # Never show malformed metadata or send a repair request.
    try:
        value = json.loads(raw.strip())
    except (ValueError, TypeError):
        return body.rstrip(), unknown
    if not isinstance(value, dict) or set(value) != {'kind', 'confidence', 'evidence'}:
        return body.rstrip(), unknown
    if value['kind'] not in ('chat', 'discussion', 'task', 'unknown') or value['confidence'] not in ('high', 'low'):
        return body.rstrip(), unknown
    evidence = value['evidence']
    if not isinstance(evidence, str) or len(evidence) > len(original):
        return body.rstrip(), unknown
    if value['kind'] == 'task' and (not evidence.strip() or evidence not in original):
        return body.rstrip(), unknown
    return body.rstrip(), value
