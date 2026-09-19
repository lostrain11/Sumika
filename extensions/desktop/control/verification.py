"""Post-action OCR verification; uncertainty fails closed."""
from extensions.desktop.ocr.ocr import recognize

def verify_text(image, expected, *, provider='auto', language='eng', min_similarity=1.0, enabled=True):
    if not enabled:return {'disabled':True}
    if not isinstance(expected,str) or not expected.strip():raise ValueError('expected text required')
    if not isinstance(min_similarity,(int,float)) or not 0<=min_similarity<=1:raise ValueError('invalid similarity')
    result=recognize(image,provider=provider,language=language)
    actual=result.get('text','')
    # Substring is intentional: OCR often includes surrounding UI labels.
    matched=expected.casefold() in actual.casefold()
    score=1.0 if matched else 0.0
    return {'status':'verified' if matched and score>=min_similarity else 'unknown','matched':matched,'score':score,'provider':result['provider'],'boundary':'OCR evidence only; does not authorize or prove semantic success'}
