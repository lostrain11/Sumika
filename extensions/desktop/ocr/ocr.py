"""Harness-neutral OCR boundary with explicit provider selection."""
import argparse
import importlib.util
import json
import shutil
import subprocess
import os
from pathlib import Path


RAPIDOCR_JSON = os.environ.get('SUMIKA_RAPIDOCR_JSON', r'D:\Tools\Umi-OCR\2.1.5\Umi-OCR_Rapid_v2.1.5\UmiOCR-data\plugins\win7_x64_RapidOCR-json\RapidOCR-json.exe')

def providers():
    rapid = RAPIDOCR_JSON if Path(RAPIDOCR_JSON).is_file() else (shutil.which('RapidOCR-json') or None)
    return {
        'tesseract': shutil.which('tesseract'),
        'rapidocr_json': rapid,
        'rapidocr': bool(rapid) or bool(importlib.util.find_spec('rapidocr') or importlib.util.find_spec('rapidocr_onnxruntime')),
    }


def recognize(image, provider='auto', language='eng'):
    image = Path(image).resolve(strict=True)
    if not image.is_file():
        raise ValueError('image must be a regular file')
    available = providers()
    chosen = provider
    if chosen == 'auto':
        chosen = 'tesseract' if available['tesseract'] else ('rapidocr_json' if available['rapidocr_json'] else ('rapidocr' if available['rapidocr'] else None))
    if chosen == 'tesseract' and available['tesseract']:
        result = subprocess.run([available['tesseract'], str(image), 'stdout', '-l', language],
                                capture_output=True, text=True, encoding='utf-8', timeout=60)
        if result.returncode:
            raise RuntimeError(result.stderr.strip() or 'tesseract failed')
        return {'provider': 'tesseract', 'text': result.stdout, 'needs_translation': True}
    if chosen == 'rapidocr_json' and available['rapidocr_json']:
        models = str(Path(available['rapidocr_json']).parent / 'models')
        result = subprocess.run([available['rapidocr_json'], '--models', models, '--det', 'ch_PP-OCRv4_det_infer.onnx', '--cls', 'ch_ppocr_mobile_v2.0_cls_infer.onnx', '--rec', 'rec_ch_PP-OCRv4_infer.onnx', '--keys', 'ppocr_keys_v1.txt', '--image_path', str(image), '--ensureLogger', '0'], capture_output=True, text=True, encoding='utf-8', timeout=60)
        if result.returncode:
            raise RuntimeError(result.stderr.strip() or 'RapidOCR-json failed')
        lines = []
        for line in result.stdout.splitlines():
            try:
                item = json.loads(line)
                lines.extend(x.get('text', '') for x in item.get('data', item if isinstance(item, list) else []) if isinstance(x, dict))
            except json.JSONDecodeError:
                continue
        return {'provider': 'rapidocr-json', 'text': '\n'.join(x for x in lines if x), 'needs_translation': True}
    if chosen == 'rapidocr' and available['rapidocr']:
        if importlib.util.find_spec('rapidocr'):
            from rapidocr import RapidOCR
            result = RapidOCR()(str(image))
            result = result.txts if hasattr(result, 'txts') else result
        else:
            from rapidocr_onnxruntime import RapidOCR
            result, _ = RapidOCR()(str(image))
        lines = [item[1] if isinstance(item, (list, tuple)) else str(item) for item in (result or [])]
        return {'provider': 'rapidocr', 'text': '\n'.join(lines), 'needs_translation': True}
    raise RuntimeError('No OCR provider available; install/enable tesseract or rapidocr_onnxruntime')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['status', 'recognize'])
    parser.add_argument('image', nargs='?')
    parser.add_argument('--provider', choices=['auto', 'tesseract', 'rapidocr_json', 'rapidocr'], default='auto')
    parser.add_argument('--language', default='eng')
    args = parser.parse_args()
    try:
        if args.action == 'status':
            print(json.dumps({'providers': providers()}, ensure_ascii=False)); return 0
        if not args.image: raise ValueError('image is required')
        print(json.dumps(recognize(args.image, args.provider, args.language), ensure_ascii=False)); return 0
    except (OSError, ValueError, RuntimeError, ImportError) as error:
        print('ocr: '+str(error)); return 2


if __name__ == '__main__':
    raise SystemExit(main())
