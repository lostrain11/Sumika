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
SOURCE_SUFFIXES = {'.py', '.js', '.mjs', '.json', '.css', '.html', '.md', '.png', '.vrm', '.lock', '.ps1'}


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
        if product:
            dirs[:] = [name for name in dirs if name not in SKIP_DIRS]
        for name in dirs + files:
            p = Path(directory)/name
            if p.is_symlink() or p.is_junction():
                raise ValueError('linked source: ' + str(p))
        for name in files:
            p = Path(directory)/name
            if product and (p.suffix not in SOURCE_SUFFIXES or '.test.' in name):
                continue
            yield p, p.relative_to(root)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--destination', type=Path, required=True)
    parser.add_argument('--dsh-runtime', type=Path, required=True)
    parser.add_argument('--host-runtimes', type=Path, required=True)
    parser.add_argument('--launcher', type=Path, required=True)
    args = parser.parse_args()
    destination = args.destination.absolute()
    if destination.exists():
        raise ValueError('destination must be new')
    verify_reviewed_assets(ROOT)
    selected = [(args.launcher.resolve(strict=True), Path('Sumika.exe'))]
    selected.extend((p, Path('licenses')/rel) for p, rel in physical_files(ROOT/'packaging/notices'))
    for name in ('ui', 'extensions', 'sumika_next', 'tools'):
        selected.extend((p, Path(name)/rel) for p, rel in physical_files(ROOT/name, product=True))
    selected.extend((p, Path('runtime/dsh')/rel) for p, rel in physical_files(args.dsh_runtime.resolve(strict=True)))
    for name in ('python', 'node'):
        selected.extend((p, Path('runtime')/name/rel)
                        for p, rel in physical_files(args.host_runtimes.resolve(strict=True)/'runtime'/name))
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
