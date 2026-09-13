"""Independent Mem0-shaped memory adapter with local SQLite baseline storage.

The backend can later be replaced by Mem0 OSS without changing callers. Raw user facts
are stored with explicit provenance; this module never asks an LLM to infer facts.
"""
import json,sqlite3,time
from pathlib import Path

class MemoryStore:
 def __init__(self,path,enabled=True):
  self.path=Path(path); self.enabled=enabled
  if enabled:
   self.path.parent.mkdir(parents=True,exist_ok=True); self.db=sqlite3.connect(self.path)
   self.db.execute('create table if not exists memories (id integer primary key, scope text, text text, source text, created real, updated real)');self.db.commit()
 def add(self,text,*,user_id,role_id,project_id='default',source='user'):
  if not self.enabled:return {'disabled':True}
  if not isinstance(text,str) or not text.strip():raise ValueError('memory text must be nonempty')
  scope=json.dumps([user_id,role_id,project_id],ensure_ascii=False)
  now=time.time();self.db.execute('insert into memories(scope,text,source,created,updated) values(?,?,?,?,?)',(scope,text,source,now,now));self.db.commit();return {'id':self.db.execute('select last_insert_rowid()').fetchone()[0]}
 def search(self,query,*,user_id,role_id,project_id='default',limit=8):
  if not self.enabled:return []
  scope=json.dumps([user_id,role_id,project_id],ensure_ascii=False)
  terms=[x for x in query.lower().split() if x]
  rows=self.db.execute('select id,text,source from memories where scope=? order by updated desc',(scope,)).fetchall()
  ranked=sorted(rows,key=lambda r:sum(t in r[1].lower() for t in terms),reverse=True)
  return [{'id':r[0],'text':r[1],'source':r[2]} for r in ranked[:limit] if not terms or any(t in r[1].lower() for t in terms)]
 def close(self):
  if self.enabled:self.db.close()
