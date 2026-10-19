"""Probe shipped DSH scheduling in an isolated profile with a loopback model.

Unlike verify_schedule_dsh.py this exercises the upstream scheduler, not the
Sumika dispatch bridge. It never migrates existing reminders or touches users.
"""
import argparse
import json
from pathlib import Path
import sys
import subprocess
import time
import uuid
import urllib.request

SOURCE = Path(__file__).resolve().parents[1]


def catalog(adapter):
    """The public catalog method has no request argument (unlike legacy DTO RPCs)."""
    rpc_id = uuid.uuid4().hex
    body = json.dumps({'type': 'client-request', 'rpcId': rpc_id,
                       'method': 'schedule/catalog', 'payload': {'args': {}}}).encode()
    request = urllib.request.Request(adapter.url + '/api/schedule/catalog', data=body,
                                    headers={'Content-Type': 'application/json', 'Origin': adapter.url})
    with adapter._opener.open(request, timeout=20) as response:
        value = json.load(response)
    assert value.get('rpcId') == rpc_id and value.get('result', {}).get('ok') is True, value
    return value['result']['value']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--product', type=Path, default=SOURCE)
    parser.add_argument('--output', type=Path, default=SOURCE / '.sumika-next/acceptance-20261018/native-schedule')
    parser.add_argument('--browser', action='store_true')
    args = parser.parse_args()
    product = args.product.resolve()
    sys.path[:0] = [str(product), str(SOURCE / 'tests_next'), str(SOURCE / 'tools')]
    from p2_fixture import ModelFixture
    from sumika_next.dsh import Dsh
    from verify_dsh_recovery import prompt, finish, snapshot

    base = args.output.resolve() / uuid.uuid4().hex
    home, work = base / 'home', base / 'work'
    home.mkdir(parents=True)
    work.mkdir()
    report = {'passed': False, 'product': str(product), 'checks': {},
              'external_model_calls': 0,
              'boundary': ('Native scheduler API/delivery and existing manager entry/list browser clicks; '
                           'editing/deletion checked through API; no model-quality claim.' if args.browser else
                           'Native scheduler API and delivery; no browser clicks or model-quality claim.')}
    adapter = Dsh(product, home)
    evidence = {}
    with ModelFixture() as model:
        model.recipe = [
            ('schedule_create', {'title': 'Synthetic delivery', 'prompt': 'SYNTHETIC_NATIVE_DUE', 'after_seconds': 60 if args.browser else 30}),
            ('schedule_create', {'title': 'Synthetic daily', 'prompt': 'SYNTHETIC_DAILY',
                                 'daily': {'time': '12:00:00', 'time_zone': 'Asia/Shanghai'}}),
            ('schedule_create', {'title': 'Synthetic weekly', 'prompt': 'SYNTHETIC_WEEKLY',
                                 'weekly': {'time': '12:00:00', 'time_zone': 'Asia/Shanghai', 'weekdays': [1, 5]}}),
        ]
        (home / '.env').write_text('DEEPSEEK_API_KEY=loopback-fixture-not-a-secret\n', encoding='utf-8')
        (home / 'cordis.patch.yml').write_text(json.dumps([
            {'id': 'session-title-llm', 'disabled': True},
            {'id': 'llm-deepseek', 'config': {'baseURL': model.url}},
            {'id': 'session-telemetry-otel', 'disabled': True},
        ]), encoding='utf-8')
        if args.browser:
            from ui.workbench import ensure_skin
            assert ensure_skin(home, root=product)['registered']
        try:
            adapter.start()
            sid = 'native-schedule-fixture'
            adapter._rpc('session/create', {'sessionId': sid, 'cwd': str(work)})
            stream = adapter.stream('session/follow', {'address': {'kind': 'session', 'sessionId': sid}}, timeout=45)
            try:
                next(stream)
                prompt(adapter, sid, 'Create the three synthetic local schedules once.')
                evidence['creation'] = finish(stream)
            finally:
                stream.close()
            records = adapter._rpc('schedule/list', {'sessionId': sid})
            evidence['created'] = records
            assert len(records) == 3, records
            report['checks']['native_tools_create_three_rules'] = True
            due = next(x for x in records if x['kind'] == 'after')
            daily = next(x for x in records if x['kind'] == 'daily')
            weekly = next(x for x in records if x['kind'] == 'weekly')
            assert daily['timeZone'] == weekly['timeZone'] == 'Asia/Shanghai'
            assert weekly['weekdays'] == [1, 5]
            report['checks']['calendar_timezone_preserved'] = True
            calls = len(model.requests)
            if args.browser:
                subprocess.run(['node', str(SOURCE / 'tools/verify_native_schedule_ui.mjs')],
                               input=json.dumps({'url': adapter._browser_url, 'output': str(base)}),
                               text=True, check=True, timeout=45)
                report['checks']['native_manager_browser'] = True
            update = {'sessionId': sid, 'id': daily['id'], 'expected': daily, 'title': 'Renamed synthetic daily'}
            changed = adapter._rpc('schedule/update', update)
            evidence['updated'] = changed
            assert changed['updated'] is True, changed
            assert changed['record']['scheduledAt'] == daily['scheduledAt']
            stale = adapter._rpc('schedule/update', {**update, 'title': 'Stale overwrite'})
            evidence['stale'] = stale
            assert stale['code'] == 'schedule_conflict', stale
            report['checks']['compare_update_and_stale_refusal'] = True
            wrong = adapter._rpc('schedule/delete', {'sessionId': 'other-session', 'id': weekly['id']})
            assert wrong['deleted'] is False, wrong
            for record in (daily, weekly):
                removed = adapter._rpc('schedule/delete', {'sessionId': sid, 'id': record['id']})
                assert removed['deleted'] is True, removed
            catalog(adapter)
            assert len(model.requests) == calls
            report['checks']['management_no_model_activation_and_scoped_delete'] = True
            adapter.close()
            adapter = Dsh(product, home)
            adapter.start()
            assert any(x['id'] == due['id'] for x in catalog(adapter))
            report['checks']['restart_persists_task'] = True
            deadline = time.monotonic() + 80
            while True:
                history = adapter._rpc('schedule/history', {'sessionId': sid, 'id': due['id'], 'limit': 10})
                evidence['history'] = history
                if len(model.requests) > calls:
                    # A request proves activation; the persisted history proves delivery.
                    break
                assert time.monotonic() < deadline, history
                time.sleep(.2)
            deadline = time.monotonic() + 20
            while True:
                current = snapshot(adapter, sid)
                page = adapter._rpc('session/page', {'address': {'kind': 'session', 'sessionId': sid},
                                                     'throughSeq': current['cursor']})
                events = [r['event'] for r in page['records'] if r.get('type') == 'event']
                if events and events[-1]['type'] == 'turn/end':
                    break
                assert time.monotonic() < deadline, 'scheduled turn did not finish'
                time.sleep(.2)
            evidence['delivery_events'] = events
            assert 'SYNTHETIC_NATIVE_DUE' in json.dumps(model.requests[calls:])
            history = adapter._rpc('schedule/history', {'sessionId': sid, 'id': due['id'], 'limit': 10})
            evidence['history'] = history
            assert 'messageId' in json.dumps(history), history
            report['checks']['due_followup_in_original_session'] = True
            calls = len(model.requests)
            adapter.close()
            adapter = Dsh(product, home)
            adapter.start()
            catalog(adapter)
            time.sleep(1)
            assert len(model.requests) == calls
            report['checks']['completed_once_not_replayed_on_restart'] = True
            report['loopback_model_calls'] = calls
            report['passed'] = True
        finally:
            adapter.close()
            (base / 'evidence.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding='utf-8')
            (base / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
            print(json.dumps({'artifact': str(base), **report}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
