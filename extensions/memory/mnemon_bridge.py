"""Read-only bridge for a trusted settings file, never request-supplied scope."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from extensions.models.settings import validate
from extensions.roles.chat import open_session


def configuration(path):
    raw = Path(path).read_bytes()
    settings = validate(json.loads(raw))
    role_path = Path(settings['role']['role_dir']) / 'role.json'
    role = role_path.read_bytes()
    # Match Node's byte-based digest. Changes during loading fail closed.
    digest = hashlib.sha256(raw + b'\0' + role).hexdigest()
    if Path(path).read_bytes() != raw or role_path.read_bytes() != role:
        raise ValueError('memory settings changed')
    scope = dict(user_id=settings['role']['user_id'], role_id=json.loads(role)['id'],
                 project_id=settings['role']['project_id'])
    return settings, digest, scope


def read(path, request):
    if not isinstance(request, dict) or request.get('op') not in ('revision', 'search'):
        raise ValueError('unsupported memory read')
    allowed = {'op', 'configuration_revision'} | ({'query', 'limit'} if request['op'] == 'search' else set())
    if set(request) != allowed:
        raise ValueError('invalid memory read fields')
    if request['op'] == 'search' and (
            not isinstance(request['query'], str) or not request['query'].strip()
            or len(request['query']) > 200 or type(request['limit']) is not int
            or not 1 <= request['limit'] <= 5):
        raise ValueError('invalid memory query')
    settings, digest, scope = configuration(path)
    if request['configuration_revision'] != digest:
        raise ValueError('memory binding changed')
    if not settings['memory']['enabled']:
        raise ValueError('memory disabled')
    session = open_session(settings, for_chat=True)
    try:
        if not session.enabled or session.scope != scope:
            raise ValueError('memory role binding changed')
        revision = session.memory.scope_revision(**session.scope)
        if request['op'] == 'revision':
            result = revision
        else:
            result = session.retrieval.search(request['query'], limit=request['limit'], **session.scope)
        if configuration(path)[1] != digest or session.memory.scope_revision(**session.scope) != revision:
            raise ValueError('memory changed during read')
        return result
    finally:
        session.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--settings', type=Path, required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(read(args.settings, json.load(sys.stdin)), ensure_ascii=False))
    except Exception:
        # CLI boundary: do not expose paths, settings or provider diagnostics.
        parser.exit(2, 'canonical memory read unavailable\n')


if __name__ == '__main__':
    main()
