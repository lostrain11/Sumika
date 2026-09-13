import tempfile,unittest
from pathlib import Path
from extensions.memory.mem0_adapter import MemoryStore
class MemoryTests(unittest.TestCase):
 def test_scope_and_disabled(self):
  with tempfile.TemporaryDirectory() as d:
   m=MemoryStore(Path(d)/'m.db');m.add('喜欢鼓手',user_id='u',role_id='aoi',source='user');m.add('other',user_id='u',role_id='x');self.assertEqual(m.search('鼓手',user_id='u',role_id='aoi')[0]['text'],'喜欢鼓手');self.assertEqual(m.search('鼓手',user_id='u',role_id='x'),[]);m.close()
   m=MemoryStore(Path(d)/'x.db',False);self.assertEqual(m.add('x',user_id='u',role_id='a'),{'disabled':True});self.assertEqual(m.search('x',user_id='u',role_id='a'),[])
if __name__=='__main__':unittest.main()
