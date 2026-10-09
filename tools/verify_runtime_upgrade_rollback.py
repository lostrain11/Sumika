"""Verify isolated old/new DSH runtime and profile pairs without daily migration."""
import json
import hashlib
import sys
import uuid
import argparse
import os
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sumika_next.dsh import Dsh


def profile_hashes(profile):
    return {str(path.relative_to(profile)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in profile.rglob('*') if path.is_file()}


def comparable_records(records):
    # DSH 0.2 projects these two legacy built-in source labels into explicit
    # kinds. Preserve every other field, including content, seq and time.
    records = json.loads(json.dumps(records))
    for record in records:
        event = record.get('event', {})
        data = event.get('data', {})
        owner = data.get('message', {}) if event.get('type') == 'system/message' else data
        source = owner.get('source')
        if (isinstance(source, dict) and source.get('kind') == 'plugin'
                and source.get('plugin') == '@deepseek-ai/dsh-system-prompt'):
            source_kind = ('system-prompt' if event.get('type') == 'system/message'
                           else 'runtime-context' if event.get('type') == 'user/message' else None)
            if source_kind:
                owner['source'] = {key:value for key,value in source.items() if key != 'plugin'}
                owner['source']['kind'] = source_kind
    return records


def migrate_fixture(base, old, new):
    """Migrate stopped synthetic state; never let old runtime open new state."""
    from tests_next.p2_fixture import ModelFixture
    from tools.verify_dsh_recovery import snapshot, prompt, finish
    old_profile, new_profile = base/'old-home', base/'new-home'
    old_profile.mkdir(); work = base/'work'; work.mkdir()
    session = 'upgrade-history-fixture'
    report = {'passed':False, 'daily_profile_changed':False, 'paid_model_calls':0,
              'scope':'Populated isolated old profile copy -> new runtime -> retained old profile rollback'}
    adapter = None
    try:
        with ModelFixture() as model:
            sentinel = [{'id':'session-title-llm','disabled':True},
                        {'id':'llm-deepseek','config':{'baseURL':model.url}},
                        {'id':'session-telemetry-otel','disabled':True}]
            patch = old_profile/'cordis.patch.yml'
            patch.write_text(json.dumps(sentinel),encoding='utf8')
            (old_profile/'.env').write_text('DEEPSEEK_API_KEY=p2-local-fixture-not-a-secret\n',encoding='utf8')
            adapter = Dsh(ROOT,old_profile,runtime=old)
            adapter.start()
            adapter._rpc('session/create',{'sessionId':session,'cwd':str(work)})
            follow = adapter.stream('session/follow',{'address':{'kind':'session','sessionId':session}},timeout=30)
            next(follow)
            prompt(adapter,session,'MIGRATION_HISTORY_MARKER')
            finish(follow)
            before = snapshot(adapter,session)
            cursor = before['cursor']
            page = adapter._rpc('session/page',{'address':{'kind':'session','sessionId':session},'throughSeq':cursor})
            assert 'MIGRATION_HISTORY_MARKER' in json.dumps(page), 'old history marker missing'
            assert 'P2_FIXTURE_DONE' in json.dumps(page), 'old model reply missing'
            adapter.close(); adapter = None
            old_files = profile_hashes(old_profile)
            # Generated dependency trees are rebuildable and may contain links.
            # All saved state must be physical files; no links followed.
            for directory, dirs, files in os.walk(old_profile,followlinks=False):
                dirs[:] = [name for name in dirs if name != 'node_modules']
                for name in dirs + files:
                    path = Path(directory)/name
                    if path.is_symlink() or path.is_junction():
                        raise ValueError('linked migration fixture state')
            shutil.copytree(old_profile,new_profile,ignore=shutil.ignore_patterns('node_modules'))
            request_count = len(model.requests)
            adapter = Dsh(ROOT,new_profile,runtime=new)
            adapter.start()
            recovered = snapshot(adapter,session)
            migrated_page = adapter._rpc('session/page',{'address':{'kind':'session','sessionId':session},'throughSeq':cursor})
            (base/'old-page.json').write_text(json.dumps(page,indent=2),encoding='utf8')
            (base/'new-page.json').write_text(json.dumps(migrated_page,indent=2),encoding='utf8')
            assert comparable_records(migrated_page['records']) == comparable_records(page['records']), 'migrated history differs'
            assert recovered['cursor'] == cursor, 'migration replayed session work'
            assert len(model.requests) == request_count, 'migration dispatched model'
            import yaml
            assert yaml.safe_load((new_profile/'cordis.patch.yml').read_text(encoding='utf8')) == sentinel
            adapter.close(); adapter = None
            assert profile_hashes(old_profile) == old_files, 'new runtime modified rollback source'
            adapter = Dsh(ROOT,old_profile,runtime=old)
            adapter.start()
            restored = snapshot(adapter,session)
            rollback_page = adapter._rpc('session/page',{'address':{'kind':'session','sessionId':session},'throughSeq':cursor})
            assert rollback_page['records'] == page['records'], 'old rollback history differs'
            assert restored['cursor'] == cursor and len(model.requests) == request_count
            report.update(passed=True, migrated_history_content_preserved=True,
                source_label_migration='legacy built-in plugin -> system-prompt/runtime-context', rollback_history_identical=True,
                no_model_replay=True, unrelated_config_preserved=True, old_profile_bytes_preserved=True,
                history_records=len(page['records']), old_version=json.loads((old/'release.json').read_text())['version'],
                new_version=json.loads((new/'release.json').read_text())['version'])
    except Exception as error:
        report['failure'] = {'type':type(error).__name__, 'reason':str(error)[:200]}
        raise
    finally:
        if adapter is not None:
            adapter.close()
        (base/'report.json').write_text(json.dumps(report,indent=2),encoding='utf8')
        print(json.dumps(report),flush=True)


def migration_failure_fixture(base, old, new):
    """An interrupted profile migration must fail closed; recovery uses the
    verified old pair and the old runtime never opens the migrated profile."""
    from tests_next.p2_fixture import ModelFixture
    from tools.verify_dsh_recovery import snapshot, prompt, finish
    old_profile, new_profile = base/'old-home', base/'new-home'
    old_profile.mkdir(); work = base/'work'; work.mkdir()
    session = 'upgrade-failure-fixture'
    report = {'passed':False, 'daily_profile_changed':False, 'paid_model_calls':0,
              'scope':'Populated old profile -> interrupted copy -> fail-closed new runtime -> verified old-pair recovery'}
    adapter = None
    try:
        with ModelFixture() as model:
            (old_profile/'.env').write_text('DEEPSEEK_API_KEY=p2-local-fixture-not-a-secret\n',encoding='utf8')
            adapter = Dsh(ROOT,old_profile,runtime=old)
            adapter.start()
            adapter._rpc('session/create',{'sessionId':session,'cwd':str(work)})
            follow = adapter.stream('session/follow',{'address':{'kind':'session','sessionId':session}},timeout=30)
            next(follow)
            prompt(adapter,session,'MIGRATION_FAILURE_MARKER')
            finish(follow)
            page = adapter._rpc('session/page',{'address':{'kind':'session','sessionId':session},'throughSeq':snapshot(adapter,session)['cursor']})
            assert 'MIGRATION_FAILURE_MARKER' in json.dumps(page), 'old history marker missing'
            adapter.close(); adapter = None
            old_files = profile_hashes(old_profile)
            shutil.copytree(old_profile,new_profile,ignore=shutil.ignore_patterns('node_modules'))
            store = next(new_profile.glob('sessions/**/'+session+'/session.v3.jsonl.zstd'))
            raw = store.read_bytes()
            store.write_bytes(raw[:len(raw)//2])
            adapter = Dsh(ROOT,new_profile,runtime=new)
            adapter.start()
            try:
                broken = adapter._rpc('session/page',{'address':{'kind':'session','sessionId':session},'throughSeq':10**9})
                assert 'MIGRATION_FAILURE_MARKER' not in json.dumps(broken), 'corrupt migration served old history'
            except Exception as error:
                report['migration_failure_detected'] = {'type':type(error).__name__,'reason':str(error)[:120]}
            finally:
                adapter.close(); adapter = None
            assert profile_hashes(old_profile) == old_files, 'failed migration touched the rollback source'
            adapter = Dsh(ROOT,old_profile,runtime=old)
            adapter.start()
            restored = adapter._rpc('session/page',{'address':{'kind':'session','sessionId':session},'throughSeq':snapshot(adapter,session)['cursor']})
            assert restored['records'] == page['records'], 'old-pair recovery history differs'
            adapter.close(); adapter = None
            report.update(passed=True, fail_closed=True, old_pair_history_identical=True,
                old_runtime_never_opened_new_profile=True, old_profile_bytes_preserved=True,
                history_records=len(page['records']),
                old_version=json.loads((old/'release.json').read_text())['version'],
                new_version=json.loads((new/'release.json').read_text())['version'])
    except Exception as error:
        report['failure'] = {'type':type(error).__name__, 'reason':str(error)[:200]}
        raise
    finally:
        if adapter is not None:
            adapter.close()
        (base/'report.json').write_text(json.dumps(report,indent=2),encoding='utf8')
        print(json.dumps(report),flush=True)


def run_pair(label, runtime, profile, work):
    adapter = Dsh(ROOT, profile, runtime=runtime)
    adapter.start(port=0)
    try:
        session = f'{label}-{uuid.uuid4().hex[:10]}'
        adapter._rpc('session/create', {'sessionId': session, 'cwd': str(work)})
        value = adapter._rpc('session/list', {'_request': {}})
        assert isinstance(value, (list, dict)), value
        return {'version': json.loads((runtime / 'release.json').read_text())['version'],
                'profile': str(profile), 'session': session, 'started': True}
    finally:
        adapter.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path)
    parser.add_argument('--new-runtime',type=Path)
    parser.add_argument('--migrate-fixture',action='store_true')
    parser.add_argument('--migration-failure-fixture',action='store_true')
    args = parser.parse_args()
    base = args.output or ROOT / '.sumika-next' / ('runtime-upgrade-' + uuid.uuid4().hex)
    base = base.resolve()
    base.mkdir()
    old = ROOT / 'runtime/dsh'
    new = args.new_runtime or next(iter(sorted((ROOT / '.sumika-next/package').glob('dsh-runtime-hoisted-*'))))
    if args.migrate_fixture:
        return migrate_fixture(base,old,new)
    if args.migration_failure_fixture:
        return migration_failure_fixture(base,old,new)
    work = base / 'work'; work.mkdir()
    old_profile = base / 'profiles' / '0.1.5-rc.2'
    new_profile = base / 'profiles' / '0.2.0-rc.2'
    old_profile.mkdir(parents=True); new_profile.mkdir(parents=True)
    old_result = run_pair('old', old, old_profile, work)
    old_files = {str(p.relative_to(old_profile)): hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in old_profile.rglob('*') if p.is_file()}
    new_result = run_pair('new', new, new_profile, work)
    assert old_files == {str(p.relative_to(old_profile)): hashlib.sha256(p.read_bytes()).hexdigest()
                         for p in old_profile.rglob('*') if p.is_file()}, 'new runtime changed old profile'
    rollback_result = run_pair('rollback', old, old_profile, work)
    assert old_result['profile'] != new_result['profile']
    assert old_result['version'] != new_result['version']
    report = {'passed': True, 'old': old_result, 'new': new_result, 'rollback': rollback_result,
              'new_runtime_preserved_old_profile_bytes': True,
              'upgrade_pair_isolated': True, 'rollback_pair_isolated': True,
              'daily_runtime_changed': False, 'daily_profile_changed': False,
              'migration_performed': False,
              'boundary': 'Runtime/profile switch was simulated only in isolated directories; no in-place downgrade or data migration.'}
    (base / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf8')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
