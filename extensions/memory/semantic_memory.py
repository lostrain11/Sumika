"""Offline FastEmbed semantic retrieval over scoped EmbeddedMemory records.

Embedding weights are explicitly installed beforehand. Runtime never downloads
models, calls a server or silently substitutes a different provider.
"""
import hashlib
import json
import math
from pathlib import Path
from extensions.memory.embedded_memory import EmbeddedMemory


class SemanticMemory(EmbeddedMemory):
    def __init__(self,path,*,cache_dir,enabled=True,threshold=0.45,embedding_python=None):
        self.threshold=threshold
        self.embedding_python=embedding_python
        self.cache_dir=cache_dir
        if enabled:
            cache=Path(cache_dir)
            weights=list(cache.rglob('*.onnx'))
            if not weights:raise ValueError('install local embedding model first')
            if embedding_python is None:
                from fastembed import TextEmbedding
                self.embedder=TextEmbedding('BAAI/bge-small-zh-v1.5',cache_dir=str(cache),local_files_only=True)
            digest=hashlib.sha256()
            for p in sorted(weights):
                with p.open('rb') as f:
                    while block:=f.read(1024*1024):digest.update(block)
            self.model_id='BAAI/bge-small-zh-v1.5:'+digest.hexdigest()
        super().__init__(path,enabled)
        if enabled:
            self.db.execute('CREATE TABLE IF NOT EXISTS embeddings (memory_id INTEGER, model TEXT, vector TEXT, PRIMARY KEY(memory_id,model))')
            self.db.commit()

    def search(self,query,*,user_id,role_id,project_id='default',limit=8,source=None):
        if not self.enabled:return []
        if not isinstance(query,str) or type(limit) is not int or not 1<=limit<=100:raise ValueError('invalid search')
        if not query.strip():return []
        scope=self._scope(user_id,role_id,project_id)
        rows=self.db.execute('SELECT id,text,source FROM memories WHERE scope=? AND active=1'+(' AND source=?' if source is not None else ''),[scope]+([source] if source is not None else [])).fetchall()
        if not rows:return []
        vectors={i:json.loads(v) for i,v in self.db.execute('SELECT e.memory_id,e.vector FROM embeddings e JOIN memories m ON m.id=e.memory_id WHERE e.model=? AND m.scope=? AND m.active=1',(self.model_id,scope))}
        missing=[r for r in rows if r[0] not in vectors]
        if self.embedding_python is not None:
            from extensions.memory.embedding_runtime import embed_batch
            added,q=embed_batch(self.embedding_python,self.cache_dir,[r[1] for r in missing],query)
        else:
            added=self.embedder.embed([r[1] for r in missing]) if missing else []
            q=[float(x) for x in next(self.embedder.query_embed(query))]
        with self.db:
            for row,vec in zip(missing,added):
                vectors[row[0]]=[float(x) for x in vec]
                self.db.execute('INSERT OR REPLACE INTO embeddings VALUES (?,?,?)',(row[0],self.model_id,json.dumps(vectors[row[0]])))
        def score(v):
            return sum(a*b for a,b in zip(q,v))/(math.sqrt(sum(a*a for a in q))*math.sqrt(sum(a*a for a in v)))
        # Preserve exact identifiers (paths, model names, acronyms) that embeddings
        # can otherwise drop below threshold. This is a declared hybrid policy.
        ranked=sorted([(max(score(vectors[i]),1.0 if query.strip().casefold() in t.casefold() else -1),i,t,s) for i,t,s in rows],reverse=True)
        return [dict(id=i,text=t,source=s,score=round(n,6),retrieval='hybrid') for n,i,t,s in ranked if n>=self.threshold][:limit]

    def restore_json(self,src,*,user_id,role_id,project_id='default'):
        """Restore facts and invalidate vectors whose text may have changed."""
        scope=self._scope(user_id,role_id,project_id)
        result=super().restore_json(src,user_id=user_id,role_id=role_id,project_id=project_id)
        if self.enabled:
            with self.db:
                self.db.execute('DELETE FROM embeddings WHERE memory_id IN (SELECT id FROM memories WHERE scope=?)',(scope,))
        return result

    def reset_scope(self,*,user_id,role_id,project_id='default'):
        result=super().reset_scope(user_id=user_id,role_id=role_id,project_id=project_id)
        if self.enabled:
            scope=self._scope(user_id,role_id,project_id)
            with self.db:
                self.db.execute('DELETE FROM embeddings WHERE memory_id IN (SELECT id FROM memories WHERE scope=?)',(scope,))
        return result
