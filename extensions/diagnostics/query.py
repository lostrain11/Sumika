"""Read-only diagnostics over existing continuity records; never export raw payloads."""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import zipfile


def identifier(value):
    if value is None:return None
    text=str(value)
    # Correlatable opaque tokens replace arbitrary text, paths and likely secrets.
    if re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}',text) and not re.search(r'sk-|bearer|token|password|secret',text,re.I):return text
    return 'redacted-'+hashlib.sha256(text.encode()).hexdigest()[:16]


def markers(payload):
    result=[]
    for key in ('status','state','error_kind','error_code'):
        value=payload.get(key)
        if isinstance(value,str):
            result.extend(m for m in ('error','failed','denied','timeout','unknown') if m in value.lower())
    if payload.get('isError') is True:result.append('error')
    return sorted(set(result))


def query(root, *, task=None, session=None, call_id=None, error_kind=None, error_only=False, limit=50, before=None):
    db=Path(root)/'.sumika-continuity/records.sqlite3'
    if not db.is_file():raise ValueError('continuity database missing')
    if type(limit) is not int or not 1<=limit<=100:raise ValueError('invalid limit')
    if before is not None and (type(before) is not int or before<1):raise ValueError('invalid cursor')
    clauses=[];args=[]
    for key,value in (('task',task),('session',session)):
        if value is not None:
            if not isinstance(value,str) or not value:raise ValueError('invalid filter')
            clauses.append(key+'=?');args.append(value)
    if before is not None:clauses.append('seq<?');args.append(before)
    sql='SELECT seq,data FROM records'+(' WHERE '+' AND '.join(clauses) if clauses else '')+' ORDER BY seq DESC'
    out=[]
    # mode=ro prevents accidental database creation or mutation; stream matching
    # rows so recent unrelated records cannot hide an older failure.
    with closing(sqlite3.connect(db.resolve().as_uri()+'?mode=ro',uri=True)) as conn:
        for seq,raw in conn.execute(sql,args):
            record=json.loads(raw);payload=record.get('payload',{})
            if not isinstance(payload,dict):payload={}
            ids=[payload[k] for k in ('callId','toolCallId','source_id') if isinstance(payload.get(k),str)]
            if call_id is not None and call_id not in ids:continue
            found=markers(payload)
            if error_only and not found:continue
            if error_kind is not None and error_kind not in found and error_kind!=payload.get('error_code') and error_kind!=payload.get('error_kind'):continue
            out.append({'seq':seq,'kind':identifier(record.get('kind')),'task':identifier(record.get('task')),
                'session':identifier(record.get('session')),'git_head':identifier(record.get('git_head')),
                'recorded_at':record.get('recorded_at') if re.fullmatch(r'[0-9T:.+Z-]{10,40}',str(record.get('recorded_at'))) else None,
                'call_ids':[identifier(v) for v in ids],'error_markers':found,
                'error_code':identifier(payload.get('error_code')),
                'provenance':'observed_record_metadata','source':'continuity.records','dsh_version':None})
            if len(out)==limit:break
    release=Path(root)/'runtime/dsh/release.json'
    if release.is_file():
        try:version=identifier(json.loads(release.read_text(encoding='utf8')).get('version'))
        except (OSError,ValueError,AttributeError):version=None
        for row in out:row['dsh_version']=version
    return out


def timeline(root, task, out=None):
    rows=query(root,task=task,limit=100)
    result={'schema_version':2,'task':identifier(task),'events':list(reversed(rows)),
            'next_before':rows[-1]['seq'] if len(rows)==100 else None,
            'boundary':'Metadata only; no original text, reasoning or tool arguments. Recorded outcomes are not independent verification. DSH-native event adapter is not connected.'}
    if out:
        p=Path(out)
        with p.open('x',encoding='utf8') as f:json.dump(result,f,ensure_ascii=False,indent=2)
        return {'path':str(p),'events':len(rows)}
    return result


def evidence_bundle(root, task, out):
    root=Path(root).resolve();out=Path(out).resolve()
    data=timeline(root,task)
    # Project documents are arbitrary user text: hashes prove identity without
    # copying raw goals, local paths, prompts or credentials into the bundle.
    sources=[]
    for rel in ('docs/project/handoff.json','docs/project/progress.json','docs/project/plan.json'):
        p=root/rel
        if p.is_file():
            with p.open('rb') as f:sha=hashlib.file_digest(f,'sha256').hexdigest()
            sources.append({'source':rel,'sha256':sha})
    files={'timeline.json':json.dumps(data,ensure_ascii=False,indent=2),
           'sources.json':json.dumps(sources,indent=2)}
    out.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(out,'x',zipfile.ZIP_DEFLATED) as z:
        for name,content in files.items():z.writestr(name,content)
    return {'path':str(out),'files':list(files)}
