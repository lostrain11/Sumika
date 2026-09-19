"""Explicitly paired remote local-model nodes; no implicit fallback."""
import json, secrets, urllib.request, ipaddress
from urllib.parse import urlparse

class DeviceRegistry:
    def __init__(self, database):
        self.db=database; self.db.execute('CREATE TABLE IF NOT EXISTS devices (id TEXT PRIMARY KEY, endpoint TEXT NOT NULL, provider TEXT NOT NULL, capabilities TEXT NOT NULL, token_hash TEXT NOT NULL, enabled INTEGER NOT NULL)'); self.db.commit()
    def register(self, device_id, endpoint, provider, capabilities, token=None, *, enabled=True):
        if not all(isinstance(x,str) and x.strip() for x in (device_id,endpoint,provider)): raise ValueError('device identity required')
        parsed=urlparse(endpoint)
        if parsed.scheme not in ('http','https') or not parsed.hostname: raise ValueError('invalid device endpoint')
        if parsed.scheme=='http':
            host=parsed.hostname.casefold()
            local=host in ('localhost','127.0.0.1','::1') or host.endswith('.local') or '.' not in host
            try: local=local or ipaddress.ip_address(host).is_private
            except ValueError: pass
            if not local: raise ValueError('http device endpoint must be private')
        if not isinstance(capabilities,list) or any(not isinstance(x,str) or not x.strip() for x in capabilities): raise ValueError('invalid capabilities')
        if token is None: token=secrets.token_urlsafe(24)
        if not isinstance(token,str) or not token: raise ValueError('token required')
        import hashlib
        self.db.execute('INSERT OR REPLACE INTO devices VALUES (?,?,?,?,?,?)',(device_id,endpoint.rstrip('/'),provider,json.dumps(sorted(set(capabilities))),hashlib.sha256(token.encode()).hexdigest(),int(enabled))); self.db.commit()
        return {'id':device_id,'endpoint':endpoint.rstrip('/'),'provider':provider,'capabilities':sorted(set(capabilities)),'token':token,'enabled':enabled}
    def list(self):
        return [dict(id=i,endpoint=e,provider=p,capabilities=json.loads(c),enabled=bool(en)) for i,e,p,c,_,en in self.db.execute('SELECT id,endpoint,provider,capabilities,token_hash,enabled FROM devices ORDER BY id')]
    def revoke(self, device_id): self.db.execute('DELETE FROM devices WHERE id=?',(device_id,)); self.db.commit(); return {'revoked':self.db.total_changes>0}
    def health(self, device_id):
        row=self.db.execute('SELECT endpoint FROM devices WHERE id=? AND enabled=1',(device_id,)).fetchone()
        if not row: return {'status':'unknown','reason':'device not registered or disabled'}
        try:
            req=urllib.request.Request(row[0]+'/v1/models')
            with urllib.request.urlopen(req,timeout=3) as r: json.loads(r.read().decode())
            return {'status':'ready'}
        except OSError: return {'status':'unknown','reason':'device unreachable'}
