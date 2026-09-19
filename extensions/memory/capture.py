"""Harness-neutral capture of explicit user memory instructions.

Only a trusted host supplies accepted user messages. Text cannot choose origin,
scope or event identity. Ordinary conversation needs a separate inference flow.
"""
import hashlib
import json
import re
from .write_policy import MemoryWriter

DIRECTIVE=re.compile(r'^(?:请)?记住(?:\[([^\]\r\n]+)\])?[：:]([\s\S]+)$')


def capture(memory,scope,*,namespace,session_id,messages):
    if not memory.enabled:return {'disabled':True}
    if any(not isinstance(x,str) or not x.strip() for x in (namespace,session_id)):raise ValueError('host event namespace and session required')
    if not isinstance(messages,list) or len(messages)>100:raise ValueError('invalid user message batch')
    records=[]
    for message in messages:
        if not isinstance(message,dict) or set(message)!={'id','text'}:raise ValueError('invalid host user message')
        if any(not isinstance(message[k],str) or not message[k].strip() for k in ('id','text')):raise ValueError('message identity and text required')
        match=DIRECTIVE.fullmatch(message['text'])
        if not match:continue
        key,text=match.groups()
        if not text.strip() or (key is not None and not key.strip()):raise ValueError('empty memory instruction')
        identity=json.dumps([namespace,session_id,message['id']],ensure_ascii=False)
        records.append((hashlib.sha256(identity.encode()).hexdigest(),text,key))
    writer=MemoryWriter(memory,scope)
    # A crash between records is safe: retries reuse the same event identity.
    results=[writer.record(origin='user',event_id=event,text=text,fact_key=key) for event,text,key in records]
    return {'recorded':len(results),'duplicates':sum(bool(r.get('duplicate')) for r in results)}
