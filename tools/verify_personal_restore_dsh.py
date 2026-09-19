"""Offline snapshot/restore of a real isolated DSH profile, without task replay."""
import argparse
import json
import os
from pathlib import Path
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'tests_next'), str(ROOT/'tools')]
from p2_fixture import ModelFixture
from verify_dsh_recovery import prompt, finish, snapshot
from backup_personal_data import backup, restore, rebind_role_paths, inventory
from extensions.models.settings import example, save
from sumika_next.daily import default_home
from ui.workbench import WorkbenchController


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--restored-product', type=Path, help='Use a separate existing product installation after data restore')
    parser.add_argument('--rollback-product', type=Path, help='Also restore the pre-change snapshot into new data and start a retained prior product')
    args = parser.parse_args()
    restored_product = args.restored_product.resolve(strict=True) if args.restored_product else ROOT
    rollback_product = args.rollback_product.resolve(strict=True) if args.rollback_product else None
    base = ROOT/'.sumika-next/package'/('profile-restore-'+uuid.uuid4().hex)
    source, target, work = base/'original data', base/'restored data', base/'work'
    source.mkdir(parents=True)
    work.mkdir()
    report = {'passed': False, 'checks': {}, 'external_model_calls': 0}
    previous = os.environ.get('SUMIKA_DATA_DIR')
    controller = None
    try:
        os.environ['SUMIKA_DATA_DIR'] = str(source)
        save(example(ROOT/'extensions/roles/defaults/sumika-guide', source/'memory.sqlite3'),
             source/'role-model-settings.json')
        with ModelFixture() as model:
            home = default_home(ROOT)
            home.mkdir(parents=True)
            (home/'.env').write_text('DEEPSEEK_API_KEY=restore-local-fixture-not-secret\n', encoding='utf8')
            (home/'cordis.patch.yml').write_text(json.dumps([
                {'id': 'session-title-llm', 'disabled': True},
                {'id': 'llm-deepseek', 'config': {'baseURL': model.url}},
                {'id': 'session-telemetry-otel', 'disabled': True},
            ]), encoding='utf8')
            model.recipe = [('write', {'file_path': 'result.txt', 'content': 'verified original task'})]
            controller = WorkbenchController(ROOT)
            controller.start()
            adapter = controller.adapter
            sid = 'restored-history'
            adapter._rpc('session/create', {'sessionId': sid, 'cwd': str(work)})
            stream = adapter.stream('session/follow', {'address': {'kind': 'session', 'sessionId': sid}}, timeout=60)
            try:
                next(stream)
                prompt(adapter, sid, 'Complete the isolated original task exactly once.')
                events = finish(stream)
            finally:
                stream.close()
            assert events[-1]['event']['data']['reason']['kind'] == 'completed'
            assert (work/'result.txt').read_text() == 'verified original task'
            controller.stop()
            report['checks']['original_native_task_completed_and_stopped'] = True
            report['backup'] = backup(source, base/'snapshot')
            report['restore'] = restore(base/'snapshot', target)
            report['rebind'] = rebind_role_paths(target, source)
            source_profile_hashes = inventory(source)
            original_requests = len(model.requests)
            original_mtime = (work/'result.txt').stat().st_mtime_ns
            os.environ['SUMIKA_DATA_DIR'] = str(target)
            controller = WorkbenchController(restored_product)
            controller.start()
            adapter = controller.adapter
            rows = json.loads((default_home(restored_product)/'cordis.patch.yml').read_text(encoding='utf8'))
            owned = [item for row in rows for item in row.get('insert', [])
                     if item.get('id') in ('sumika-skin', 'sumika-brand', 'sumika-workbench')]
            assert len(owned) == 3
            assert all(Path(item['name']).resolve().is_relative_to(restored_product) for item in owned)
            report['checks']['plugins_bound_to_selected_installation'] = True
            report['different_installation'] = restored_product != ROOT
            assert any(item['sessionId'] == sid for item in adapter.list_sessions())
            state = snapshot(adapter, sid)
            page = adapter._rpc('session/page', {'address': {'kind': 'session', 'sessionId': sid},
                                                'throughSeq': state['cursor']})
            serialized = json.dumps(page)
            assert 'Complete the isolated original task exactly once.' in serialized
            assert 'verified original task' in serialized
            assert any(r.get('event', {}).get('type') == 'tool/result' for r in page['records'])
            controller.stop()
            assert len(model.requests) == original_requests, 'restored startup unexpectedly called model'
            assert (work/'result.txt').stat().st_mtime_ns == original_mtime
            assert source_profile_hashes == inventory(source)
            report['checks'].update(history_and_tool_records_restored=True, no_task_replay=True,
                                    original_profile_unchanged=True, restored_workbench_stopped=True)
            if rollback_product is not None:
                # Keep the candidate's data untouched for diagnosis. Roll back using
                # the pre-change snapshot, never ask an older runtime to downgrade it.
                candidate_hashes = inventory(target)
                rollback_data = base/'rollback data'
                report['rollback_restore'] = restore(base/'snapshot', rollback_data)
                rebind_role_paths(rollback_data, source)
                os.environ['SUMIKA_DATA_DIR'] = str(rollback_data)
                controller = WorkbenchController(rollback_product)
                controller.start()
                adapter = controller.adapter
                assert any(item['sessionId'] == sid for item in adapter.list_sessions())
                rollback_state = snapshot(adapter, sid)
                rollback_page = adapter._rpc('session/page', {
                    'address': {'kind': 'session', 'sessionId': sid}, 'throughSeq': rollback_state['cursor']})
                assert 'verified original task' in json.dumps(rollback_page)
                rows = json.loads((default_home(rollback_product)/'cordis.patch.yml').read_text(encoding='utf8'))
                plugins = [item for row in rows for item in row.get('insert', [])
                           if item.get('id') in ('sumika-skin', 'sumika-brand', 'sumika-workbench')]
                assert len(plugins) == 3 and all(Path(item['name']).resolve().is_relative_to(rollback_product) for item in plugins)
                controller.stop()
                assert len(model.requests) == original_requests
                assert (work/'result.txt').stat().st_mtime_ns == original_mtime
                assert inventory(target) == candidate_hashes
                assert inventory(source) == source_profile_hashes
                report['checks'].update(prior_product_restored_original_history=True,
                    rollback_plugins_bound_to_prior_product=True, rollback_did_not_replay=True,
                    candidate_data_preserved=True)
                report['rollback_product'] = str(rollback_product)
                report['rollback_boundary'] = 'Explicit retained-version and pre-change snapshot recovery; not automatic update, schema downgrade, failure injection or clean-machine acceptance.'
            report['passed'] = True
    finally:
        try:
            if controller is not None:
                controller.stop()
        finally:
            if previous is None:
                os.environ.pop('SUMIKA_DATA_DIR', None)
            else:
                os.environ['SUMIKA_DATA_DIR'] = previous
            (base/'report.json').write_text(json.dumps(report, indent=2), encoding='utf8')
            print('ARTIFACT', base, json.dumps(report), flush=True)


if __name__ == '__main__':
    main()
