"""Office Skill through real DSH/native terminal, with a local deterministic model."""
import importlib.util
import json
from pathlib import Path
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'tests_next')]
from p2_fixture import ModelFixture
from sumika_next.dsh import Dsh
from verify_dsh_recovery import finish, prompt

spec = importlib.util.spec_from_file_location('office_install', ROOT/'extensions/office/install.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


def quote(value):
    return "'" + str(value).replace("'", "''") + "'"


def run(adapter, model, session, work, recipe):
    model.responses = 0; model.recipe = recipe
    adapter._rpc('session/create', {'sessionId': session, 'cwd': str(work)})
    stream = adapter.stream('session/follow', {'address': {'kind': 'session', 'sessionId': session}}, timeout=90)
    next(stream)
    prompt(adapter, session, 'Validate the local office Skill and fixture files.')
    events = finish(stream)
    errors = [f['event']['data'] for f in events if f.get('event', {}).get('type') == 'turn/end'
              and f['event']['data']['reason'].get('kind') != 'completed']
    assert not errors, errors
    return events


def main():
    base = ROOT/'.sumika-next'/('p5-office-'+uuid.uuid4().hex)
    base.mkdir(); home = base/'home'; work = base/'work'
    home.mkdir(); work.mkdir()
    python = ROOT/'.sumika-next/office-env/Scripts/python.exe'
    skill = installer.install(work, python)
    runner = skill/'scripts/run.py'
    exercise = work/'verify files.py'
    exercise.write_bytes((ROOT/'extensions/office/verify_files.py').read_bytes())
    command = (f'& {quote(python)} -X utf8 -B {quote(runner)} exec '
               f'{quote(exercise)} --output {quote(work/"files")}; exit $LASTEXITCODE')
    report = {'passed': False, 'external_model_calls': 0, 'checks': {}}
    events = {}
    with ModelFixture() as model:
        (home/'.env').write_text('DEEPSEEK_API_KEY=p5-local-fixture-not-a-secret\n')
        (home/'cordis.patch.yml').write_text(json.dumps([
            {'id': 'session-title-llm', 'disabled': True},
            {'id': 'llm-deepseek', 'config': {'baseURL': model.url}},
            {'id': 'session-telemetry-otel', 'disabled': True}]), encoding='utf-8')
        adapter = Dsh(ROOT, home)
        try:
            adapter.start()
            events['enabled'] = run(adapter, model, 'office-enabled', work, [
                ('skill', {'name': 'sumika-office'}),
                ('pwsh', {'command': command, 'description': 'Exercise local office file libraries',
                          'workdir': str(work), 'timeoutMs': 60000})])
            serialized = json.dumps(events['enabled'], ensure_ascii=False)
            assert 'This skill uses an independent Python environment' in serialized, 'Skill not loaded'
            results = [block for frame in events['enabled']
                       if frame.get('event', {}).get('type') == 'tool/result'
                       for block in frame['event']['data']['message']['content']]
            assert len(results) == 2 and all(not block.get('isError') for block in results)
            # Native terminal prints an exit marker only for nonzero exits.
            terminal_text = ''.join(b.get('text', '') for b in results[-1]['content'])
            assert json.loads(terminal_text)['passed'] is True
            file_report = json.loads((work/'files/report.json').read_text(encoding='utf-8'))
            assert file_report['passed']
            report['checks']['native_skill_load'] = True
            report['checks']['native_terminal_file_roundtrips'] = file_report
            # Same Skill remains discoverable; its execution entry refuses new disabled work.
            config = skill/'runtime.json'; settings = json.loads(config.read_text(encoding='utf-8'))
            settings['enabled'] = False
            config.write_text(json.dumps(settings), encoding='utf-8')
            sentinel = work/'should not run.py'
            sentinel.write_text('from pathlib import Path\nPath("disabled-write.txt").write_text("bad")\n')
            disabled = f'& {quote(python)} -X utf8 -B {quote(runner)} exec {quote(sentinel)}; exit $LASTEXITCODE'
            events['disabled'] = run(adapter, model, 'office-disabled', work, [
                ('pwsh', {'command': disabled, 'description': 'Verify disabled office refuses work',
                          'workdir': str(work), 'timeoutMs': 15000})])
            wire = json.dumps([frame['event']['data']['message']['content']
                               for frame in events['disabled']
                               if frame.get('event', {}).get('type') == 'tool/result'])
            assert 'Office module is disabled' in wire and '[exit code: 2]' in wire, wire
            assert not (work/'disabled-write.txt').exists()
            report['checks']['disabled_no_work_exit_preserved'] = True
            report['passed'] = True
        finally:
            adapter.close()
            (base/'events.json').write_text(json.dumps(events, ensure_ascii=False, indent=2), encoding='utf-8')
            (base/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
            print('ARTIFACT', base, 'PASSED', report['passed'], flush=True)


if __name__ == '__main__':
    main()
