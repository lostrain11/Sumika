import tempfile,unittest
from pathlib import Path
from extensions.diagnostics.query import query
from extensions.continuity.continuity import initialize,ingest
class DiagnosticsTests(unittest.TestCase):
 def test_error_query_reuses_records(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d);initialize(p);ingest(p,{'harness':'fixture','session':'s','task':'t','events':[{'kind':'tool','source_id':'1','payload':{'status':'failed','error_code':'E1','callId':'c1'}}]});rows=query(p,task='t',error_only=True);self.assertEqual(rows[0]['task'],'t');self.assertIn('failed',rows[0]['error_markers']);self.assertEqual(rows[0]['call_ids'],['c1'])
if __name__=='__main__':unittest.main()
