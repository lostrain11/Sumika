"""Host-facing provenance boundary; never derives authority from remembered text.

The host supplies the origin and native event id. Do not expose origin selection
as model tool parameters. Inferred facts stay as proposals, outside retrieval.
"""
import json


class MemoryWriter:
    def __init__(self,memory,scope):
        self.memory=memory;self.scope=dict(scope)

    def record(self,*,origin,event_id,text,fact_key=None):
        if not self.memory.enabled:return {'disabled':True}
        if origin not in ('user','role_card','model'):raise ValueError('unknown memory origin')
        if not isinstance(event_id,str) or not event_id.strip() or not isinstance(text,str) or not text.strip():raise ValueError('event id and text required')
        if fact_key is not None and (not isinstance(fact_key,str) or not fact_key.strip()):raise ValueError('invalid fact key')
        if origin!='model':
            return self.memory.add(text,source=origin,event_id=event_id,fact_key=fact_key,**self.scope)
        scope=self.memory._scope(self.scope['user_id'],self.scope['role_id'],self.scope.get('project_id','default'))
        data=json.dumps(dict(text=text,fact_key=fact_key,source='model_proposal'),ensure_ascii=False,sort_keys=True)
        with self.memory.db:
            self.memory.db.execute('BEGIN IMMEDIATE')
            prior=self.memory.db.execute('SELECT data FROM memory_proposals WHERE scope=? AND event=?',(scope,event_id)).fetchone()
            if prior and prior[0]!=data:raise ValueError('model proposal event conflict')
            self.memory.db.execute('INSERT OR IGNORE INTO memory_proposals VALUES (?,?,?)',(scope,event_id,data))
        return {'status':'proposal','event_id':event_id,'retrievable':False}
