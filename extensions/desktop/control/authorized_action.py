"""Orchestrate an authorized UIA action and optional OCR post-check."""
from .verification import verify_text

def execute(controller, *, handle, process_id, action, approved, expected_snapshot_hash=None,
            verification_image=None, expected_text=None, ocr_provider='auto', language='eng'):
    result=controller.act(handle,process_id,action,approved=approved,expected_snapshot_hash=expected_snapshot_hash)
    if expected_text is None:return result
    if verification_image is None:raise ValueError('verification image required')
    check=verify_text(verification_image,expected_text,provider=ocr_provider,language=language)
    result['post_verification']=check
    if check['status']!='verified':
        result['status']='unknown';result['boundary']='UIA action executed, but OCR did not prove expected visible text'
    return result
