"""Orchestrate an authorized UIA action and optional OCR post-check."""
from pathlib import Path
from .verification import verify_text

def execute(controller, *, handle, process_id, action, approved, expected_snapshot_hash=None,
            automation_id=None, control_type=None, text=None, keys=None,
            verification_image=None, expected_text=None, ocr_provider='auto', language='eng',
            capture_verification=None):
    """Capture callbacks are trusted host functions, separately authorized by it.

    Static images are allowed as lexical evidence, never as proof of a fresh
    post-action state. No capture is initiated unless the host supplies a callback.
    """
    if approved is not True:
        raise PermissionError('native approval required for desktop mutation')
    if type(handle) is not int or handle <= 0 or type(process_id) is not int or process_id <= 0:
        raise ValueError('positive numeric handle and process id required')
    if action not in ('set_text', 'invoke', 'focus', 'minimize', 'maximize', 'restore', 'hotkey'):
        raise ValueError('unsupported desktop action')
    if action == 'set_text' and not isinstance(text, str):
        raise ValueError('text required')
    if action == 'hotkey' and (not isinstance(keys, list) or not keys
                              or any(not isinstance(key, str) or not key for key in keys)):
        raise ValueError('key list required')
    for name, value in (('automation_id', automation_id), ('control_type', control_type),
                        ('expected_snapshot_hash', expected_snapshot_hash)):
        if value is not None and (not isinstance(value, str) or not value):
            raise ValueError(f'nonempty {name} required')
    if capture_verification is not None and not callable(capture_verification):
        raise ValueError('capture callback must be callable')
    if expected_text is None and (verification_image is not None or capture_verification is not None):
        raise ValueError('expected text required for verification')
    if expected_text is not None:
        if not isinstance(expected_text, str) or not expected_text.strip():
            raise ValueError('expected text required')
        if verification_image is None and capture_verification is None:
            raise ValueError('verification image required or provide an authorized capture callback')
        if verification_image is not None and capture_verification is not None:
            raise ValueError('choose static image or capture callback')
        if verification_image is not None and not Path(verification_image).is_file():
            raise ValueError('verification image must be an existing file')
        if ocr_provider not in ('auto', 'rapidocr', 'rapidocr_json', 'tesseract', 'windows'):
            raise ValueError('unsupported OCR provider')
        if not isinstance(language, str) or not language.strip():
            raise ValueError('OCR language required')
    result = controller.act(handle, process_id, action, approved=approved,
                            expected_snapshot_hash=expected_snapshot_hash,
                            automation_id=automation_id, control_type=control_type,
                            text=text, keys=keys)
    if expected_text is None or result.get('status') != 'performed':
        return result
    result = dict(result)
    try:
        if capture_verification is not None:
            verification_image = capture_verification(handle=handle, process_id=process_id)
        check = verify_text(verification_image, expected_text, provider=ocr_provider, language=language)
        check['freshness'] = 'host_capture_after_action' if capture_verification is not None else 'not_established'
    except Exception as error:
        check = {'status': 'unknown', 'error_type': type(error).__name__,
                 'boundary': 'Action already executed; capture/OCR failed; do not retry automatically'}
    result['post_verification']=check
    if check.get('status') != 'verified' or check.get('freshness') != 'host_capture_after_action':
        result['status'] = 'unknown'
        result['action_executed'] = True
        result['retry_allowed'] = False
        result['boundary'] = 'UIA action executed; fresh expected visible text not proven; do not retry automatically'
    return result
