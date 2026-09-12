"""Real isolated DSH Plan, reconnect, restart and cancellation acceptance.

Only deterministic loopback model calls. No sandbox escalation responses.
"""
import json
from pathlib import Path
import subprocess
import sys
import uuid
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests_next'))
from p2_fixture import ModelFixture
from sumika_next.dsh import Dsh


def snapshot(adapter, session):
    stream = adapter.stream('session/follow', {'address': {'kind': 'session', 'sessionId': session}})
    try:
        return next(stream)
    finally:
        stream.close()


def prompt(adapter, session, request):
    assert adapter._rpc('session/prompt', {
        'sessionId': session, 'requestId': request, 'mode': 'queue',
        'content': [{'type': 'text', 'text': request}],
    }) == {'accepted': True}


def finish(stream):
    events = []
    for frame in stream:
        events.append(frame)
        if frame.get('event', {}).get('type') == 'turn/end':
            stream.close()
            return events
    raise AssertionError('stream ended without turn/end')


def main():
    base = ROOT / '.sumika-next' / ('p2-recovery-' + uuid.uuid4().hex)
    base.mkdir()
    home, work = base / 'home', base / 'work'
    home.mkdir(); work.mkdir()
    subprocess.run(['git', 'init', '-q', str(work)], check=True)
    report = {'checks': {}, 'complete': False}
    evidence = {}
    adapter = Dsh(ROOT, home)
    with ModelFixture() as model:
        (home / '.env').write_text('DEEPSEEK_API_KEY=p2-local-fixture-not-a-secret\n', encoding='utf-8')
        (home / 'cordis.patch.yml').write_text(json.dumps([
            {'id': 'session-title-llm', 'disabled': True},
            {'id': 'llm-deepseek', 'config': {'baseURL': model.url}},
            {'id': 'session-telemetry-otel', 'disabled': True},
        ]), encoding='utf-8')
        try:
            adapter.start()
            session = 'p2-plan'
            adapter._rpc('session/create', {'sessionId': session, 'cwd': str(work)})
            commands = adapter._rpc('commands/list', {'agentId': session})
            assert any(c['name'] == 'plan' for c in commands)
            value = adapter._rpc('commands/execute', {
                'agentId': session, 'line': '/plan on', 'submittedAttachments': []})
            evidence['plan-command'] = value
            assert value['result']['kind'] == 'success', value
            for label in ['Keep planning', 'Approve']:
                model.responses = 0
                model.recipe = [('exit_plan_mode', {'plan': '# P2 local plan\nRead the fixture only.'})]
                follow = adapter.stream('session/follow', {'address': {'kind': 'session', 'sessionId': session}}, timeout=30)
                next(follow)
                events = adapter.stream('$events', {}, timeout=30)
                ready = next(events)
                assert ready['type'] == 'ready'
                prompt(adapter, session, 'P2_PLAN_' + label)
                for event in events:
                    if event['type'] != 'waterfall':
                        continue
                    assert event['event'] == 'user-questions/request', event
                    assert event['agentId'] == session, event
                    assert event['request']['questions'][0]['id'] == 'plan-review', event
                    evidence[label] = event
                    adapter._rpc('$events/result', {
                        'clientId': ready['clientId'], 'eventId': event['eventId'],
                        'outcome': {'kind': 'result', 'value': {'answers': [
                            {'id': 'plan-review', 'selected': [label]}]}}})
                    break
                events.close()
                evidence[label + '-turn'] = finish(follow)
                state = snapshot(adapter, session)
                evidence[label + '-snapshot'] = state
                assert state['projections']['values']['plan']['active'] == (label == 'Keep planning')
                print('PLAN', label, 'verified', flush=True)
            report['checks']['plan_review'] = True
            before = snapshot(adapter, session)
            cursor = before['cursor']
            page = adapter._rpc('session/page', {
                'address': {'kind': 'session', 'sessionId': session}, 'throughSeq': cursor})
            assert page['records']
            again = snapshot(adapter, session)
            assert again['cursor'] == cursor
            report['checks']['reconnect'] = True
            count = len(model.requests)
            adapter.close()
            adapter = Dsh(ROOT, home)
            adapter.start()
            recovered = snapshot(adapter, session)
            after = adapter._rpc('session/page', {
                'address': {'kind': 'session', 'sessionId': session}, 'throughSeq': cursor})
            assert after['records'] == page['records']
            assert len(model.requests) == count, 'restart replayed model work'
            evidence['restart'] = recovered
            report['checks']['restart_history_no_replay'] = True
            print('RESTART history verified', flush=True)
            # Hold a genuine HTTP model request until native cancellation finishes.
            model.hold.clear()
            model.waiting.clear()
            model.block = True
            follow = adapter.stream('session/follow', {'address': {'kind': 'session', 'sessionId': session}}, timeout=30)
            next(follow)
            prompt(adapter, session, 'P2_CANCEL_ACTIVE')
            assert model.waiting.wait(15), 'model request never became active'
            assert adapter._rpc('session/cancel', {'sessionId': session}) == {'accepted': True}
            follow.close()
            model.hold.set()
            deadline = time.monotonic() + 30
            while True:
                cancelled = snapshot(adapter, session)
                records = adapter._rpc('session/page', {
                    'address': {'kind': 'session', 'sessionId': session}, 'throughSeq': cancelled['cursor']})['records']
                evidence['cancel'] = records
                new_events = [r['event'] for r in records if r.get('type') == 'event' and r['event']['seq'] > cursor]
                if any(e['type'] == 'assistant/attempt' for e in new_events) and new_events[-1]['type'] == 'step/end':
                    break
                assert time.monotonic() < deadline, 'cancel not persisted'
                time.sleep(.2)
            evidence['cancel-snapshot'] = cancelled
            assert 'P2_CANCEL_ACTIVE' in json.dumps(records)
            assert not any(e['type'] in {'tool/call', 'assistant/message'} for e in new_events)
            count = len(model.requests)
            time.sleep(1)
            assert snapshot(adapter, session)['cursor'] == cancelled['cursor'], 'late output changed history'
            assert len(model.requests) == count, 'cancelled model request was retried'
            print('CANCEL active request and late output verified', flush=True)
            report['checks']['active_model_cancel'] = True
            report['complete'] = True
        finally:
            model.hold.set()
            adapter.close()
            (base / 'evidence.json').write_text(json.dumps(evidence, indent=2), encoding='utf-8')
            (base / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
            print('ARTIFACT', base, 'REPORT', report, flush=True)


if __name__ == '__main__':
    main()
