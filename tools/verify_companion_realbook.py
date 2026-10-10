"""Real-book PDF acceptance: page-tracked flips over a user-supplied book.

Delivery package P4 extension. Unlike the generated-fixture verifier, a real
book has no lesson markers, so the invariants are structural: the reader's
own page selector increments, the visible content fingerprint changes on
every flip, the absolute document identity stays bound, and jump-backs
reverse all of it. Only page numbers and content hashes are recorded — no
book text is persisted, and no model or memory writes occur.

``--expect-weak`` declares an image-only or hand-drawn book whose pages have
no usable text layer: the strong viewport-vs-text-layer cross-check is then
honestly unavailable, and acceptance rests on the selector, identity and
fingerprint evidence alone, recorded as ``content_verification:
weak-declared``.
"""
import argparse
import base64
import hashlib
import json
import io
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tools'))

from verify_companion_pdf import continuous_binding, owned_profile_window
from extensions.companion.windows_learning import WindowsLearningCollector


class PageTextIndex:
    """Canonical per-page text from the PDF's own text layer (pypdf).

    The rendered page number and print quality are irrelevant here: what is
    verified is that the viewport really shows page N's content. Pages
    without a usable text layer (scans, image covers) honestly downgrade to
    the weak fingerprint-only check instead of pretending to verify.
    """

    def __init__(self, pdf_path):
        from pypdf import PdfReader
        self._reader = PdfReader(str(pdf_path))
        self._cache = {}

    @staticmethod
    def _normalize(text):
        return ''.join(str(text or '').split())

    @staticmethod
    def _grams(text, size=8):
        return {text[i:i+size] for i in range(0, max(0, len(text) - size + 1))}

    def page_text(self, page):
        if page not in self._cache:
            try:
                self._cache[page] = self._normalize(
                    self._reader.pages[page - 1].extract_text() or '')
            except Exception:
                self._cache[page] = ''
        return self._cache[page]

    def verify(self, page, visible_text):
        """Return (mode, ratio): strong/weak/none plus the matched ratio."""
        canonical = self.page_text(page)
        visible = self._normalize(visible_text or '')
        if len(canonical) < 32:
            return ('none', 0.0)
        if not visible:
            return ('weak', 0.0)
        page_grams = self._grams(canonical)
        visible_grams = self._grams(visible)
        matched = len(page_grams & visible_grams)
        ratio = matched / max(1, len(page_grams))
        return ('strong', round(ratio, 3))


def evaluate_gate(report, *, flips_requested, expect_weak=False):
    """Structural invariants always apply; only the text-layer check differs.

    Default acceptance needs a clear majority of strong page verifications.
    ``expect_weak`` honestly declares that the strong check is unavailable
    (image-only or hand-drawn book) and accepts on selector, identity and
    fingerprint evidence alone.
    """
    structural = (report.get('flips_ok') == flips_requested
                  and report.get('jump_back', {}).get('page_matches', False)
                  and report.get('absolute_document_identity', False))
    report['content_verification'] = 'weak-declared' if expect_weak else 'strong-majority'
    report['passed'] = bool(structural and
                            (expect_weak or
                             report.get('strong_page_verifications', 0) * 2 >= flips_requested))
    return report['passed']


def fingerprint(bundle):
    text_hash = hashlib.sha256((bundle.text or '').encode('utf8')).hexdigest()[:16]
    image_hash = ''
    if bundle.image:
        image_hash = hashlib.sha256(
            base64.b64decode(bundle.image['data_base64'])).hexdigest()[:16]
    return {'text_sha': text_hash, 'image_sha': image_hash,
            'page': bundle.metadata.get('reader_context', {}).get('page'),
            'document': bundle.metadata.get('reader_context', {}).get('document_path', '')}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pdf', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--flips', type=int, default=22)
    parser.add_argument('--allow-desktop-input', action='store_true',
                        help='Explicitly permit owned Edge focus and keyboard navigation')
    parser.add_argument('--min-page-overlap', type=float, default=0.2,
                        help='Minimum canonical-page n-gram overlap for the strong check')
    parser.add_argument('--expect-weak', action='store_true',
                        help='Declare an image-only/hand-drawn book: accept on '
                             'selector/identity/fingerprint evidence, no text-layer cross-check')
    args = parser.parse_args()
    if not args.allow_desktop_input:
        parser.error('real-book acceptance drives a focused Edge window; pass --allow-desktop-input')
    from pywinauto import Desktop
    args.output.mkdir(parents=True, exist_ok=False)
    pdf = args.pdf.resolve(strict=True)

    before = {w.handle for w in Desktop(backend='uia').windows()}
    process = subprocess.Popen(['C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
        '--user-data-dir=' + str(args.output/'profile'), '--no-first-run', '--disable-sync',
        '--force-renderer-accessibility', pdf.as_uri()],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    window = None
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        matches = [w for w in Desktop(backend='uia').windows()
                   if w.handle not in before and pdf.name in w.window_text()
                   and owned_profile_window(w, args.output/'profile')]
        if len(matches) == 1:
            window = matches[0]
            break
        time.sleep(.3)
    if window is None:
        raise RuntimeError('owned PDF reader window did not appear')
    window.set_focus()
    time.sleep(3)
    report = {'passed': False, 'pdf': pdf.name, 'scope':
              'User-supplied real book; only page numbers and content hashes recorded, no book text stored',
              'flips_requested': args.flips, 'flips': []}

    collector = WindowsLearningCollector(approved=True)
    target = f'window:{window.handle}:pid:{window.process_id()}'
    first = collector(target)
    if not first.valid:
        raise RuntimeError('first capture invalid')
    page_index = PageTextIndex(pdf)
    previous = fingerprint(first)
    report['absolute_document_identity'] = (previous['document'] == str(pdf))
    if not report['absolute_document_identity']:
        raise RuntimeError('document identity not bound to the supplied file: ' + str(previous['document']))

    lifecycle = continuous_binding(window, pdf)
    report['continuous_worker'] = lifecycle

    page_box = None
    for entry in window.descendants(control_type='Edit'):
        if entry.is_visible() and (entry.get_value() or '').strip().isdigit():
            page_box = entry
            break

    current_page = previous['page']
    flips_ok = 0
    for index in range(args.flips):
        next_page = (current_page or index + 1) + 1
        if page_box is not None:
            page_box.set_edit_text(str(next_page))
            page_box.type_keys('{ENTER}')
        else:
            from pywinauto import keyboard
            window.set_focus()
            keyboard.send_keys('{PGDN}')
        deadline = time.monotonic() + 12
        bundle = None
        while time.monotonic() < deadline:
            bundle = collector(target)
            if bundle.valid and fingerprint(bundle)['page'] == next_page:
                break
            time.sleep(.3)
        if bundle is None or not bundle.valid:
            record = {'flip': index + 1, 'ok': False, 'reason': 'capture invalid'}
            report['flips'].append(record)
            break
        current = fingerprint(bundle)
        page_ok = current['page'] == next_page
        moved = (current['text_sha'] != previous['text_sha']
                 or current['image_sha'] != previous['image_sha'])
        identity_ok = current['document'] == str(pdf)
        # Cross-check the viewport against the PDF's own text layer for page N:
        # proves the rendered content IS page N, independent of any printed
        # page number or its print quality.
        mode, ratio = ('none', 0.0)
        if current['page']:
            mode, ratio = page_index.verify(current['page'], bundle.text)
        content_ok = (moved and identity_ok and page_ok
                      and (mode != 'strong' or ratio >= args.min_page_overlap))
        record = {'flip': index + 1, 'ok': bool(content_ok),
                  'page': current['page'], 'page_matches_selector': page_ok,
                  'content_changed': moved, 'identity_stable': identity_ok,
                  'page_text_check': mode, 'page_text_overlap': ratio,
                  'text_sha': current['text_sha'], 'image_sha': current['image_sha']}
        report['flips'].append(record)
        if record['ok']:
            flips_ok += 1
        previous = current
        current_page = next_page
    report['flips_ok'] = flips_ok

    # Jump-back: return to an earlier page; page number and content must reverse.
    back_page = max(1, (current_page or 2) - 3)
    if page_box is not None:
        page_box.set_edit_text(str(back_page))
        page_box.type_keys('{ENTER}')
        deadline = time.monotonic() + 12
        bundle = None
        while time.monotonic() < deadline:
            bundle = collector(target)
            if bundle.valid and fingerprint(bundle)['page'] == back_page:
                break
            time.sleep(.3)
        back = fingerprint(bundle)
        mode, ratio = ('none', 0.0)
        if back['page']:
            mode, ratio = page_index.verify(back['page'], bundle.text)
        report['jump_back'] = {'page': back['page'], 'page_matches': back['page'] == back_page,
                               'content_differs': back['text_sha'] != previous['text_sha'],
                               'identity_stable': back['document'] == str(pdf),
                               'page_text_check': mode, 'page_text_overlap': ratio}
        if back['page'] == back_page:
            current_page = back_page

    strong_verified = sum(1 for flip in report['flips']
                          if flip.get('page_text_check') == 'strong'
                          and flip.get('page_text_overlap', 0) >= args.min_page_overlap)
    report['strong_page_verifications'] = strong_verified
    # Real books contain image-only pages (covers, dedications, blanks) with
    # no text layer; --expect-weak additionally declares a book whose pages
    # never yield a text layer at all.
    passed = evaluate_gate(report, flips_requested=args.flips,
                           expect_weak=args.expect_weak)
    window.capture_as_image().save(args.output/'reader-screen.png')
    (args.output/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps({'passed': passed, 'flips_ok': flips_ok,
                      'flips_requested': args.flips,
                      'content_verification': report['content_verification'],
                      'jump_back': report.get('jump_back'),
                      'identity': report['absolute_document_identity']}))
    try:
        process.terminate()
    except Exception:
        pass


if __name__ == '__main__':
    main()
