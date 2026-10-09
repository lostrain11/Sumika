"""Combine existing authorized window text and WGC adapters for learning."""
from dataclasses import replace
from pathlib import Path
import re

from .windows_visual import WindowsVisualCollector
from .windows_text import WindowsTextCollector
from .windows_ocr import WindowsOCR


class WindowsLearningCollector:
    def __init__(self, *, approved=False, visual=None, text=None, ocr=None, expected_document=None):
        if approved is not True:
            raise PermissionError('explicit window capture consent required')
        self.expected_document = self.validate_expected_document(expected_document)
        self.visual = visual if visual is not None else WindowsVisualCollector(approved=True)
        self.text = text if text is not None else WindowsTextCollector()
        self.ocr = ocr if ocr is not None else WindowsOCR()
        self._ocr_scope = None

    def start(self):
        self.visual.start()

    def stop(self):
        self._ocr_scope = None
        try:
            self.visual.stop()
        finally:
            self.ocr.stop()

    def _clear_ocr(self):
        if self._ocr_scope is not None:
            self.ocr.stop()
        self._ocr_scope = None

    def _read_ocr(self, visual):
        # WindowsOCR already reuses exact encoded/RGB pixels. Scope that cache
        # to the current target/page/viewport; never create a second cache.
        import copy
        scope = (visual.target, visual.metadata.get('reader_context'),
                 visual.metadata.get('image_region'))
        if scope != self._ocr_scope:
            self._clear_ocr()
            self._ocr_scope = copy.deepcopy(scope)
        return self.ocr(visual.image)

    @staticmethod
    def validate_expected_document(value):
        if value is None:
            return None
        if not isinstance(value, (str, Path)) or not str(value).strip():
            raise ValueError('absolute expected PDF path required')
        path = Path(value)
        if not path.is_absolute() or path.suffix.lower() != '.pdf':
            raise ValueError('absolute expected PDF path required')
        return str(path.resolve())

    def __call__(self, target, *, expected_document=None):
        expected_document = self.validate_expected_document(expected_document)
        if self.expected_document is not None:
            if expected_document is not None and expected_document != self.expected_document:
                raise ValueError('cannot override bound PDF document')
            expected_document = self.expected_document
        match = re.fullmatch(r'window:([1-9][0-9]*):pid:([1-9][0-9]*)', target)
        if match is None:
            raise ValueError('exact window HWND/PID target required')
        handle, pid = map(int, match.groups())
        text = None
        identity_changed = False
        title_before = None
        reader_before = None
        region_before = None
        try:
            reader_before = self.text.reader_context(handle=handle, process_id=pid)
            if isinstance(reader_before, dict):
                region_before = self.text.reader_region(handle=handle, process_id=pid)
        except ValueError:
            identity_changed = True
        except Exception:
            pass
        try:
            title_before = self.text.window_title(handle=handle, process_id=pid)
            text = self.text.collect(handle=handle, process_id=pid, kind='document', selected=True,
                                     visible_selection_only=True)
            if text.metadata.get('reason') == 'window page changed during text collection':
                identity_changed = True
            elif not text.valid or not text.text.strip():
                text = self.text.collect(handle=handle, process_id=pid, kind='document', selected=False)
            if text.metadata.get('reason') == 'window page changed during text collection':
                identity_changed = True
        except ValueError:
            identity_changed = True
        except Exception:
            # Unsupported UIA text must not disable valid authorized visuals.
            # The visual adapter independently revalidates HWND/PID ownership.
            text = None
        try:
            visual = self.visual(target)
        except Exception:
            self._clear_ocr()
            raise
        if text is not None and text.metadata.get('reason') == 'PDF reader is not ready':
            self._clear_ocr()
            return replace(visual, valid=False, text='', image=None,
                metadata=dict(visual.metadata, reason='PDF reader is not ready',
                              text_status='reader_not_ready'))
        try:
            title_after = self.text.window_title(handle=handle, process_id=pid)
        except ValueError:
            identity_changed = True
            title_after = None
        except Exception:
            title_after = None
        if isinstance(title_before, str) and isinstance(title_after, str) and title_before != title_after:
            identity_changed = True
        if identity_changed or (text is not None and text.target != target):
            self._clear_ocr()
            return replace(visual, valid=False, text='', image=None,
                           metadata=dict(visual.metadata, reason='window page or text identity changed'))
        if not visual.valid:
            self._clear_ocr()
            return visual
        reader_metadata = {}
        if isinstance(reader_before, dict):
            reader_metadata = {'reader_context': reader_before,
                'page': reader_before['page'], 'media_identity': reader_before}
            if expected_document is not None:
                expected = str(Path(expected_document).resolve())
                actual = reader_before.get('document_path')
                if actual is not None and Path(actual) != Path(expected):
                    self._clear_ocr()
                    return replace(visual, valid=False, text='', image=None,
                        metadata=dict(visual.metadata, reason='PDF document identity changed',
                                      expected_document=expected, actual_document=actual))
                reader_metadata['document_identity_verified'] = (
                    actual is not None and Path(actual) == Path(expected))
            visual = replace(visual, metadata=dict(visual.metadata, **reader_metadata))
            try:
                region_after = self.text.reader_region(handle=handle, process_id=pid)
                if isinstance(region_before, dict) and region_before == region_after:
                    visual = self._crop_reader(visual, region_before)
            except Exception:
                pass

        def verified(result):
            if not isinstance(reader_before, dict):
                return result
            try:
                current = self.text.reader_context(handle=handle, process_id=pid)
            except Exception:
                current = None
            if current != reader_before:
                self._clear_ocr()
                return replace(result, valid=False, text='', image=None,
                    metadata=dict(result.metadata, reason='PDF page changed during collection'))
            return result
        if (visual.image and (text is None or not text.valid or not text.text.strip()
                              or text.metadata.get('text_role') == 'reader-navigation')):
            try:
                derived = self._read_ocr(visual)
            except Exception:
                self._clear_ocr()
                derived = {'status':'unavailable','text':''}
            if derived['text']:
                return verified(replace(visual,text=derived['text'][:12000],metadata=dict(visual.metadata,
                    text_source='windows-ocr',text_status='ocr_available',
                    ocr_regions=derived['regions'],ocr_truncated=derived['truncated'],
                    reader_navigation=text.text[:1000] if text is not None and text.valid else '',
                    text_metadata=dict(text.metadata) if text is not None else {})))
            visual = replace(visual,metadata=dict(visual.metadata,ocr_status=derived['status']))
        else:
            self._clear_ocr()
        if text is None or not text.valid or not text.text.strip():
            return verified(replace(visual, metadata=dict(visual.metadata, text_status='unavailable')))
        return verified(replace(visual, text=text.text[:12000], metadata=dict(visual.metadata,
            text_source=text.source, text_observed_at=text.observed_at.isoformat(),
            text_metadata=dict(text.metadata), text_status=(
                'navigation_only' if text.metadata.get('text_role') == 'reader-navigation'
                else 'available'))))

    @staticmethod
    def _crop_reader(visual, region):
        import base64
        import io
        from PIL import Image
        width, height = region['window_size']
        if (not visual.image or width <= 0 or height <= 0
                or width != visual.metadata.get('width')
                or height != visual.metadata.get('height')):
            return visual
        bounds = region['bounds']
        with Image.open(io.BytesIO(base64.b64decode(visual.image['data_base64'], validate=True))) as source:
            box = (round(bounds[0]*source.width/width), round(bounds[1]*source.height/height),
                   round(bounds[2]*source.width/width), round(bounds[3]*source.height/height))
            if not (0 <= box[0] < box[2] <= source.width and 0 <= box[1] < box[3] <= source.height):
                return visual
            with source.crop(box) as cropped:
                buffer = io.BytesIO()
                cropped.save(buffer, format='JPEG', quality=85)
        return replace(visual, image={'media_type':'image/jpeg',
            'data_base64':base64.b64encode(buffer.getvalue()).decode('ascii')},
            metadata=dict(visual.metadata, image_region={
                'kind':'pdf-viewport', 'window_size':[width,height], 'bounds':bounds,
                'coordinate_space':'window-pixels', 'ocr_coordinate_space':'cropped-image-normalized'}))
