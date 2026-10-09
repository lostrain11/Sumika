"""Inspect an explicit reader window, optionally verifying reversible page turns."""
import argparse
import base64
import json
import time
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from extensions.companion.windows_learning import WindowsLearningCollector
from extensions.companion.windows_text import WindowsTextCollector
from extensions.companion.qa import CompanionQuestionService


def reader_button(text_collector, handle, process_id, title, name):
    window = text_collector.controller._window(handle, process_id)
    if window.window_text() != title:
        raise RuntimeError('reader tab changed; navigation rejected')
    documents = [c for c in window.descendants(control_type='Document') if c.is_visible()]
    document = text_collector._active_document(window, documents, title)
    if document is None or not document.window_text().endswith(' - 微信读书'):
        raise RuntimeError('active WeRead document required')
    buttons = [c for c in document.descendants(control_type='Button')
               if c.is_visible() and c.is_enabled() and c.window_text() == name]
    if len(buttons) != 1:
        raise RuntimeError('reader navigation target missing or ambiguous')
    return buttons[0]

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--handle',type=int,required=True)
    parser.add_argument('--process-id',type=int,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--page-turn',action='store_true',
        help='Verify existing WeRead next page, then return to the initial page')
    args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=False)
    collector=WindowsLearningCollector(approved=True)
    report={'scope':'Explicit HWND capture capability probe; optional next/previous navigation; no model or memory writes',
            'passed':False}
    try:
        target=f'window:{args.handle}:pid:{args.process_id}'
        bundle=collector(target)
        selected=WindowsTextCollector().collect(handle=args.handle,process_id=args.process_id,
            kind='ebook',selected=True,visible_selection_only=True)
        report.update(valid=bundle.valid,text_status=bundle.metadata.get('text_status'),
            text_source=bundle.metadata.get('text_source'),text_chars=len(bundle.text),
            selected_chars=len(selected.text),selected_valid=selected.valid,
            image_available=bundle.image is not None,metadata=dict(bundle.metadata))
        # Raw page text remains in memory, outside durable role memory/history.
        if bundle.image:
            (args.output/'current-page.jpg').write_bytes(base64.b64decode(bundle.image['data_base64']))
        report['passed']=bool(bundle.valid and bundle.image)
        report['acceptance']=('visual_with_navigation_capture_only'
            if bundle.metadata.get('text_status') == 'navigation_only' else
            'visual_with_ocr_capture_only' if bundle.metadata.get('text_status') == 'ocr_available' else
            'visual_capture_only' if not bundle.text else 'text_and_visual_capture_only')
        if args.page_turn:
            text_collector = WindowsTextCollector()
            title = text_collector.window_title(handle=args.handle, process_id=args.process_id)
            turned = False
            try:
                reader_button(text_collector,args.handle,args.process_id,title,'下一页').invoke()
                turned = True
                time.sleep(0.8)
                new_page = collector(target)
                if not new_page.valid or not new_page.image:
                    raise RuntimeError('new reader page observation unavailable')
                (args.output/'next-page.jpg').write_bytes(base64.b64decode(new_page.image['data_base64']))
                # Local adapter fixture only: prove replacement/cancellation,
                # not model comprehension. No personal prose persisted.
                def fixture_reply(*a, **kw):
                    service.update(new_page)
                    return {'text':'fixture old-page reply'}
                service = CompanionQuestionService(fixture_reply)
                service.update(bundle)
                reply = service.ask('解释当前页的图',session_id='reader-fixture')
                report['page_turn']={'valid':True,'stale_reply_rejected':reply['status']=='stale_response',
                    'model_calls':0,'scope':'real page capture plus local question-binding fixture'}
                if not report['page_turn']['stale_reply_rejected']:
                    raise RuntimeError('page change did not invalidate old response')
            finally:
                if turned:
                    reader_button(text_collector,args.handle,args.process_id,title,'上一页').invoke()
                    time.sleep(0.8)
                    restored = collector(target)
                    report['return_capture_valid']=bool(restored.valid and restored.image)
                    if restored.image:
                        (args.output/'returned-page.jpg').write_bytes(base64.b64decode(restored.image['data_base64']))
                    if not report['return_capture_valid']:
                        raise RuntimeError('returned page capture unavailable; verify reader position')
    except Exception as error:
        report['passed']=False
        report['failure_type']=type(error).__name__
        raise
    finally:
        collector.stop()
        (args.output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
        print(json.dumps(report,ensure_ascii=False))
    if not report.get('passed'):raise RuntimeError('reader observation unavailable')

if __name__=='__main__':main()
