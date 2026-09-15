"""Ordered capability configuration; provider selection never falls back silently."""
import json
import sqlite3


class CapabilityStore:
    def __init__(self, path):
        self.db = sqlite3.connect(path)
        self.db.execute('CREATE TABLE IF NOT EXISTS capabilities (id TEXT PRIMARY KEY, position INTEGER NOT NULL, enabled INTEGER NOT NULL, provider TEXT NOT NULL, options TEXT NOT NULL)')
        self.db.commit()

    def configure(self, capability, provider, *, enabled=True, options=None):
        if not isinstance(capability, str) or not capability.strip() or not isinstance(provider,str) or not provider.strip() or type(enabled) is not bool:
            raise ValueError('invalid capability')
        encoded = json.dumps(options or {}, ensure_ascii=False)
        with self.db:
            self.db.execute('INSERT INTO capabilities VALUES (?, (SELECT COALESCE(MAX(position),-1)+1 FROM capabilities),?,?,?) ON CONFLICT(id) DO UPDATE SET enabled=excluded.enabled,provider=excluded.provider,options=excluded.options', (capability,int(enabled),provider,encoded))

    def list(self):
        return [dict(id=i,enabled=bool(e),provider=p,options=json.loads(o)) for i,e,p,o in self.db.execute('SELECT id,enabled,provider,options FROM capabilities ORDER BY position,id')]

    def resolve(self, capability):
        for item in self.list():
            if item['id'] == capability:
                if not item['enabled']: raise PermissionError('capability disabled')
                return item
        raise ValueError('capability not configured')

    def reorder(self, ids):
        current = [r['id'] for r in self.list()]
        if len(ids)!=len(set(ids)) or set(ids)!=set(current): raise ValueError('reorder must include every capability exactly once')
        with self.db:
            self.db.executemany('UPDATE capabilities SET position=? WHERE id=?',enumerate(ids))

    def remove(self, capability):
        with self.db: self.db.execute('DELETE FROM capabilities WHERE id=?',(capability,))

    def close(self): self.db.close()
