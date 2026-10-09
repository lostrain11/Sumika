"""Real Windows UIA acceptance on an owned synthetic Edge document only."""
import json
import argparse
from pathlib import Path
import subprocess
import sys
import time
import uuid
import sqlite3
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from extensions.companion.windows_text import WindowsTextCollector
from pywinauto import Desktop
from extensions.models.settings import example, save
from ui.server import serve


def verify_question_loop(base, window):
    requests = []

    class Fixture(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            requests.append(payload)
            response = json.dumps({'message': {'content': '导数表示函数在一点的变化率。'},
                                   'done_reason': 'stop', 'model': 'fixture'}).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(response)))
            self.end_headers()
            self.wfile.write(response)

    model = ThreadingHTTPServer(('127.0.0.1', 0), Fixture)
    threading.Thread(target=model.serve_forever, daemon=True).start()
    bridge = None
    try:
        settings = example(ROOT/'extensions/roles/defaults/sampleA', base/'memory.sqlite3')
        settings.update(enabled=True, provider='ollama', model='fixture',
                        endpoint=f'http://127.0.0.1:{model.server_port}')
        settings['memory'].update(auto_extract=True, model_proposals=True)
        path = base/'settings.json'
        save(settings, path)
        bridge = serve(path, port=0, capability_database=base/'capabilities.sqlite3',
                       schedule_directory=base/'schedules')
        threading.Thread(target=bridge.serve_forever, daemon=True).start()
        url = f'http://127.0.0.1:{bridge.server_port}'
        with urllib.request.urlopen(url+'/api/manage/session') as response:
            token = json.load(response)['csrf']

        def post(route, payload):
            request = urllib.request.Request(url+route, data=json.dumps(payload).encode(),
                headers={'Content-Type': 'application/json', 'X-Sumika-CSRF': token})
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.load(response)

        observed = post('/api/companion/collect', {'consent': True, 'handle': window.handle,
            'process_id': window.process_id(), 'kind': 'web'})
        assert observed['valid'], observed
        answer = post('/api/companion/ask', {'question': '这段教程中导数是什么意思？'})
        assert '变化率' in answer['text'], answer
        assert answer['observation_target'] == observed['target'], answer
        assert answer['observation_source'] == 'web-visible', answer
        prompt = requests[-1]['messages'][-1]['content']
        assert 'VISIBLE_LESSON' in prompt and 'OFFSCREEN_SECRET' not in prompt
        assert '[参考内容开始]' in prompt and '[用户问题]' in prompt
        assert answer['memory_proposals'] == 0 and not answer['auto_extracted']
        documents = window.descendants(control_type='Document')
        assert len(documents) == 1, 'selection document is ambiguous'
        buttons = window.descendants(control_type='Button', title='Select fixture fragment')
        assert len(buttons) == 1, 'selection fixture button is ambiguous'
        buttons[0].click_input()
        selected = post('/api/companion/collect', {'consent': True, 'handle': window.handle,
            'process_id': window.process_id(), 'kind': 'document', 'selected': True})
        assert selected['valid'] and selected['source'] == 'document-selection', selected
        selected_answer = post('/api/companion/ask', {'question': '仅解释选中的内容', 'session': 'selection'})
        assert selected_answer['observation_source'] == 'document-selection', selected_answer
        selected_prompt = requests[-1]['messages'][-1]['content']
        assert 'SELECTED_FRAGMENT' in selected_prompt, repr(selected_prompt)
        for excluded in ('VISIBLE_LESSON', 'UNSELECTED_VISIBLE', 'OFFSCREEN_SECRET', 'COLLAPSED_SECRET'):
            assert excluded not in selected_prompt, f'unselected content leaked: {excluded}'
        visible_selection=WindowsTextCollector().collect(handle=window.handle,process_id=window.process_id(),
            selected=True,visible_selection_only=True)
        assert 'SELECTED_FRAGMENT' in visible_selection.text, 'visible selection intersection lost selected text'
        scroll_buttons=window.descendants(control_type='Button',title='Scroll to next chapter')
        assert len(scroll_buttons)==1
        scroll_buttons[0].click_input()
        time.sleep(.3)
        offscreen_selection=WindowsTextCollector().collect(handle=window.handle,process_id=window.process_id(),
            selected=True,visible_selection_only=True)
        assert 'SELECTED_FRAGMENT' not in offscreen_selection.text, 'old offscreen selection leaked into continuous context'
        with sqlite3.connect(base/'memory.sqlite3') as db:
            assert db.execute('SELECT count(*) FROM memories').fetchone()[0] == 0
        with sqlite3.connect(base/'role-conversations.sqlite3') as db:
            persisted = '\n'.join(db.iterdump())
            assert 'VISIBLE_LESSON' not in persisted and 'SELECTED_FRAGMENT' not in persisted
        return {'collect_ask_http': True, 'local_provider_requests': len(requests),
                'source_bound': True, 'screen_memory_writes': 0,
                'screen_chat_persistence': False, 'real_model_quality_verified': False,
                'selected_fragment_http_ask': True, 'unselected_content_excluded': True,
                'continuous_selection_visible_only':True,
                'selection_fixture': 'Owned Edge DOM selection read via UIA, not an ebook reader'}
    finally:
        if bridge is not None:
            bridge.shutdown()
            bridge.server_close()
        model.shutdown()
        model.server_close()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--learning',action='store_true',help='Also capture only the owned fixture through the combined UIA/WGC collector')
    parser.add_argument('--output-root',type=Path,default=ROOT/'.sumika-next')
    args=parser.parse_args()
    base = args.output_root.resolve()/('companion-text-'+uuid.uuid4().hex)
    base.mkdir()
    title = 'SumikaTextFixture-'+uuid.uuid4().hex
    page = base/'lesson.html'
    page.write_text(f'''<!doctype html><html lang="zh"><meta charset="utf-8"><title>{title}</title>
<body><main><h1>导数教程</h1><p>VISIBLE_LESSON: 导数表示函数在一点的变化率。</p>
<p id="fragment">SELECTED_FRAGMENT</p><p>UNSELECTED_VISIBLE</p>
<button onclick="const r=document.createRange();r.selectNodeContents(document.getElementById('fragment'));const s=window.getSelection();s.removeAllRanges();s.addRange(r)">Select fixture fragment</button>
<button onclick="window.scrollTo(0,document.body.scrollHeight)">Scroll to next chapter</button>
<details><summary>折叠证明</summary><p>COLLAPSED_SECRET</p></details>
<div style="height:3000px"></div><p>OFFSCREEN_SECRET</p></main></body></html>''', encoding='utf8')
    browser = subprocess.Popen([
        'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
        '--user-data-dir='+str(base/'profile'), '--no-first-run', '--disable-sync',
        '--force-renderer-accessibility', '--app='+page.as_uri()],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    window = None
    report = {'passed': False, 'fixture': str(base), 'real_uia': True, 'model_calls': 0}
    try:
        deadline = time.monotonic()+25
        while time.monotonic() < deadline:
            matches = [w for w in Desktop(backend='uia').windows() if title in w.window_text()]
            if len(matches) == 1:
                window = matches[0]
                break
            time.sleep(.3)
        assert window is not None, 'owned fixture window did not appear'
        bundle = WindowsTextCollector().collect(handle=window.handle, process_id=window.process_id())
        report['valid'] = bundle.valid
        report['source'] = bundle.source
        report['metadata'] = dict(bundle.metadata)
        report['visible_marker'] = 'VISIBLE_LESSON' in bundle.text
        report['offscreen_excluded'] = 'OFFSCREEN_SECRET' not in bundle.text
        report['collapsed_excluded'] = 'COLLAPSED_SECRET' not in bundle.text
        assert bundle.valid and report['visible_marker'], 'visible text was not available'
        assert report['offscreen_excluded'] and report['collapsed_excluded'], 'UIA leaked hidden content'
        if args.learning:
            from extensions.companion.windows_learning import WindowsLearningCollector
            collector=WindowsLearningCollector(approved=True)
            try:
                observation=collector(f'window:{window.handle}:pid:{window.process_id()}')
                assert observation.valid and observation.image, 'owned learning visual capture unavailable'
                assert 'VISIBLE_LESSON' in observation.text, 'combined collector lost visible text'
                assert 'OFFSCREEN_SECRET' not in observation.text and 'COLLAPSED_SECRET' not in observation.text
                report['combined_uia_wgc']=True
                report['combined_source']=observation.source
                report['combined_text_source']=observation.metadata['text_source']
            finally:
                collector.stop()
        report.update(verify_question_loop(base, window))
        report['passed'] = True
    finally:
        if window is not None:
            window.close()
        try:
            browser.wait(timeout=10)
        except subprocess.TimeoutExpired:
            browser.terminate()
            browser.wait(timeout=5)
        (base/'report.json').write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf8')
        print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()
