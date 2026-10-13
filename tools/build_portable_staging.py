"""Assemble an explicit internal test package without following filesystem links.

No model downloads, profile copies, upstream edits or removal of old packages.
Inventory success is not release acceptance or a redistribution license audit.
"""
import argparse
import json
import os
import shutil
import sys
from pathlib import Path
import subprocess

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


def reject_runtime_dev_paths(runtime):
    """A packaged capability runtime must be relocatable: _pth entries stay
    inside the runtime. An absolute development checkout line would silently
    bind the shipped interpreter to the build machine."""
    for path in sorted(runtime.glob('*._pth')):
        for number, line in enumerate(path.read_text(encoding='utf8').splitlines(), start=1):
            entry = line.strip()
            if entry and (Path(entry).drive or Path(entry).root):
                raise ValueError(f'{path.name}:{number} must not bind machine paths: {entry}')


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
        raise ValueError('Windows executable required: ' + str(path))
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


def directory_digest(directory):
    """Bounded input summary: one sha256 over sorted relative paths and sizes.

    The full per-file inventory ships in the manifest; this digest only pins
    the INPUT directory a candidate was built from.
    """
    import hashlib
    accumulator = hashlib.sha256()
    count = 0
    for path, relative in physical_files(directory):
        accumulator.update(relative.as_posix().encode('utf8'))
        accumulator.update(str(path.stat().st_size).encode('ascii'))
        count += 1
    return {'files': count, 'sha256': accumulator.hexdigest()}


def source_state(root):
    """Source identity for the receipt: commit plus an honest dirty summary."""
    import subprocess
    def git(*arguments):
        try:
            result = subprocess.run(['git', *arguments], cwd=str(root),
                                    capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.TimeoutExpired):
            return None
        return result.stdout.strip() if result.returncode == 0 else None
    status = git('status', '--porcelain')
    dirty = status.splitlines() if status else []
    return {'commit': git('rev-parse', 'HEAD') or 'unavailable',
            'dirty': bool(dirty),
            'dirty_entries': len(dirty),
            'dirty_sample': sorted(dirty)[:20]}


def build_receipt(args, destination):
    """R7 build receipt: source, inputs, generator, command and acceptance.

    Inventory success is not acceptance, so the receipt records the
    acceptance COMMAND, never a pass claim. Resource warnings, when a build
    produces any, are located separately in their own evidence file; this
    section stays empty unless a located warning is being reported — it is
    never a leak claim and never a place to hide one.
    """
    inputs = {'launcher': {'sha256': digest(args.launcher.resolve())},
              'host_runtimes': directory_digest(args.host_runtimes.resolve(strict=True)),
              'dsh_runtime': directory_digest(args.dsh_runtime.resolve(strict=True))}
    lock = args.dsh_runtime.resolve(strict=True)/'release.json'
    if lock.is_file():
        data = json.loads(lock.read_text(encoding='utf8'))
        inputs['dsh_lock'] = {'version': data.get('version'), 'sha256': digest(lock)}
    for name, path in (('pet_host', args.pet_host),
                       ('process_audio_helper', args.process_audio_helper),
                       ('desktop_runtime', args.desktop_runtime),
                       ('voice_runtime', args.voice_runtime)):
        if path is not None:
            resolved = path.resolve(strict=True)
            inputs[name] = (digest(resolved) if resolved.is_file()
                            else directory_digest(resolved))
    return {
        'source': source_state(ROOT),
        'inputs': inputs,
        'generator': {'companion_extension_builder': {
            'sha256': digest(ROOT/'tools'/'build_companion_extension.mjs')}},
        'command': {'argv': list(sys.argv), 'destination': str(destination)},
        'acceptance': {
            'command': 'python -B tools/verify_portable_staging.py --destination '
                       + str(destination),
            'status': 'not_run_by_builder; inventory success is not release acceptance'},
        'resource_warnings': [],
        'resource_warning_policy': 'located in separate evidence with a cause; '
                                   'never a leak claim, never hidden here',
    }


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
            reject_runtime_dev_paths(runtime)
            selected.extend((p, Path('runtime')/name/rel) for p, rel in physical_files(runtime))
    browser = ROOT/'runtime/browserskill'
    if browser.is_dir():
        selected.extend((p, Path('runtime/browserskill')/rel) for p, rel in browser_runtime_files(browser))
    # R5/P05: the Bilibili companion MV3 extension ships inside the candidate
    # (built by the single-source generator) so the user can load it without
    # running any developer tooling.
    import subprocess as _subprocess
    extension_dir = destination.parent/'p05-extension-build'
    if extension_dir.exists():
        import shutil as _shutil
        _shutil.rmtree(extension_dir)
    node = os.environ.get('SUMIKA_NODE') or shutil.which('node')
    if node is None:
        raise ValueError('node is required to build the bundled browser extension')
    build = _subprocess.run([node, str(ROOT/'tools'/'build_companion_extension.mjs'),
                             str(extension_dir)], cwd=str(ROOT),
                            capture_output=True, text=True, timeout=120)
    if build.returncode:
        raise ValueError('browser extension build failed: ' + build.stderr[-400:])
    selected.extend((p, Path('browser-extensions/sumika-companion')/rel)
                    for p, rel in physical_files(extension_dir))
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
                'build': build_receipt(args, destination),
                'boundary': 'No release acceptance; optional dependencies, licenses and lifecycle still require verification.'}
    (destination/'package-manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf8')
    print(json.dumps(verify(destination), indent=2))


if __name__ == '__main__':
    main()
