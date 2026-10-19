"""Harness-neutral OCR boundary with explicit provider selection.

Recognition returns text lines with box coordinates, confidence and elapsed
time, which real-time subtitle or overlay work needs to place a translation
under the original text. Nothing here captures the screen or calls a model.
"""
import argparse
import importlib.util
import json
import os
import platform
import shutil
import subprocess
import time
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
RAPIDOCR_JSON = os.environ.get(
    "SUMIKA_RAPIDOCR_JSON",
    r"D:\Tools\Umi-OCR\2.1.5\Umi-OCR_Rapid_v2.1.5\UmiOCR-data\plugins\win7_x64_RapidOCR-json\RapidOCR-json.exe")

# Runs inside the extension's isolated interpreter; prints one JSON object.
ENV_SCRIPT = '''
import json, sys, time
try:
    from rapidocr import RapidOCR
except ModuleNotFoundError as error:
    if error.name != 'rapidocr':
        raise
    from rapidocr_onnxruntime import RapidOCR
from extensions.desktop.ocr.ocr import _rapidocr_lines
engine = RapidOCR()
start = time.perf_counter()
result = engine(sys.argv[1], use_det=sys.argv[2] != "0")
elapsed = (time.perf_counter() - start) * 1000
lines = _rapidocr_lines(result)
print(json.dumps({"lines": lines, "elapsed_ms": elapsed}, ensure_ascii=False))
'''


def _has_module(name):
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def _runtime_has(python, name):
    base = Path(python).parent
    if base.name.casefold() in ('scripts', 'bin'):
        base = base.parent
    sites = [base/'Lib/site-packages', *base.glob('lib/python*/site-packages')]
    return any((site.joinpath(*name.split('.'))).is_dir() or (site/(name+'.py')).is_file()
               for site in sites)


def env_python(*, root=None):
    """Interpreter of the isolated OCR environment, if one is installed."""
    root = Path(root) if root is not None else ROOT
    explicit = os.environ.get("SUMIKA_OCR_PYTHON")
    if explicit is not None:
        return str(explicit) if explicit and Path(explicit).is_file() and any(
            _runtime_has(explicit, name) for name in ('rapidocr', 'rapidocr_onnxruntime')) else None
    for candidate in (root / ".sumika-next" / name / "Scripts" / "python.exe"
                      for name in ('ocr-env', 'desktop-env', 'office-env')):
        if candidate.is_file() and any(_runtime_has(candidate, name)
                                       for name in ('rapidocr', 'rapidocr_onnxruntime')):
            return str(candidate)
    return None


def windows_python():
    from extensions.desktop.runtime import capability_python
    if platform.system()!='Windows':
        return None
    selected = capability_python('desktop', root=ROOT)
    if selected:
        return selected if _runtime_has(selected, 'winrt.windows.media.ocr') else None
    if 'SUMIKA_DESKTOP_PYTHON' in os.environ:
        return None
    return sys.executable if _has_module('winrt.windows.media.ocr') else None


def providers():
    rapid_json = RAPIDOCR_JSON if Path(RAPIDOCR_JSON).is_file() else (shutil.which("RapidOCR-json") or None)
    local_module = ('SUMIKA_OCR_PYTHON' not in os.environ and
                    (_has_module('rapidocr') or _has_module('rapidocr_onnxruntime')))
    python = env_python()
    windows = windows_python()
    return {
        "tesseract": shutil.which("tesseract"),
        "rapidocr_json": rapid_json,
        "rapidocr": local_module or bool(python),
        "rapidocr_env_python": python,
        "windows": bool(windows),
        "windows_env_python": windows,
    }


def _shape(provider, lines, elapsed_ms=None):
    texts = [line["text"] for line in lines if line.get("text")]
    return {"provider": provider, "text": "\n".join(texts), "lines": lines,
            "elapsed_ms": round(elapsed_ms, 1) if elapsed_ms is not None else None,
            "needs_translation": True}


def _rapidocr_in_env(image, python, detect=True):
    started = time.perf_counter()
    result = subprocess.run([python, "-c", ENV_SCRIPT, str(image), "1" if detect else "0"],
                            cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=300)
    if result.returncode:
        raise RuntimeError((result.stderr or "rapidocr failed").strip()[-400:])
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    return _shape("rapidocr", payload.get("lines", []),
                  payload.get("elapsed_ms", (time.perf_counter() - started) * 1000))


def _windows_in_env(image, python, language):
    language = {'eng':'en-US','chi_sim':'zh-Hans-CN','jpn':'ja-JP'}.get(language,language)
    if not isinstance(language,str) or not language.strip() or len(language)>64:
        raise ValueError('valid Windows OCR language required')
    if image.stat().st_size > 20*1024*1024:
        raise ValueError('OCR image exceeds file budget')
    code = '''import asyncio,base64,json,sys
from pathlib import Path
from PIL import Image
from extensions.companion.windows_ocr import _recognize,normalize_text
path=Path(sys.argv[1])
with Image.open(path) as image:
 width,height=image.size
rows=asyncio.run(_recognize({'data_base64':base64.b64encode(path.read_bytes()).decode('ascii')},language=sys.argv[2]))
lines=[]
for row in rows:
 left,top,right,bottom=row['region']
 lines.append({'text':normalize_text(row['text']),'score':None,'box':[[left*width,top*height],[right*width,top*height],[right*width,bottom*height],[left*width,bottom*height]]})
print(json.dumps({'lines':lines},ensure_ascii=False))
'''
    started = time.perf_counter()
    result = subprocess.run([python,'-X','utf8','-B','-c',code,str(image),language],
        cwd=ROOT,capture_output=True,text=True,encoding='utf8',timeout=30,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    if result.returncode:
        raise RuntimeError('Windows OCR failed; check image budget and installed OCR language')
    return _shape('windows',json.loads(result.stdout)['lines'],(time.perf_counter()-started)*1000)


def _rapidocr_in_process(image, detect=True):
    engine = _engine()
    started = time.perf_counter()
    result = engine(str(image), use_det=detect)
    elapsed = (time.perf_counter() - started) * 1000
    return _shape("rapidocr", _rapidocr_lines(result), elapsed)


def _rapidocr_lines(result):
    # rapidocr_onnxruntime returns (rows, timing); rapidocr returns an object.
    if isinstance(result, tuple) and len(result) == 2:
        result = result[0]
    texts = getattr(result, "txts", None)
    lines = []
    if texts is not None:
        boxes = getattr(result, "boxes", None)
        scores = getattr(result, "scores", None)
        for index, text in enumerate(texts):
            box = boxes[index] if boxes is not None and index < len(boxes) else None
            lines.append({"text": text,
                          "score": float(scores[index]) if scores is not None and index < len(scores) else None,
                          "box": box.tolist() if hasattr(box, "tolist") else box})
    else:
        for item in (result or []):
            box = item[0] if isinstance(item, (list, tuple)) else None
            lines.append({"text": item[1] if isinstance(item, (list, tuple)) else str(item),
                          "score": float(item[2]) if isinstance(item, (list, tuple)) and len(item) > 2 and item[2] is not None else None,
                          "box": box.tolist() if hasattr(box, "tolist") else box})
    return lines


_ENGINE = None


def _engine():
    """Reuse one engine per process: construction loads ONNX models (~1s)."""
    global _ENGINE
    if _ENGINE is None:
        if importlib.util.find_spec("rapidocr"):
            from rapidocr import RapidOCR
        else:
            from rapidocr_onnxruntime import RapidOCR
        _ENGINE = RapidOCR()
    return _ENGINE


def recognize(image, provider="auto", language="eng", detect=True):
    """Recognize text. detect=False skips the detection model for a known region."""
    image = Path(image).resolve(strict=True)
    if not image.is_file():
        raise ValueError("image must be a regular file")
    available = providers()
    chosen = provider
    if chosen == "auto":
        if available["rapidocr"]:
            chosen = "rapidocr"
        elif available["tesseract"]:
            chosen = "tesseract"
        elif available["rapidocr_json"]:
            chosen = "rapidocr_json"
        elif available.get('windows'):
            chosen = 'windows'
        else:
            chosen = None
    if chosen == "rapidocr" and available["rapidocr"]:
        if 'SUMIKA_OCR_PYTHON' not in os.environ and (_has_module('rapidocr') or _has_module('rapidocr_onnxruntime')):
            return _rapidocr_in_process(image, detect)
        return _rapidocr_in_env(image, available["rapidocr_env_python"], detect)
    if chosen == 'windows' and available.get('windows'):
        return _windows_in_env(image,available['windows_env_python'],language)
    if chosen == "tesseract" and available["tesseract"]:
        started = time.perf_counter()
        result = subprocess.run([available["tesseract"], str(image), "stdout", "-l", language],
                                capture_output=True, text=True, encoding="utf-8", timeout=120)
        if result.returncode:
            raise RuntimeError(result.stderr.strip() or "tesseract failed")
        lines = [{"text": line.strip(), "score": None, "box": None}
                 for line in result.stdout.splitlines() if line.strip()]
        return _shape("tesseract", lines, (time.perf_counter() - started) * 1000)
    if chosen == "rapidocr_json" and available["rapidocr_json"]:
        models = str(Path(available["rapidocr_json"]).parent / "models")
        started = time.perf_counter()
        result = subprocess.run(
            [available["rapidocr_json"], "--models", models,
             "--det", "ch_PP-OCRv4_det_infer.onnx", "--cls", "ch_ppocr_mobile_v2.0_cls_infer.onnx",
             "--rec", "rec_ch_PP-OCRv4_infer.onnx", "--keys", "ppocr_keys_v1.txt",
             "--image_path", str(image), "--ensureLogger", "0"],
            capture_output=True, text=True, encoding="utf-8", timeout=120)
        if result.returncode:
            raise RuntimeError(result.stderr.strip() or "RapidOCR-json failed")
        lines = []
        for line in result.stdout.splitlines():
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            entries = item.get('data', []) if isinstance(item,dict) else item if isinstance(item,list) else []
            if not isinstance(entries,list):
                continue
            for entry in entries:
                if isinstance(entry, dict) and entry.get("text"):
                    lines.append({"text": entry["text"], "score": entry.get("score"),
                                  "box": entry.get("box")})
        return _shape("rapidocr-json", lines, (time.perf_counter() - started) * 1000)
    raise RuntimeError("No OCR provider available for selection; check RapidOCR, Tesseract or Windows OCR runtime")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["status", "recognize"])
    parser.add_argument("image", nargs="?")
    parser.add_argument("--provider", choices=["auto", "tesseract", "rapidocr_json", "rapidocr", "windows"],
                        default="auto")
    parser.add_argument("--language", default="eng")
    args = parser.parse_args()
    try:
        if args.action == "status":
            print(json.dumps({"providers": providers()}, ensure_ascii=False))
            return 0
        if not args.image:
            raise ValueError("image is required")
        print(json.dumps(recognize(args.image, args.provider, args.language), ensure_ascii=False))
        return 0
    except (OSError, ValueError, RuntimeError, ImportError, subprocess.SubprocessError) as error:
        print("ocr: " + str(error))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
