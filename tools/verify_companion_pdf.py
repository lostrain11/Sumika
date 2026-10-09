"""Owned two-page PDF fixture in Edge; no personal files or model calls."""
import argparse
import base64
import io
import json
from pathlib import Path
import subprocess
import sys
import time
import threading

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def owned_profile_window(window, profile):
    """Edge may relaunch; verify its actual profile rather than launcher PID."""
    import re
    pid = window.process_id()
    command = subprocess.run(['powershell.exe', '-NoProfile', '-Command',
        f'(Get-CimInstance Win32_Process -Filter "ProcessId={int(pid)}").CommandLine'],
        capture_output=True, text=True, timeout=8, check=True).stdout.strip()
    argument = re.search(r'--user-data-dir=(?:"([^"]+)"|([^\s]+))', command)
    return bool(argument and Path(argument.group(1) or argument.group(2)).resolve() == profile.resolve())


def continuous_binding(window, pdf, *, timeout=25):
    """Exercise the actual child worker, retaining only bounded status facts."""
    from extensions.companion.perception_process import PerceptionProcess
    condition = threading.Condition()
    samples = []
    def observe(value):
        metadata = value.get('metadata', {})
        with condition:
            samples.append({'valid':value.get('valid'), 'has_image':bool(value.get('image')),
                'has_text':bool(value.get('text')), 'verified':metadata.get('document_identity_verified'),
                'reason':metadata.get('reason')})
            del samples[:-8]
            condition.notify_all()
    owner = PerceptionProcess(root=ROOT, python=sys.executable,
        on_observation=observe, on_clear=lambda:None)
    def wait_for(predicate):
        with condition:
            if not condition.wait_for(lambda:any(predicate(sample) for sample in samples), timeout):
                raise RuntimeError('continuous PDF worker acceptance timed out: ' + str(owner.status()))
    arguments = dict(handle=window.handle, process_id=window.process_id(), approved=True)
    checks = {}
    try:
        owner.start(**arguments, expected_document=pdf)
        wait_for(lambda sample:sample['valid'] and sample['verified'] is True)
        owner.pause()
        checks['pause_releases_worker'] = not owner.status()['alive'] and owner.status()['status'] == 'paused'
        with condition: samples.clear()
        owner.resume()
        wait_for(lambda sample:sample['valid'] and sample['verified'] is True)
        checks['resume_preserves_document'] = True
        owner.stop()
        checks['stop_clears_binding'] = not owner.status()['alive'] and owner.status()['target'] is None
        with condition: samples.clear()
        owner.start(**arguments, expected_document=pdf.parent/'alternate'/pdf.name)
        wait_for(lambda sample:sample['reason'] == 'PDF document identity changed')
        with condition:
            rejected = [sample for sample in samples if sample['reason'] == 'PDF document identity changed']
            checks['different_path_discards_payload'] = bool(rejected) and all(
                not sample['valid'] and not sample['has_text'] and not sample['has_image'] for sample in rejected)
        if not all(checks.values()):
            raise RuntimeError('continuous PDF lifecycle failed')
        return checks
    finally:
        owner.stop()


def generate(path, *, scanned=False, chinese_math=False):
    from reportlab.pdfgen import canvas
    from pypdf import PdfReader
    document=canvas.Canvas(str(path),pagesize=(600,800))
    for marker in ('FIRST_PAGE_LESSON','SECOND_PAGE_LESSON'):
        if scanned:
            from PIL import Image, ImageDraw, ImageFont
            from reportlab.lib.utils import ImageReader
            bitmap = Image.new('RGB', (1200,1600), 'white')
            draw = ImageDraw.Draw(bitmap)
            font = ImageFont.truetype('C:/Windows/Fonts/arial.ttf', 40)
            draw.text((110,180),marker.replace('_',' '),font=font,fill='black')
            draw.text((110,260),'A derivative measures the rate of change.',font=font,fill='black')
            if chinese_math:
                chinese = ImageFont.truetype('C:/Windows/Fonts/msyh.ttc', 40)
                lesson = ('导数表示函数的瞬时变化率。' if marker.startswith('FIRST')
                          else '积分表示曲线下的有向面积。')
                draw.text((110,350),lesson,font=chinese,fill='black')
                formula = "f(x) = x²,  f′(x) = 2x" if marker.startswith('FIRST') else '∫ 2x dx = x² + C'
                draw.text((110,440),formula,font=chinese,fill='black')
                draw.line([(140,1000),(1000,1000)],fill='black',width=4)
                draw.line([(140,1000),(140,580)],fill='black',width=4)
                curve = [(140+x,1000-round((x/820)**2*370)) for x in range(821)]
                draw.line(curve,fill='#146b42',width=5)
                draw.text((170,1080),'图：函数曲线',font=chinese,fill='black')
            document.drawImage(ImageReader(bitmap),0,0,width=600,height=800)
            bitmap.close()
        else:
            document.setFont('Helvetica',20)
            document.drawString(55,710,marker)
            document.setFont('Helvetica',14)
            document.drawString(55,670,'A derivative measures the rate of change.')
        document.showPage()
    document.save()
    pages=PdfReader(path).pages
    assert len(pages)==2
    if scanned:
        assert all(not page.extract_text().strip() for page in pages)


def text_loop(output, *, fixture=None):
    """Exercise the real HTTP/Office subprocess chain with a local reply fixture."""
    import threading
    import urllib.request
    import urllib.error
    from ui.server import serve
    output.mkdir(parents=True, exist_ok=False)
    pdf = output/'lesson.pdf'
    if fixture is not None:
        import shutil
        shutil.copyfile(fixture, pdf)
    else:
        launcher = ROOT/'.agents/skills/sumika-office/scripts/run.py'
        subprocess.run([sys.executable, '-X', 'utf8', '-B', str(launcher), 'exec',
                        str(Path(__file__).resolve()), '--generate', str(pdf)], check=True)
    server = serve(output/'settings.json', port=0, schedule_directory=output/'schedules')
    prompts = []
    server.sumika_bridge._companion._role_chat = lambda prompt, **kwargs: (
        prompts.append(prompt) or {'text':'Local PDF reply fixture'})
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f'http://127.0.0.1:{server.server_address[1]}'
    bundled = (ROOT/'runtime/desktop/python.exe').is_file()
    report = {'passed':False, 'runtime':'bundled-desktop' if bundled else 'office-development',
        'scope':'Real HTTP and extraction subprocess; synthetic PDF/local reply, no paid model calls'}
    def request(route, body=None):
        headers = {'Content-Type':'application/json'}
        if body is not None:
            with urllib.request.urlopen(base+'/api/manage/session') as response:
                headers['X-Sumika-CSRF'] = json.load(response)['csrf']
        req = urllib.request.Request(base+route, headers=headers,
            data=json.dumps(body).encode('utf8') if body is not None else None)
        with urllib.request.urlopen(req, timeout=25) as response:
            return json.load(response)
    try:
        for page, marker, absent in ((1,'FIRST_PAGE_LESSON','SECOND_PAGE_LESSON'),
                                     (2,'SECOND_PAGE_LESSON','FIRST_PAGE_LESSON')):
            result = request('/api/companion/collect', {
                'kind':'pdf','consent':True,'pdf_path':str(pdf),'page':page})
            assert result['valid']
            current = server.sumika_bridge._companion.latest
            assert marker in current.text and absent not in current.text
            assert current.metadata['page'] == page
            request('/api/companion/ask', {'question':'Explain the current page'})
            assert marker in prompts[-1] and absent not in prompts[-1]
        report['page_bound_questions'] = 2
        try:
            request('/api/companion/collect', {'kind':'pdf','consent':True,'pdf_path':str(pdf),'page':3})
            raise AssertionError('out-of-range page accepted')
        except urllib.error.HTTPError as error:
            assert error.code == 400
            error.close()
        assert server.sumika_bridge._companion.latest is None
        report.update(failed_page_clears_context=True, paid_model_calls=0, passed=True)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        (output/'report.json').write_text(json.dumps(report, indent=2), encoding='utf8')
    print(json.dumps(report))


def relocated_loop(output, runtime):
    """Copy product sources and standalone desktop runtime; no development skill."""
    import os
    import shutil
    from tools.build_portable_staging import physical_files
    runtime = runtime.resolve(strict=True)
    if not (runtime/'python.exe').is_file() or (runtime/'pyvenv.cfg').exists():
        raise ValueError('standalone runtime required')
    output.mkdir(parents=True, exist_ok=False)
    fixture = output/'fixture.pdf'
    launcher = ROOT/'.agents/skills/sumika-office/scripts/run.py'
    subprocess.run([sys.executable, '-X', 'utf8', '-B', str(launcher), 'exec',
                    str(Path(__file__).resolve()), '--generate', str(fixture)], check=True)
    product = output/'product'
    for name in ('ui','extensions','sumika_next'):
        for source, relative in physical_files(ROOT/name, product=True):
            target = product/name/relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
    for source, relative in physical_files(runtime):
        target = product/'runtime/desktop'/relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    script = product/'tools/verify_companion_pdf.py'
    script.parent.mkdir(parents=True)
    shutil.copyfile(Path(__file__), script)
    env = dict(os.environ)
    env.pop('SUMIKA_DESKTOP_PYTHON', None)
    env.pop('PYTHONPATH', None)
    env.pop('PYTHONHOME', None)
    subprocess.run([str(product/'runtime/desktop/python.exe'), '-X', 'utf8', '-B',
        str(script), '--text-loop','--pdf',str(fixture),'--output',str(output/'acceptance')],
        cwd=product, env=env, check=True, timeout=90)
    report = json.loads((output/'acceptance/report.json').read_text(encoding='utf8'))
    assert report['passed'] and report['runtime'] == 'bundled-desktop'
    assert not (product/'.agents').exists()
    print(json.dumps({'passed':True,'product':str(product),'development_skill_present':False,
                      'report':str(output/'acceptance/report.json')}))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--generate',type=Path)
    parser.add_argument('--pdf',type=Path)
    parser.add_argument('--output',type=Path)
    parser.add_argument('--text-loop', action='store_true')
    parser.add_argument('--desktop-runtime', type=Path)
    parser.add_argument('--native-address', action='store_true',
                        help='Owned regular Edge window with native address toolbar')
    parser.add_argument('--same-name-mismatch', action='store_true',
                        help='Verify known alternate same-name PDF path is rejected')
    parser.add_argument('--scanned', action='store_true', help='Image-only PDF fixture and OCR acceptance')
    parser.add_argument('--require-region', action='store_true', help='Require verified PDF viewport crop')
    parser.add_argument('--chinese-math', action='store_true', help='Chinese/math scanned learning fixture')
    parser.add_argument('--continuous', action='store_true', help='Verify actual bound continuous worker lifecycle')
    parser.add_argument('--allow-desktop-input', action='store_true', help='Explicitly permit owned Edge focus and keyboard navigation')
    args=parser.parse_args()
    if args.chinese_math and not args.scanned:
        parser.error('--chinese-math requires --scanned')
    if args.desktop_runtime:
        if not args.output:
            parser.error('--output required')
        relocated_loop(args.output.resolve(), args.desktop_runtime)
        return
    if args.text_loop:
        if not args.output:
            parser.error('--output required')
        text_loop(args.output.resolve(), fixture=args.pdf)
        return
    if args.generate:
        generate(args.generate, scanned=args.scanned, chinese_math=args.chinese_math)
        return
    if not args.pdf or not args.output:
        parser.error('--pdf and --output required')
    if not args.allow_desktop_input:
        parser.error('live PDF reader acceptance requires --allow-desktop-input')
    if args.continuous and not args.native_address:
        parser.error('--continuous requires --native-address')
    if args.same_name_mismatch and not args.native_address:
        parser.error('--same-name-mismatch requires --native-address')
    from pywinauto import Desktop
    from PIL import Image
    from extensions.companion.windows_learning import WindowsLearningCollector
    args.output.mkdir(parents=True,exist_ok=False)
    pdf=args.pdf.resolve(strict=True)
    before = {w.handle for w in Desktop(backend='uia').windows()}
    process=subprocess.Popen(['C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
        '--user-data-dir='+str(args.output/'profile'),'--no-first-run','--disable-sync',
        '--force-renderer-accessibility',pdf.as_uri() if args.native_address else '--app='+pdf.as_uri()],
        stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    window=collector=None
    report={'passed':False,'scope':'Owned Edge PDF reader; no real model or ebook application acceptance'}
    first_marker = 'FIRST PAGE LESSON' if args.scanned else 'FIRST_PAGE_LESSON'
    def has_marker(text, marker):
        if args.scanned:
            return ''.join(marker.split()) in ''.join(text.split())
        return marker in text
    second_marker = 'SECOND PAGE LESSON' if args.scanned else 'SECOND_PAGE_LESSON'
    try:
        deadline=time.monotonic()+25
        while time.monotonic()<deadline:
            matches=[w for w in Desktop(backend='uia').windows()
                     if w.handle not in before and pdf.name in w.window_text()
                     and owned_profile_window(w, args.output/'profile')]
            if len(matches)==1:
                window=matches[0]
                break
            time.sleep(.3)
        if window is None:
            raise RuntimeError('owned PDF reader did not appear')
        report['owned_window_pid'] = window.process_id()
        report['launcher_pid'] = process.pid
        window.set_focus()
        report['owned_reader_focused'] = True
        time.sleep(2)
        collector=WindowsLearningCollector(approved=True)
        deadline = time.monotonic() + 10
        while True:
            result=collector(f'window:{window.handle}:pid:{window.process_id()}')
            if result.metadata.get('page') == 1 and has_marker(result.text, first_marker):
                break
            if time.monotonic() >= deadline:
                break
            time.sleep(.3)
        if not result.valid or not result.image:
            raise RuntimeError('owned PDF capture unavailable')
        report.update(source=result.source,text_status=result.metadata.get('text_status'),
            first_page_context=result.metadata.get('reader_context'),
            text_contains_first=has_marker(result.text, first_marker),
            text_contains_second=has_marker(result.text, second_marker),
            text_source=result.metadata.get('text_source'), image_available=True)
        report['first_text_sample'] = result.text[:1200]
        report['image_region'] = result.metadata.get('image_region')
        report['uia_reader_region'] = collector.text.reader_region(handle=window.handle, process_id=window.process_id())
        report['native_frame_size'] = [result.metadata.get('width'), result.metadata.get('height')]
        if args.require_region and not report['image_region']:
            raise RuntimeError('PDF viewport image was not cropped')
        if args.native_address:
            identity = result.metadata.get('reader_context', {})
            report['absolute_document_identity'] = Path(
                identity.get('document_path', '')).resolve() == pdf.resolve()
            if not report['absolute_document_identity']:
                raise RuntimeError('native PDF absolute identity not bound')
        if args.continuous:
            report['continuous_worker'] = continuous_binding(window, pdf)
        if args.same_name_mismatch:
            import shutil
            other = args.output/'alternate'/pdf.name
            other.parent.mkdir()
            shutil.copyfile(pdf, other)
            target = f'window:{window.handle}:pid:{window.process_id()}'
            wrong = collector(target, expected_document=other)
            report['same_name_path_rejected'] = (not wrong.valid and not wrong.text
                and wrong.image is None
                and wrong.metadata.get('reason') == 'PDF document identity changed')
            if not report['same_name_path_rejected']:
                raise RuntimeError('same-name alternate PDF path accepted')
            correct = collector(target, expected_document=pdf)
            report['matching_path_accepted'] = (correct.valid
                and correct.metadata.get('document_identity_verified') is True)
            if not report['matching_path_accepted']:
                raise RuntimeError('matching PDF path rejected')
        window.capture_as_image().save(args.output/'reader-screen.png')
        report['pdf_document_visible'] = any(
            entry.is_visible() and entry.window_text() == pdf.name
            for entry in window.descendants(control_type='Document'))
        with Image.open(io.BytesIO(base64.b64decode(result.image['data_base64']))) as bitmap:
            report['image_size']=list(bitmap.size)
            bitmap.save(args.output/'page.png')
        if report['text_contains_second']:
            raise RuntimeError('offscreen PDF page entered visible context')
        page_inputs=[entry for entry in window.descendants(control_type='Edit')
                     if entry.is_visible() and entry.get_value()=='1']
        report['page_input_count']=len(page_inputs)
        if len(page_inputs)==1:
            page_inputs[0].set_edit_text('2')
            page_inputs[0].type_keys('{ENTER}')
        else:
            from pywinauto import keyboard
            window.set_focus()
            keyboard.send_keys('^{END}')
            report['navigation_method']='Ctrl+End in owned PDF window'
        deadline = time.monotonic() + 8
        while True:
            second=collector(f'window:{window.handle}:pid:{window.process_id()}')
            if (second.metadata.get('page') == 2 and has_marker(second.text, second_marker)
                    and not has_marker(second.text, first_marker)):
                break
            if time.monotonic() >= deadline:
                break
            time.sleep(.3)
        report['second_page_context'] = second.metadata.get('reader_context')
        report['second_text_sample'] = second.text[:1200]
        if not has_marker(result.text, first_marker) or not has_marker(second.text, second_marker):
            raise RuntimeError('PDF visible native text missing current-page lesson')
        report['visible_page_text_verified'] = True
        report['visible_native_page_text_verified'] = not args.scanned
        if args.scanned:
            from pypdf import PdfReader
            report['no_pdf_text_layer'] = all(not page.extract_text().strip() for page in PdfReader(pdf).pages)
            if not report['no_pdf_text_layer']:
                raise RuntimeError('scan fixture unexpectedly has a PDF text layer')
            report['scan_text_source'] = result.metadata.get('text_source')
            report['local_ocr_samples'] = []
            for bundle, marker, absent in ((result, first_marker, second_marker), (second, second_marker, first_marker)):
                derived = collector.ocr(bundle.image)
                report['local_ocr_samples'].append(derived.get('text', '')[:1200])
                if args.require_region and (not bundle.metadata.get('image_region')
                        or 'Microsoft Edge' in derived.get('text','')
                        or pdf.name in derived.get('text','')):
                    raise RuntimeError('PDF viewport OCR contains browser chrome or is uncropped')
                if not has_marker(derived.get('text', ''), marker) or has_marker(derived.get('text', ''), absent):
                    raise RuntimeError('local OCR does not identify current scanned PDF page')
            report['local_ocr_pages_verified'] = True
            if args.chinese_math:
                phrases = ('导数表示函数的瞬时变化率', '积分表示曲线下的有向面积')
                report['chinese_prose_verified'] = all(
                    phrase in ''.join(sample.split())
                    for phrase, sample in zip(phrases, report['local_ocr_samples']))
                report['formula_ocr_exact'] = [
                    "f′(x)=2x" in ''.join(report['local_ocr_samples'][0].split()),
                    '∫2xdx=x²+C' in ''.join(report['local_ocr_samples'][1].split())]
                if not report['chinese_prose_verified']:
                    raise RuntimeError('Chinese scanned lesson prose was not recognized')
                received_images = []
                from extensions.companion.qa import CompanionQuestionService
                image_service = CompanionQuestionService(lambda prompt, **kwargs:
                    (received_images.append(kwargs.get('images')) or {'text':'Local multimodal fixture'}))
                for bundle in (result, second):
                    image_service.update(bundle)
                    image_service.ask('解释当前页的公式和曲线')
                report['formula_diagram_image_bound'] = all(
                    images == [bundle.image] for images,bundle in zip(received_images,(result,second)))
                if not report['formula_diagram_image_bound']:
                    raise RuntimeError('formula question did not carry current cropped page image')
        from extensions.companion.qa import CompanionQuestionService
        prompts = []
        service = CompanionQuestionService(lambda prompt, **kwargs:
            (prompts.append(prompt) or {'text': 'Local page explanation'}), include_images=False)
        for bundle, marker, absent in ((result, first_marker, second_marker),
                                      (second, second_marker, first_marker)):
            service.update(bundle)
            service.ask('Explain the derivative definition on this page')
            if not has_marker(prompts[-1], marker) or has_marker(prompts[-1], absent):
                raise RuntimeError('PDF question references wrong visible page')
        report['visible_page_questions_verified'] = True
        report['paid_model_calls'] = 0
        if result.metadata.get('page') != 1 or second.metadata.get('page') != 2:
            raise RuntimeError('PDF page selector not bound to captured context')
        if not second.valid or not second.image or second.image==result.image:
            raise RuntimeError('PDF navigation did not replace captured page')
        if has_marker(second.text, first_marker):
            raise RuntimeError('old PDF page text survived navigation')
        with Image.open(io.BytesIO(base64.b64decode(second.image['data_base64']))) as bitmap:
            bitmap.save(args.output/'page-2.png')
        report['page_navigation_updates_visual']=True
        report['second_page_text_status']=second.metadata.get('text_status')
        if args.same_name_mismatch:
            # Navigate only the dedicated acceptance browser. Same basename
            # keeps its native title stable; the path must still fence context.
            from extensions.companion.windows_text import WindowsTextCollector
            addresses = [entry for entry in window.descendants(control_type='Edit')
                         if entry.is_visible() and WindowsTextCollector._native_address(entry)]
            if len(addresses) != 1:
                raise RuntimeError('owned native address is ambiguous')
            addresses[0].set_edit_text(other.resolve().as_uri())
            addresses[0].type_keys('{ENTER}')
            deadline = time.monotonic() + 12
            while True:
                replacement = collector(target)
                identity = replacement.metadata.get('reader_context', {})
                if (replacement.valid and identity.get('document_path') == str(other.resolve())
                        and has_marker(replacement.text, first_marker)):
                    break
                if time.monotonic() >= deadline:
                    raise RuntimeError('same-name navigation did not bind new file')
                time.sleep(.3)
            if replacement.metadata.get('media_identity') == second.metadata.get('media_identity'):
                raise RuntimeError('same-name file retained previous media identity')
            wrong = collector(target, expected_document=pdf)
            if wrong.valid or wrong.text or wrong.image:
                raise RuntimeError('previous file path accepted after same-name navigation')
            from extensions.companion.context_fusion import ContextFusion
            from extensions.companion.contracts import ObservationBundle
            fusion = ContextFusion()
            fusion.visual(second)
            fusion.audio(ObservationBundle.now(source='application-audio-transcript',
                target=target, valid=True, text='Old document audio',
                metadata={'media_identity': second.metadata['media_identity']}))
            updated = fusion.visual(replacement)
            if updated.metadata.get('application_audio'):
                raise RuntimeError('old file audio survived same-name navigation')
            report['same_name_navigation_identity_changed'] = True
            report['previous_path_rejected_after_navigation'] = True
            report['old_document_audio_cleared'] = True
        report['passed']=True
    finally:
        if collector is not None: collector.stop()
        if window is not None: window.close()
        try: process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.terminate();process.wait(timeout=5)
        (args.output/'report.json').write_text(json.dumps(report,indent=2),encoding='utf8')
        print(json.dumps(report))


if __name__=='__main__':
    main()
