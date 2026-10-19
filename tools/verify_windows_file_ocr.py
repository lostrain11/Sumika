"""Generated-image OCR acceptance; never captures devices or user windows."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import uuid


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--product', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    product = args.product.resolve(strict=True)
    output = args.output.resolve() / uuid.uuid4().hex
    output.mkdir(parents=True)
    bundled = product / 'runtime/python/python.exe'
    primary = str(bundled) if bundled.is_file() else sys.executable
    report = {'passed': False, 'product': str(product), 'python': primary,
              'checks': [], 'device_capture': False, 'external_calls': 0}

    def run(python, code, *extra):
        result = subprocess.run([python, '-X', 'utf8', '-B', '-c', code, *map(str, extra)],
                                cwd=product, capture_output=True, text=True, encoding='utf8', timeout=60)
        if result.returncode:
            raise RuntimeError(result.stderr[-3000:] or result.stdout[-3000:])
        return json.loads(result.stdout)

    try:
        desktop = run(primary, 'from extensions.desktop.ocr.ocr import windows_python; import json; print(json.dumps(windows_python()))')
        assert desktop, 'Windows OCR runtime missing'
        report['desktop_python'] = desktop
        run(desktop, '''from PIL import Image,ImageDraw,ImageFont
from pathlib import Path
import json,sys
folder=Path(sys.argv[1])
font=ImageFont.truetype('C:/Windows/Fonts/msyh.ttc',42)
for name,text in [('english','SUMIKA OCR 12345'),('chinese','学习计划 每天阅读三十分钟')]:
    image=Image.new('RGB',(1000,160),'white')
    ImageDraw.Draw(image).text((32,40),text,font=font,fill='black')
    image.save(folder/(name+'.png'))
Image.new('RGB',(2100,2000),'white').save(folder/'oversize.png')
print(json.dumps(True))
''', output)
        result = run(primary, '''import json,sys
from pathlib import Path
from extensions.capabilities import CapabilityStore
from extensions.desktop.service import execute
from extensions.desktop.ocr.ocr import recognize
folder=Path(sys.argv[1]);checks=[];results={}
with_store=CapabilityStore(folder/'capabilities.sqlite3')
try:
    with_store.configure('ocr','windows',enabled=False)
    request={'capability':'ocr','operation':'recognize','arguments':{'image':str(folder/'english.png'),'language':'eng'}}
    try: execute(with_store,request)
    except PermissionError: checks.append('disabled_service_rejects')
    else: raise AssertionError('disabled service executed')
    with_store.configure('ocr','windows',enabled=True)
    for name,language,expected in [('english','eng','SUMIKAOCR12345'),('chinese','chi_sim','每天阅读三十分钟')]:
        request['arguments']={'image':str(folder/(name+'.png')),'language':language}
        result=execute(with_store,request)
        assert result['provider']=='windows',result
        compact=''.join(result['text'].split())
        assert expected in compact,(expected,compact)
        assert result['lines'],result
        for line in result['lines']:
            assert line['score'] is None
            assert len(line['box'])==4
            for x,y in line['box']: assert 0<=x<=1000 and 0<=y<=160
        results[name]=result;checks.append(name+'_real_service_text_and_pixel_boxes')
    for label,image,language in [('unavailable_language','english.png','zz-ZZ'),('pixel_budget','oversize.png','eng')]:
        try: recognize(folder/image,provider='windows',language=language)
        except RuntimeError: checks.append(label+'_rejects_without_fallback')
        else: raise AssertionError(label+' unexpectedly accepted')
finally: with_store.close()
print(json.dumps({'checks':checks,'results':results},ensure_ascii=False))
''', output)
        report.update(result)
        report['passed'] = True
    except Exception as error:
        report['error'] = str(error)
    finally:
        (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf8')
        print(json.dumps({'passed': report['passed'], 'report': str(output/'report.json'), 'error': report.get('error')}, ensure_ascii=False))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
