"""Replaceable ranking boundary; canonical state controls returned text/authority."""
from typing import Protocol


class RetrievalProvider(Protocol):
    def capabilities(self): ...
    def search(self, query, *, scope, source, limit): ...


class LocalRetrievalProvider:
    def __init__(self, memory):
        self.memory = memory

    def capabilities(self):
        return {'scope_filter': True, 'source_filter': True, 'revisioned_hits': True}

    def search(self, query, *, scope, source=None, limit=8):
        hits = self.memory.search(query, source=source, limit=limit, **scope)
        return [{**hit, 'engine_id': type(self.memory).__name__} for hit in hits]


class MemoryRetrieval:
    def __init__(self, repository, provider):
        self.repository, self.provider = repository, provider

    def search(self, query, *, user_id, role_id, project_id='default', source=None, limit=8):
        if not self.repository.enabled:
            return []
        if not isinstance(query, str) or type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError('invalid search')
        if not query.strip():
            return []
        capabilities = self.provider.capabilities()
        if not all(capabilities.get(k) is True for k in ('scope_filter', 'source_filter', 'revisioned_hits')):
            raise ValueError('retrieval provider lacks required isolation/version capabilities')
        scope = dict(user_id=user_id, role_id=role_id, project_id=project_id)
        revision = self.repository.scope_revision(**scope)
        hits = self.provider.search(query, scope=dict(scope), source=source, limit=limit)
        if not isinstance(hits, list) or len(hits) > 100:
            raise ValueError('invalid retrieval result')
        records, seen = [], set()
        for hit in hits:
            if not isinstance(hit, dict) or not isinstance(hit.get('record_id'), str) or type(hit.get('revision')) is not int:
                continue
            record = self.repository.get_record(hit['record_id'], **scope)
            if (not record or not record['active'] or record['revision'] != hit['revision']
                    or record['record_id'] in seen or (source is not None and record['source'] != source)):
                continue
            seen.add(record['record_id'])
            # Never trust provider-supplied text, provenance or confirmation.
            value = {k: record[k] for k in ('id', 'record_id', 'revision', 'text', 'source')}
            for key in ('score', 'retrieval', 'engine_id'):
                if key in hit:
                    value[key] = hit[key]
            records.append(value)
        # A deletion may commit on another connection after an early hit was
        # hydrated. Discard this whole in-flight result rather than returning a
        # mixed snapshot or retrying an external provider without authorization.
        if not self.repository.enabled or self.repository.scope_revision(**scope) != revision:
            return []
        return records[:limit]
