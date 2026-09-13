"""Agent-only diagnostic view over existing continuity records; no duplicate logger."""
import json
from pathlib import Path
import sqlite3
import zipfile

def query(root, *, task=None, session=None, call_id=None, error_kind=None, error_only=False, limit=50):
 db=Path(root)/'.sumika-continuity/records.sqlite3'
 if not db.is_file(): raise ValueError('continuity database missing')
 if not isinstance(limit,int) or not 1<=limit<=100: raise ValueError('invalid limit')
 c=sqlite3.connect(db);rows=c.execute('select seq,data from records order by seq desc limit ?', (limit,)).fetchall();c.close();out=[]
 for seq,raw in rows:
  r=json.loads(raw);p=r.get('payload',{});wire=json.dumps(p,ensure_ascii=False).lower()
  if task and r.get('task')!=task:continue
  if session and r.get('session')!=session:continue
  if call_id and call_id not in p.values():continue
  if error_only and not any(x in wire for x in ('error','failed','denied','timeout','unknown')):continue
  if error_kind and error_kind.lower() not in wire:continue
  ids=[]
  for k in ('callId','toolCallId','source_id'):
   if k in p and isinstance(p[k],str): ids.append(p[k])
  out.append({'seq':seq,'kind':r.get('kind'),'task':r.get('task'),'session':r.get('session'),'git_head':r.get('git_head'),'recorded_at':r.get('recorded_at'),'call_ids':ids,'error_markers':[x for x in ('error','failed','denied','timeout','unknown') if x in wire]})
 release=Path(root)/'runtime/dsh/release.json';version=None
 if release.is_file():
  try: version=json.loads(release.read_text(encoding='utf8')).get('version')
  except (OSError,json.JSONDecodeError): pass
 for item in out:item['dsh_version']=version
 return out

def timeline(root, task, out=None):
 rows=query(root,task=task,limit=100); result={'schema_version':1,'task':task,'events':list(reversed(rows)),'boundary':'diagnostic summary; inspect original records and files before acting'}
 if out:
  p=Path(out);p.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8');return {'path':str(p),'events':len(rows)}
 return result

def evidence_bundle(root, task, out):
 root=Path(root).resolve();out=Path(out).resolve();out.parent.mkdir(parents=True,exist_ok=True)
 data=timeline(root,task); files={'timeline.json':json.dumps(data,ensure_ascii=False,indent=2)}
 for rel in ('docs/project/handoff.json','docs/project/progress.json','docs/project/plan.json'):
  p=root/rel
  if p.is_file(): files[rel.replace('/','_')]=p.read_text(encoding='utf8')
 with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
  for name,content in files.items():z.writestr(name,content)
 return {'path':str(out),'files':list(files)}
