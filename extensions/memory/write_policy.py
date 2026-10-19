"""Host-facing provenance boundary; never derives authority from remembered text.

The host supplies the origin and native event id. Do not expose origin selection
as model tool parameters. Inferred facts stay as proposals, outside retrieval.
"""
class MemoryWriter:
    def __init__(self,memory,scope):
        self.memory=memory;self.scope=dict(scope)

    def record(self,*,origin,event_id,text,fact_key=None,evidence=None):
        if not self.memory.enabled:return {'disabled':True}
        if origin not in ('user','role_card','model'):raise ValueError('unknown memory origin')
        if not isinstance(event_id,str) or not event_id.strip() or not isinstance(text,str) or not text.strip():raise ValueError('event id and text required')
        if fact_key is not None and (not isinstance(fact_key,str) or not fact_key.strip()):raise ValueError('invalid fact key')
        if origin!='model':
            # The host may attach the original message evidence so message-level
            # retraction/purge can find facts written from that message.
            return self.memory.add(text,source=origin,event_id=event_id,fact_key=fact_key,
                                   evidence=evidence,**self.scope)
        return self.memory.put_proposal(event_id=event_id,text=text,fact_key=fact_key,**self.scope)
