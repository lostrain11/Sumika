"""Bounded PDF page context for the companion learning contract.

The adapter never guesses a page from a window title or from OCR. Callers must
bind an absolute PDF file and the currently visible one-based page explicitly.
"""
from pathlib import Path
import re

if __package__ in (None, ''):
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from extensions.companion.contracts import ObservationBundle


def extract_page_text(pdf_path, page_number, *, max_chars=12000):
    """Extract only one page from a text PDF; return empty text for scans."""
    path = Path(pdf_path)
    if not path.is_absolute():
        raise ValueError('absolute PDF file required')
    path = path.resolve(strict=True)
    if path.suffix.lower() != '.pdf':
        raise ValueError('PDF file required')
    if type(page_number) is not int or page_number < 1:
        raise ValueError('one-based PDF page required')
    if type(max_chars) is not int or not 100 <= max_chars <= 12000:
        raise ValueError('invalid PDF text budget')
    from pypdf import PdfReader
    reader = PdfReader(str(path), strict=False)
    if page_number > len(reader.pages):
        raise ValueError('PDF page outside document')
    page = reader.pages[page_number - 1]
    raw = page.extract_text() or ''
    text = re.sub(r'\s+', ' ', raw).strip()[:max_chars]
    return {'text': text, 'page': page_number, 'pages': len(reader.pages),
            'file': str(path), 'text_available': bool(text),
            'truncated': len(raw) > max_chars}


def page_observation(*, pdf_path, page_number, target, image=None,
                     selected_text='', title=None, max_chars=12000):
    """Build a page-bound observation without using unseen pages."""
    extracted = extract_page_text(pdf_path, page_number, max_chars=max_chars)
    selected = re.sub(r'\s+', ' ', selected_text).strip() if isinstance(selected_text, str) else ''
    text = (selected or extracted['text'])[:max_chars]
    metadata = {'file': extracted['file'], 'page': page_number,
                'page_count': extracted['pages'], 'text_source':
                'pdf-page-text' if extracted['text_available'] else 'visual-ocr-required',
                'text_available': bool(text),
                'selected': bool(selected), 'truncated': len(selected) > max_chars if selected else extracted['truncated']}
    if selected:
        metadata['text_source'] = 'pdf-selection'
    if title:
        metadata['title'] = str(title)[:512]
    return ObservationBundle.now(source='pdf-page', target=target, valid=bool(text or image),
        text=text, image=image, metadata=metadata)


def main():
    """Explicit page adapter for the existing isolated collection endpoint."""
    import argparse
    from dataclasses import asdict
    import json
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pdf', required=True)
    parser.add_argument('--page', required=True, type=int)
    args = parser.parse_args()
    path = Path(args.pdf)
    bundle = page_observation(pdf_path=path, page_number=args.page,
                              target='pdf:' + str(path.resolve()))
    value = asdict(bundle)
    value['observed_at'] = bundle.observed_at.isoformat()
    print(json.dumps(value, ensure_ascii=False))


if __name__ == '__main__':
    main()
