"""Verify the relocated library and runtime model discovery without generation."""
import json
import os
from pathlib import Path
import socket
import subprocess
import time
import urllib.request

root=Path('E:/Models')
reports=[]
opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
exe=Path(os.environ['LOCALAPPDATA'])/'Programs/Ollama/ollama.exe'
for library in ('main','neon','legacy-minicpm'):
    folder=root/'Ollama'/library
    manifests=list((folder/'manifests').rglob('*'))
    manifests=[p for p in manifests if p.is_file()]
    expected=[]
    for path in manifests:
        data=json.loads(path.read_text())
        for descriptor in [data['config'],*data['layers']]:
            blob=folder/'blobs'/descriptor['digest'].replace(':','-')
            assert blob.is_file() and blob.stat().st_size==descriptor['size'],str(blob)
        parts=path.relative_to(folder/'manifests').parts
        expected.append('/'.join(parts[2:-1])+':'+parts[-1])
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    env=dict(os.environ,OLLAMA_HOST=f'127.0.0.1:{port}',OLLAMA_MODELS=str(folder),OLLAMA_NO_CLOUD='1')
    process=subprocess.Popen([str(exe),'serve'],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW)
    try:
        for _ in range(40):
            assert process.poll() is None,'owned runtime exited'
            try:
                with opener.open(f'http://127.0.0.1:{port}/api/tags',timeout=1) as r:rows=json.load(r)['models']
                break
            except OSError:time.sleep(.25)
        else:raise RuntimeError('runtime did not start')
        actual=sorted(m['name'] for m in rows)
        assert actual==sorted(expected),(actual,expected)
        reports.append({'library':str(folder),'models':actual,'runtime_discovery':'passed'})
    finally:
        if process.poll() is None:
            subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW)
        process.wait(timeout=20)
report={'status':'passed','generation_requests':0,'libraries':reports}
(root/'migration-records'/'runtime-verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
print(json.dumps(report,ensure_ascii=False))
