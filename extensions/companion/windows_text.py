"""Read explicitly selected Windows documents through the existing UIA adapter."""
import argparse
from dataclasses import asdict
import json
import os
import re
from pathlib import Path
from urllib.parse import unquote, urlparse
from .contracts import ObservationBundle
from extensions.desktop.control.uia import WindowsController


class WindowsTextCollector:
    def __init__(self, controller=None, *, max_chars=12000):
        self.controller = controller or WindowsController()
        if type(max_chars) is not int or not 256 <= max_chars <= 50000:
            raise ValueError('invalid text budget')
        self.max_chars = max_chars

    def window_title(self, *, handle, process_id):
        """Revalidate the same native window and read its current page title."""
        return self.controller._window(handle, process_id).window_text()

    def reader_context(self, *, handle, process_id, window=None):
        """Read an Edge PDF page selector, never infer a page from prose."""
        window = window if window is not None else self.controller._window(handle, process_id)
        if not window.is_visible() or window.is_minimized():
            return None
        selectors = [entry for entry in window.descendants(control_type='Edit')
                     if entry.is_visible() and entry.element_info.automation_id == 'pageselector']
        if len(selectors) != 1:
            return None
        entry = selectors[0]
        value = entry.get_value()
        if not isinstance(value, str) or re.fullmatch(r'[1-9][0-9]{0,5}', value) is None:
            return None
        # Require the control to belong to a PDF document, not another edit
        # with a numeric value or a page selector in an inactive document.
        parent = entry
        document = None
        for _ in range(12):
            parent = parent.parent()
            if parent is None:
                break
            if (parent.element_info.control_type == 'Document'
                    and parent.is_visible() and parent.window_text().lower().endswith('.pdf')):
                document = parent.window_text()
                break
        title = window.window_text()
        if document is None or not (title == document or title.startswith(document + ' ')):
            return None
        return {'kind': 'pdf', 'document': document, 'page': int(value),
                'page_source': 'edge-uia-pageselector',
                **self._document_identity(window)}

    @staticmethod
    def _document_identity(window):
        """Use an exposed Edge file URL when available; never infer a path."""
        candidates = []
        try:
            candidates = [entry for entry in window.descendants(control_type='Edit')
                          if entry.is_visible()
                          and WindowsTextCollector._native_address(entry)]
        except Exception:
            return {'document_identity': 'unknown'}
        if len(candidates) != 1:
            return {'document_identity': 'unknown'}
        try:
            address = candidates[0].get_value()
        except Exception:
            return {'document_identity': 'unknown'}
        if not isinstance(address, str):
            return {'document_identity': 'unknown'}
        if address.lower().startswith('file:'):
            parsed = urlparse(address)
            if parsed.scheme.lower() != 'file' or parsed.query:
                return {'document_identity': 'unknown'}
            raw = unquote(parsed.path)
            # Network files require separate access; do not resolve UNC here.
            if parsed.netloc and parsed.netloc.lower() != 'localhost':
                return {'document_identity': 'unknown'}
            if re.fullmatch(r'/[A-Za-z]:/.*', raw):
                raw = raw[1:]
        elif re.fullmatch(r'[A-Za-z]:[\\/].*', address):
            # Edge exposes local paths without the file scheme in its toolbar.
            raw = address
        else:
            return {'document_identity': 'unknown'}
        if '\x00' in raw:
            return {'document_identity': 'unknown'}
        try:
            path = Path(raw).resolve(strict=False)
        except (OSError, ValueError):
            return {'document_identity': 'unknown'}
        if path.suffix.lower() != '.pdf' or not path.is_absolute():
            return {'document_identity': 'unknown'}
        return {'document_identity': 'file-url', 'document_path': str(path)}

    def reader_region(self, *, handle, process_id):
        window = self.controller._window(handle, process_id)
        documents = [entry for entry in window.descendants(control_type='Document')
                     if entry.is_visible() and entry.window_text() == 'PDF Document'
                     and entry.element_info.automation_id == 'RootWebArea']
        if len(documents) != 1:
            return None
        outer, inner = window.rectangle(), documents[0].rectangle()
        if os.name == 'nt':
            import ctypes
            from ctypes.wintypes import RECT
            visible = RECT()
            result = ctypes.windll.dwmapi.DwmGetWindowAttribute(
                ctypes.c_void_p(handle), 9, ctypes.byref(visible), ctypes.sizeof(visible))
            if result == 0:
                outer = visible
        values = [outer.left, outer.top, outer.right, outer.bottom,
                  inner.left, inner.top, inner.right, inner.bottom]
        if any(type(value) is not int for value in values):
            return None
        left, top = max(outer.left, inner.left), max(outer.top, inner.top)
        right, bottom = min(outer.right, inner.right), min(outer.bottom, inner.bottom)
        if right <= left or bottom <= top:
            return None
        return {'window_size': [outer.right-outer.left, outer.bottom-outer.top],
                'bounds': [left-outer.left, top-outer.top, right-outer.left, bottom-outer.top]}

    @staticmethod
    def _native_address(entry):
        # Dynamic view_* IDs are not stable. Require a native toolbar ancestor
        # outside every page Document; a page's own input cannot supply identity.
        parent = entry
        toolbar = False
        for _ in range(12):
            parent = parent.parent()
            if parent is None:
                return toolbar
            kind = parent.element_info.control_type
            if kind == 'Document':
                return False
            toolbar = toolbar or kind == 'ToolBar'
            if kind == 'Window':
                return toolbar
        return False

    @staticmethod
    def _active_document(window, documents, title):
        if len(documents) == 1:
            return documents[0]
        # Chromium can expose background Documents as visible. Require both
        # the selected native tab and native window title to identify one page.
        try:
            tabs = [tab for tab in window.descendants(control_type='TabItem')
                    if tab.is_visible() and tab.iface_selection_item.CurrentIsSelected]
            if len(tabs) != 1:
                return None
            tab_title = tabs[0].window_text()
            matches = []
            for document in documents:
                name = document.window_text()
                if (name and (title == name or title.startswith(name + ' '))
                        and (tab_title == name or tab_title.startswith(name + ' - '))):
                    matches.append(document)
            return matches[0] if len(matches) == 1 else None
        except Exception:
            return None

    def collect(self, *, handle, process_id, kind='web', selected=False, visible_selection_only=False):
        if type(handle) is not int or handle <= 0 or type(process_id) is not int or process_id <= 0:
            raise ValueError('positive window handle and process id required')
        if kind not in ('web', 'ebook', 'document') or type(selected) is not bool or type(visible_selection_only) is not bool:
            raise ValueError('invalid content kind or selection mode')
        if process_id == os.getpid():
            raise ValueError('companion cannot observe its own window')
        target = f'window:{handle}:pid:{process_id}'
        window = self.controller._window(handle, process_id)
        if not window.is_visible() or window.is_minimized():
            return ObservationBundle.now(source='windows-uia', target=target, valid=False,
                                         metadata={'reason': 'window is not visible'})
        title = window.window_text()
        documents = [c for c in window.descendants(control_type='Document') if c.is_visible()]
        reader = self.reader_context(handle=handle, process_id=process_id, window=window)
        edge_pdf = ('Microsoft Edge' in title and (
            re.search(r'\.pdf(?:\s|$)', title, re.IGNORECASE) is not None or any(
                item.window_text().lower().endswith('.pdf')
                and title.startswith(item.window_text() + ' ') for item in documents)))
        if edge_pdf and reader is None:
            return ObservationBundle.now(source='windows-uia', target=target, valid=False,
                metadata={'reason': 'PDF reader is not ready', 'text_role': 'reader-navigation'})
        if reader is not None and not selected:
            pdf_documents = [item for item in documents if item.window_text() == reader['document']]
            if len(pdf_documents) == 1:
                parts, remaining = [], self.max_chars
                for entry in pdf_documents[0].descendants(control_type='Text'):
                    if not entry.is_visible():
                        continue
                    value = entry.window_text().strip()
                    if value:
                        parts.append(value[:remaining])
                        remaining -= len(value) + 1
                    if remaining <= 0:
                        break
                text = '\n'.join(parts)[:self.max_chars]
                if text:
                    current = self.controller._window(handle, process_id)
                    if (current.window_text() != title
                            or self.reader_context(handle=handle, process_id=process_id) != reader):
                        return ObservationBundle.now(source='windows-uia', target=target, valid=False,
                            metadata={'reason': 'window page changed during text collection'})
                    return ObservationBundle.now(source=f'{kind}-visible', target=target,
                        valid=True, text=text, metadata={'title': title, 'collector': 'windows-uia',
                            'selected': False, 'text_role': 'content', 'reader_context': reader,
                            'text_source': 'pdf-visible-uia', 'truncated': remaining <= 0})
            # A PDF without accessible prose may be a scan. Let the learning
            # collector use the bound page image/OCR, never generic toolbar text.
            return ObservationBundle.now(source='windows-uia', target=target, valid=False,
                metadata={'reason': 'PDF visible text is unavailable', 'reader_context': reader})
        document = self._active_document(window, documents, title)
        if document is None:
            return ObservationBundle.now(source='windows-uia', target=target, valid=False,
                                         metadata={'reason': 'document is missing or ambiguous'})
        try:
            pattern = document.iface_text
            ranges = pattern.GetSelection() if selected else pattern.GetVisibleRanges()
            bounded = [ranges.GetElement(index) for index in range(min(ranges.Length, 100))]
            if selected and visible_selection_only:
                visible = pattern.GetVisibleRanges()
                intersections = []
                for selection in bounded:
                    for index in range(min(visible.Length, 100)):
                        current = visible.GetElement(index)
                        clipped = selection.Clone()
                        # UIA TextPatternRange endpoints: Start=0, End=1.
                        if clipped.CompareEndpoints(0, current, 0) < 0:
                            clipped.MoveEndpointByRange(0, current, 0)
                        if clipped.CompareEndpoints(1, current, 1) > 0:
                            clipped.MoveEndpointByRange(1, current, 1)
                        if clipped.CompareEndpoints(0, clipped, 1) < 0:
                            intersections.append(clipped)
                bounded = intersections
            parts = []
            remaining = self.max_chars
            for current in bounded:
                text = current.GetText(remaining)
                if text and text.strip():
                    parts.append(text.strip())
                    remaining -= len(text)
                if remaining <= 0:
                    break
            text = '\n'.join(parts)[:self.max_chars]
        except (AttributeError, NotImplementedError):
            return ObservationBundle.now(source='windows-uia', target=target, valid=False,
                                         metadata={'reason': 'visible text pattern is unavailable'})
        # Re-check the original native identity after the potentially slow COM read.
        current = self.controller._window(handle, process_id)
        if current.window_text() != title:
            return ObservationBundle.now(source='windows-uia', target=target, valid=False,
                metadata={'reason':'window page changed during text collection'})
        if len(documents) > 1:
            current_documents = [c for c in current.descendants(control_type='Document') if c.is_visible()]
            active = self._active_document(current, current_documents, title)
            if active is None or active.element_info != document.element_info:
                return ObservationBundle.now(source='windows-uia', target=target, valid=False,
                    metadata={'reason':'window page changed during text collection'})
        # WeRead renders the body separately; UIA ranges currently expose only
        # chrome/anchors. Never label those ranges as the book's visible prose.
        reader_navigation = document.window_text().endswith(' - 微信读书')
        if reader_navigation:
            text = '\n'.join(line.strip() for line in text.replace('\ufffc', '').splitlines()
                             if line.strip())
        return ObservationBundle.now(source=f'{kind}-selection' if selected else f'{kind}-visible',
            target=target, valid=bool(text), text=text,
            metadata={'title': title, 'collector': 'windows-uia',
                      'selected': selected, 'visible_selection_only':visible_selection_only,
                      'text_role': 'reader-navigation' if reader_navigation else 'content',
                      'truncated': remaining <= 0})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--handle', type=int, required=True)
    parser.add_argument('--process-id', type=int, required=True)
    parser.add_argument('--kind', choices=('web', 'ebook', 'document'), default='web')
    parser.add_argument('--selected', action='store_true')
    args = parser.parse_args()
    bundle = WindowsTextCollector().collect(handle=args.handle, process_id=args.process_id,
                                            kind=args.kind, selected=args.selected)
    value = asdict(bundle)
    value['observed_at'] = bundle.observed_at.isoformat()
    print(json.dumps(value, ensure_ascii=False))


if __name__ == '__main__':
    main()
