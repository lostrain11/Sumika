import subprocess, sys, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; SCRIPT=ROOT/'extensions/desktop/control/control.py'
class DesktopControlTests(unittest.TestCase):
    def run_(self,*args): return subprocess.run([sys.executable,'-B',str(SCRIPT),*args],capture_output=True,text=True)
    def test_status(self): self.assertEqual(self.run_('status').returncode,0)
    def test_click_requires_confirmation(self):
        r=self.run_('click','--x','1','--y','1'); self.assertEqual(r.returncode,2); self.assertIn('requires explicit',r.stdout)
if __name__=='__main__': unittest.main()
