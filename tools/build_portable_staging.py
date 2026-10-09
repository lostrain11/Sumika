"""Assemble an explicit internal test package without following filesystem links.

No model downloads, profile copies, upstream edits or removal of old packages.
Inventory success is not release acceptance or a redistribution license audit.
"""
import argparse
import json
import os
from pathlib import Path
import shutil

try:
    from .verify_portable_staging import digest, safe_path, verify
except ImportError:
    from verify_portable_staging import digest, safe_path, verify

ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRS = {'node_modules', '__pycache__', '.git', '.pytest_cache'}
RUNTIME_SKIP_DIRS = {'__pycache__', '.git', '.pytest_cache'}
SOURCE_SUFFIXES = {'.py', '.js', '.mjs', '.json', '.css', '.html', '.md', '.png', '.svg', '.txt', '.vrm', '.lock', '.ps1'}


def reference_registry_asset(root):
    source = root/'docs/project/reference-projects.json'
    if source.is_symlink() or source.is_junction() or not source.is_file():
        raise ValueError('reference registry must be a physical file')
    data = json.loads(source.read_text(encoding='utf8'))
    if data.get('schema_version') != 1 or not isinstance(data.get('projects'), list) or not data['projects']:
        raise ValueError('invalid reference registry')
    return source, Path('extensions/desktop/reference-projects.json')


def browser_runtime_files(root):
    """Executable plus explicit notices only; never ship updater scratch files."""
    if root.is_symlink() or root.is_junction():
        raise ValueError('linked browser runtime')
    for name in ('bsk.exe', 'LICENSE', 'LICENSE.txt', 'NOTICE', 'NOTICE.txt'):
        path = root/name
        if path.is_symlink() or path.is_junction():
            raise ValueError('linked browser runtime file')
        if path.is_file():
            yield path, Path(name)
        elif name == 'bsk.exe':
            raise ValueError('BrowserSkill executable missing')


def verify_reviewed_assets(root):
    ledger = json.loads((root/'packaging/reviewed-assets.json').read_text(encoding='utf8'))
    if ledger.get('schema_version') != 1 or not ledger.get('files'):
        raise ValueError('reviewed asset ledger missing')
    for name, expected in ledger['files'].items():
        safe_path(name)
        source = root/name
        if not source.resolve().is_relative_to(root.resolve()) or digest(source) != expected:
            raise ValueError('reviewed asset changed: ' + name)
    notice_root = root/'packaging/notices'
    notices = json.loads((notice_root/'sources.json').read_text(encoding='utf8'))
    for item in notices['sources']:
        source = notice_root/item['file']
        if not source.resolve().is_relative_to(notice_root.resolve()) or digest(source) != item['sha256']:
            raise ValueError('reviewed notice changed')


def physical_files(root, *, product=False):
    if root.is_symlink() or root.is_junction():
        raise ValueError('linked source root')
    for directory, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = [name for name in dirs if name not in (SKIP_DIRS if product else RUNTIME_SKIP_DIRS)]
        for name in dirs + files:
            p = Path(directory)/name
            if p.is_symlink() or p.is_junction():
                raise ValueError('linked source: ' + str(p))
        for name in files:
            p = Path(directory)/name
            if p.suffix.casefold() == '.pyc':
                continue
            if product and (p.suffix not in SOURCE_SUFFIXES or '.test.' in name):
                continue
            yield p, p.relative_to(root)


def executable_asset(path):
    """Reject scripts renamed to EXE before creating a candidate directory."""
    path = path.resolve(strict=True)
    if path.suffix.lower() != '.exe' or not path.is_file() or path.is_symlink() or path.is_junction():
        raise ValueError('physical Windows executable required: ' + str(path))
    with path.open('rb') as source:
        header = source.read(64)
        if len(header) != 64 or header[:2] != b'MZ':
            raise ValueError('Windows executable DOS header missing: ' + str(path))
        offset = int.from_bytes(header[60:64], 'little')
        if offset < 64 or offset > path.stat().st_size - 4:
            raise ValueError('invalid Windows executable PE offset: ' + str(path))
        source.seek(offset)
        if source.read(4) != b'PE\x00\x00':
            raise ValueError('Windows executable PE header missing: ' + str(path))
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--destination', type=Path, required=True)
    parser.add_argument('--dsh-runtime', type=Path, required=True)
    parser.add_argument('--host-runtimes', type=Path, required=True)
    parser.add_argument('--launcher', type=Path, required=True)
    parser.add_argument('--pet-host', type=Path, help='Optional self-contained desktop pet host')
    parser.add_argument('--process-audio-helper', type=Path,
                        help='Optional self-contained process loopback helper executable')
    parser.add_argument('--desktop-runtime', type=Path,
                        help='Optional physical standalone capability Python directory')
    parser.add_argument('--voice-runtime', type=Path,
                        help='Optional physical standalone continuous voice Python directory')
    args = parser.parse_args()
    destination = args.destination.absolute()
    if destination.exists():
        raise ValueError('destination must be new')
    verify_reviewed_assets(ROOT)
    for relative in ('ui/app/tokens.css', 'ui/app/icons.js', 'ui/vendor/icons/hard-drive.svg',
                     'ui/vendor/icons/info.svg', 'tools/run_module.py'):
        if not (ROOT / relative).is_file():
            raise ValueError('required current UI/startup resource missing: ' + relative)
    selected = [(executable_asset(args.launcher), Path('Sumika.exe'))]
    selected.append(reference_registry_asset(ROOT))
    if args.pet_host:
        selected.append((executable_asset(args.pet_host), Path('SumikaPet.exe')))
    if args.process_audio_helper:
        selected.append((executable_asset(args.process_audio_helper),
                         Path('runtime/process-audio/SumikaProcessAudio.exe')))
        selected.append((ROOT/'extensions/desktop/native/ProcessAudio/LICENSE-NAudio.txt',
                         Path('licenses/NAudio-MIT.txt')))
    selected.extend((p, Path('licenses')/rel) for p, rel in physical_files(ROOT/'packaging/notices'))
    for name in ('ui', 'extensions', 'sumika_next', 'tools'):
        selected.extend((p, Path(name)/rel) for p, rel in physical_files(ROOT/name, product=True))
    selected.extend((p, Path('runtime/dsh')/rel) for p, rel in physical_files(args.dsh_runtime.resolve(strict=True)))
    for name in ('python', 'node'):
        selected.extend((p, Path('runtime')/name/rel)
                        for p, rel in physical_files(args.host_runtimes.resolve(strict=True)/'runtime'/name))
    for name, directory in (('desktop', args.desktop_runtime), ('voice', args.voice_runtime)):
        if directory is not None:
            runtime = directory.resolve(strict=True)
            if not (runtime/'python.exe').is_file() or (runtime/'pyvenv.cfg').exists():
                raise ValueError('capability runtime must be standalone Python, not a development venv')
            selected.extend((p, Path('runtime')/name/rel) for p, rel in physical_files(runtime))
    browser = ROOT/'runtime/browserskill'
    if browser.is_dir():
        selected.extend((p, Path('runtime/browserskill')/rel) for p, rel in browser_runtime_files(browser))
    seen = set()
    for source, relative in selected:
        safe_path(relative.as_posix())
        if relative.as_posix().casefold() in seen:
            raise ValueError('duplicate output selection')
        seen.add(relative.as_posix().casefold())
        if source.is_symlink() or source.is_junction() or not source.is_file():
            raise ValueError('source is not a physical file')
    destination.mkdir(parents=True)
    inventory = []
    for source, relative in selected:
        target = destination/relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        inventory.append({'path': relative.as_posix(), 'size': target.stat().st_size, 'sha256': digest(target)})
    manifest = {'kind': 'portable-staging', 'schema_version': 2,
                'status': 'internal-test-candidate', 'files': inventory,
                'boundary': 'No release acceptance; optional dependencies, licenses and lifecycle still require verification.'}
    (destination/'package-manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf8')
    print(json.dumps(verify(destination), indent=2))


if __name__ == '__main__':
    main()
