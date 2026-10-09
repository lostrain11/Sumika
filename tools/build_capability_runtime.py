"""Assemble standalone capability Python from an existing baseline and pinned site."""
import argparse
from importlib import metadata
import json
from pathlib import Path
import shutil
import subprocess


def build(baseline, site, lock, destination, *, dependency_sites=()):
    baseline, site = Path(baseline).resolve(strict=True), Path(site).resolve(strict=True)
    sites = [site, *(Path(path).resolve(strict=True) for path in dependency_sites)]
    destination = Path(destination).absolute()
    if destination.exists():
        raise ValueError('destination must be new')
    if not (baseline/'python.exe').is_file() or (baseline/'pyvenv.cfg').exists():
        raise ValueError('standalone baseline required')
    installed = {}
    for directory in sites:
        for dist in metadata.distributions(path=[str(directory)]):
            name = dist.metadata['Name'].lower().replace('_', '-')
            # First site owns existing packages; supplements supply only missing
            # locked dependencies rather than replacing native runtime packages.
            installed.setdefault(name, dist)
    selected = []
    for row in Path(lock).read_text(encoding='utf8').splitlines():
        row = row.strip()
        if not row or row.startswith('#'):
            continue
        name, version = row.split('==')
        dist = installed.get(name.lower().replace('_', '-'))
        if dist is None or dist.version != version:
            raise ValueError('installed dependency does not match lock: ' + name)
        selected.append((name, version, dist))
    # Explicit files only; no junction traversal or development venv metadata.
    def copy(source, target):
        if source.is_symlink() or source.is_junction():
            raise ValueError('linked runtime source')
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    for source in baseline.rglob('*'):
        if source.is_symlink() or source.is_junction():
            raise ValueError('linked baseline')
        if source.is_file() and '__pycache__' not in source.parts and source.suffix != '.pyc':
            copy(source, destination/source.relative_to(baseline))
    for name, version, dist in selected:
        previous = [d for d in metadata.distributions(path=[str(destination/'Lib/site-packages')])
                    if (d.metadata.get('Name') or '').lower().replace('_', '-') == name.lower().replace('_', '-')]
        for old in previous:
            for entry in old.files or ():
                target = Path(old.locate_file(entry))
                if target.resolve().is_relative_to(destination.resolve()) and target.is_file():
                    target.unlink()
        for entry in dist.files or ():
            path = Path(str(entry))
            if path.is_absolute() or '..' in path.parts or '__pycache__' in path.parts or path.suffix == '.pyc':
                continue
            source = Path(dist.locate_file(entry))
            if not any(source.resolve().is_relative_to(directory) for directory in sites):
                raise ValueError('distribution file escaped site')
            if source.is_file():
                copy(source, destination/'Lib/site-packages'/path)
    # _pth deliberately does not run site/.pth hooks. Expose the needed PyWin32
    # modules and put its runtime DLLs beside Python for relocated imports.
    for source in (destination/'Lib/site-packages/pywin32_system32').glob('*.dll'):
        copy(source, destination/source.name)
    (destination/'python314._pth').write_text(
        'Lib\nDLLs\nLib\\site-packages\nLib\\site-packages\\win32\n'
        'Lib\\site-packages\\win32\\lib\nLib\\site-packages\\Pythonwin\n..\\..\n', encoding='utf8')
    voice = (any(name == 'pipecat-ai' for name, _, _ in selected)
             or (baseline/'Lib/site-packages/pipecat').is_dir())
    extra = ('from pipecat.pipeline.worker import PipelineWorker; '
             'from pipecat.audio.vad.silero import SileroVADAnalyzer; '
             'SileroVADAnalyzer(sample_rate=16000); ') if voice else ''
    # Voice and WGC workers run in separate processes: importing OpenCV before
    # ONNX Runtime has an observed native DLL conflict on this Windows host.
    desktop_probe = '' if voice else 'import windows_capture,winrt.windows.graphics.capture; '
    if any(name == 'pypdf' for name, _, _ in selected):
        desktop_probe += 'import pypdf; '
    if not voice and any(name == 'winrt-Windows.Media.Ocr' for name, _, _ in selected):
        desktop_probe += ('from winrt.windows.media.ocr import OcrEngine; '
                          'from winrt.windows.graphics.imaging import SoftwareBitmap; '
                          'from winrt.windows.storage.streams import DataWriter; '
                          'list(OcrEngine.available_recognizer_languages); ')
    probe = subprocess.run([str(destination/'python.exe'), '-I', '-X', 'utf8', '-B', '-c',
        extra +
        'import sys,pythoncom,win32api,win32com.client,pywinauto,sounddevice,vosk; '
        'import httpx,httpx_sse; ' + desktop_probe +
        'assert sys.flags.isolated and sys.flags.no_site; print("capability imports passed")'],
        capture_output=True, text=True, encoding='utf8', errors='replace', timeout=60)
    report = {'passed': probe.returncode == 0, 'root': str(destination),
              'dependencies': {name: version for name, version, _ in selected},
              'stdout': probe.stdout, 'stderr': probe.stderr,
              'scope': 'Relocated dependency imports only; not audio/capture hardware acceptance'}
    (destination.parent/(destination.name+'-report.json')).write_text(
        json.dumps(report, indent=2), encoding='utf8')
    if probe.returncode:
        raise RuntimeError('capability import failed: ' + probe.stderr[-1500:])
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('baseline', 'site', 'lock', 'destination'):
        parser.add_argument('--'+name, type=Path, required=True)
    parser.add_argument('--dependency-site', type=Path, action='append', default=[],
                        help='Existing supplementary site for missing locked dependencies')
    args = parser.parse_args()
    print(json.dumps(build(args.baseline, args.site, args.lock, args.destination,
                           dependency_sites=args.dependency_site), indent=2))
