"""Local role/memory service. CLI is usable through any Harness terminal tool.

Only explicit facts are stored. This service never infers user confirmation or
executes a role card's instructions. Models and tool authorization stay in Harness.
"""
import argparse
import json
import sys
from pathlib import Path
from extensions.memory.embedded_memory import EmbeddedMemory
from extensions.roles.context import build
from extensions.roles.roles import load_role


class RoleSession:
    def __init__(self, role_dir, database, *, user_id, project_id, work_model, role_model, enabled=True, memory_provider='embedded', embedding_cache=None, embedding_python=None, memory_enabled=True, card_context_enabled=False, card_context_budget_chars=8000, target_language='zh-Hans', language_policy=None, allow_card_policy=True):
        if type(enabled) is not bool: raise ValueError('invalid enabled')
        if type(card_context_enabled) is not bool: raise ValueError('invalid card context switch')
        if type(allow_card_policy) is not bool: raise ValueError('invalid card policy switch')
        self.enabled=enabled
        if not enabled: return
        self.role=load_role(role_dir)
        if not self.role.get('enabled',True):
            self.enabled=False
            return
        if self.role['verified']['status']=='failed':raise ValueError('role checksum mismatch')
        self.compiled_card=None
        self.card_context_status='off'
        self.card_context_budget_chars=card_context_budget_chars
        self.target_language=target_language
        self.language_policy=language_policy
        self.allow_card_policy=allow_card_policy
        if card_context_enabled:
            from extensions.roles.card_context import compile_card
            if type(card_context_budget_chars) is not int or card_context_budget_chars<1:
                raise ValueError('invalid card context budget')
            # Card context is a preference for the whole client, but a card is a
            # per-role asset. A role without a usable card keeps its own persona and
            # worldbook instead of failing every reply; the reason is recorded so
            # the caller can report it rather than pretending the card was used.
            card=self.role.get('assets',{}).get('card')
            if not card:
                self.card_context_status='unavailable: this role has no card asset'
            else:
                try:
                    self.compiled_card=compile_card(card)
                    self.card_context_status='on'
                except (ValueError,OSError) as error:
                    self.compiled_card=None
                    self.card_context_status='unavailable: '+str(error)
        self.scope=dict(user_id=user_id,role_id=self.role['id'],project_id=project_id)
        if any(not isinstance(x,str) or not x.strip() for x in (*self.scope.values(),work_model,role_model)):raise ValueError('invalid session configuration')
        if type(memory_enabled) is not bool:raise ValueError('invalid memory switch')
        if not memory_enabled:self.memory=EmbeddedMemory(database,enabled=False)
        elif memory_provider=='embedded':self.memory=EmbeddedMemory(database)
        elif memory_provider=='semantic':
            from extensions.memory.semantic_memory import SemanticMemory
            if embedding_cache is None:raise ValueError('embedding_cache required')
            self.memory=SemanticMemory(database,cache_dir=embedding_cache,embedding_python=embedding_python)
        else:raise ValueError('unsupported memory provider; no fallback')
        self.work_model=work_model;self.role_model=role_model

    def request(self, operation, data):
        if not self.enabled:return {'disabled':True}
        if operation=='context':
            user=data['user_content']
            if not isinstance(user,str):raise ValueError('user_content must be text')
            mode=data.get('mode','work')
            if mode not in ('work','role'):raise ValueError('unknown mode')
            if self.compiled_card is not None:
                from extensions.roles.card_context import select_context
                selected=select_context(self.compiled_card,user,budget_chars=self.card_context_budget_chars,
                    memory=self.memory.search(data.get('query',user),**self.scope),
                    target_language=self.target_language,language_policy=self.language_policy,
                    allow_card_policy=self.allow_card_policy)
                role_block=dict(selected['role_context'])
                memories=role_block.pop('memory')
                context=build(user_content=user,role_block=role_block,memory_records=memories,task_context=data.get('task_context'))
                return dict(context=context,selection=selected['selection'],role_context=selected['role_context'],model=self.work_model if mode=='work' else self.role_model,mode=mode)
            words=user.casefold()
            worldbook=[]
            for item in self.role.get('worldbook',[]):
                if isinstance(item,str):worldbook.append(item)
                elif isinstance(item,dict) and item.get('enabled',True):
                    keys=item.get('keys',[])
                    if item.get('constant') or any(isinstance(k,str) and k and k.casefold() in words for k in keys):
                        worldbook.append(item.get('content',''))
            memories=self.memory.search(data.get('query',user),**self.scope)
            role_block=dict(name=self.role['name'],persona=self.role['persona'],worldbook=worldbook)
            context=build(user_content=user,role_block=role_block,memory_records=memories,task_context=data.get('task_context'))
            return dict(context=context,role_context={**role_block,'memory':memories,'recent':[]},
                        model=self.work_model if mode=='work' else self.role_model,mode=mode)
        if operation=='remember':return self.memory.add(data['text'],source=data.get('source','user'),fact_key=data.get('fact_key'),event_id=data.get('event_id'),**self.scope)
        if operation=='localize_names':
            from extensions.roles.card_context import localize_names
            if not isinstance(data.get('text'),str):raise ValueError('text required')
            if self.compiled_card is None:
                raise ValueError('card context required')
            return localize_names(data['text'],self.compiled_card.get('name_map',{}))
        if operation=='search':return self.memory.search(data['query'],**self.scope)
        if operation=='relations_all':return self.memory.list_relations(**self.scope,limit=data.get('limit',100))
        if operation=='sources':return self.memory.source_counts(**self.scope)
        if operation=='relate':return self.memory.relate(data['subject'],data['predicate'],data['object'],**self.scope)
        if operation=='relations':return self.memory.related(data['subject'],**self.scope)
        if operation=='edit_relation':return self.memory.edit_relation(data['subject'],data['predicate'],data['object'],data['new_object'],**self.scope)
        if operation=='delete_relation':return self.memory.delete_relation(data['subject'],data['predicate'],data['object'],**self.scope)
        if operation=='forget':
            scope=self.memory._scope(**dict(user=self.scope['user_id'],role=self.scope['role_id'],project=self.scope['project_id']))
            with self.memory.db:
                count=self.memory.db.execute('UPDATE memories SET active=0 WHERE id=? AND scope=?',(data['id'],scope)).rowcount
            return {'forgotten':count}
        if operation=='reset_to_card':
            facts=[self.role['persona']] if self.role['persona'].strip() else []
            facts.extend(x if isinstance(x,str) else x.get('content','') for x in self.role.get('worldbook',[]) if isinstance(x,(dict,str)))
            return self.memory.restore_role_snapshot([x for x in facts if x.strip()],**self.scope)
        if operation=='restore':return self.memory.restore_json(data['path'],**self.scope)
        if operation=='export':return self.memory.export_json(data['path'],**self.scope)
        raise ValueError('unsupported operation')

    def close(self):
        if self.enabled:self.memory.close()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config',type=Path,required=True);p.add_argument('--request',type=Path)
    args=p.parse_args();session=None
    try:
        config=json.loads(args.config.read_text(encoding='utf8'))
        request=json.loads(args.request.read_text(encoding='utf8')) if args.request else json.load(sys.stdin)
        session=RoleSession(**config)
        print(json.dumps(session.request(request['operation'],request.get('data',{})),ensure_ascii=False))
        return 0
    except (OSError,ValueError,KeyError,TypeError) as e:
        p.exit(2,'role service: '+str(e)+'\n')
    finally:
        if session:session.close()


if __name__=='__main__':raise SystemExit(main())
