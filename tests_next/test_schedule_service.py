from datetime import datetime,timezone
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from extensions.desktop.scheduler import Schedule
from extensions.desktop.schedule_service import ScheduleService
from extensions.desktop.schedule_dsh import DshScheduleBridge
from extensions.desktop.schedule_runner import occurrence
from sumika_next.contracts import Trust


class ServiceTests(unittest.TestCase):
    def test_timezone_and_daylight_saving(self):
        s=Schedule('x','daily','09:00','test',timezone_name='Asia/Shanghai')
        due=occurrence(s,datetime(2026,1,2,2,tzinfo=timezone.utc))
        self.assertEqual(due,datetime(2026,1,2,1,tzinfo=timezone.utc))
        spring=Schedule('s','daily','02:30','test',timezone_name='America/New_York')
        self.assertIsNone(occurrence(spring,datetime(2026,3,8,12,tzinfo=timezone.utc)))
        fall=Schedule('f','daily','01:30','test',timezone_name='America/New_York')
        self.assertEqual(occurrence(fall,datetime(2026,11,1,8,tzinfo=timezone.utc)),datetime(2026,11,1,5,30,tzinfo=timezone.utc))
    def test_persistent_reminders_no_model_and_disabled_task(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);s=ScheduleService(p/'s.json',p/'db')
            s.store.upsert(Schedule('r','once','2026-01-01T00:00:00+00:00','remember'))
            s.store.upsert(Schedule('e','once','2026-01-01T00:00:00+00:00','execute','execute'))
            now=datetime(2026,1,2,tzinfo=timezone.utc)
            self.assertEqual(len(s.tick(now)),1)
            key=s.reminders()[0]['key'];s.close()
            s=ScheduleService(p/'s.json',p/'db')
            self.assertEqual(s.tick(now),[])
            self.assertEqual(len(s.reminders()),1)
            s.acknowledge(key);self.assertEqual(s.reminders(),[])
            s.close()

    def test_changed_action_and_untrusted_adapter_refused(self):
        with tempfile.TemporaryDirectory() as d:
            calls=[]
            adapter=SimpleNamespace(instance=SimpleNamespace(trust=Trust.MANAGED,instance_id='owned'),_rpc=lambda *a:calls.append(a))
            bridge=DshScheduleBridge(adapter,{'e':dict(enabled=True,action='approved',workspace=d)})
            altered=Schedule('e','daily','09:00','changed','execute')
            with self.assertRaises(PermissionError):bridge.dispatch(altered,'key')
            adapter.instance.trust=Trust.UNVERIFIED
            with self.assertRaises(PermissionError):bridge.dispatch(Schedule('e','daily','09:00','approved','execute'),'key')
            self.assertEqual(calls,[])

    def test_invalid_schedule_never_saved(self):
        for kind,value in [('daily','24:00'),('weekly','7 12:00'),('once','2026-01-01T12:00:00')]:
            with self.assertRaises(ValueError):Schedule('x',kind,value,'task')
