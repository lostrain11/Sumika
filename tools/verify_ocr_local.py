"""Real OCR recognition of a generated fixture, without capturing the screen."""
import json
from pathlib import Path
import sys
import tempfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PIL import Image,ImageDraw,ImageFont
from extensions.desktop.ocr.ocr import recognize

with tempfile.TemporaryDirectory(prefix='sumika-ocr-') as d:
    p=Path(d)/'test.png'
    image=Image.new('RGB',(1000,200),'white')
    ImageDraw.Draw(image).text((20,50),'Sumika OCR test 123',font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',48),fill='black')
    image.save(p)
    result=recognize(p,provider='rapidocr_json')
    compact=''.join(result['text'].split()).lower()
    assert 'sumikaocrtest123' in compact,result
    report={'passed':True,'provider':result['provider'],'fixture':'generated English text and digits','screen_capture':False,'text':result['text']}
    Path('docs/project/ocr-local-evidence.json').write_text(json.dumps(report,indent=2),encoding='utf8')
    print(json.dumps(report))
