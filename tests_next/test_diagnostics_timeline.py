import tempfile,unittest,json
from pathlib import Path
from extensions.diagnostics.query import timeline
from extensions.continuity.continuity import initialize,ingest
class TimelineTests(unittest.TestCase):
 def test_timeline_and_export(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d);initialize(p);ingest(p,{'harness':'x','session':'s','task':'t','events':[{'kind':'tool','source_id':'a','payload':{'status':'failed'}},{'kind':'turn_end','source_id':'b','payload':{'status':'unknown'}}]});out=p/'timeline.json';r=timeline(p,'t',out);self.assertEqual(r['events'],2);self.assertEqual(len(json.loads(out.read_text())['events']),2)
if __name__=='__main__':unittest.main()
