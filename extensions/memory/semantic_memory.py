"""Offline FastEmbed semantic retrieval over scoped EmbeddedMemory records.

Embedding weights are explicitly installed beforehand. Runtime never downloads
models, calls a server or silently substitutes a different provider.
"""
import hashlib
import json
import math
from pathlib import Path
from extensions.memory.embedded_memory import EmbeddedMemory
from extensions.memory.embedding_runtime import validate_embeddings


class SemanticMemory(EmbeddedMemory):
    def __init__(self,path,*,cache_dir,enabled=True,threshold=0.45,embedding_python=None):
        self.threshold=threshold
        self.embedding_python=embedding_python
        self.cache_dir=cache_dir
        if enabled:
            cache=Path(cache_dir)
            # Only the pinned BGE model belongs in the cache identity. Another
            # .onnx file in the same cache directory must not invalidate every
            # stored vector and force a full re-embed.
            weights=[p for p in cache.rglob('*.onnx')
                     if 'bge-small-zh-v1.5' in str(p).casefold()]
            if not weights:
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
        scope_fields=dict(user_id=user_id,role_id=role_id,project_id=project_id)
        revision=self.scope_revision(**scope_fields)
        rows=self.db.execute('SELECT id,text,source,record_id,revision FROM memories WHERE scope=? AND active=1'+(' AND source=?' if source is not None else ''),[scope]+([source] if source is not None else [])).fetchall()
        if not rows:return []
        try:
            vectors={i:json.loads(v) for i,v in self.db.execute('SELECT e.memory_id,e.vector FROM embeddings e JOIN memories m ON m.id=e.memory_id WHERE e.model=? AND m.scope=? AND m.active=1',(self.model_id,scope))}
        except (ValueError, TypeError) as error:
            raise RuntimeError('语义记忆缓存损坏，请重建记忆索引。') from error
        missing=[r for r in rows if r[0] not in vectors]
        if self.embedding_python is not None:
            from extensions.memory.embedding_runtime import embed_batch
            added,q=embed_batch(self.embedding_python,self.cache_dir,[r[1] for r in missing],query)
        else:
            try:
                added=[[float(x) for x in v] for v in self.embedder.embed([r[1] for r in missing])] if missing else []
                q=[float(x) for x in next(iter(self.embedder.query_embed(query)))]
            except (ValueError, TypeError, StopIteration, OverflowError) as error:
                raise RuntimeError('本地语义记忆返回无效向量。') from error
        # Validate the entire batch before any cache commit: zip must never
        # silently truncate missing embeddings or mismatched vector dimensions.
        validate_embeddings(added, q, count=len(missing))
        vectors.update({row[0]: vector for row, vector in zip(missing, added)})
        validate_embeddings([vectors[row[0]] for row in rows], q, count=len(rows))
        with self.db:
            # Embedding can take seconds in another process. Fence its cache
            # commit against concurrent canonical changes before writing rows.
            self.db.execute('BEGIN IMMEDIATE')
            if not self.enabled or self.scope_revision(**scope_fields)!=revision:return []
            for row,vec in zip(missing,added):
                self.db.execute('INSERT OR REPLACE INTO embeddings VALUES (?,?,?)',(row[0],self.model_id,json.dumps(vectors[row[0]])))
        def score(v):
            # Normalize before multiplying to avoid overflow/underflow for
            # finite nonzero vectors returned by interchangeable embedders.
            qnorm, vnorm = math.hypot(*q), math.hypot(*v)
            return sum((a/qnorm)*(b/vnorm) for a,b in zip(q,v))
        # Preserve exact identifiers (paths, model names, acronyms) that embeddings
        # can otherwise drop below threshold. This is a declared hybrid policy.
        # A single-character query is too weak to count as an exact identifier
        # hit; the boost is capped below saturation so cosine still orders the
        # remaining results.
        needle=query.strip().casefold()
        exact_boost=len(needle)>=2
        ranked=sorted([(max(score(vectors[i]),0.85 if exact_boost and needle in t.casefold() else -1),i,t,s,record_id,revision) for i,t,s,record_id,revision in rows],reverse=True)
        results=[dict(id=i,record_id=record_id,revision=record_revision,text=t,source=s,score=round(n,6),retrieval='hybrid') for n,i,t,s,record_id,record_revision in ranked if n>=self.threshold][:limit]
        return results if self.enabled and self.scope_revision(**scope_fields)==revision else []

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
