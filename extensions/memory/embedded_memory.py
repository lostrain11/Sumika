"""Embedded long-term memory: stdlib SQLite FTS5, no service or external dependency."""
import json,sqlite3,time,math
from pathlib import Path

class EmbeddedMemory:
 def __init__(self,path,enabled=True):
  self.enabled=enabled;self.path=Path(path)
  if enabled:
   self.path.parent.mkdir(parents=True,exist_ok=True);self.db=sqlite3.connect(self.path)
   self.db.executescript('''create table if not exists memories(id integer primary key,scope text not null,text text not null,source text not null,active integer not null default 1,created real,updated real); create virtual table if not exists memory_fts using fts5(text,content=memories,content_rowid=id); create table if not exists relations(scope text,subject text,predicate text,object text,source text,active integer default 1,created real);''');self.db.commit()
   with self.db:
    self.db.execute('BEGIN IMMEDIATE')
    columns={r[1] for r in self.db.execute('pragma table_info(memories)')}
    for column in ('fact_key','event_id'):
     if column not in columns:self.db.execute(f'alter table memories add column {column} text')
    self.db.execute('CREATE UNIQUE INDEX IF NOT EXISTS memory_event ON memories(scope,source,event_id) WHERE event_id IS NOT NULL')
    self.db.execute('CREATE TABLE IF NOT EXISTS memory_proposals (scope TEXT, event TEXT, data TEXT, PRIMARY KEY(scope,event))')
 def _scope(self,user,role,project):
  if any(not isinstance(x,str) or not x.strip() for x in (user,role,project)):raise ValueError('scope identifiers must be nonempty')
  return json.dumps([user,role,project],ensure_ascii=False)
 def add(self,text,*,user_id,role_id,project_id='default',source='user',fact_key=None,event_id=None):
  if not self.enabled:return {'disabled':True}
  if not isinstance(text,str) or not text.strip():raise ValueError('memory text must be nonempty')
  now=time.time();scope=self._scope(user_id,role_id,project_id)
  if not isinstance(source,str) or not source.strip() or (fact_key is not None and (not isinstance(fact_key,str) or not fact_key.strip())):raise ValueError('invalid provenance or fact key')
  if event_id is not None and (not isinstance(event_id,str) or not event_id.strip()):raise ValueError('invalid source event id')
  with self.db:
   self.db.execute('BEGIN IMMEDIATE')
   if event_id is not None:
    previous=self.db.execute('SELECT id,text,fact_key FROM memories WHERE scope=? AND source=? AND event_id=?',(scope,source,event_id)).fetchone()
    if previous:
     if previous[1:]!=(text,fact_key):raise ValueError('source event conflicts with existing memory')
     return {'id':previous[0],'fact_key':fact_key,'duplicate':True}
   if fact_key:
    self.db.execute('update memories set active=0,updated=? where scope=? and source=? and active=1 and (fact_key=? or (fact_key is null and substr(text,1,?)=?))',(now,scope,source,fact_key,len(fact_key)+1,fact_key+'='))
   c=self.db.execute('insert into memories(scope,text,source,created,updated,fact_key,event_id) values(?,?,?,?,?,?,?)',(scope,text,source,now,now,fact_key,event_id));i=c.lastrowid;self.db.execute('insert into memory_fts(rowid,text) values(?,?)',(i,text))
  return {'id':i,'fact_key':fact_key}
 def search(self,query,*,user_id,role_id,project_id='default',limit=8,source=None):
  if not self.enabled:return []
  if not isinstance(query,str) or type(limit) is not int or not 1<=limit<=100:raise ValueError('invalid search')
  terms=query.split()
  if not terms:return []
  scope=self._scope(user_id,role_id,project_id);q=' OR '.join('"'+x.replace('"','""')+'"' for x in terms)
  source_sql=' and m.source=?' if source else ''; params=[q,scope]+([source] if source else [])+[limit]
  rows=self.db.execute('select m.id,m.text,m.source from memory_fts f join memories m on m.id=f.rowid where f.text match ? and m.scope=?'+source_sql+' and m.active=1 order by rank,m.updated desc limit ?',params).fetchall()
  if not rows:
   rows=self.db.execute('select id,text,source from memories where scope=? and active=1'+(' and source=?' if source else '')+' order by updated desc',([scope,source] if source else [scope])).fetchall()
   terms=[t for t in query.split() if t]; rows=[r for r in rows if any(t in r[1] for t in terms)][:limit]
  return [{'id':i,'text':t,'source':s} for i,t,s in rows]
 def relate(self,subject,predicate,object,*,user_id,role_id,project_id='default',source='user'):
  if not self.enabled:return {'disabled':True}
  scope=self._scope(user_id,role_id,project_id);self.db.execute('insert into relations values(?,?,?,?,?,1,?)',(scope,subject,predicate,object,source,time.time()));self.db.commit();return {'stored':True}
 def edit_relation(self,subject,predicate,object,new_object,*,user_id,role_id,project_id='default'):
  if not self.enabled:return {'disabled':True}
  scope=self._scope(user_id,role_id,project_id);c=self.db.execute('update relations set object=? where scope=? and subject=? and predicate=? and object=? and active=1',(new_object,scope,subject,predicate,object));self.db.commit();return {'updated':c.rowcount}
 def delete_relation(self,subject,predicate,object,*,user_id,role_id,project_id='default'):
  if not self.enabled:return {'disabled':True}
  scope=self._scope(user_id,role_id,project_id);c=self.db.execute('update relations set active=0 where scope=? and subject=? and predicate=? and object=? and active=1',(scope,subject,predicate,object));self.db.commit();return {'deleted':c.rowcount}
 def reset_scope(self,*,user_id,role_id,project_id='default'):
  """Reset learned memory; imported role-card snapshots live outside this store."""
  if not self.enabled:return {'disabled':True}
  scope=self._scope(user_id,role_id,project_id);self.db.execute('update memories set active=0 where scope=?',(scope,));self.db.execute('update relations set active=0 where scope=?',(scope,));self.db.commit();return {'reset':True,'scope':scope}
 def restore_role_snapshot(self, facts, *, user_id, role_id, project_id='default', source='role_card'):
  if not self.enabled:return {'disabled':True}
  if not isinstance(facts,list) or any(not isinstance(f,str) or not f.strip() for f in facts):raise ValueError('invalid snapshot facts')
  scope=self._scope(user_id,role_id,project_id);now=time.time()
  rows=[dict(scope=scope,text=f,source=source,active=1,created=now,updated=now) for f in facts]
  self._import_rows(rows,[],scope,True)
  return {'restored':len(rows),'scope':scope}
 def source_counts(self,*,user_id,role_id,project_id='default'):
  """Active memory counts per provenance source for the current scope."""
  if not self.enabled:return []
  scope=self._scope(user_id,role_id,project_id)
  return [dict(source=src,count=count) for src,count in self.db.execute(
   'select source,count(*) from memories where scope=? and active=1 group by source order by count(*) desc,source',(scope,))]
 def list_relations(self,*,user_id,role_id,project_id='default',limit=100):
  if not self.enabled:return []
  if type(limit) is not int or not 1<=limit<=500:raise ValueError('invalid relation limit')
  scope=self._scope(user_id,role_id,project_id)
  return [dict(subject=s,predicate=p,object=o,source=src) for s,p,o,src in self.db.execute(
   'select subject,predicate,object,source from relations where scope=? and active=1 order by rowid desc limit ?',(scope,limit))]
 def related(self,subject,*,user_id,role_id,project_id='default',depth=2):
  if not self.enabled:return []
  scope=self._scope(user_id,role_id,project_id);front={subject};seen=set();out=[]
  for _ in range(max(1,depth)):
   rows=self.db.execute('select subject,predicate,object,source from relations where scope=? and active=1 and subject in (%s)'%','.join('?'*len(front)),[scope,*front]).fetchall() if front else []
   front=set()
   for s,p,o,src in rows:
    edge=(s,p,o,src)
    if edge not in seen:seen.add(edge);out.append({'subject':s,'predicate':p,'object':o,'source':src});front.add(o)
  return out
 def forget(self,id):
  if not self.enabled:return {'disabled':True}
  self.db.execute('update memories set active=0,updated=? where id=?',(time.time(),id));self.db.commit();return {'forgotten':id}
 def export_json(self,out,*,user_id=None,role_id=None,project_id='default'):
  if not self.enabled:return {'disabled':True}
  with self.db:
   self.db.execute('BEGIN')
   rows=self.db.execute('select id,scope,text,source,active,created,updated,fact_key,event_id from memories').fetchall()
   relations=self.db.execute('select scope,subject,predicate,object,source,active,created from relations').fetchall()
   proposals=self.db.execute('select scope,event,data from memory_proposals').fetchall()
  data={'schema_version':3,'memories':[dict(zip(('id','scope','text','source','active','created','updated','fact_key','event_id'),r)) for r in rows], 'relations':[dict(zip(('scope','subject','predicate','object','source','active','created'),r)) for r in relations], 'proposals':[dict(scope=s,event=e,data=json.loads(d)) for s,e,d in proposals]}
  if user_id is not None or role_id is not None:
   scope=self._scope(user_id,role_id,project_id)
   for key in ('memories','relations','proposals'):data[key]=[r for r in data[key] if r['scope']==scope]
  Path(out).write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf8');return {'count':len(data['memories']),'relations':len(data['relations'])}
 def _read_export(self,src,scope):
  data=json.loads(Path(src).read_text(encoding='utf8'))
  if isinstance(data,list):data={'schema_version':2,'memories':data,'relations':[]}
  if not isinstance(data,dict) or type(data.get('schema_version')) is not int or data['schema_version'] not in (2,3):raise ValueError('unsupported memory export')
  groups=[]
  for key,fields in [('memories',('text','source')),('relations',('subject','predicate','object','source'))]:
   rows=data.get(key)
   if not isinstance(rows,list):raise ValueError('invalid export collection')
   selected=[]
   for r in rows:
    if not isinstance(r,dict):raise ValueError('invalid export row')
    if r.get('scope')!=scope:continue
    if any(not isinstance(r.get(f),str) or not r[f].strip() for f in fields) or type(r.get('active')) is not int or r['active'] not in (0,1):raise ValueError('invalid memory row')
    for f in ('created','updated') if key=='memories' else ('created',):
     if type(r.get(f)) not in (int,float) or not math.isfinite(r[f]):raise ValueError('invalid timestamp')
    if key=='memories':
     for f in ('fact_key','event_id'):
      if r.get(f) is not None and (not isinstance(r[f],str) or not r[f].strip()):raise ValueError('invalid memory identity')
    selected.append(r)
   groups.append(selected)
  proposals=data.get('proposals',[]) if data['schema_version']==3 else []
  if not isinstance(proposals,list):raise ValueError('invalid proposals')
  selected=[]
  for row in proposals:
   if not isinstance(row,dict):raise ValueError('invalid proposal')
   if row.get('scope')!=scope:continue
   payload=row.get('data')
   if not isinstance(row.get('event'),str) or not row['event'].strip() or not isinstance(payload,dict):raise ValueError('invalid proposal identity')
   if payload.get('source')!='model_proposal' or not isinstance(payload.get('text'),str) or not payload['text'].strip():raise ValueError('invalid proposal provenance')
   key=payload.get('fact_key')
   if key is not None and (not isinstance(key,str) or not key.strip()):raise ValueError('invalid proposal fact key')
   extra={}
   for field in ('quote','message_id','status'):
    if field in payload:
     if not isinstance(payload[field],str) or not payload[field].strip():raise ValueError('invalid proposal metadata')
     extra[field]=payload[field]
   if extra.get('status','pending') not in ('pending','accepted','rejected'):raise ValueError('invalid proposal status')
   selected.append(dict(scope=scope,event=row['event'],data=dict(text=payload['text'],fact_key=key,source='model_proposal',**extra)))
  return (*groups,selected)
 def _import_rows(self,rows,relations,scope,replace,proposals=()):
  with self.db:
   self.db.execute('BEGIN IMMEDIATE')
   if replace:
    self.db.execute('update memories set active=0 where scope=?',(scope,))
    self.db.execute('update relations set active=0 where scope=?',(scope,))
   for row in rows:
    event=row.get('event_id')
    prior=self.db.execute('SELECT id,text,fact_key FROM memories WHERE scope=? AND source=? AND event_id=?',(scope,row['source'],event)).fetchone() if event is not None else None
    if prior:
     if prior[1:]!=(row['text'],row.get('fact_key')):raise ValueError('source event conflicts with existing memory')
     # Only explicit restore may reactivate an existing event; merge/replay cannot.
     if replace:self.db.execute('UPDATE memories SET active=?,updated=? WHERE id=?',(row['active'],row['updated'],prior[0]))
     continue
    c=self.db.execute('insert into memories(scope,text,source,active,created,updated,fact_key,event_id) values(?,?,?,?,?,?,?,?)',tuple(row[f] for f in ('scope','text','source','active','created','updated'))+(row.get('fact_key'),event))
    self.db.execute('insert into memory_fts(rowid,text) values(?,?)',(c.lastrowid,row['text']))
   for row in relations:
    self.db.execute('insert into relations(scope,subject,predicate,object,source,active,created) values(?,?,?,?,?,?,?)',tuple(row[f] for f in ('scope','subject','predicate','object','source','active','created')))
   for row in proposals:
    payload=json.dumps(row['data'],ensure_ascii=False,sort_keys=True)
    prior=self.db.execute('SELECT data FROM memory_proposals WHERE scope=? AND event=?',(scope,row['event'])).fetchone()
    if prior and prior[0]!=payload:raise ValueError('model proposal event conflict')
    self.db.execute('INSERT OR IGNORE INTO memory_proposals VALUES (?,?,?)',(scope,row['event'],payload))
  return {'imported':len(rows),'relations':len(relations),'proposals':len(proposals)}
 def import_json(self,src,*,user_id,role_id,project_id='default'):
  if not self.enabled:return {'disabled':True}
  scope=self._scope(user_id,role_id,project_id)
  rows,relations,proposals=self._read_export(src,scope)
  return self._import_rows(rows,relations,scope,False,proposals)
 def restore_json(self,src,*,user_id,role_id,project_id='default'):
  """Restore one scope atomically; invalid or conflicting data leaves it unchanged.

  Keep event tombstones and proposal history so subsequent retries stay idempotent.
  """
  if not self.enabled:return {'disabled':True}
  scope=self._scope(user_id,role_id,project_id);rows,relations,proposals=self._read_export(src,scope)
  if not rows and not relations and not proposals:raise ValueError('export does not contain target scope; use reset_scope to clear explicitly')
  return self._import_rows(rows,relations,scope,True,proposals)
 def close(self):
  if self.enabled:self.db.close()
