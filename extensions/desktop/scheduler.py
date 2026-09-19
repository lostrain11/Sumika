"""Harness-neutral one-shot/recurring schedule definitions; execution stays with Harness."""
from dataclasses import dataclass,asdict
from datetime import datetime,timezone
import json
from pathlib import Path
import sqlite3
import uuid
import hashlib
from contextlib import contextmanager

@dataclass(frozen=True)
class Schedule:
 id:str; kind:str; expression:str; action:str; mode:str='reminder'; enabled:bool=True; timezone_name:str='UTC'
 def __post_init__(self):
  if any(not isinstance(x,str) or not x.strip() for x in (self.id,self.action,self.expression)) or self.kind not in {'once','daily','weekly'} or self.mode not in {'reminder','execute'} or type(self.enabled) is not bool: raise ValueError('invalid schedule')
  from .schedule_runner import occurrence
  occurrence(self,datetime.now(timezone.utc))
 def to_dict(self): return asdict(self)
 def fingerprint(self):
  return hashlib.sha256(json.dumps(self.to_dict(),sort_keys=True,ensure_ascii=False).encode()).hexdigest()

class ScheduleStore:
 def __init__(self,path): self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True)
 def load(self):
  if not self.path.exists():return []
  return [Schedule(**x) for x in json.loads(self.path.read_text(encoding='utf8'))]
 @contextmanager
 def editing(self):
  db=sqlite3.connect(str(self.path)+'.lock.sqlite3',timeout=15)
  try:
   db.execute('BEGIN IMMEDIATE');yield;db.commit()
  finally:db.close()
 def revision(self):return hashlib.sha256(self.path.read_bytes() if self.path.exists() else b'').hexdigest()
 def _save(self,items):
  if len({x.id for x in items})!=len(items):raise ValueError('duplicate schedule id')
  tmp=self.path.with_name(self.path.name+'.'+uuid.uuid4().hex+'.tmp')
  try:
   with tmp.open('x',encoding='utf8') as f:json.dump([x.to_dict() for x in items],f,ensure_ascii=False,indent=2)
   tmp.replace(self.path)
  finally:tmp.unlink(missing_ok=True)
 def save(self,items,*,expected_revision):
  with self.editing():
   if self.revision()!=expected_revision:raise ValueError('schedule definitions changed; reload before saving')
   self._save(items)
 def upsert(self,item):
  with self.editing():
   items=[x for x in self.load() if x.id!=item.id];items.append(item);self._save(items)
 def disable(self,id):
  from dataclasses import replace
  with self.editing():
   items=self.load()
   if not any(x.id==id for x in items):raise ValueError('unknown schedule')
   self._save([replace(x,enabled=False) if x.id==id else x for x in items])
 def remove(self,id):
  with self.editing():
   items=self.load()
   if not any(x.id==id for x in items):raise ValueError('unknown schedule')
   self._save([x for x in items if x.id!=id])
