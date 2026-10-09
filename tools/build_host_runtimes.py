"""Stage an isolated Windows Python/Node baseline from installed assets.

Does not download, alter installations, bundle models, or include optional
desktop/voice/OCR dependencies. Source and destination must be explicit.
"""
import argparse
import hashlib
from importlib import metadata
import json
from pathlib import Path
import shutil
import subprocess
import sys


def copy(source, target):
    if source.is_symlink() or source.is_junction():
        raise ValueError('linked source is not supported: ' + str(source))
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--destination', type=Path, required=True)
    parser.add_argument('--node-directory', type=Path, required=True)
    parser.add_argument('--dependency-site', type=Path,
                        help='Explicit additional installed site-packages for model dependencies')
    args = parser.parse_args()
    destination = args.destination.absolute()
    if destination.exists():
        raise ValueError('choose a new destination; existing files are preserved')
    source = Path(sys.base_prefix)
    node = args.node_directory.resolve(strict=True)
    if sys.platform != 'win32' or sys.version_info[:2] != (3, 14):
        raise ValueError('this baseline requires verified Windows Python 3.14')
    required = ('python.exe', 'python3.dll', 'python314.dll', 'vcruntime140.dll',
                'vcruntime140_1.dll', 'LICENSE.txt')
    for name in required:
        if not (source/name).is_file():
            raise ValueError('missing Python runtime asset: ' + name)
    for name in ('node.exe', 'LICENSE'):
        if not (node/name).is_file():
            raise ValueError('missing Node runtime asset: ' + name)
    distributions = [('tzdata', '2025.2', 'tzdata'), ('websocket-client', '1.9.2', 'websocket'),
        ('httpx', '0.28.1', 'httpx'), ('httpx-sse', '0.4.0', 'httpx_sse'),
        ('httpcore', '1.0.9', 'httpcore'), ('h11', '0.16.0', 'h11'),
        ('anyio', '4.12.0', 'anyio'), ('certifi', '2026.7.22', 'certifi'),
        ('idna', '3.19', 'idna'), ('typing_extensions', '4.16.0', 'typing_extensions.py')]
    additional = {}
    if args.dependency_site:
        site = args.dependency_site.resolve(strict=True)
        additional = {dist.metadata['Name'].lower().replace('_', '-'): dist
                      for dist in metadata.distributions(path=[str(site)])}
    selected_distributions = {}
    for name, version, _ in distributions:
        dist = additional.get(name.lower().replace('_', '-')) or metadata.distribution(name)
        if dist.version != version:
            raise ValueError('dependency version mismatch: ' + name)
        selected_distributions[name] = dist
    destination.mkdir(parents=True)
    python = destination/'runtime/python'
    for name in required:
        copy(source/name, python/name)
    # Standard library and extension modules only, not the developer site-packages.
    for directory in ('Lib', 'DLLs'):
        for path in (source/directory).rglob('*'):
            relative = path.relative_to(source/directory)
            if any(part in ('site-packages', '__pycache__', 'test', 'tests', 'idlelib', 'turtledemo')
                   for part in relative.parts):
                continue
            if path.is_symlink() or path.is_junction():
                raise ValueError('linked standard library asset')
            if path.is_file() and path.suffix not in ('.pyc', '.pyo'):
                copy(path, python/directory/relative)
    for name, version, package in distributions:
        dist = selected_distributions[name]
        for entry in dist.files or ():
            parts = Path(entry).parts
            # Keep the module and its distribution metadata/licenses; no scripts.
            if not parts or not (parts[0] == package or parts[0].endswith('.dist-info')):
                continue
            if '..' in parts or '__pycache__' in parts or Path(entry).suffix == '.pyc':
                continue
            copy(Path(dist.locate_file(entry)), python/'Lib/site-packages'/entry)
    # _pth isolates imports from global/user site-packages, registry and PYTHONPATH.
    # The product root is explicit so `-m ui.server` can import Sumika modules.
    (python/'python314._pth').write_text('Lib\nDLLs\nLib\\site-packages\n..\\..\n', encoding='utf8')
    for name in ('node.exe', 'LICENSE'):
        copy(node/name, destination/'runtime/node'/name)
    probe = subprocess.run([str(python/'python.exe'), '-B', '-c',
        'import sys,sqlite3,ssl,ctypes,zoneinfo,websocket,httpx,httpx_sse,httpcore,h11,anyio; '
        'assert sys.flags.isolated and sys.flags.no_site and sys.flags.ignore_environment; '
        'from pathlib import Path; assert Path(sys.executable).parents[2] in [Path(p) for p in sys.path]; '
        'assert str(zoneinfo.ZoneInfo("Asia/Shanghai")) == "Asia/Shanghai"; '
        'print(sys.version.split()[0])'], capture_output=True, text=True, check=True)
    node_version = subprocess.run([str(destination/'runtime/node/node.exe'), '--version'],
                                  capture_output=True, text=True, check=True).stdout.strip()
    report = {'status': 'baseline_imports_passed', 'python': probe.stdout.strip(), 'node': node_version,
              'dependencies': {name: version for name, version, _ in distributions},
              'binary_sha256': {name: hashlib.sha256((destination/name).read_bytes()).hexdigest()
                                for name in ('runtime/python/python.exe', 'runtime/node/node.exe')},
              'boundary': 'Installed local assets, not an independently verified vendor archive; optional capability dependencies and full product startup not accepted.'}
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
