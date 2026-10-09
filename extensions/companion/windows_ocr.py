"""Local text and normalized regions derived from the already-authorized frame."""
import asyncio
import base64
import hashlib
import io
import re


def normalize_text(text):
    # Windows Chinese OCR separates ideographs with spaces. Keep Latin spaces.
    return re.sub(r'(?<=[\u3400-\u9fff])\s+(?=[\u3400-\u9fff])', '', text).strip()


async def _recognize(image):
    from PIL import Image
    from winrt.windows.media.ocr import OcrEngine
    from winrt.windows.globalization import Language
    from winrt.windows.graphics.imaging import SoftwareBitmap, BitmapPixelFormat
    from winrt.windows.storage.streams import DataWriter

    engine = OcrEngine.try_create_from_language(Language('zh-Hans-CN'))
    if engine is None:
        engine = OcrEngine.try_create_from_user_profile_languages()
    if engine is None:
        raise RuntimeError('no installed Windows OCR language')
    with Image.open(io.BytesIO(base64.b64decode(image['data_base64'], validate=True))) as source:
        if source.width * source.height > 4_000_000:
            raise ValueError('OCR image exceeds pixel budget')
        if max(source.size) > OcrEngine.max_image_dimension:
            raise ValueError('OCR image exceeds native dimension limit')
        pixels = source.convert('RGBA')
        writer = DataWriter()
        bitmap = None
        try:
            writer.write_bytes(pixels.tobytes('raw', 'BGRA'))
            bitmap = SoftwareBitmap.create_copy_from_buffer(writer.detach_buffer(),
                BitmapPixelFormat.BGRA8, pixels.width, pixels.height)
            result = await engine.recognize_async(bitmap)
            rows = []
            for line in result.lines[:100]:
                words = [word.bounding_rect for word in line.words]
                if not words:
                    continue
                left, top = min(w.x for w in words), min(w.y for w in words)
                right, bottom = max(w.x+w.width for w in words), max(w.y+w.height for w in words)
                rows.append({'text': line.text, 'region': [round(left/pixels.width,4),
                    round(top/pixels.height,4),round(right/pixels.width,4),round(bottom/pixels.height,4)]})
            return rows
        finally:
            if bitmap is not None:
                bitmap.close()
            writer.close()
            pixels.close()


class WindowsOCR:
    """Single-frame cache keyed by encoded bytes and decoded RGB pixels.

    Encoding metadata may change without changing the visible pixels. Pixel
    equality safely avoids another OCR call; approximate thumbnail equality
    could miss a changed formula symbol and must not authorize reuse.
    """
    def __init__(self, recognizer=None, *, max_chars=12000):
        self._recognizer = recognizer or (lambda image: asyncio.run(_recognize(image)))
        self._max = max_chars
        self._signature = None
        self._fingerprint = None
        self._result = None

    def stop(self):
        self._signature = self._fingerprint = self._result = None

    @staticmethod
    def _make_fingerprint(image):
        try:
            from PIL import Image
            raw = base64.b64decode(image['data_base64'], validate=True)
            with Image.open(io.BytesIO(raw)) as source:
                if source.width * source.height > 4_000_000:
                    return None
                with source.convert('RGB') as pixels:
                    digest = hashlib.sha256()
                    digest.update(str(pixels.size).encode('ascii'))
                    digest.update(pixels.tobytes())
                    return digest.digest()
        except Exception:
            return None

    def __call__(self, image):
        signature = hashlib.sha256(image['data_base64'].encode('ascii')).hexdigest()
        if signature == self._signature:
            return dict(self._result)
        fingerprint = self._make_fingerprint(image)
        if (self._result is not None and fingerprint is not None and
                fingerprint == self._fingerprint):
            self._signature = signature
            return dict(self._result)
        rows = self._recognizer(image)
        regions, parts, used = [], [], 0
        for row in rows[:100]:
            text = normalize_text(row['text'])
            region = row['region']
            if not text:
                continue
            if len(region) != 4 or any(type(v) not in (int,float) or not 0 <= v <= 1 for v in region):
                raise ValueError('invalid OCR region')
            if region[0] >= region[2] or region[1] >= region[3]:
                raise ValueError('empty OCR region')
            prefix = f'[区域 {region}] '
            remaining = self._max-used-len(prefix)-1
            if remaining <= 0:
                break
            bounded = text[:remaining]
            parts.append(prefix+bounded)
            regions.append(region)
            used += len(prefix)+len(bounded)+1
            if bounded != text:
                break
        result = {'text':'\n'.join(parts),'regions':regions,
                  'status':'available' if parts else 'empty',
                  'truncated':len(regions)<len(rows)}
        self._signature, self._fingerprint, self._result = signature, fingerprint, result
        return dict(result)
