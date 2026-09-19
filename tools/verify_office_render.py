"""Real office roundtrip, PDF conversion and formula recalculation evidence."""
import argparse
import json
from pathlib import Path
import sys
import tempfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from extensions.office.verify_files import verify
from extensions.office.render import convert
from openpyxl import load_workbook
from pypdf import PdfReader

p=argparse.ArgumentParser();p.add_argument('--soffice',required=True);p.add_argument('--out',required=True);args=p.parse_args()
root=Path(tempfile.mkdtemp(prefix='office-render-',dir='.sumika-next'))
verify(root/'files')
pages={}
for kind in ('docx','pptx','xlsx'):
    r=convert(root/'files'/('edited.'+kind),root/kind,executable=args.soffice)
    reader=PdfReader(r['path']);assert len(reader.pages)>0
    assert any(page.extract_text().strip() for page in reader.pages)
    pages[kind]=len(reader.pages)
r=convert(root/'files/edited.xlsx',root/'recalc',executable=args.soffice,format='xlsx')
book=load_workbook(r['path'],data_only=True)
assert book['进度']['B4'].value==7;book.close()
report=dict(passed=True,pdf_pages=pages,recalculated_value=7,artifact=str(root),visual_layout_review='not_run')
Path(args.out).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8');print(json.dumps(report))
