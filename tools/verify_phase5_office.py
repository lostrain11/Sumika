"""Office Skill through real DSH/native terminal, with a local deterministic model."""
import importlib.util
import json
import os
import argparse
import shutil
import subprocess
from pathlib import Path
import sys
import uuid

SOURCE = Path(__file__).resolve().parents[1]
ROOT = Path(os.environ.get('SUMIKA_TEST_CANDIDATE', str(SOURCE))).resolve(strict=True)
sys.path[:0] = [str(ROOT), str(SOURCE/'tests_next'), str(SOURCE/'tools')]
from p2_fixture import ModelFixture
from sumika_next.dsh import Dsh
from verify_dsh_recovery import finish, prompt
sys.path.insert(0, str(ROOT))

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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repair-fixture-acl', action='store_true',
                        help='Use bundled diagnosis script only on generated work directory')
    parser.add_argument('--native-office-catalog', action='store_true',
                        help='Verify upstream progressive Office skills without invoking installers')
    parser.add_argument('--native-office-workflow', action='store_true',
                        help='Verify automatic product wiring and actual bundled Python file operations')
    parser.add_argument('--native-office-engines', action='store_true',
                        help='Also require official engine skills and execute conversion/recalculation through DSH')
    args = parser.parse_args()
    if args.native_office_engines and not args.native_office_workflow:
        parser.error('--native-office-engines requires --native-office-workflow')
    base = SOURCE/'.sumika-next'/('p5-office-'+uuid.uuid4().hex)
    base.mkdir(); home = base/'home'; work = base/'work'
    home.mkdir(); work.mkdir()
    if args.repair_fixture_acl:
        scripts = list({p.resolve() for p in (ROOT/'runtime/dsh/node_modules/.pnpm').glob(
            '*/node_modules/@deepseek-ai/dsh-sandbox-windows-acl/assets/diagnose-windows-sandbox-acl/scripts/diagnose-windows-sandbox-acl.ps1')})
        physical = ROOT/'runtime/dsh/node_modules/@deepseek-ai/dsh-sandbox-windows-acl/assets/diagnose-windows-sandbox-acl/scripts/diagnose-windows-sandbox-acl.ps1'
        if not scripts and physical.is_file():
            scripts = [physical.resolve()]
        if len(scripts)!=1:
            raise RuntimeError('expected one bundled ACL diagnosis script')
        shell = shutil.which('pwsh') or shutil.which('powershell')
        if not shell:
            raise RuntimeError('PowerShell required for fixture ACL repair')
        repaired = subprocess.run([shell,'-NoProfile','-File',str(scripts[0]),
            '-Path',str(work),'-AllowRoot',str(work),'-Out',str(base/'acl-recovery')],
            capture_output=True,text=True,encoding='utf8')
        (base/'acl-repair-output.txt').write_text(repaired.stdout+repaired.stderr,encoding='utf8')
        repaired.check_returncode()
    python = SOURCE/'.sumika-next/office-env/Scripts/python.exe'
    if args.native_office_workflow:
        python = ROOT/'runtime/office/dependencies/python/python.exe'
        if not python.is_file():
            raise RuntimeError('candidate has no bundled Office payload')
    else:
        skill = installer.install(work, python)
        runner = skill/'scripts/run.py'
    exercise = work/'verify files.py'
    exercise.write_bytes((ROOT/'extensions/office/verify_files.py').read_bytes())
    command = (f'& {quote(python)} -X utf8 -B '
               + ('' if args.native_office_workflow else f'{quote(runner)} exec ')
               + f'{quote(exercise)} --output {quote(work/"files")}; exit $LASTEXITCODE')
    report = {'passed': False, 'external_model_calls': 0, 'checks': {}, 'candidate': str(ROOT),
              'office_environment': str(python), 'boundary': 'Real native DSH Skill/terminal, explicit host Office environment; no natural-language model quality claim.'}
    events = {}
    with ModelFixture() as model:
        (home/'.env').write_text('DEEPSEEK_API_KEY=p5-local-fixture-not-a-secret\n')
        patches = [
            {'id': 'session-title-llm', 'disabled': True},
            {'id': 'llm-deepseek', 'config': {'baseURL': model.url}},
            {'id': 'session-telemetry-otel', 'disabled': True}]
        if args.native_office_catalog:
            package = ROOT/'runtime/dsh/node_modules/@deepseek-ai/dsh-skill-office/lib/index.js'
            if not package.is_file():
                packages = list((ROOT/'runtime/dsh/node_modules/.pnpm').glob(
                    '*/node_modules/@deepseek-ai/dsh-skill-office/lib/index.js'))
                if len(packages)!=1:
                    raise RuntimeError('expected one upstream Office provider')
                package = packages[0].resolve()
            patches.append({'insert':[{'id':'sumika-office-reuse-probe','name':str(package),
                                       'config':{'cli':False}}]})
        (home/'cordis.patch.yml').write_text(json.dumps(patches), encoding='utf-8')
        if args.native_office_workflow:
            from ui.workbench import ensure_skin
            ensure_skin(home, root=ROOT)
            registered = json.loads((home/'cordis.patch.yml').read_text(encoding='utf8'))
            ids = {item.get('id') for row in registered for item in row.get('insert', [])}
            assert {'sumika-native-office','sumika-workspace-dependencies'} <= ids
            report['checks']['automatic_product_profile_wiring'] = True
        adapter = Dsh(ROOT, home)
        try:
            adapter.start()
            if args.native_office_catalog or args.native_office_workflow:
                names = ['office','office-docx','office-xlsx','office-pptx',
                         'office-render','office-recalculate','office-export-pdf']
                events['catalog'] = run(adapter,model,'native-office-catalog',work,
                    [('skill',{'name':name}) for name in names])
                messages = [frame['event']['data']['message'] for frame in events['catalog']
                            if frame.get('event',{}).get('type')=='tool/result']
                assert len(messages)==len(names), 'missing native Office skill results'
                for name,message in zip(names,messages):
                    assert not message.get('isError',False), (name,message)
                    text = json.dumps(message,ensure_ascii=False)
                    assert f'name=\\"{name}\\"' in text, (name,text[:150])
                report['checks']['upstream_seven_skills_loaded'] = True
                report['checks']['authoring_guides_request_native_dependency_tool'] = all(
                    'load_workspace_dependencies' in json.dumps(message)
                    for message in messages[1:4])
                if args.native_office_engines:
                    for message in messages[4:]:
                        text = json.dumps(message,ensure_ascii=False)
                        assert 'Installed LibreOffice Kit' in text and 'is disabled' not in text, text
                    report['checks']['official_engine_paths_in_native_skills'] = True
                declared = {tool.get('name',tool.get('function',{}).get('name'))
                            for request in model.requests for tool in request.get('tools',[])}
                report['native_dependency_tool_declared'] = 'load_workspace_dependencies' in declared
                if args.native_office_workflow:
                    assert report['native_dependency_tool_declared']
                    events['dependencies'] = run(adapter,model,'native-office-dependencies',work,
                        [('load_workspace_dependencies',{})])
                    dependency_messages = [f['event']['data']['message'] for f in events['dependencies']
                        if f.get('event',{}).get('type')=='tool/result']
                    assert len(dependency_messages)==1 and not dependency_messages[0].get('isError')
                    result = json.loads(''.join(b.get('text','') for b in dependency_messages[0]['content']))
                    assert Path(result['python']).resolve()==python.resolve(), result
                    report['checks']['dependency_paths_point_to_candidate'] = result
                    events['files'] = run(adapter,model,'native-office-files',work,
                        [('pwsh',{'command':command,'description':'Verify bundled Office file libraries',
                                  'workdir':str(work),'timeoutMs':60000})])
                    messages = [f['event']['data']['message'] for f in events['files']
                        if f.get('event',{}).get('type')=='tool/result']
                    assert len(messages)==1 and not messages[0].get('isError'), messages
                    file_report = json.loads((work/'files/report.json').read_text(encoding='utf8'))
                    assert file_report['passed'], file_report
                    report['checks']['bundled_file_roundtrips'] = file_report
                    if args.native_office_engines:
                        engine_script = work/'exercise engines.py'
                        engine_script.write_text('''import json,subprocess,sys
from pathlib import Path
from pypdf import PdfReader
from openpyxl import load_workbook
root=Path(sys.argv[1]);files=Path(sys.argv[2])
node=root/'runtime/node/node.exe'
cli=root/'runtime/dsh/node_modules/@deepseek-ai/libreoffice-kit/lib/cli.js'
calls=[]
for operation,source,target in [('convert','edited.docx','native.pdf'),('recalculate','edited.xlsx','calculated.xlsx')]:
 result=subprocess.run([str(node),str(cli),operation,'--input',str(files/source),'--output',str(files/target),'--timeout-ms','60000'],capture_output=True,text=True,encoding='utf8',timeout=90)
 assert result.returncode==0,result.stderr
 calls.append(json.loads(result.stdout))
assert all(c['backend']=='native' for c in calls)
assert len(PdfReader(files/'native.pdf').pages)==1
book=load_workbook(files/'calculated.xlsx',data_only=True)
assert book['进度']['B4'].value==7
book.close()
report={'passed':True,'native_calls':calls,'cached_sum':7}
(files/'native-engine-results.json').write_text(json.dumps(report,ensure_ascii=False),encoding='utf8')
print(json.dumps(report,ensure_ascii=False))
''',encoding='utf8')
                        engine_command = (f'& {quote(python)} -X utf8 -B {quote(engine_script)} '
                            f'{quote(ROOT)} {quote(work/"files")}; exit $LASTEXITCODE')
                        events['engines'] = run(adapter,model,'native-office-engines',work,
                            [('pwsh',{'command':engine_command,'description':'Verify bundled official Office engines',
                                      'workdir':str(work),'timeoutMs':180000})])
                        engine_report = json.loads((work/'files/native-engine-results.json').read_text(encoding='utf8'))
                        assert engine_report['passed'],engine_report
                        report['checks']['native_terminal_official_engines'] = engine_report
                report['loopback_model_calls'] = len(model.requests)
                report['boundary'] = ('Official progressive skills and bundled Python authoring roundtrips through native DSH; '
                    + ('official engines verified, no clean-machine or natural-language quality claim.' if args.native_office_engines
                       else 'no official LibreOfficeKit engines, clean-machine or natural-language quality claim.')
                    if args.native_office_workflow else 'Official progressive skills real native loading only; '
                    'dependency tool declaration check, no downloads or execution of official engines.')
                report['passed'] = True
                return
            events['enabled'] = run(adapter, model, 'office-enabled', work, [
                ('skill', {'name': 'sumika-office'}),
                ('pwsh', {'command': command, 'description': 'Exercise local office file libraries',
                          'workdir': str(work), 'timeoutMs': 60000})])
            serialized = json.dumps(events['enabled'], ensure_ascii=False)
            assert 'This skill uses an independent Python environment' in serialized, 'Skill not loaded'
            messages = [frame['event']['data']['message'] for frame in events['enabled']
                        if frame.get('event', {}).get('type') == 'tool/result']
            assert all(not message.get('isError', False) for message in messages)
            results = [block for frame in events['enabled']
                       if frame.get('event', {}).get('type') == 'tool/result'
                       for block in frame['event']['data']['message']['content']]
            assert len(results) == 2 and all(not block.get('isError') for block in results)
            # Native terminal prints an exit marker only for nonzero exits.
            terminal_text = (results[-1]['text'] if results[-1].get('type')=='text'
                             else ''.join(b.get('text', '') for b in results[-1]['content']))
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
            report['loopback_model_calls'] = len(model.requests)
            report['passed'] = True
        finally:
            adapter.close()
            (base/'events.json').write_text(json.dumps(events, ensure_ascii=False, indent=2), encoding='utf-8')
            (base/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
            print('ARTIFACT', base, 'PASSED', report['passed'], flush=True)


if __name__ == '__main__':
    main()
