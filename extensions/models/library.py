"""Read-only, bounded model discovery. No download, import or runtime startup."""
import hashlib
import json
import os
import time
from pathlib import Path


def scan(roots, *, max_files=20000, timeout=10):
    if not isinstance(roots,list) or len(roots)>16:
        raise ValueError('最多指定16个模型目录')
    result=[]; issues=[]; seen=set(); visited=0; started=time.monotonic()
    for raw in roots:
        if not isinstance(raw,str) or not Path(raw).is_absolute():
            raise ValueError('模型目录必须是绝对路径')
        root=Path(raw).resolve()
        if not root.is_dir():
            issues.append({'path':raw,'status':'missing'});continue
        def error(exc):issues.append({'path':str(exc.filename),'status':'unreadable'})
        for directory,dirs,files in os.walk(root,followlinks=False,onerror=error):
            dirs[:]=[n for n in dirs if n not in ('node_modules','.git','.locks','migration-records')
                     and not Path(directory,n).is_symlink() and not Path(directory,n).is_junction()]
            for name in files:
                visited+=1
                if visited>max_files or time.monotonic()-started>timeout:
                    return {'models':result,'issues':issues+[{'status':'scan_limit'}],'complete':False}
                p=Path(directory,name)
                if p.is_symlink():continue
                try:
                    canonical=str(p.resolve())
                    if canonical in seen:continue
                    seen.add(canonical)
                    parts=p.parts
                    if 'manifests' in parts:
                        index=parts.index('manifests');library=Path(*parts[:index])
                        if p.stat().st_size>1024*1024:continue
                        value=json.loads(p.read_text(encoding='utf8'))
                        layers=[value['config'],*value['layers']]
                        valid=True
                        for layer in layers:
                            digest=layer['digest']
                            if not isinstance(digest,str) or len(digest)!=71 or not digest.startswith('sha256:') or any(c not in '0123456789abcdef' for c in digest[7:]):
                                raise ValueError('invalid digest')
                            blob=library/'blobs'/digest.replace(':','-')
                            if not blob.is_file() or blob.stat().st_size!=layer['size']:valid=False
                        rel=p.relative_to(library/'manifests').parts
                        model='/'.join(rel[2:-1])+':'+rel[-1]
                        result.append({'id':hashlib.sha256(canonical.encode()).hexdigest()[:24],
                            'name':model,'path':canonical,'library':str(library),'format':'ollama',
                            'bytes':sum(x['size'] for x in layers),'status':'registered' if valid else 'incomplete',
                            'runtime':'Ollama','note':'已登记不代表服务已启动或该端点加载了本库'})
                    elif p.suffix.lower() in ('.gguf','.safetensors','.onnx'):
                        result.append({'id':hashlib.sha256(canonical.encode()).hexdigest()[:24],
                            'name':name,'path':canonical,'format':p.suffix[1:].lower(),
                            'bytes':p.stat().st_size,'status':'discovered','runtime':None,
                            'note':'仅发现权重文件；模型类型与运行时兼容性待核验'})
                except (OSError,ValueError,KeyError,TypeError):
                    issues.append({'path':str(p),'status':'unreadable_or_invalid'})
    return {'models':result,'issues':issues,'complete':True}
