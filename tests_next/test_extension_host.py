import concurrent.futures
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from sumika_next.contracts import HarnessInstance,Trust
from sumika_next.extension_host import ExtensionHost
from extensions.desktop.scheduler import Schedule,ScheduleStore


class HostTests(unittest.TestCase):
    def test_concurrent_edits_and_stale_save(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'s.json'
            def add(i):ScheduleStore(path).upsert(Schedule(str(i),'daily','09:00','test'))
            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:list(pool.map(add,range(20)))
            store=ScheduleStore(path);self.assertEqual(len(store.load()),20)
            revision=store.revision();store.disable('0')
            with self.assertRaises(ValueError):store.save([],expected_revision=revision)
            self.assertEqual(len(store.load()),20)

    def test_disabled_does_not_create_store(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'config';p.write_text('{"schema_version":1,"enabled":false}')
            host=ExtensionHost(None,p);self.assertEqual(host.tick(),[]);host.close()
            self.assertEqual(len(list(Path(d).iterdir())),1)

    def test_lifecycle_and_mutated_schedule_refused(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);directory=root/'schedules';directory.mkdir()
            job=Schedule('j','once','2020-01-01T00:00:00+00:00','approved','execute')
            store=ScheduleStore(directory/'schedules.json');store.upsert(job)
            binding=dict(enabled=True,action=job.action,workspace=d,fingerprint=job.fingerprint())
            p=root/'config.json';p.write_text(json.dumps(dict(schema_version=1,enabled=True,schedules=dict(directory=str(directory),execution_bindings={'j':binding}))))
            calls=[]
            def rpc(method,args):calls.append(method);return {'accepted':True}
            adapter=SimpleNamespace(instance=HarnessInstance('dsh','owned',Trust.MANAGED),_rpc=rpc)
            host=ExtensionHost(adapter,p)
            store.upsert(Schedule('j','once','2021-01-01T00:00:00+00:00','approved','execute'))
            self.assertEqual(host.tick()[0]['state'],'unknown')
            self.assertEqual(calls,[])
            host.close();self.assertEqual(host.tick(),[])
