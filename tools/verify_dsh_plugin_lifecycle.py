"""Exercise native plugin management in a fresh candidate profile only."""
import argparse
import json
import sys
import urllib.request
import uuid
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sumika_next.dsh import Dsh


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--runtime', type=Path, default=ROOT / '.sumika-next/dsh-upgrade/0.2.0-rc.2')
    args = parser.parse_args()
    base = ROOT / '.sumika-next' / ('plugin-lifecycle-' + uuid.uuid4().hex)
    home = base / 'home'
    home.mkdir(parents=True)
    sentinel = [{'id': 'session-title-llm', 'disabled': True},
                {'id': 'session-telemetry-otel', 'disabled': True}]
    patch = home / 'profiles' / 'web' / 'cordis.patch.yml'
    patch.parent.mkdir(parents=True)
    patch.write_text(json.dumps(sentinel), encoding='utf8')
    adapter = Dsh(ROOT, home, runtime=args.runtime)
    results = {}

    def rpc(method, **arguments):
        rpc_id = uuid.uuid4().hex
        payload = dict(type='client-request', rpcId=rpc_id,
                       method='pluginManager/' + method, payload={'args': arguments})
        request = urllib.request.Request(adapter.url + '/api/pluginManager/' + method,
            data=json.dumps(payload).encode(),
            headers={'Content-Type': 'application/json', 'Origin': adapter.url})
        with adapter._opener.open(request, timeout=120) as response:
            data = json.load(response)
        assert data['rpcId'] == rpc_id and data['result']['ok'], data
        value = data['result'].get('value')
        results.setdefault(method, []).append(value)
        (base / 'operations.json').write_text(json.dumps(results, indent=2), encoding='utf8')
        return value

    def fixture(name, peer):
        directory = base / name
        directory.mkdir()
        manifest = dict(name=name, version='1.0.0', type='module', main='./index.mjs',
                        peerDependencies={'@deepseek-ai/dsh': peer},
                        peerDependenciesMeta={'@deepseek-ai/dsh': {'optional': True}},
                        dsh={'bundle': {'patch': './cordis.patch.yml'}})
        (directory / 'package.json').write_text(json.dumps(manifest), encoding='utf8')
        (directory / 'index.mjs').write_text('export default function apply(ctx) {}\n', encoding='utf8')
        (directory / 'cordis.patch.yml').write_text(json.dumps([
            {'insert': [{'id': name, 'name': name, 'config': {'token': 'retained-fixture'}}]}
        ]), encoding='utf8')
        return directory

    good = fixture('sumika-fixture-compatible', '>=0.2.0-rc.2 <0.3.0')
    bad = fixture('sumika-fixture-incompatible', '>=99.0.0')
    try:
        adapter.start()
        assert rpc('inspect', spec=str(good))['status'] == 'accepted'
        installed = rpc('installBundle', spec=str(good))
        assert installed['application'] in ('applied', 'restart-required'), installed
        assert not installed.get('error'), installed
        if installed['application'] == 'restart-required':
            adapter.close()
            adapter.start()
        bundles = rpc('listBundles')
        bundle = next(b for b in bundles if b['name'] == good.name)
        assert bundle['installed'] and bundle['enabled'], bundle
        row = next(p for p in rpc('listPlugins') if p.get('patchId') == good.name)
        entry_id = row['entryId']
        for enabled in (False, True):
            change = rpc('setPluginEnabled', id=entry_id, enabled=enabled)
            assert change['application'] in ('applied', 'restart-required'), change
            adapter.close()
            adapter.start()
            rows = rpc('listPlugins')
            row = next(p for p in rows if p.get('patchId') == good.name)
            assert row['enabled'] is enabled, row
            entry_id = row['entryId']
        profile = patch.parent / 'package.json'
        before = {p: p.read_bytes() if p.exists() else None
                  for p in (profile, patch.parent / 'pnpm-lock.yaml', patch)}
        rejected = rpc('installBundle', spec=str(bad))
        assert rejected['application'] == 'failed', rejected
        assert rejected.get('error', {}).get('code') == 'incompatible-version', rejected
        assert all((p.read_bytes() if p.exists() else None) == value for p, value in before.items())
        assert not rpc('listVersionExemptions')['exemptions']
        removed = rpc('removeBundle', name=good.name)
        assert removed['application'] in ('applied', 'restart-required'), removed
        adapter.close()
        adapter.start()
        assert not any(b['name'] == good.name and b['installed'] for b in rpc('listBundles'))
        persisted = yaml.safe_load(patch.read_text(encoding='utf8'))
        for item in sentinel:
            assert item in persisted, persisted
        report = dict(passed=True, runtime=str(args.runtime.resolve()), artifact=str(base),
                      installed=True, toggled=True, removed=True, incompatible_rejected=True,
                      failed_install_restored=True, unrelated_config_preserved=True,
                      external_model_calls=0, daily_profile_changed=False)
        (base / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf8')
        print(json.dumps(report))
    finally:
        adapter.close()


if __name__ == '__main__':
    main()
