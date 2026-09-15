"""Runtime readiness probes for capability pages.

Only cheap, side-effect-free checks are used (module lookup and file presence),
so opening the page cannot start a device, load a model or spawn a process. A
capability is reported ready only when its dependency is actually present.
"""
import importlib.util
import glob as glob_module
import os
import platform
import shutil
from pathlib import Path


def _module(name):
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def _any_module(*names):
    return [name for name in names if _module(name)]


def _site_packages(root, env):
    """Locate an extension's isolated site-packages on Windows or POSIX layouts."""
    base = Path(root) / ".sumika-next" / env
    candidates = [base / "Lib" / "site-packages"]
    candidates.extend(sorted(base.glob("lib/python*/site-packages")))
    return next((path for path in candidates if path.is_dir()), None)


def _env_provides(root, env, packages):
    site = _site_packages(root, env)
    if site is None:
        return []
    found = set()
    for entry in site.iterdir():
        name = entry.name.casefold()
        for package in packages:
            if name == package.casefold() or name.startswith(package.casefold() + "-") \
                    or name.startswith(package.casefold() + "."):
                found.add(package)
    return sorted(found)


def _resolve(root, packages, envs):
    """Return (ready_names, source) from the bridge interpreter or extension envs."""
    local = _any_module(*packages)
    if local:
        return local, "本进程"
    for env in envs:
        provided = _env_provides(root, env, packages)
        if provided:
            return provided, f"隔离环境 {env}"
    return [], ""


def _rapidocr_json():
    """Umi-OCR's RapidOCR-json executable, if one is configured or installed."""
    explicit = os.environ.get("SUMIKA_RAPIDOCR_JSON") or \
        r"D:\Tools\Umi-OCR\2.1.5\Umi-OCR_Rapid_v2.1.5\UmiOCR-data\plugins\win7_x64_RapidOCR-json\RapidOCR-json.exe"
    if Path(explicit).is_file():
        return explicit
    return shutil.which("RapidOCR-json")


def probes(root=None, *, home=None):
    root = Path(root).resolve() if root else Path(__file__).resolve().parents[1]
    home = Path(home) if home else Path.home()
    rows = []

    def add(identifier, label, ready, detail, *, extra=None):
        rows.append({"id": identifier, "label": label, "ready": bool(ready),
                     "detail": detail, **(extra or {})})

    python_ocr, ocr_source = _resolve(root, ("rapidocr", "rapidocr_onnxruntime", "pytesseract"),
                                      ("ocr-env", "desktop-env", "office-env"))
    binary_ocr = shutil.which("tesseract")
    umi = _rapidocr_json()
    add("ocr", "OCR / 截屏翻译", bool(python_ocr or binary_ocr or umi),
        f"{ocr_source}：{', '.join(python_ocr)}" if python_ocr
        else (f"Umi-OCR RapidOCR：{umi}" if umi
              else ("tesseract 可执行文件可用" if binary_ocr else "未安装 Tesseract 或 RapidOCR，识别不可用")))

    voice_modules, voice_source = _resolve(root, ("vosk", "sounddevice"),
                                          ("voice-env", "desktop-env"))
    voice_models = [path for path in (home / ".sumika-next" / "voice-models",
                                      root / ".sumika-next" / "voice-models")
                   if path.is_dir() and any(child.is_dir() for child in path.iterdir())]
    add("voice", "语音", len(voice_modules) == 2 and bool(voice_models),
        (f"{voice_source}：{', '.join(voice_modules)}；模型 {voice_models[0].name}" if voice_modules and voice_models
         else f"模块 {', '.join(voice_modules) or '无'}；模型目录 {voice_models[0] if voice_models else '未找到或为空'}"))

    browser_skill = root / "runtime" / "browserskill" / "bsk.exe"
    add("browser", "网页咨询（内含浏览器）", browser_skill.is_file(),
        f"BrowserSkill：{browser_skill}" if browser_skill.is_file() else "未找到 runtime/browserskill/bsk.exe")

    desktop_modules, desktop_source = _resolve(root, ("pywinauto", "pywinctl", "pyautogui"),
                                              ("desktop-env", "office-env"))
    add("desktop", "桌面控制", platform.system() == "Windows" and bool(desktop_modules),
        f"平台 {platform.system()}；{desktop_source or '未找到环境'}：{', '.join(desktop_modules) or '无'}")

    office_modules, office_source = _resolve(root, ("docx", "openpyxl", "pptx", "fitz", "pymupdf"),
                                            ("office-env",))
    add("office", "办公文件", bool(office_modules),
        f"{office_source or '未找到环境'}：{', '.join(office_modules) or '无'}")

    camera_modules, camera_source = _resolve(root, ("cv2",), ("desktop-env", "office-env"))
    add("camera", "摄像头感知", bool(camera_modules),
        f"{camera_source or '未找到环境'}：{', '.join(camera_modules) or '无'}")

    semantic, semantic_source = _resolve(root, ("fastembed",), ("memory-env",))
    add("memory-semantic", "语义长期记忆", bool(semantic),
        f"{semantic_source}：{', '.join(semantic)}" if semantic
        else "未安装 fastembed，语义检索回落到内置关键词检索")

    schedule_store = home / "Sumika" / "schedules"
    add("schedule", "定时任务", True,
        f"定义目录 {schedule_store}（随应用运行，不安装系统开机任务）")
    return rows


def voice_model(root=None, *, home=None):
    """First usable Vosk model directory, or None."""
    root = Path(root).resolve() if root else Path(__file__).resolve().parents[1]
    home = Path(home) if home else Path.home()
    for base in (home / ".sumika-next" / "voice-models", root / ".sumika-next" / "voice-models"):
        if not base.is_dir():
            continue
        for child in sorted(base.iterdir()):
            if child.is_dir() and any(child.iterdir()):
                return child
    return None


def soffice_path():
    """LibreOffice's executable if this machine has one, in the usual layouts."""
    explicit = os.environ.get("SUMIKA_SOFFICE")
    if explicit and Path(explicit).is_file():
        return explicit
    found = shutil.which("soffice") or shutil.which("soffice.exe")
    if found:
        return found
    for pattern in (r"C:\Program Files\LibreOffice\program\soffice.exe",
                    r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
                    r"D:\Tools\LibreOffice\*\program\soffice.exe",
                    r"D:\Program Files\LibreOffice\program\soffice.exe"):
        for candidate in sorted(glob_module.glob(pattern)):
            if Path(candidate).is_file():
                return candidate
    return None


def service_capabilities(root=None, *, home=None):
    """Capability-registry entries this machine can actually serve.

    `extensions/desktop/service.py` resolves every device and desktop operation
    through the CapabilityStore, so a capability missing from the registry cannot
    run at all. This derives the entries from the same dependency checks the
    probes above use: a capability whose dependency is absent is left out instead
    of being registered with a provider that would fail at call time.

    Returns a list of ``{"id", "provider", "enabled", "options"}`` in a stable
    order. Options carry the values those providers require, such as Vosk's model
    directory and LibreOffice's executable.
    """
    root = Path(root).resolve() if root else Path(__file__).resolve().parents[1]
    home = Path(home) if home else Path.home()
    entries = []

    rapidocr, _ = _resolve(root, ("rapidocr", "rapidocr_onnxruntime"),
                           ("ocr-env", "desktop-env", "office-env"))
    if rapidocr:
        entries.append({"id": "ocr", "provider": "rapidocr", "enabled": True, "options": {}})
    elif _rapidocr_json():
        entries.append({"id": "ocr", "provider": "rapidocr_json", "enabled": True, "options": {}})
    elif shutil.which("tesseract"):
        entries.append({"id": "ocr", "provider": "tesseract", "enabled": True, "options": {}})

    desktop_modules, _ = _resolve(root, ("pywinauto", "pywinctl"), ("desktop-env", "office-env"))
    if platform.system() == "Windows" and len(desktop_modules) == 2:
        entries.append({"id": "desktop", "provider": "windows-uia", "enabled": True, "options": {}})

    # SAPI synthesis lives behind pywin32/comtypes, which ship in the extension
    # environments rather than the bridge interpreter.
    win32, _ = _resolve(root, ("win32com", "pywin32"), ("voice-env", "desktop-env"))
    if platform.system() == "Windows" and win32:
        entries.append({"id": "voice", "provider": "windows-sapi", "enabled": True, "options": {}})

    vosk, _ = _resolve(root, ("vosk",), ("voice-env", "desktop-env"))
    model = voice_model(root, home=home)
    if vosk and model is not None:
        entries.append({"id": "asr", "provider": "vosk", "enabled": True,
                        "options": {"model": str(model)}})

    camera, _ = _resolve(root, ("cv2",), ("desktop-env", "office-env"))
    if camera:
        entries.append({"id": "camera", "provider": "opencv", "enabled": True, "options": {}})

    microphone, _ = _resolve(root, ("sounddevice",), ("desktop-env",))
    if microphone:
        entries.append({"id": "microphone", "provider": "sounddevice", "enabled": True, "options": {}})

    office_render = soffice_path()
    if office_render:
        entries.append({"id": "office-render", "provider": "libreoffice", "enabled": True,
                        "options": {"executable": office_render}})
    return entries
