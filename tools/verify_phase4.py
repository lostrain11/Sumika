"""Real DSH plugin, tools, model-route/restart/compact continuity acceptance.

Two independent deterministic loopback providers; no cloud calls or credentials.
"""
import json
from pathlib import Path
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'tests_next'), str(ROOT/'extensions/continuity')]
from continuity import handle
from install import install
from p2_fixture import ModelFixture
from sumika_next.dsh import Dsh
from verify_dsh_recovery import finish, prompt, snapshot


def run(adapter, model, session, request, recipe):
    model.responses = 0; model.recipe = recipe
    stream = adapter.stream('session/follow', {'address': {'kind': 'session', 'sessionId': session}}, timeout=60)
    next(stream)
    prompt(adapter, session, request)
    events = finish(stream)
    errors = [f['event']['data'] for f in events if f.get('event', {}).get('type') == 'turn/end'
              and f['event']['data']['reason'].get('kind') != 'completed']
    assert not errors, errors
    return events


def main():
    base = ROOT/'.sumika-next'/('p4-'+uuid.uuid4().hex)
    base.mkdir(); home = base/'home'; work = base/'work'; other = base/'unregistered'
    home.mkdir(); work.mkdir(); other.mkdir()
    subprocess.run(['git', 'init', '-q', str(work)], check=True)
    report = {'complete': False, 'external_model_calls': 0, 'checks': {}}
    evidence = {}
    with ModelFixture() as first, ModelFixture() as second:
        (home/'.env').write_text('DEEPSEEK_API_KEY=p4-local-fixture-not-a-secret\n')
        patches = [
            {'id': 'session-title-llm', 'disabled': True},
            {'id': 'llm-deepseek', 'config': {'baseURL': first.url}},
            {'id': 'session-telemetry-otel', 'disabled': True}]
        patch = home/'cordis.patch.yml'
        patch.write_text(json.dumps(patches), encoding='utf-8')
        install(work, home, ROOT/'runtime/dsh')
        adapter = Dsh(ROOT, home)
        try:
            adapter.start()
            session = 'p4-first'
            adapter._rpc('session/create', {'sessionId': session, 'cwd': str(work)})
            original = 'P4 原文保持空白\n  实现读取器，写入器留到下一步。\n```python\nx = 1\n```'
            common = {'task': 'p4-task', 'sources': [], 'uncertainties': ['integration report is a model claim']}
            plan = {**common, 'kind': 'plan', 'summary': 'reader first', 'plan': 'read then write',
                    'reason': 'initial scope', 'affected_tasks': ['p4-task']}
            outcome = {**common, 'kind': 'outcome', 'summary': 'reader implemented; writer pending',
                       'implemented': ['reader'], 'verification': [
                           {'command': 'reader-test', 'result': 'passed', 'evidence': ['reader.txt']},
                           {'command': 'writer-test', 'result': 'not_run', 'evidence': []},
                           {'command': 'integration-test', 'result': 'failed', 'evidence': []}],
                       'remaining': ['writer'], 'limitations': ['fixture acceptance'], 'next': 'implement writer only'}
            evidence['first'] = run(adapter, first, session, original, [
                ('skill', {'name': 'sumika-continuity'}),
                ('write', {'file_path': 'reader.txt', 'content': 'reader implemented once'}),
                ('continuity_record', {'report': json.dumps(plan)}),
                ('continuity_record', {'report': json.dumps(outcome)}),
                ('continuity_query', {})])
            rows = handle(work, {'action': 'query'})['records']
            originals = [r for r in rows if r['kind'] == 'original']
            assert len(originals) == 1 and originals[0]['payload']['content'][0]['text'] == original
            assert any(r['kind'] == 'outcome' for r in rows), rows
            assert (work/'reader.txt').read_text() == 'reader implemented once'
            report['checks']['original_skill_tools_outcome'] = True
            plan2 = dict(plan, plan='keep reader; implement writer after failed integration',
                         reason='integration failure', sources=[originals[0]['id']])
            evidence['plan-change'] = run(adapter, first, session, 'Change plan; keep original reader.', [
                ('continuity_query', {}), ('continuity_query', {}),
                ('continuity_record', {'report': json.dumps(plan2)})])
            rows = handle(work, {'action': 'query', 'query': {'kind': 'plan'}})['records']
            assert len(rows) == 2 and rows[1]['payload']['previous_plan']['plan'] == plan['plan']
            report['checks']['plan_history'] = True
            first.recipe = []; first.responses = 0
            compact = adapter._rpc('commands/execute', {'agentId': session, 'line': '/compact', 'submittedAttachments': []})
            evidence['compact'] = compact
            assert compact['result']['kind'] == 'success', compact
            deadline = time.monotonic() + 10
            while not handle(work, {'action': 'query', 'query': {'kind': 'compact'}})['records']:
                assert time.monotonic() < deadline, 'compaction capture did not settle'
                time.sleep(.1)
            adapter.close()
            # Different model backend and new live session; only project records carry task state.
            patches = json.loads(patch.read_text(encoding='utf-8'))
            next(p for p in patches if p.get('id') == 'llm-deepseek')['config']['baseURL'] = second.url
            patch.write_text(json.dumps(patches), encoding='utf-8')
            adapter = Dsh(ROOT, home); adapter.start()
            new_session = 'p4-second'
            adapter._rpc('session/create', {'sessionId': new_session, 'cwd': str(work)})
            evidence['resume'] = run(adapter, second, new_session, 'Continue the project from its records.', [
                ('continuity_query', {'query': json.dumps({'task': 'p4-task'})}),
                ('read', {'file_path': 'reader.txt'}),
                ('write', {'file_path': 'writer.txt', 'content': 'writer added after recovery'})])
            received = json.dumps(second.requests[0], ensure_ascii=False)
            for marker in ['SUMIKA_CONTINUITY', 'reader implemented; writer pending',
                           'implement writer only', 'not_run', 'failed', 'keep reader; implement writer']:
                assert marker in received, marker
            assert original in [b.get('text', '') for r in handle(work, {'action': 'query',
                                'query': {'kind': 'original'}})['records']
                                for b in r['payload']['content']]
            assert (work/'reader.txt').read_text() == 'reader implemented once'
            assert (work/'writer.txt').exists()
            assert handle(work, {'action': 'query', 'query': {'kind': 'compact'}})['records']
            report['checks']['compact_new_model_new_session_handoff'] = True
            # Same-session resume backfills without duplicating accepted originals.
            before = len(handle(work, {'action': 'query', 'query': {'kind': 'original'}})['records'])
            evidence['same-session'] = run(adapter, second, session, 'Resume original session once.', [])
            after = len(handle(work, {'action': 'query', 'query': {'kind': 'original'}})['records'])
            assert after == before+1
            report['checks']['same_session_backfill_idempotent'] = True
            adapter._rpc('session/create', {'sessionId': 'p4-unregistered', 'cwd': str(other)})
            evidence['unregistered'] = run(adapter, second, 'p4-unregistered', 'Unregistered project.', [])
            assert not (other/'.sumika-continuity').exists()
            report['checks']['workspace_opt_in'] = True
            adapter.close()
            patches = json.loads(patch.read_text(encoding='utf-8'))
            plugin = next(p['insert'][0] for p in patches if p.get('insert') and p['insert'][0]['id'] == 'sumika-continuity')
            plugin['config']['enabled'] = False
            patch.write_text(json.dumps(patches), encoding='utf-8')
            count = len(handle(work, {'action': 'query', 'query': {'limit': 100}})['records'])
            adapter = Dsh(ROOT, home); adapter.start()
            adapter._rpc('session/create', {'sessionId': 'p4-disabled', 'cwd': str(work)})
            second.requests.clear()
            run(adapter, second, 'p4-disabled', 'Plugin disabled.', [])
            wire = second.requests[0]
            assert 'SUMIKA_CONTINUITY' not in json.dumps(wire)
            assert not any(t['function']['name'].startswith('continuity_') for t in wire.get('tools', []))
            assert len(handle(work, {'action': 'query', 'query': {'limit': 100}})['records']) == count
            report['checks']['disabled_no_capture_tools_injection_data_preserved'] = True
            report['complete'] = True
        finally:
            adapter.close()
            (base/'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
            (base/'evidence.json').write_text(json.dumps(evidence, ensure_ascii=False), encoding='utf-8')
            print('ARTIFACT', base, 'REPORT', report, flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
