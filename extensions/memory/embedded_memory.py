"""Embedded long-term memory: stdlib SQLite FTS5, no service or external dependency."""
import json,sqlite3,time,math,uuid
from pathlib import Path
from extensions.memory.repository import SQLiteRepository, evidence_refs

class EmbeddedMemory(SQLiteRepository):
 def __init__(self,path,enabled=True):
  self.enabled=enabled;self.path=Path(path)
  if enabled:
   self.path.parent.mkdir(parents=True,exist_ok=True);self.db=sqlite3.connect(self.path)
   # Use SQLite's consistent backup API before migrating an existing database.
   # This may also contain usage tables; never copy an open .db file blindly.
   if self.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='memories'").fetchone():
    if 'record_id' not in {r[1] for r in self.db.execute('PRAGMA table_info(memories)')}:
     backup=self.path.with_name(self.path.name+'.pre-repository-'+uuid.uuid4().hex+'.sqlite3')
     target=sqlite3.connect(backup)
     try:self.db.backup(target)
     finally:target.close()
   self.db.executescript('''create table if not exists memories(id integer primary key,scope text not null,text text not null,source text not null,active integer not null default 1,created real,updated real); create virtual table if not exists memory_fts using fts5(text,content=memories,content_rowid=id); create table if not exists relations(scope text,subject text,predicate text,object text,source text,active integer default 1,created real);''');self.db.commit()
   with self.db:
    self.db.execute('BEGIN IMMEDIATE')
    columns={r[1] for r in self.db.execute('pragma table_info(memories)')}
    for column in ('fact_key','event_id'):
     if column not in columns:self.db.execute(f'alter table memories add column {column} text')
    self.db.execute('CREATE UNIQUE INDEX IF NOT EXISTS memory_event ON memories(scope,source,event_id) WHERE event_id IS NOT NULL')
    self.db.execute('CREATE TABLE IF NOT EXISTS memory_proposals (scope TEXT, event TEXT, data TEXT, PRIMARY KEY(scope,event))')
    self._migrate_repository()
 def _scope(self,user,role,project):
  if any(not isinstance(x,str) or not x.strip() for x in (user,role,project)):raise ValueError('scope identifiers must be nonempty')
  return json.dumps([user,role,project],ensure_ascii=False)
 def add(self,text,*,user_id,role_id,project_id='default',source='user',fact_key=None,event_id=None,evidence=None):
  if not self.enabled:return {'disabled':True}
  if not isinstance(text,str) or not text.strip():raise ValueError('memory text must be nonempty')
  scope=self._scope(user_id,role_id,project_id)
  if not isinstance(source,str) or not source.strip() or (fact_key is not None and (not isinstance(fact_key,str) or not fact_key.strip())):raise ValueError('invalid provenance or fact key')
  if event_id is not None and (not isinstance(event_id,str) or not event_id.strip()):raise ValueError('invalid source event id')
  refs=evidence_refs(evidence,source=source,event_id=event_id)
  with self.db:
   self.db.execute('BEGIN IMMEDIATE')
   return self._add_in_transaction(text,scope=scope,source=source,fact_key=fact_key,event_id=event_id,refs=refs)
 def _add_in_transaction(self,text,*,scope,source,fact_key,event_id,refs):
  now=time.time()
  if self._is_purged(scope,refs=refs,source=source,event_id=event_id):return {'status':'suppressed','retrievable':False}
  if event_id is not None:
   previous=self.db.execute('SELECT id,text,fact_key,record_id,revision FROM memories WHERE scope=? AND source=? AND event_id=?',(scope,source,event_id)).fetchone()
   if previous:
    if previous[1:3]!=(text,fact_key):raise ValueError('source event conflicts with existing memory')
    return {'id':previous[0],'record_id':previous[3],'revision':previous[4],'fact_key':fact_key,'duplicate':True}
  if self._is_suppressed(scope,refs):return {'status':'suppressed','retrievable':False}
  if fact_key:
   self.db.execute("update memories set active=0,status='superseded',revision=revision+1,updated=? where scope=? and source=? and active=1 and (fact_key=? or (fact_key is null and substr(text,1,?)=?))",(now,scope,source,fact_key,len(fact_key)+1,fact_key+'='))
  record_id=uuid.uuid4().hex
  c=self.db.execute('insert into memories(scope,text,source,created,updated,fact_key,event_id,record_id,evidence_refs) values(?,?,?,?,?,?,?,?,?)',(scope,text,source,now,now,fact_key,event_id,record_id,json.dumps(refs,ensure_ascii=False)));i=c.lastrowid
  self.db.execute('insert into memory_fts(rowid,text) values(?,?)',(i,text))
  self._invalidate_vectors(scope)
  return {'id':i,'record_id':record_id,'revision':1,'fact_key':fact_key}
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
  records=[self.get_record(i,user_id=user_id,role_id=role_id,project_id=project_id) for i,t,s in rows]
  return [{k:record[k] for k in ('id','record_id','revision','text','source')} for record in records if record and record['active']]
 def relate(self,subject,predicate,object,*,user_id,role_id,project_id='default',source='user'):
  if not self.enabled:return {'disabled':True}
  scope=self._scope(user_id,role_id,project_id);self.db.execute('insert into relations(scope,subject,predicate,object,source,active,created,record_id) values(?,?,?,?,?,1,?,?)',(scope,subject,predicate,object,source,time.time(),uuid.uuid4().hex));self.db.commit();return {'stored':True}
 def edit_relation(self,subject,predicate,object,new_object,*,user_id,role_id,project_id='default'):
  if not self.enabled:return {'disabled':True}
  scope=self._scope(user_id,role_id,project_id);c=self.db.execute('update relations set object=?,revision=revision+1 where scope=? and subject=? and predicate=? and object=? and active=1',(new_object,scope,subject,predicate,object));self.db.commit();return {'updated':c.rowcount}
 def delete_relation(self,subject,predicate,object,*,user_id,role_id,project_id='default'):
  if not self.enabled:return {'disabled':True}
  scope=self._scope(user_id,role_id,project_id);c=self.db.execute("update relations set active=0,status='deleted',revision=revision+1 where scope=? and subject=? and predicate=? and object=? and active=1",(scope,subject,predicate,object));self.db.commit();return {'deleted':c.rowcount}
 def reset_scope(self,*,user_id,role_id,project_id='default'):
  """Reset learned memory; imported role-card snapshots live outside this store."""
  if not self.enabled:return {'disabled':True}
  scope=self._scope(user_id,role_id,project_id)
  with self.db:
   self.db.execute('BEGIN IMMEDIATE')
   self._forget_scope_in_transaction(scope)
  return {'reset':True,'scope':scope}
 def restore_role_snapshot(self, facts, *, user_id, role_id, project_id='default', source='role_card'):
  if not self.enabled:return {'disabled':True}
  if not isinstance(facts,list) or any(not isinstance(f,str) or not f.strip() for f in facts):raise ValueError('invalid snapshot facts')
  scope=self._scope(user_id,role_id,project_id);now=time.time()
  rows=[dict(scope=scope,text=f,source=source,active=1,created=now,updated=now) for f in facts]
  self._import_rows(rows,[],scope,True,reset=True)
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
  return [dict(subject=s,predicate=p,object=o,source=src,record_id=rid,revision=rev) for s,p,o,src,rid,rev in self.db.execute(
   'select subject,predicate,object,source,record_id,revision from relations where scope=? and active=1 order by rowid desc limit ?',(scope,limit))]
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
  row=self.db.execute('SELECT scope FROM memories WHERE id=?',(id,)).fetchone()
  if row:
   user,role,project=json.loads(row[0]);self.forget_record(id,user_id=user,role_id=role,project_id=project)
  return {'forgotten':id}
 def export_json(self,out,*,user_id=None,role_id=None,project_id='default'):
  if not self.enabled:return {'disabled':True}
  with self.db:
   self.db.execute('BEGIN')
   rows=self.db.execute('select id,scope,text,source,active,created,updated,fact_key,event_id,record_id,revision,status,evidence_refs from memories').fetchall()
   relations=self.db.execute('select scope,subject,predicate,object,source,active,created,record_id,revision,status from relations').fetchall()
   proposals=self.db.execute('select scope,event,data from memory_proposals').fetchall()
   suppressions=self.db.execute('select scope,evidence_key,created from memory_suppressions').fetchall()
   purges=self.db.execute('SELECT scope,kind,identity_hash FROM memory_purge_tombstones').fetchall()
  data={'schema_version':5,'memories':[dict(zip(('id','scope','text','source','active','created','updated','fact_key','event_id','record_id','revision','status','evidence_refs'),r)) for r in rows], 'relations':[dict(zip(('scope','subject','predicate','object','source','active','created','record_id','revision','status'),r)) for r in relations], 'proposals':[dict(scope=s,event=e,data=json.loads(d)) for s,e,d in proposals], 'suppressions':[dict(scope=s,evidence_key=k,created=t) for s,k,t in suppressions]}
  data['purge_tombstones']=[dict(scope=s,kind=k,identity_hash=h) for s,k,h in purges]
  for row in data['memories']:row['evidence_refs']=json.loads(row['evidence_refs'])
  if user_id is not None or role_id is not None:
   scope=self._scope(user_id,role_id,project_id)
   for key in ('memories','relations','proposals','suppressions','purge_tombstones'):data[key]=[r for r in data[key] if r['scope']==scope]
  Path(out).write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf8');return {'count':len(data['memories']),'relations':len(data['relations'])}
 def _read_export(self,src,scope):
  data=json.loads(Path(src).read_text(encoding='utf8'))
  if isinstance(data,list):data={'schema_version':2,'memories':data,'relations':[]}
  if not isinstance(data,dict) or type(data.get('schema_version')) is not int or data['schema_version'] not in (2,3,4,5):raise ValueError('unsupported memory export')
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
    if data['schema_version']>=4:
     if not isinstance(r.get('record_id'),str) or not r['record_id'].strip() or len(r['record_id'])>128 or type(r.get('revision')) is not int or r['revision']<1:raise ValueError('invalid stable memory identity')
     if r.get('status') not in ('active','superseded','deleted') or bool(r['active'])!=(r['status']=='active'):raise ValueError('invalid memory lifecycle')
    if key=='memories':r={**r,'evidence_refs':evidence_refs(r.get('evidence_refs'),source=r['source'],event_id=r.get('event_id'))}
    selected.append(r)
   ids=[r['record_id'] for r in selected if 'record_id' in r]
   if len(set(ids))!=len(ids):raise ValueError('duplicate stable memory identity')
   groups.append(selected)
  proposals=data.get('proposals',[]) if data['schema_version']>=3 else []
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
   if 'revision' in payload:
    if type(payload['revision']) is not int or payload['revision']<1:raise ValueError('invalid proposal revision')
    extra['revision']=payload['revision']
   if 'evidence_refs' in payload:extra['evidence_refs']=evidence_refs(payload['evidence_refs'],source='model_proposal',event_id=row['event'])
   elif 'message_id' in extra:
    from extensions.memory.repository import message_evidence
    extra['evidence_refs']=message_evidence(extra['message_id'])
   selected.append(dict(scope=scope,event=row['event'],data=dict(text=payload['text'],fact_key=key,source='model_proposal',**extra)))
  suppressions=data.get('suppressions',[]) if data['schema_version']>=4 else []
  if not isinstance(suppressions,list):raise ValueError('invalid suppression collection')
  selected_suppressions=[]
  for row in suppressions:
   if not isinstance(row,dict):raise ValueError('invalid suppression')
   if row.get('scope')!=scope:continue
   key=row.get('evidence_key');created=row.get('created')
   if not isinstance(key,str) or len(key)!=64 or any(c not in '0123456789abcdef' for c in key) or type(created) not in (int,float) or not math.isfinite(created):raise ValueError('invalid suppression identity')
   selected_suppressions.append(row)
  if data['schema_version']<4:
   by_event={p['event']:p['data'].get('evidence_refs') for p in selected}
   for row in groups[0]:
    refs=by_event.get(row.get('event_id'))
    if row['source']=='user-confirmed' and refs:row['evidence_refs']=refs
  purges=data.get('purge_tombstones',[]) if data['schema_version']>=5 else []
  if not isinstance(purges,list):raise ValueError('invalid purge collection')
  selected_purges=[]
  for row in purges:
   if not isinstance(row,dict):raise ValueError('invalid purge tombstone')
   if row.get('scope')!=scope:continue
   key=row.get('identity_hash')
   if row.get('kind') not in ('evidence','record','event','proposal') or not isinstance(key,str) or len(key)!=64 or any(c not in '0123456789abcdef' for c in key):raise ValueError('invalid purge tombstone')
   selected_purges.append(row)
  return (*groups,selected,selected_suppressions,selected_purges)
 def _import_rows(self,rows,relations,scope,replace,proposals=(),suppressions=(),purges=(),*,reset=False):
  with self.db:
   self.db.execute('BEGIN IMMEDIATE')
   if reset:
    self._forget_scope_in_transaction(scope)
   elif replace:
    self.db.execute("update memories set active=0,status='superseded',revision=revision+1 where scope=? AND active=1",(scope,))
    self.db.execute("update relations set active=0,status='superseded',revision=revision+1 where scope=? AND active=1",(scope,))
    # Explicit historical restore may undo suppression for the selected scope;
    # merge never does. Restore the snapshot's suppression set below.
    self.db.execute('DELETE FROM memory_suppressions WHERE scope=?',(scope,))
   for row in purges:self._purge_guard(scope,row['kind'],row['identity_hash'])
   self._enforce_purges_in_transaction(scope) if purges else None
   for row in suppressions:self.db.execute('INSERT OR IGNORE INTO memory_suppressions VALUES (?,?,?)',(scope,row['evidence_key'],row['created']))
   for row in rows:
    event=row.get('event_id')
    stable=row.get('record_id')
    if self._is_purged(scope,refs=row.get('evidence_refs',[]),record_id=stable,source=row['source'],event_id=event):continue
    prior=self.db.execute('SELECT id,text,fact_key,scope,source,event_id,record_id,revision FROM memories WHERE record_id=?',(stable,)).fetchone() if stable else None
    by_event=self.db.execute('SELECT id,text,fact_key,scope,source,event_id,record_id,revision FROM memories WHERE scope=? AND source=? AND event_id=?',(scope,row['source'],event)).fetchone() if event is not None else None
    if prior and (prior[3:6]!=(scope,row['source'],event) or (by_event and prior[0]!=by_event[0])):raise ValueError('stable identity conflict')
    prior=prior or by_event
    if prior:
     if prior[1:3]!=(row['text'],row.get('fact_key')):raise ValueError('source event conflicts with existing memory')
     if stable and prior[6]!=stable:raise ValueError('source event has another stable identity')
     # Only explicit restore may reactivate an existing event; merge/replay cannot.
     if replace:self.db.execute('UPDATE memories SET active=?,status=?,revision=?,updated=?,evidence_refs=? WHERE id=?',(row['active'],row.get('status','active' if row['active'] else 'superseded'),max(prior[7]+1,row.get('revision',1)),row['updated'],json.dumps(row.get('evidence_refs',[])),prior[0]))
     current=self.db.execute('SELECT status FROM memories WHERE id=?',(prior[0],)).fetchone()[0]
     if not replace and row.get('status')=='deleted' and (current!='deleted' or row.get('revision',1)>prior[7]):
      self._suppress(scope,row.get('evidence_refs',[]))
      self.db.execute("UPDATE memories SET active=0,status='deleted',revision=?,updated=? WHERE id=?",(max(prior[7]+1,row.get('revision',1)),row['updated'],prior[0]))
     elif not replace and stable and row.get('status')=='superseded' and current=='active' and row.get('revision',1)>prior[7]:
      self.db.execute("UPDATE memories SET active=0,status='superseded',revision=?,updated=? WHERE id=?",(row['revision'],row['updated'],prior[0]))
     continue
    refs=row.get('evidence_refs',[]);suppressed=self._is_suppressed(scope,refs)
    c=self.db.execute('insert into memories(scope,text,source,active,created,updated,fact_key,event_id,record_id,revision,status,evidence_refs) values(?,?,?,?,?,?,?,?,?,?,?,?)',(scope,row['text'],row['source'],0 if suppressed else row['active'],row['created'],row['updated'],row.get('fact_key'),event,stable or uuid.uuid4().hex,row.get('revision',1),'deleted' if suppressed else row.get('status','active' if row['active'] else 'superseded'),json.dumps(refs)))
    self.db.execute('insert into memory_fts(rowid,text) values(?,?)',(c.lastrowid,row['text']))
   for row in relations:
    stable=row.get('record_id');prior=self.db.execute('SELECT scope,subject,predicate,object,source,revision,status FROM relations WHERE record_id=?',(stable,)).fetchone() if stable else None
    if prior:
     if (prior[0],prior[1],prior[2],prior[4])!=tuple(row[f] for f in ('scope','subject','predicate','source')):raise ValueError('relation identity conflict')
     if replace:self.db.execute('UPDATE relations SET object=?,active=?,status=?,revision=? WHERE record_id=?',(row['object'],row['active'],row.get('status','active' if row['active'] else 'superseded'),max(prior[5]+1,row.get('revision',1)),stable))
     elif row.get('status')=='deleted' and (prior[6]!='deleted' or row.get('revision',1)>prior[5]):self.db.execute("UPDATE relations SET active=0,status='deleted',revision=? WHERE record_id=?",(max(prior[5]+1,row.get('revision',1)),stable))
     elif row.get('revision',1)==prior[5] and prior[3]!=row['object']:raise ValueError('relation revision conflict')
    else:self.db.execute('insert into relations(scope,subject,predicate,object,source,active,created,record_id,revision,status) values(?,?,?,?,?,?,?,?,?,?)',tuple(row[f] for f in ('scope','subject','predicate','object','source','active','created'))+(stable or uuid.uuid4().hex,row.get('revision',1),row.get('status','active' if row['active'] else 'superseded')))
   for row in proposals:
    if self._is_purged(scope,refs=row['data'].get('evidence_refs',[]),proposal_event=row['event']):continue
    payload=json.dumps(row['data'],ensure_ascii=False,sort_keys=True)
    prior=self.db.execute('SELECT data FROM memory_proposals WHERE scope=? AND event=?',(scope,row['event'])).fetchone()
    if prior:
     old=json.loads(prior[0])
     if any(old.get(k)!=row['data'].get(k) for k in ('text','fact_key','quote','message_id')):raise ValueError('model proposal event conflict')
     # Merge must preserve a resolved decision; explicit restore can restore it.
     if replace:
      restored={**row['data'],'revision':max(old.get('revision',1)+1,row['data'].get('revision',1))}
      payload=json.dumps(restored,ensure_ascii=False,sort_keys=True)
      self.db.execute('UPDATE memory_proposals SET data=? WHERE scope=? AND event=?',(payload,scope,row['event']))
    self.db.execute('INSERT OR IGNORE INTO memory_proposals VALUES (?,?,?)',(scope,row['event'],payload))
   self._apply_suppressions(scope);self._invalidate_vectors(scope)
  return {'imported':len(rows),'relations':len(relations),'proposals':len(proposals)}
 def import_json(self,src,*,user_id,role_id,project_id='default'):
  if not self.enabled:return {'disabled':True}
  scope=self._scope(user_id,role_id,project_id)
  rows,relations,proposals,suppressions,purges=self._read_export(src,scope)
  return self._import_rows(rows,relations,scope,False,proposals,suppressions,purges)
 def restore_json(self,src,*,user_id,role_id,project_id='default'):
  """Restore one scope atomically; invalid or conflicting data leaves it unchanged.

  Keep event tombstones and proposal history so subsequent retries stay idempotent.
  """
  if not self.enabled:return {'disabled':True}
  scope=self._scope(user_id,role_id,project_id);rows,relations,proposals,suppressions,purges=self._read_export(src,scope)
  if not rows and not relations and not proposals and not suppressions and not purges:raise ValueError('export does not contain target scope; use reset_scope to clear explicitly')
  return self._import_rows(rows,relations,scope,True,proposals,suppressions,purges)
 def close(self):
  if self.enabled:self.db.close()
