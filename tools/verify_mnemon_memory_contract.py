"""Isolated Mnemon public-SDK contract probe; synthetic data, no provider/model.

Reuses the reviewed published artifact and real candidate Cordis dependency.
Nothing is installed into or edited inside node_modules or a daily profile.
"""
import argparse
import json
import subprocess
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from extensions.memory.embedded_memory import EmbeddedMemory
from extensions.memory.repository import message_evidence

SCOPE = dict(user_id='fixture-user', role_id='fixture-role', project_id='fixture-project')


def bridge(base, request):
    # The fixture host owns scope mapping; request/model scope cannot override it.
    with_memory = EmbeddedMemory(base / 'canonical.sqlite3')
    try:
        op = request['op']
        if op == 'seed':
            own = with_memory.add('用户喜欢茉莉花茶', evidence=message_evidence('fixture-message'), **SCOPE)
            for foreign in ({**SCOPE, 'role_id': 'other-role'},
                            {**SCOPE, 'user_id': 'other-user'},
                            {**SCOPE, 'project_id': 'other-project'}):
                with_memory.add('用户喜欢茉莉花茶：其他范围秘密', **foreign)
            with_memory.put_proposal(event_id='unconfirmed', text='用户喜欢红茶',
                                    quote='红茶', message_id='proposal-message', **SCOPE)
            return own
        if op == 'search':
            return with_memory.search(request['query'], limit=5, **SCOPE)
        if op == 'revision':
            return with_memory.scope_revision(**SCOPE)
        if op == 'correct':
            return with_memory.correct_record(request['record_id'], '用户喜欢黑咖啡',
                expected_revision=1, event_id='fixture-correction', **SCOPE)
        if op == 'forget':
            return with_memory.forget_record(request['record_id'], **SCOPE)
        if op == 'rebuild':
            return with_memory.rebuild_indexes(**SCOPE)
        raise ValueError('unsupported fixture operation')
    finally:
        with_memory.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifact', type=Path, default=ROOT / '.sumika-next/dsh-market-20261017/packages/dsh-mnemon/source/package')
    parser.add_argument('--runtime', type=Path, default=ROOT / '.sumika-next/dsh-upgrade/0.2.0-rc.2')
    parser.add_argument('--bridge', type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.bridge:
        print(json.dumps(bridge(args.bridge, json.load(sys.stdin)), ensure_ascii=False))
        return
    package = json.loads((args.artifact / 'package.json').read_text(encoding='utf8'))
    assert package['name'] == 'dsh-mnemon' and package['version'] == '0.5.29'
    cordis = list((args.runtime / 'node_modules/.pnpm').glob('@deepseek-ai+cordis@4.0.4*/node_modules/@deepseek-ai/cordis/lib/index.js'))
    assert len(cordis) == 1, 'expected reviewed real Cordis 4.0.4 dependency'
    base = ROOT / '.sumika-next' / ('mnemon-contract-' + uuid.uuid4().hex)
    base.mkdir()
    # Resolve public export paths from the published manifest; no private exports.
    entries = {name: (args.artifact / package['exports'][name]['default']).resolve().as_uri()
               for name in ('./testing', './extension-sdk')}
    config = dict(entries=entries, cordis=cordis[0].resolve().as_uri(),
                  python=sys.executable, bridge=str(Path(__file__).resolve()), base=str(base))
    (base / 'config.json').write_text(json.dumps(config), encoding='utf8')
    result = subprocess.run(['node', str(ROOT / 'tools/verify_mnemon_memory_contract.mjs'),
                             str(base / 'config.json')], cwd=ROOT, capture_output=True,
                            text=True, encoding='utf8', timeout=90)
    (base / 'stdout.log').write_text(result.stdout, encoding='utf8')
    (base / 'stderr.log').write_text(result.stderr, encoding='utf8')
    print(result.stdout)
    if result.returncode:
        print(result.stderr, file=sys.stderr)
        raise SystemExit(result.returncode)
    print(f'Evidence: {base}')


if __name__ == '__main__':
    main()
