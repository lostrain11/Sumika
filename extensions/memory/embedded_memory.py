"""Embedded long-term memory: stdlib SQLite FTS5, no service or external dependency."""
import json,sqlite3,time
from pathlib import Path

class EmbeddedMemory:
 def __init__(self,path,enabled=True):
  self.enabled=enabled;self.path=Path(path)
  if enabled:
   self.path.parent.mkdir(parents=True,exist_ok=True);self.db=sqlite3.connect(self.path)
   self.db.executescript('''create table if not exists memories(id integer primary key,scope text not null,text text not null,source text not null,active integer not null default 1,created real,updated real); create virtual table if not exists memory_fts using fts5(text,content=memories,content_rowid=id); create table if not exists relations(scope text,subject text,predicate text,object text,source text,active integer default 1,created real);''');self.db.commit()
 def _scope(self,user,role,project):return json.dumps([user,role,project],ensure_ascii=False)
 def add(self,text,*,user_id,role_id,project_id='default',source='user',fact_key=None):
  if not self.enabled:return {'disabled':True}
  if not isinstance(text,str) or not text.strip():raise ValueError('memory text must be nonempty')
  now=time.time();scope=self._scope(user_id,role_id,project_id)
  if fact_key:
   self.db.execute('update memories set active=0,updated=? where scope=? and source=? and text like ? and active=1',(now,scope,source,fact_key+'=%'))
  c=self.db.execute('insert into memories(scope,text,source,created,updated) values(?,?,?,?,?)',(scope,text,source,now,now));i=c.lastrowid;self.db.execute('insert into memory_fts(rowid,text) values(?,?)',(i,text));self.db.commit();return {'id':i,'fact_key':fact_key}
 def search(self,query,*,user_id,role_id,project_id='default',limit=8,source=None):
  if not self.enabled:return []
  scope=self._scope(user_id,role_id,project_id);q=' OR '.join(x for x in query.split() if x)
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
  self.reset_scope(user_id=user_id,role_id=role_id,project_id=project_id)
  count=0
  for fact in facts:
   if isinstance(fact,str) and fact.strip(): self.add(fact,user_id=user_id,role_id=role_id,project_id=project_id,source=source);count+=1
  return {'restored':count,'scope':self._scope(user_id,role_id,project_id)}
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
 def export_json(self,out):
  if not self.enabled:return {'disabled':True}
  rows=self.db.execute('select id,scope,text,source,active,created,updated from memories').fetchall();Path(out).write_text(json.dumps([dict(zip(('id','scope','text','source','active','created','updated'),r)) for r in rows],ensure_ascii=False,indent=2),encoding='utf8');return {'count':len(rows)}
 def import_json(self,src,*,user_id,role_id,project_id='default'):
  if not self.enabled:return {'disabled':True}
  rows=json.loads(Path(src).read_text(encoding='utf8'))
  if not isinstance(rows,list): raise ValueError('memory export must be a list')
  scope=self._scope(user_id,role_id,project_id);count=0
  for row in rows:
   if not isinstance(row,dict) or row.get('scope')!=scope or not isinstance(row.get('text'),str): continue
   c=self.db.execute('insert into memories(scope,text,source,active,created,updated) values(?,?,?,?,?,?)',(scope,row['text'],row['source'],int(row.get('active',1)),row.get('created',time.time()),row.get('updated',time.time())));self.db.execute('insert into memory_fts(rowid,text) values(?,?)',(c.lastrowid,row['text']));count+=1
  self.db.commit();return {'imported':count}
 def restore_json(self,src,*,user_id,role_id,project_id='default'):
  """Replace one scope from an export; invalid rows are skipped and old data is recoverable by reimport."""
  if not self.enabled:return {'disabled':True}
  self.reset_scope(user_id=user_id,role_id=role_id,project_id=project_id)
  return self.import_json(src,user_id=user_id,role_id=role_id,project_id=project_id)
 def close(self):
  if self.enabled:self.db.close()
