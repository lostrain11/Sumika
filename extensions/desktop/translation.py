"""OCR + explicit translator provider. No browser tabs, routing or paid fallback."""
from extensions.desktop.ocr.ocr import recognize


def translate_image(image, *, translate, target_language='zh-CN', ocr_provider='auto', enabled=True):
    if not enabled:return {'disabled':True}
    if not callable(translate):raise ValueError('translator provider required')
    result=recognize(image,provider=ocr_provider)
    original=result['text']
    translated=translate(original,target_language) if original.strip() else ''
    if not isinstance(translated,str):raise ValueError('translator must return text')
    return dict(original_text=original,translated_text=translated,target_language=target_language,ocr_provider=result['provider'])
