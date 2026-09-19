"""Native DSH terminal invokes real local role and semantic-memory service."""
import json
from pathlib import Path
import sys
import tempfile
import shutil
import uuid
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tests_next')]
from p2_fixture import ModelFixture
from sumika_next.dsh import Dsh
from verify_phase5_office import run,quote

base=ROOT/'.sumika-next'/('role-dsh-'+uuid.uuid4().hex)
base.mkdir()
home=base/'home';home.mkdir()
work=base/'work';work.mkdir()
shutil.copytree(ROOT/'.sumika-next/embedding-models',work/'models')
shutil.copytree(ROOT/'extensions/roles/defaults/sampleA',work/'role')
base=work
config={'role_dir':str(work/'role'),'database':str(base/'memory.db'),'user_id':'synthetic-test','project_id':'isolated','work_model':'work','role_model':'role','memory_provider':'semantic','embedding_cache':str(work/'models')}
(work/'service.py').write_text('import sys\nsys.path.insert(0,'+repr(str(ROOT))+')\nfrom extensions.roles.service import main\nraise SystemExit(main())\n',encoding='utf8')
(base/'config.json').write_text(json.dumps(config),encoding='utf8')
requests=[{'operation':'remember','data':{'text':'用户每晚十点半睡觉，不希望深夜收到提醒。'}},{'operation':'context','data':{'user_content':'几点以后不要打扰我休息','query':'几点以后不要打扰我休息','mode':'work'}}]
for i,r in enumerate(requests):(base/f'{i}.json').write_text(json.dumps(r,ensure_ascii=False),encoding='utf8')
python=ROOT/'.sumika-next/memory-env/Scripts/python.exe'
commands=[f'& {quote(python)} -X utf8 -B {quote(work/"service.py")} --config {quote(base/"config.json")} --request {quote(base/f"{i}.json")}; if ($LASTEXITCODE -ne 0) {{ exit $LASTEXITCODE }}' for i in range(2)]
with ModelFixture() as model:
    (home/'.env').write_text('DEEPSEEK_API_KEY=local-fixture-not-a-secret\n')
    (home/'cordis.patch.yml').write_text(json.dumps([{'id':'session-title-llm','disabled':True},{'id':'llm-deepseek','config':{'baseURL':model.url}},{'id':'session-telemetry-otel','disabled':True}]),encoding='utf8')
    adapter=Dsh(ROOT,home)
    try:
        adapter.start()
        events=run(adapter,model,'role-service',work,[('pwsh',{'command':'\n'.join(commands),'description':'Verify isolated role memory CLI','workdir':str(work),'timeoutMs':60000})])
        results=[f['event']['data']['message']['content'] for f in events if f.get('event',{}).get('type')=='tool/result']
        wire=json.dumps(results,ensure_ascii=False)
        assert 'memory_context' in wire and 'original_user_content' in wire and '[exit code:' not in wire,wire
        report=dict(passed=True,native_terminal=True,semantic_memory=True,external_model_calls=0,artifact=str(base))
        (ROOT/'docs/project/role-service-dsh-evidence.json').write_text(json.dumps(report,indent=2),encoding='utf8')
        print(json.dumps(report))
    finally:adapter.close()
