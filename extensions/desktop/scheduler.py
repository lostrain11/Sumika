"""Harness-neutral one-shot/recurring schedule definitions; execution stays with Harness."""
from dataclasses import dataclass,asdict
from datetime import datetime,timezone
import json
from pathlib import Path

@dataclass(frozen=True)
class Schedule:
 id:str; kind:str; expression:str; action:str; mode:str='reminder'; enabled:bool=True
 def __post_init__(self):
  if not self.id.strip() or self.kind not in {'once','daily','weekly'} or self.mode not in {'reminder','execute'} or not self.action.strip(): raise ValueError('invalid schedule')
 def to_dict(self): return asdict(self)

class ScheduleStore:
 def __init__(self,path): self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True)
 def load(self):
  if not self.path.exists():return []
  return [Schedule(**x) for x in json.loads(self.path.read_text(encoding='utf8'))]
 def save(self,items):
  tmp=self.path.with_suffix('.tmp');tmp.write_text(json.dumps([x.to_dict() for x in items],ensure_ascii=False,indent=2),encoding='utf8');tmp.replace(self.path)
 def upsert(self,item):
  items=[x for x in self.load() if x.id!=item.id];items.append(item);self.save(items)
 def disable(self,id): self.upsert(next(Schedule(x.id,x.kind,x.expression,x.action,x.mode,False) for x in self.load() if x.id==id))
