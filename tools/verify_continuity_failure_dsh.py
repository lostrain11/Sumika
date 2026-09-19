"""Real DSH failure acceptance with a proven loopback model baseline.

All data belongs to a new isolated profile. No cloud calls or personal data.
"""
import json
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tests_next'), str(ROOT / 'extensions/continuity')]
from p2_fixture import ModelFixture
from install import install
from sumika_next.dsh import Dsh
from verify_dsh_recovery import finish, prompt
from reconcile_continuity import inspect, reconcile


def turn(adapter, sid, request):
    stream = adapter.stream('session/follow', {
        'address': {'kind': 'session', 'sessionId': sid}}, timeout=30)
    try:
        next(stream)
        prompt(adapter, sid, request)
        return [frame['event'] for frame in finish(stream) if frame.get('event')]
    finally:
        stream.close()


def main():
    base = ROOT / '.sumika-next' / ('continuity-failure-' + uuid.uuid4().hex)
    home, work = base / 'home', base / 'work'
    home.mkdir(parents=True)
    work.mkdir()
    report = {'passed': False, 'checks': {}, 'external_model_calls': 0}
    adapter = None
    try:
        with ModelFixture() as model:
            (home / '.env').write_text('DEEPSEEK_API_KEY=local-fixture-not-a-secret\n', encoding='utf-8')
            (home / 'cordis.patch.yml').write_text(json.dumps([
                {'id': 'session-title-llm', 'disabled': True},
                {'id': 'llm-deepseek', 'config': {'baseURL': model.url}},
                {'id': 'session-telemetry-otel', 'disabled': True},
            ]), encoding='utf-8')
            install(work, home, ROOT / 'runtime/dsh')
            adapter = Dsh(ROOT, home)
            adapter.start()
            sid = 'continuity-failure'
            adapter._rpc('session/create', {'sessionId': sid, 'cwd': str(work)})
            baseline = turn(adapter, sid, 'healthy baseline')
            assert baseline[-1]['data']['reason']['kind'] == 'completed'
            assert len(model.requests) > 0
            report['checks']['healthy_model_and_plugin'] = True
            baseline_requests = len(model.requests)
            # Stop first: never race the plugin writer with database corruption.
            adapter.close()
            assert adapter.process is None or adapter.process.poll() is not None
            db = work / '.sumika-continuity/records.sqlite3'
            (base / 'healthy-records.sqlite3').write_bytes(db.read_bytes())
            db.write_bytes(b'not sqlite')
            adapter = Dsh(ROOT, home)
            adapter.start()
            for attempt in range(2):
                events = turn(adapter, sid, 'failure-probe-' + str(attempt))
                reason = events[-1]['data']['reason']
                # Require the plugin error, not just an absence of model traffic.
                serialized = json.dumps(events)
                has_cause = 'Continuity outcome unknown; automatic retries disabled' in serialized
                report['checks']['attempt_' + str(attempt)] = {
                    'reason_kind': reason.get('kind'),
                    'continuity_error_observed': has_cause,
                    'new_model_requests': len(model.requests) - baseline_requests,
                }
                assert reason.get('kind') != 'completed', reason
                assert has_cause, 'missing continuity failure evidence'
                assert len(model.requests) == baseline_requests
                assert db.read_bytes() == b'not sqlite'
            adapter.close()
            (base/'corrupt-records.sqlite3').write_bytes(db.read_bytes())
            repaired = (base/'healthy-records.sqlite3').read_bytes()
            db.write_bytes(repaired)
            adapter = Dsh(ROOT, home)
            adapter.start()
            events = turn(adapter, sid, 'after-repair-do-not-replay')
            assert events[-1]['data']['reason']['kind'] != 'completed'
            assert 'Continuity outcome unknown; automatic retries disabled' in json.dumps(events)
            assert len(model.requests) == baseline_requests
            assert db.read_bytes() == repaired, 'restored storage was automatically written'
            report['checks']['repair_and_restart_preserve_unknown_fence'] = True
            report['checks']['repaired_database_not_replayed'] = True
            adapter.close()
            inspected = inspect(work, sid)
            report['reconciliation'] = reconcile(work, home, sid, inspected['state_sha256'], inspected['database_sha256'])
            assert db.read_bytes() == repaired
            adapter = Dsh(ROOT, home)
            adapter.start()
            assert any(s['sessionId'] == sid for s in adapter.list_sessions())
            assert len(model.requests) == baseline_requests, 'reconciliation automatically replayed model work'
            events = turn(adapter, sid, 'explicit-new-turn-after-reconciliation')
            assert events[-1]['data']['reason']['kind'] == 'completed'
            assert len(model.requests) == baseline_requests + 1
            report['checks']['explicit_reconciliation_then_new_turn'] = True
            report['passed'] = True
    finally:
        try:
            if adapter is not None:
                adapter.close()
        finally:
            (base / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
            print('ARTIFACT', base, 'REPORT', json.dumps(report))


if __name__ == '__main__':
    main()
