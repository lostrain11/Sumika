import tempfile,unittest
from pathlib import Path
from extensions.desktop.scheduler import Schedule,ScheduleStore
class SchedulerTests(unittest.TestCase):
 def test_persist_and_disable(self):
  with tempfile.TemporaryDirectory() as d:
   s=ScheduleStore(Path(d)/'s.json');s.upsert(Schedule('a','daily','09:00','检查更新'));self.assertTrue(s.load()[0].enabled);s.disable('a');self.assertFalse(s.load()[0].enabled)
 def test_invalid_mode(self):
  with self.assertRaises(ValueError):Schedule('a','daily','x','y','bad')
if __name__=='__main__':unittest.main()
