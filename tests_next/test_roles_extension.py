import json, subprocess, sys, tempfile, zipfile
from pathlib import Path
import unittest
ROOT=Path(__file__).resolve().parents[1]; SCRIPT=ROOT/'extensions/roles/roles.py'
spec_env={'schema_version':1,'work_model':'dev-model','role_model':'companion-model','roles':[{'id':'aoi','name':'Aoi','persona':'calm'}]}
class RoleTests(unittest.TestCase):
 def test_config_and_context_are_separate(self):
  ns={};exec(SCRIPT.read_text(encoding='utf-8'),ns); block=ns['context_block'](spec_env['roles'][0],['fact']); self.assertEqual(block['source'],'role_context');self.assertIn('must not alter',block['boundary'])
 def test_package_roundtrip_and_traversal_rejection(self):
  ns={};exec(SCRIPT.read_text(encoding='utf-8'),ns)
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);z=root/'r.zip'
   with zipfile.ZipFile(z,'w') as f:f.writestr('role.json',json.dumps({'schema_version':1,'id':'aoi','name':'Aoi'}));f.writestr('card/info.txt','x')
   path=ns['import_package'](z,root/'store');out=ns['export_package']('aoi',root/'store',root/'out.zip');self.assertTrue(path.is_dir() and out.is_file())
   bad=root/'bad.zip'
   with zipfile.ZipFile(bad,'w') as f:f.writestr('../escape.txt','x');f.writestr('role.json',json.dumps({'schema_version':1,'id':'bad','name':'bad'}))
   with self.assertRaises(ValueError):ns['import_package'](bad,root/'store')
if __name__=='__main__':unittest.main()
