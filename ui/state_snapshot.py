"""UI-safe backend state projection; no secrets, prompts or raw page content."""
from datetime import datetime, timezone

ALLOWED=('unknown','pending','running','completed','failed','cancelled')

def snapshot(*,session=None,role=None,memory=None,modules=(),approvals=()):
    def text(value,default='unknown'):
        return value if isinstance(value,str) and value else default
    return {
        'schema_version':1,
        'generated_at':datetime.now(timezone.utc).isoformat(),
        'session':dict(session or {}),
        'role':dict(role or {}),
        'memory':dict(memory or {}),
        'modules':[dict(id=m.get('id'),enabled=bool(m.get('enabled')),provider=text(m.get('provider')),health=text(m.get('health'))) for m in modules if isinstance(m,dict) and isinstance(m.get('id'),str)],
        'approvals':[dict(id=a.get('id'),status=text(a.get('status'))) for a in approvals if isinstance(a,dict) and isinstance(a.get('id'),str)],
    }

def validate_state(state):
    if not isinstance(state,dict) or state.get('schema_version')!=1:raise ValueError('invalid UI state schema')
    session=state.get('session',{})
    if not isinstance(session,dict):raise ValueError('invalid session projection')
    status=session.get('status')
    if status is not None and status not in ALLOWED:raise ValueError('invalid session status')
    forbidden=('api_key','token','password','cookie','prompt','page_content')
    encoded=str(state).casefold()
    if any(key in encoded for key in forbidden):raise ValueError('secret or raw content in UI state')
    return state
