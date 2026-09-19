from datetime import datetime,timezone
from pathlib import Path
import tempfile
import unittest
from extensions.capabilities import CapabilityStore
from extensions.desktop.scheduler import Schedule
from extensions.desktop.schedule_runner import ScheduleRunner


class BackendTests(unittest.TestCase):
    def test_provider_selection_switch_disable_order_remove(self):
        with tempfile.TemporaryDirectory() as d:
            s=CapabilityStore(Path(d)/'db')
            s.configure('ocr','rapidocr');s.configure('voice','local')
            s.reorder(['voice','ocr'])
            s.configure('ocr','tesseract',enabled=False)
            with self.assertRaises(PermissionError):s.resolve('ocr')
            self.assertEqual(s.list()[0]['id'],'voice')
            s.remove('voice')
            with self.assertRaises(ValueError):s.resolve('voice')
            s.close()

    def test_restart_never_replays_unknown(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'db';r=ScheduleRunner(path)
            jobs=[Schedule('a','once','2026-01-01T00:00:00+00:00','test','execute')]
            calls=[]
            def dispatch(job,key):
                calls.append(key)
                raise RuntimeError('connection lost after action')
            now=datetime(2026,1,2,tzinfo=timezone.utc)
            self.assertEqual(r.tick(jobs,now,remind=dispatch,dispatch=dispatch)[0]['state'],'unknown')
            r.close();r=ScheduleRunner(path)
            self.assertEqual(r.tick(jobs,now,remind=dispatch,dispatch=dispatch),[])
            self.assertEqual(len(calls),1)
            due=r.history()[0]['due']
            with self.assertRaises(ValueError):r.reconcile('a',due,outcome='confirmed_completed',evidence='')
            r.reconcile('a',due,outcome='confirmed_not_executed',evidence='native task history inspected')
            self.assertEqual(r.tick(jobs,now,remind=dispatch,dispatch=dispatch),[])
            self.assertEqual(r.history()[0]['state'],'confirmed_not_executed');r.close()

    def test_daily_reminder_and_disabled(self):
        with tempfile.TemporaryDirectory() as d:
            r=ScheduleRunner(Path(d)/'db')
            now=datetime(2026,1,2,12,tzinfo=timezone.utc)
            job=Schedule('a','daily','10:00','remind')
            def no_dispatch(*args):raise AssertionError('reminder must not execute')
            self.assertEqual(r.tick([job],now,remind=lambda *args:'receipt',dispatch=no_dispatch)[0]['state'],'notified')
            self.assertEqual(r.tick([job],now,remind=lambda *args:'receipt',dispatch=no_dispatch),[])
            r.close()
