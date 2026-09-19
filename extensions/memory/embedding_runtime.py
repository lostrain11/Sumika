"""Explicit installed offline embedding runtime; no downloader or fallback."""
import json
import math
import os
from pathlib import Path
import subprocess


def installed_runtime():
    root=Path(__file__).resolve().parents[2]
    python=root/'.sumika-next/memory-env/Scripts/python.exe'
    cache=root/'.sumika-next/embedding-models'
    if not python.is_file() or not list(cache.rglob('*.onnx')):
        raise ValueError('语义记忆依赖未就绪：需要本地 memory-env 和 embedding-models；不会自动下载或切换实现。')
    return python,cache


def embed_batch(python, cache, texts, query):
    env={k:v for k,v in os.environ.items() if not k.endswith(('_API_KEY','_API_TOKEN'))}
    env.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',HF_HUB_DISABLE_TELEMETRY='1')
    worker=Path(__file__).with_name('embedding_worker.py')
    try:
        result=subprocess.run([str(python),'-X','utf8','-B',str(worker),str(cache)],
            input=json.dumps({'texts':texts,'query':query},ensure_ascii=False),
            text=True,encoding='utf8',capture_output=True,timeout=60,env=env,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    except (OSError,subprocess.TimeoutExpired) as error:
        raise RuntimeError('本地语义记忆运行失败；未切换 provider。') from error
    if result.returncode:raise RuntimeError('本地语义记忆依赖或模型加载失败；未切换 provider。')
    try:
        value=json.loads(result.stdout)
        vectors=value['vectors'];q=value['query']
        if len(vectors)!=len(texts) or not q:raise ValueError('count')
        for vector in [q,*vectors]:
            if len(vector)!=len(q) or not all(type(x) in (int,float) and math.isfinite(x) for x in vector):raise ValueError('vector')
            if not any(vector):raise ValueError('zero vector')
        return vectors,q
    except (ValueError,TypeError,KeyError) as error:
        raise RuntimeError('本地语义记忆返回无效向量。') from error
