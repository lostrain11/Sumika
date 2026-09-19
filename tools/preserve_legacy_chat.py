"""Read known legacy room histories into personal backup storage; no restart."""
import hashlib
import json
from pathlib import Path
import sys
import urllib.parse
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from extensions.models.settings import default_path, load
from extensions.roles.roles import load_role
from extensions.roles.conversations import Conversations


def main():
    def get(route):
        with urllib.request.urlopen('http://127.0.0.1:8765' + route, timeout=10) as response:
            return json.load(response)
    settings_path = default_path()
    settings = load(settings_path)
    roles = get('/api/roles')
    sessions = ['ui-role-chat', 'room-default'] + ['room-' + r['id'] for r in roles['roles']]
    histories = {s: get('/api/role/chat/history?session=' + urllib.parse.quote(s))['messages'] for s in sessions}
    # Preserve the read-only snapshot before any journal import. It contains
    # private chat text and belongs beside personal data, never source/evidence.
    directory = settings_path.parent / 'backups' / ('legacy-chat-' + uuid.uuid4().hex)
    directory.mkdir(parents=True)
    raw = json.dumps({'histories': histories, 'coverage': 'known UI sessions only; legacy API cannot enumerate arbitrary sessions'},
                     ensure_ascii=False, indent=2).encode('utf8')
    backup = directory / 'histories.json'
    with backup.open('xb') as output:
        output.write(raw)
    digest = hashlib.sha256(raw).hexdigest()
    if hashlib.sha256(backup.read_bytes()).hexdigest() != digest:
        raise RuntimeError('backup verification failed')
    active = load_role(settings['role']['role_dir'])['id']
    if roles['active']['id'] != active:
        raise RuntimeError('active role changed; snapshot kept, import refused')
    session = 'room-' + active
    # Only import the explicitly attributable active room. Other histories stay
    # in the snapshot for deliberate mapping, not guessed role assignments.
    role = settings['role']
    scope = json.dumps([role['user_id'], str(Path(role['role_dir']).resolve()), role['project_id']], ensure_ascii=False)
    store = Conversations(settings_path.parent / 'role-conversations.sqlite3')
    inserted = store.import_legacy(scope, session, histories[session])
    print(json.dumps({'backup': str(backup), 'sha256': digest, 'messages': {s:len(m) for s,m in histories.items()},
                      'imported_turns': inserted, 'process_stopped': False, 'coverage_complete': False}))


if __name__ == '__main__':
    main()
