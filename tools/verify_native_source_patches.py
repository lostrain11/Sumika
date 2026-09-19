"""Verify pinned candidate Windows web build patches, without compiling sources.

Consumes existing source archives and recipe evidence. Keeps fresh affected-file
trees and all outputs. Does not execute upstream build scripts, change installed
libraries, or assert historical container/feature identity.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import tarfile
import uuid


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


RECIPE_ARCHIVES = frozenset(('mxe-build-scripts.tar.gz', 'mxe-d973945-source.tar.gz'))


def verified_recipe_bytes(base, materials):
    """Require exact archive identities and hash both buffers before parsing."""
    document = json.loads(materials.read_text(encoding='utf8'))
    entries = document.get('archives') if isinstance(document, dict) else None
    if not isinstance(entries, list):
        raise ValueError('recipe materials must declare an archives list')
    bindings = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError('recipe archive binding must be an object')
        name, digest = entry.get('file'), entry.get('sha256')
        if not isinstance(name, str) or name not in RECIPE_ARCHIVES or name in bindings:
            raise ValueError('unexpected or duplicate recipe archive identity')
        if not isinstance(digest, str) or not re.fullmatch(r'[0-9a-f]{64}', digest):
            raise ValueError('invalid recipe archive SHA256')
        bindings[name] = digest
    if set(bindings) != RECIPE_ARCHIVES:
        raise ValueError('missing recipe archive binding')
    buffers = {}
    for name, digest in bindings.items():
        raw = (base/name).read_bytes()
        if sha(raw) != digest:
            raise ValueError('recipe archive checksum mismatch: '+name)
        buffers[name] = raw
    return buffers


def verify(args, base, output, report):
    recipes = json.loads((base/'windows-component-recipes.json').read_text())
    if not isinstance(recipes, dict) or not isinstance(recipes.get('components'), list) or not recipes['components']:
        raise ValueError('recipe evidence must contain nonempty components')
    materials = {r['component']: r for r in json.loads(args.materials.read_text())['archives']}
    report['stage'] = 'recipe_checksums'
    raws = verified_recipe_bytes(base, args.recipe_materials)
    report['recipe_archives'] = {name: sha(raw) for name, raw in raws.items()}
    report['stage'] = 'recipe_archive_parse'
    archives = {}
    for filename, raw in raws.items():
        with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
            archives[filename] = {m.name: archive.extractfile(m).read()
                                  for m in archive.getmembers() if m.isfile()}
    scripts = archives['mxe-build-scripts.tar.gz']
    override_path = next(n for n in scripts if n.endswith('/build/overrides.mk'))
    override = scripts[override_path].decode()
    for component in recipes['components']:
        report['stage'] = 'component_selection'
        name = component['component']
        report['current_component'] = name
        recipe = component['recipes'][0]
        pkg = PurePosixPath(recipe['path']).stem
        overrides = re.findall(r'^'+re.escape(pkg)+r'_PATCHES\s*:=\s*(.*)$', override, re.M)
        if overrides:
            expected = '/patches/'+pkg+'-[0-9]*.patch'
            if not all(expected in value for value in overrides):
                raise ValueError('Unrecognized patch override: '+pkg)
            locations = [('mxe-build-scripts.tar.gz', str(PurePosixPath(override_path).parent/'patches'))]
            rule = 'explicit build override (including empty wildcard result)'
        elif '$(PKG)_PATCHES' in recipe['text']:
            if '/patches/$(PKG)-[0-9]*.patch' not in recipe['text']:
                raise ValueError('Unrecognized recipe patch expression: '+pkg)
            locations = [(recipe['archive'], str(PurePosixPath(recipe['path']).parent/'patches'))]
            rule = 'explicit recipe patch directory'
        else:
            mxe = next(iter(archives['mxe-d973945-source.tar.gz'])).split('/')[0]
            locations = [('mxe-d973945-source.tar.gz', mxe+'/src'),
                         ('mxe-d973945-source.tar.gz', mxe+'/plugins/llvm-mingw')]
            rule = 'MXE default plugin wildcard; build overrides absent'
        patches = []
        for archive_name, directory in locations:
            for path, raw in sorted(archives[archive_name].items()):
                if str(PurePosixPath(path).parent) == directory and re.fullmatch(re.escape(pkg)+r'-[0-9].*\.patch', PurePosixPath(path).name):
                    patches.append((archive_name, path, raw))
        row = {'component': name, 'version': component['shipped_version'], 'rule': rule,
               'patches': [], 'passed': True}
        report['components'].append(row)
        if not patches:
            continue
        source = base/'component-sources'/(name+'.source')
        if name == 'mozjpeg': source = base/'component-sources/mozjpeg.recipe-source'
        if name == 'vips': source = base/'vips-8.18.6.tar.xz'
        report['stage'] = 'source_checksum'
        raw = source.read_bytes()
        if sha(raw) != materials[name]['sha256']:
            raise ValueError('Source archive checksum mismatch: '+name)
        row['source_sha256'] = sha(raw)
        tree = output/name; tree.mkdir()
        wanted = set()
        for _, path, patch in patches:
            for line in patch.decode().splitlines():
                if line.startswith('+++ /dev/null'):
                    raise ValueError('File removal requires separate review: '+path)
                if line.startswith(('--- ', '+++ ')):
                    value = line[4:].split()[0]
                    if value == '/dev/null': continue
                    parts = PurePosixPath(value).parts[1:]
                    if not parts or any(p in ('.', '..') or ':' in p for p in parts):
                        raise ValueError('Unsafe patch path')
                    wanted.add('/'.join(parts))
        report['stage'] = 'source_extraction'
        with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
            for member in archive.getmembers():
                relative = '/'.join(PurePosixPath(member.name).parts[1:])
                if relative not in wanted: continue
                if not member.isfile(): raise ValueError('Patch target is not a regular file')
                dest = tree/relative
                dest.parent.mkdir(parents=True, exist_ok=True)
                with dest.open('xb') as stream: stream.write(archive.extractfile(member).read())
        row['before'] = {p: sha((tree/p).read_bytes()) for p in sorted(wanted) if (tree/p).exists()}
        for index, (archive_name, path, patch) in enumerate(patches):
            patch_file = output/(name+'-'+str(index)+'.patch')
            patch_file.write_bytes(patch)
            item = {'archive': archive_name, 'path': path, 'sha256': sha(patch)}
            row['patches'].append(item)
            command = [str(args.patch.resolve()), '--batch', '--forward', '--fuzz=0',
                       '--no-backup-if-mismatch', '-p1', '-i', str(patch_file)]
            for mode in ('dry_run', 'apply'):
                report['stage'] = 'patch_' + mode
                result = subprocess.run(command+(['--dry-run'] if mode=='dry_run' else []),
                                        cwd=tree, capture_output=True, text=True, timeout=60)
                item[mode] = {'exit_code': result.returncode, 'output': result.stdout+result.stderr}
                if result.returncode:
                    row['passed'] = False
                    report['failure'] = {'stage': report['stage'], 'type': 'PatchFailure',
                                         'reason': name+': '+path+' exited '+str(result.returncode)}
                    break
            if not row['passed']: break
        row['after'] = {p: sha((tree/p).read_bytes()) for p in sorted(wanted) if (tree/p).exists()}
        (output/'report.json').write_text(json.dumps(report, indent=2)+'\n')
    report['passed'] = all(c['passed'] for c in report['components'])
    (output/'report.json').write_text(json.dumps(report, indent=2)+'\n')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--materials', type=Path, required=True)
    parser.add_argument('--recipe-materials', type=Path, required=True)
    parser.add_argument('--patch', type=Path, required=True)
    args = parser.parse_args(argv)
    base = args.evidence.resolve(strict=True)
    output = base/('patch-check-'+uuid.uuid4().hex)
    output.mkdir()
    report = {'status': 'candidate_patch_verification', 'components': [],
              'scope': 'Pinned web static default mozjpeg/zlib-ng/proxy-libintl recipes; no ffi-compat/nightly/all-deps.',
              'boundary': 'Affected files only. Not compilation, original container identity or complete corresponding source.'}
    report.update(passed=False, stage='setup')
    try:
        verify(args, base, output, report)
    except Exception as error:
        if report['components'] and report['components'][-1]['component'] == report.get('current_component'):
            report['components'][-1]['passed'] = False
        report.update(passed=False, failure={'stage': report['stage'],
                      'type': type(error).__name__, 'reason': str(error)})
    finally:
        (output/'report.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf8')
    print(json.dumps({'report': str(output/'report.json'), 'passed': report['passed'],
                      'components': len(report['components']),
                      'patches': sum(len(c['patches']) for c in report['components'])}))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
