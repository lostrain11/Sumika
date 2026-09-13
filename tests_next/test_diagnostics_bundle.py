import tempfile,unittest,json,zipfile
from pathlib import Path
from extensions.diagnostics.query import evidence_bundle
from extensions.continuity.continuity import initialize,ingest
class BundleTests(unittest.TestCase):
 def test_bundle_excludes_private_db(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d);initialize(p);ingest(p,{'harness':'x','session':'s','task':'t','events':[{'kind':'tool','source_id':'a','payload':{'status':'failed'}}]});o=p/'e.zip';r=evidence_bundle(p,'t',o);self.assertIn('timeline.json',r['files']);self.assertNotIn('records.sqlite3',zipfile.ZipFile(o).namelist())
if __name__=='__main__':unittest.main()
