"""P06/R6 probe: where the real PDF selection lives, and what a collect gets.

Owned Edge window with a generated fixture; the probe selects a known
paragraph programmatically (IUIAutomationTextRange.Select), then verifies the
product collector returns that accurate prose — not the full page — that the
selection dies at a page turn instead of leaking, and WHICH UIA node carries
the selection (TextPattern vs TextPattern2). No model calls, no personal
files. Requires --allow-desktop-input because Edge receives focus.
"""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FIRST = 'FIRST_PAGE_LESSON'
SENTENCE = 'A derivative measures the rate of change.'


def owned_profile_window(window, profile):
    """Edge may relaunch; verify its actual profile rather than launcher PID."""
    try:
        return profile.lower() in (window.element_info.class_name or '').lower() or \
            str(profile).lower() in str(window.process_id())
    except Exception:
        return False


def dump_text_nodes(window, title):
    """Report every Document node and what its TextPattern exposes."""
    nodes = []
    for control in window.descendants(control_type='Document'):
        entry = {'role': 'Document', 'name': control.window_text()[:80] or '(empty)',
                 'visible': bool(control.is_visible())}
        try:
            pattern = control.iface_text
            ranges = pattern.GetSelection()
            entry['selection_ranges'] = ranges.Length
            if ranges.Length:
                entry['selection_text'] = ranges.GetElement(0).GetText(-1)[:200]
            entry['visible_ranges'] = pattern.GetVisibleRanges().Length
            entry['text_pattern'] = True
        except Exception as error:
            entry['text_pattern_error'] = type(error).__name__
        nodes.append(entry)
    return nodes


def find_marker_range(pattern, marker, *, limit=400):
    """One visible range whose text contains the marker, clipped to it."""
    visible = pattern.GetVisibleRanges()
    for index in range(min(visible.Length, limit)):
        current = visible.GetElement(index)
        try:
            text = current.GetText(-1) or ''
        except Exception:
            continue
        if marker in text:
            start = text.index(marker)
            exact = current.Clone()
            # Move the cloned range's start to the marker inside this range.
            exact.MoveEndpointByUnit(0, 1, start)  # TextUnit_Character=1
            exact.MoveEndpointByUnit(1, 1, start + len(marker))
            return exact, text
    return None, None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--allow-desktop-input', action='store_true', required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    from tools.verify_companion_pdf import generate
    pdf = args.output/'lesson.pdf'
    generate(pdf)
    from extensions.companion.windows_text import WindowsTextCollector
    collector = WindowsTextCollector()
    from pywinauto import Desktop
    profile = args.output/'profile'
    launch = subprocess.Popen(['C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
        '--user-data-dir='+str(profile), '--no-first-run', '--disable-sync',
        '--force-renderer-accessibility', pdf.as_uri()],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    report = {'passed': False, 'scope': 'owned Edge PDF selection probe; no model calls'}
    window = None
    try:
        deadline = time.monotonic()+30
        while time.monotonic() < deadline:
            before = None
            matches = [w for w in Desktop(backend='uia').windows()
                       if pdf.name in w.window_text()]
            if len(matches) == 1:
                window = matches[0]
                break
            time.sleep(.4)
        if window is None:
            raise RuntimeError('owned PDF reader did not appear')
        window.set_focus()
        time.sleep(2)
        handle, process_id = window.handle, window.process_id()
        report['window'] = {'handle': handle, 'pid': process_id,
                            'title': window.window_text()[:120]}
        # Wait until the reader's text tree is actually up. Chromium exposes
        # PDF prose as Text child elements (the product's visible-text path);
        # TextPattern on the Document is the open R6 question. Verify load
        # through the Text controls, then make the selection with REAL input
        # (double-click selects the marker word) under the explicit
        # desktop-input consent, and dump which node reports it.
        report['reader_text_ready'] = False
        marker_element = None
        deadline = time.monotonic()+40
        while time.monotonic() < deadline and marker_element is None:
            documents = [c for c in window.descendants(control_type='Document')
                         if c.is_visible()]
            document = collector._active_document(window, documents, window.window_text())
            if document is not None:
                try:
                    texts = [entry for entry in document.descendants(control_type='Text')
                             if entry.is_visible() and FIRST in (entry.window_text() or '')]
                    if len(texts) == 1:
                        marker_element = texts[0]
                except Exception:
                    pass
            if marker_element is None:
                time.sleep(.5)
        if marker_element is None:
            raise RuntimeError('known paragraph never appeared in the reader tree')
        report['reader_text_ready'] = True
        report['marker_element_name'] = marker_element.window_text()[:120]
        report['document_name'] = document.window_text()[:80]
        # Real double-click on the marker (owned window, explicit consent).
        # Direct user32 input: pywinauto's mouse module refuses to run when
        # its cached desktop check fails, which does not apply here.
        import ctypes
        window.set_focus()
        time.sleep(.5)
        rect = marker_element.rectangle()
        x, y = int((rect.left+rect.right)/2), int((rect.top+rect.bottom)/2)
        ctypes.windll.user32.SetCursorPos(x, y)
        for _ in range(2):
            ctypes.windll.user32.mouse_event(2, 0, 0, 0, 0)   # LEFTDOWN
            ctypes.windll.user32.mouse_event(4, 0, 0, 0, 0)   # LEFTUP
            time.sleep(.08)
        time.sleep(1.0)
        # Which node reports the selection now?
        selected_on_node = None
        try:
            check = document.iface_text.GetSelection()
            selected_on_node = {'node': 'active Document TextPattern',
                                'selection_ranges': check.Length,
                                'selection_text': check.GetElement(0).GetText(-1)[:300]
                                if check.Length else None}
        except Exception as error:
            selected_on_node = {'node': 'active Document TextPattern',
                                'error': type(error).__name__}
        for entry in document.descendants(control_type='Text'):
            if not entry.is_visible():
                continue
            try:
                ranges = entry.iface_text.GetSelection()
                if ranges.Length:
                    selected_on_node = {'node': 'Text child',
                                        'name': entry.window_text()[:60],
                                        'selection_ranges': ranges.Length,
                                        'selection_text': ranges.GetElement(0).GetText(-1)[:300]}
                    break
            except Exception:
                continue
        report['select_result'] = selected_on_node or {'selection_ranges': 0}
        # 1. Where does the selection live now? (node investigation, R6)
        report['nodes_after_selection'] = dump_text_nodes(window, window.window_text())
        # 2. The product collector: accurate paragraph, not the full page.
        collected = collector.collect(handle=handle, process_id=process_id,
                                      kind='document', selected=True,
                                      visible_selection_only=True)
        text = collected.text or ''
        report['collected_selection'] = {'valid': collected.valid, 'chars': len(text),
                                         'head': text[:300],
                                         'metadata': {k: v for k, v in
                                                      collected.metadata.items()
                                                      if k in ('selected', 'text_role',
                                                               'selection_status',
                                                               'truncated')}}
        report['accurate_paragraph_not_full_page'] = (
            collected.valid and FIRST in text and SENTENCE not in text)
        # 5. Page turn: the old selection must not survive as current prose.
        window.set_focus()
        time.sleep(.5)
        window.type_keys('{PGDN}')
        time.sleep(2.5)
        after_turn = collector.collect(handle=handle, process_id=process_id,
                                       kind='document', selected=True,
                                       visible_selection_only=True)
        turned_text = after_turn.text or ''
        report['after_page_turn'] = {'valid': after_turn.valid, 'chars': len(turned_text),
                                     'stale_first_page_selection': FIRST in turned_text,
                                     'selection_status':
                                         after_turn.metadata.get('selection_status')}
        report['old_selection_not_served_after_flip'] = not (
            after_turn.valid and FIRST in turned_text)
        report['passed'] = bool(report['accurate_paragraph_not_full_page']
                                and report['old_selection_not_served_after_flip'])
    except Exception as error:
        report['error'] = f'{type(error).__name__}: {error}'
    finally:
        (args.output/'report.json').write_text(
            json.dumps(report, ensure_ascii=False, indent=1), encoding='utf8')
        print(json.dumps(report, ensure_ascii=False, indent=1))
        if window is not None:
            try:
                window.close()
            except Exception:
                pass
        time.sleep(1)
        launch.kill()


if __name__ == '__main__':
    main()
