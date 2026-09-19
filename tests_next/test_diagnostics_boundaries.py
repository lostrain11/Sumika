import json,sqlite3,tempfile,unittest,zipfile
from pathlib import Path
from extensions.continuity.continuity import initialize,ingest
from extensions.diagnostics.query import query,evidence_bundle
class DiagnosticBoundaries(unittest.TestCase):
 def test_filter_before_limit_and_page_without_mutation(self):
  with tempfile.TemporaryDirectory(dir='.sumika-next') as tmp:
   root=Path(tmp);initialize(root)
   ingest(root,{'harness':'fixture','session':'s','task':'old','events':[{'kind':'tool','source_id':str(i),'payload':{'status':'failed','callId':'c'}} for i in range(3)]})
   ingest(root,{'harness':'fixture','session':'other','task':'new','events':[{'kind':'tool','source_id':str(i),'payload':{'status':'ok','text':'failed denied timeout'}} for i in range(110)]})
   db=root/'.sumika-continuity/records.sqlite3';before=db.read_bytes()
   rows=query(root,task='old',call_id='c',limit=2);self.assertEqual(len(rows),2)
   rest=query(root,task='old',call_id='c',before=rows[-1]['seq']);self.assertEqual(len(rest),1)
   self.assertFalse({r['seq'] for r in rows}&{r['seq'] for r in rest})
   self.assertEqual(query(root,task='new',error_only=True),[]);self.assertEqual(db.read_bytes(),before)
   with self.assertRaises(ValueError):query(root,limit=True)
 def test_bundle_omits_raw_content_and_refuses_overwrite(self):
  with tempfile.TemporaryDirectory(dir='.sumika-next') as tmp:
   root=Path(tmp);initialize(root)
   ingest(root,{'harness':'fixture','session':'s','task':'t','events':[{'kind':'tool','source_id':'a','payload':{'status':'failed','callId':'sk-fixturecredential','text':'private prompt','error_code':'E_TEST'}}]})
   docs=root/'docs/project';docs.mkdir(parents=True);(docs/'handoff.json').write_text('{"secret":"private document"}')
   path=root/'e.zip';evidence_bundle(root,'t',path)
   with zipfile.ZipFile(path) as z:
    contents=''.join(z.read(n).decode() for n in z.namelist())
   for secret in ['sk-fixturecredential','private prompt','private document']:self.assertNotIn(secret,contents)
   self.assertIn('E_TEST',contents);before=path.read_bytes()
   with self.assertRaises(FileExistsError):evidence_bundle(root,'t',path)
   self.assertEqual(path.read_bytes(),before)

class DiagnosticCLI(unittest.TestCase):
 def test_cli_export_and_stdout(self):
  from unittest.mock import patch
  from contextlib import redirect_stdout
  import io
  from sumika_next.cli import main
  with tempfile.TemporaryDirectory(dir='.sumika-next') as tmp:
   root=Path(tmp);initialize(root)
   ingest(root,{'harness':'fixture','session':'s','task':'t','events':[{'kind':'tool','source_id':'a','payload':{'status':'failed'}}]})
   out=root/'query.json'
   for extra in (['--out',str(out)],[]):
    with patch('sys.argv',['sumika','diagnostics','--root',str(root),'--task','t',*extra]),redirect_stdout(io.StringIO()):main()
   self.assertEqual(json.loads(out.read_text(encoding='utf8'))[0]['task'],'t')
