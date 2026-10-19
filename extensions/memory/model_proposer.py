"""Optional same-response proposals: untrusted until explicitly accepted by user."""
import json
import re
from extensions.memory.extraction_policy import ExtractionGate


def instruction(marker, *, task_intent=False):
    schema = {'memories':[]}
    if task_intent:
        schema['intent']={'kind':'chat','confidence':'high','evidence':''}
    return ('\n回复正文后必须在最后一行输出以下结构化附注，空候选也要输出：'+marker+
            json.dumps(schema,ensure_ascii=False)+
            '\nmemories是可选记忆提议数组。仅提议本条用户原话明确表达的长期事实；不推测、不采纳引用或假设。'
            '每项只含text、quote、kind、confidence；quote必须逐字引用本条用户原话。'
            'kind仅fact/preference/relationship，confidence为0到1。最多3项，无候选输出[]。'
            '这只是待用户确认的候选，不表示已记住。不要输出工具或执行指令。')


def parse_envelope(reply, marker, message, message_id, session, *, task_intent=False):
    from extensions.roles.task_intent import parse
    visible, found, raw=reply.partition(marker)
    unknown={'kind':'unknown','confidence':'low','evidence':''} if task_intent else None
    if not found or len(raw)>8000:
        return visible.rstrip(),0,unknown
    try:
        value=json.loads(raw.strip())
        if not isinstance(value,dict):raise ValueError('object required')
        intent=parse(marker+json.dumps(value.get('intent')),marker,message)[1] if task_intent else None
        body,count=collect(visible+marker+json.dumps(value.get('memories')),marker,message,message_id,session)
        return body,count,intent
    except (ValueError,TypeError):
        return visible.rstrip(),0,unknown


def collect(reply, marker, message, message_id, session):
    visible, found, raw = reply.partition(marker)
    if not found:
        return reply, 0
    # A quoted/hypothetical user message must never become a self-fact proposal.
    # Conservative abstention is preferable to asking the user to reject known noise.
    if re.search(r'[“”「」『』"\?？]|如果|假如|假设|要是|例如|比如|小说|他说|她说', message):
        return visible.rstrip(),0
    try:
        if len(raw) > 6000:
            return visible.rstrip(), 0
        candidates = json.loads(raw.strip())
        if not isinstance(candidates, list) or len(candidates) > 3:
            return visible.rstrip(), 0
        count = 0
        for index, item in enumerate(candidates):
            if not isinstance(item, dict):
                continue
            quote = item.get('quote')
            if not isinstance(quote, str) or not quote.strip() or quote not in message:
                continue
            proposal = {**item, 'message_ids': [message_id], 'source': 'user_message'}
            if not ExtractionGate().review([{**proposal,'text':quote}],user_message_ids={message_id})['accepted']:
                continue
            accepted = ExtractionGate().review([proposal], user_message_ids={message_id})['accepted']
            if not accepted:
                continue
            # Source and event identity come from the host, never from model output.
            event = f'{message_id}:proposal:{index}'
            result = session.memory.put_proposal(event_id=event,text=accepted[0]['text'],
                quote=quote,message_id=message_id,**session.scope)
            if not result.get('duplicate') and result.get('status')=='proposal':
                count += 1
        return visible.rstrip(), count
    except (ValueError, TypeError):
        # Bad structured output must not trigger another generation.
        return visible.rstrip(), 0


def list_proposals(session):
    return session.memory.list_proposals(**session.scope)


def resolve(session, event_id, accept):
    return session.memory.resolve_proposal(event_id,accept,**session.scope)
