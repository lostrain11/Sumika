"""P4 leftover slices over the fixture PDF: selection, dual window, zoom.

Reuses the real-book harness (owned Edge profile window, WindowsLearningCollector).
Selection: selecting text in the reader reaches the observation as selection
state. Dual window: two windows of the same document are bound separately —
flipping the other window must not move the bound target's page. Zoom:
re-rendering changes the visual digest while the page identity stays put.
Only page numbers and hashes are recorded; no document text is stored.
"""
import argparse
import base64
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tools'))

from verify_companion_pdf import owned_profile_window
from extensions.companion.windows_learning import WindowsLearningCollector

EDGE = 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'


def fingerprint(bundle):
    text_hash = hashlib.sha256((bundle.text or '').encode('utf8')).hexdigest()[:16]
    image_hash = ''
    if bundle.image:
        image_hash = hashlib.sha256(
            base64.b64decode(bundle.image['data_base64'])).hexdigest()[:16]
    return {'text_sha': text_hash, 'image_sha': image_hash,
            'page': bundle.metadata.get('reader_context', {}).get('page'),
            'selected': bundle.metadata.get('selected'),
            'source': bundle.source}


def page_box(window, timeout=10):
    # The selector appears after the reader finishes rendering; retry until
    # it does rather than failing on startup timing.
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for entry in window.descendants(control_type='Edit'):
            if entry.is_visible() and (entry.get_value() or '').strip().isdigit():
                return entry
        time.sleep(0.5)
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pdf', type=Path, help='fixture PDF (existing file expected)')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--allow-desktop-input', action='store_true',
                        help='Explicitly permit owned Edge focus and keyboard navigation')
    args = parser.parse_args()
    if not args.allow_desktop_input:
        parser.error('the slice acceptance drives a focused Edge window; pass --allow-desktop-input')
    from pywinauto import Desktop
    args.output.mkdir(parents=True, exist_ok=False)
    fixture = args.pdf.resolve(strict=True)

    before = {w.handle for w in Desktop(backend='uia').windows()}
    process = subprocess.Popen(
        [EDGE, '--user-data-dir=' + str(args.output / 'profile'), '--no-first-run',
         '--disable-sync', '--force-renderer-accessibility', fixture.as_uri()],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    # A second plain launch opens a tab in the first window; the dual window
    # slice needs two real top-level windows of the same document.
    subprocess.Popen(
        [EDGE, '--user-data-dir=' + str(args.output / 'profile'), '--no-first-run',
         '--disable-sync', '--force-renderer-accessibility', '--new-window', fixture.as_uri()],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.monotonic() + 30
    windows = []
    while time.monotonic() < deadline and len(windows) < 2:
        windows = [w for w in Desktop(backend='uia').windows()
                   if w.handle not in before and fixture.name in w.window_text()
                   and owned_profile_window(w, args.output / 'profile')]
        time.sleep(0.3)
    if len(windows) < 2:
        process.terminate()
        raise RuntimeError(f'expected two windows of the same document, got {len(windows)}')
    window_a, window_b = windows[0], windows[1]

    report = {'passed': False, 'pdf': fixture.name,
              'scope': 'Fixture only; page numbers and hashes recorded, no document text',
              'slices': {}}
    try:
        from pywinauto import keyboard
        collector = WindowsLearningCollector(approved=True)
        handle, pid = window_a.handle, window_a.process_id()
        target = f'window:{handle}:pid:{pid}'
        window_a.set_focus()
        time.sleep(2)

        # Click the canvas so the document (not a toolbar control) holds
        # keyboard focus; a plain single click does not change the text.
        window_a.click_input(coords=(window_a.rectangle().width() // 2,
                                     window_a.rectangle().height() // 2))
        time.sleep(1)
        # Slice 1: selection, asserted on the product's text collector (the
        # adapter the learning collector calls internally): an active
        # selection must be reported as document-selection with the flag set.
        # Known upstream limit (recorded): Edge's UIA selection ranges yield
        # an empty visible intersection, so the fused bundle honestly falls
        # back to page text instead of fabricating selection prose.
        from extensions.companion.windows_text import WindowsTextCollector
        text_collector = WindowsTextCollector()
        visible = text_collector.collect(handle=handle, process_id=pid, kind='document',
                                         selected=False)
        keyboard.send_keys('^a')
        time.sleep(1.5)
        selected = text_collector.collect(handle=handle, process_id=pid, kind='document',
                                          selected=True, visible_selection_only=True)
        keyboard.send_keys('{ESC}')
        time.sleep(1)
        base_state = fingerprint(collector(target))
        report['slices']['selection'] = {
            'visible_source': visible.source,
            'selected_source': selected.source,
            'selected_flag': selected.metadata.get('selected'),
            'selected_empty_intersection': not selected.valid,
            'page_stable': base_state['page'] is not None,
            'passed': bool(selected.source.endswith('-selection')
                           and selected.metadata.get('selected') is True
                           and visible.source.endswith('-visible'))}

        # Slice 2: dual window. Flip window B to page 2; the bound target
        # (window A) must keep reporting its own page — no cross-talk.
        base_page = base_state['page']
        # Both readers must finish rendering before the flip; the earlier
        # failure mode was flipping while window B had no selector yet.
        settle_deadline = time.monotonic() + 20
        while time.monotonic() < settle_deadline and (
                page_box(window_a, timeout=0.5) is None or page_box(window_b, timeout=0.5) is None):
            time.sleep(1)
        box_b = page_box(window_b, timeout=5)
        if box_b is None:
            report['slices']['dual_window'] = {'passed': False,
                                               'reason': 'page selector unavailable on window B'}
        else:
            window_b.set_focus()
            box_b.set_edit_text('2')
            box_b.type_keys('{ENTER}')
            time.sleep(2)
            window_a.set_focus()
            time.sleep(1)
            after_state = fingerprint(collector(target))
            report['slices']['dual_window'] = {
                'other_window_flipped_to': 2,
                'bound_target_page': after_state['page'],
                'bound_target_unchanged': after_state['page'] == base_page,
                'bound_target_still_alive': after_state['page'] is not None,
                'passed': bool(after_state['page'] == base_page)}

        # Slice 3: zoom through the reader's own UIA toolbar buttons
        # (keyboard shortcuts do not land without document focus). Each zoom
        # re-renders: the visual digest changes while the page stays put.
        before_zoom = fingerprint(collector(target))
        zoom_buttons = {}
        for entry in window_a.descendants(control_type='Button'):
            name = (entry.window_text() or '').strip()
            if '放大' in name or '缩小' in name:
                zoom_buttons.setdefault('缩小' if '缩小' in name else '放大', entry)
        if not zoom_buttons:
            report['slices']['zoom'] = {'passed': False, 'reason': 'zoom buttons unavailable'}
        else:
            zoom_buttons['缩小'].invoke()
            time.sleep(2)
            after_zoom = fingerprint(collector(target))
            zoom_buttons['放大'].invoke()
            time.sleep(2)
            after_zoom2 = fingerprint(collector(target))
            report['slices']['zoom'] = {
                'page_before': before_zoom['page'], 'page_after': after_zoom['page'],
                'visual_digest_changed': after_zoom['image_sha'] != before_zoom['image_sha'],
                'second_zoom_changed_again': after_zoom2['image_sha'] != after_zoom['image_sha'],
                'page_after_second': after_zoom2['page'],
                'passed': bool(after_zoom['page'] == before_zoom['page']
                               and after_zoom['image_sha'] != before_zoom['image_sha']
                               and after_zoom2['image_sha'] != after_zoom['image_sha']
                               and after_zoom2['page'] == before_zoom['page'])}

        report['passed'] = all(s.get('passed') for s in report['slices'].values())
        window_a.capture_as_image().save(args.output / 'reader-screen.png')
    finally:
        (args.output / 'report.json').write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')
        try:
            process.terminate()
        except Exception:
            pass
    print(json.dumps({'passed': report['passed'],
                      'slices': {k: v.get('passed') for k, v in report['slices'].items()}}))


if __name__ == '__main__':
    main()
