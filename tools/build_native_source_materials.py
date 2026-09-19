"""Package verified cached source materials; not complete-source/release clearance."""
import argparse
import hashlib
import json
import os
import sys
from pathlib import Path, PurePosixPath
import zipfile

ROOT = Path(__file__).resolve().parents[1]

_MANIFEST_NAME = 'materials-manifest.json'
_BOUNDARY = ('Preserved source inputs and notices only; not full corresponding source or '
             'public release clearance.')
_REMAINING = [
    'Historical container/toolchain/build-std provenance and source scope',
    'Actual compilation, binary replacement/relinking validation',
    'Final applicable source/license scope and delivery review',
]
_HEX_DIGITS = frozenset('0123456789abcdef')


def safe_path(name):
    # Source bundles intentionally do not use the portable product root list.
    if (not isinstance(name, str) or not name or PurePosixPath(name).is_absolute()
            or any(c in name for c in '\\:*?"<>|')
            or any(ord(c) < 32 for c in name)
            or any(os.path.isreserved(part) for part in name.split('/'))
            or any(part in ('', '.', '..') or part.endswith((' ', '.')) for part in name.split('/'))):
        raise ValueError('unsafe source-material archive path')


def _require_object(value, what):
    if not isinstance(value, dict):
        raise ValueError(what + ' must be a JSON object')
    return value


def _require_list(value, what):
    if not isinstance(value, list):
        raise ValueError(what + ' must be a JSON list')
    return value


def _require_token(value, what):
    if not isinstance(value, str) or not value:
        raise ValueError(what + ' must be a non-empty string')
    if '/' in value or '\\' in value or value in ('.', '..') or value.endswith((' ', '.')):
        raise ValueError(what + ' is not a safe name: ' + repr(value))
    if any(c in value for c in ':*?"<>|') or any(ord(c) < 32 for c in value) or os.path.isreserved(value):
        raise ValueError(what + ' contains unsafe characters: ' + repr(value))
    return value


def _require_sha256(value, what):
    if not isinstance(value, str) or len(value) != 64:
        raise ValueError(what + ' must be a 64-character SHA-256 hex digest')
    if any(c not in _HEX_DIGITS for c in value):
        raise ValueError(what + ' must be a lowercase SHA-256 hex digest')
    return value


def _validate_ledgers(native, rust, recipes):
    """Validate ledger shapes, required safe names and SHA-256 fields.

    Returns (native_items, rust_items, recipe_items) with validated field tuples;
    raises ValueError on any shape/name/hash violation. Source selection and
    duplicate destination identities are resolved separately."""
    native = _require_object(native, 'native-source-materials.json')
    native_items = []
    for entry in _require_list(native.get('archives'), 'native-source-materials.json "archives"'):
        entry = _require_object(entry, 'native archive entry')
        component = _require_token(entry.get('component'), 'native archive "component"')
        sha256 = _require_sha256(entry.get('sha256'), 'native archive "sha256"')
        safe_path('sources/' + component + '.source')
        native_items.append((component, sha256))

    rust = _require_object(rust, 'native-rust-source-materials.json')
    rust_items = []
    for entry in _require_list(rust.get('packages'), 'native-rust-source-materials.json "packages"'):
        entry = _require_object(entry, 'rust package entry')
        name = _require_token(entry.get('name'), 'rust package "name"')
        version = _require_token(entry.get('version'), 'rust package "version"')
        sha256 = _require_sha256(entry.get('sha256'), 'rust package "sha256"')
        safe_path(name + '-' + version + '.crate')
        rust_items.append((name, version, sha256))

    recipes = _require_object(recipes, 'native-patch-materials.json')
    recipe_items = []
    for entry in _require_list(recipes.get('archives'), 'native-patch-materials.json "archives"'):
        entry = _require_object(entry, 'patch archive entry')
        file_name = _require_token(entry.get('file'), 'patch archive "file"')
        sha256 = _require_sha256(entry.get('sha256'), 'patch archive "sha256"')
        safe_path(file_name)
        recipe_items.append((file_name, sha256))
    return native_items, rust_items, recipe_items


def _collect_selected(native, rust, recipes, notices_dir, evidence):
    """Validate ledgers and assemble (source, destination, expected_sha256) triples.

    Also rejects duplicate destination identities (case-insensitive) and missing or
    linked source files. No bytes are copied here."""
    native_items, rust_items, recipe_items = _validate_ledgers(native, rust, recipes)
    selected = []
    for component, expected in native_items:
        name = 'sources/' + component + '.source'
        source = evidence / 'component-sources' / (component + '.source')
        if component == 'mozjpeg':
            source = evidence / 'component-sources' / 'mozjpeg.recipe-source'
        if component == 'vips':
            source = evidence / 'vips-8.18.6.tar.xz'
        selected.append((source, name, expected))
    for name, version, expected in rust_items:
        crate = name + '-' + version + '.crate'
        selected.append((evidence / 'rsvg-crates' / crate, 'rust/' + crate, expected))
    for file_name, expected in recipe_items:
        selected.append((evidence / file_name, 'recipes/' + file_name, expected))
    for source in sorted(notices_dir.iterdir()):
        if source.is_file():
            name = 'notices/' + source.name
            safe_path(name)
            selected.append((source, name, None))
    # Toolchain inputs include rebuilt runtimes (e.g. Rust std), not just crates.
    # Once declared, every archive is mandatory; never silently omit a download.
    toolchain_items = []
    ledger_path = notices_dir / 'native-toolchain-source-materials.json'
    if ledger_path.exists():
        ledger = _require_object(json.loads(ledger_path.read_text(encoding='utf8')), 'toolchain ledger')
        toolchain_items = _require_list(ledger.get('archives'), 'toolchain archives')
        for item in toolchain_items:
            item = _require_object(item, 'toolchain archive')
            component = _require_token(item.get('component'), 'toolchain component')
            version = _require_token(item.get('version'), 'toolchain version')
            expected = _require_sha256(item.get('sha256'), 'toolchain sha256')
            filename = component + '-' + version + '.source'
            selected.append((evidence / 'toolchain' / filename, 'toolchain/' + filename, expected))
    # Duplicate destination identities first, then source presence.
    names = set()
    for source, name, expected in selected:
        safe_path(name)
        if name.casefold() in names:
            raise ValueError('duplicate material destination: ' + name)
        names.add(name.casefold())
    for source, name, expected in selected:
        if not source.is_file() or source.is_symlink() or source.is_junction():
            raise ValueError('material missing or linked: ' + str(source))
    counts = {
        'native_archives': len(native_items),
        'rust_archives': len(rust_items),
        'recipe_archives': len(recipe_items),
        'toolchain_archives': len(toolchain_items),
    }
    return selected, counts


def _manifest(counts, inventory):
    return {
        'schema_version': 1,
        'status': 'internal_source_materials_incomplete',
        'counts': counts,
        'files': inventory,
        'remaining': list(_REMAINING),
        'boundary': _BOUNDARY,
    }


def _verify_bundle(destination, inventory):
    """Re-open the written bundle and confirm member count and every entry hash."""
    with zipfile.ZipFile(destination) as archive:
        if len(archive.namelist()) != len(inventory) + 1:
            raise ValueError('bundle inventory mismatch')
        for item in inventory:
            with archive.open(item['path']) as stream:
                if hashlib.file_digest(stream, 'sha256').hexdigest() != item['sha256']:
                    raise ValueError('written material hash mismatch: ' + item['path'])


def _save_report(stream, report):
    stream.seek(0)
    stream.write(json.dumps(report, indent=2) + "\n")
    stream.truncate()
    stream.flush()
    os.fsync(stream.fileno())


def _write_failure_report(stream, destination, stage, reason, inventory, counts):
    report = {
        'passed': False,
        'status': 'internal_source_materials_build_failed',
        'stage': stage,
        'reason': reason,
        'archive': str(destination.resolve()),
        'entries': list(inventory),
        'counts': counts,
        'boundary': _BOUNDARY,
    }
    _save_report(stream, report)


def build(evidence, destination, root=None):
    """Build and verify the internal source-material ZIP.

    Refuses any existing destination archive or sidecar report before writing. On a
    failure after the output is claimed, a sidecar report is preserved with
    ``passed=false``, the exact stage, the reason and the entries already written;
    the partial archive is never deleted."""
    root = Path(root) if root is not None else ROOT
    evidence = Path(evidence)
    destination = Path(destination)
    report_path = destination.with_suffix('.report.json')
    if destination.exists():
        raise ValueError('output exists; retain previous bundle: ' + str(destination))
    if report_path.exists():
        raise ValueError('report exists; retain previous report: ' + str(report_path))

    notices_dir = root / 'packaging' / 'notices'
    try:
        native = json.loads((notices_dir / 'native-source-materials.json').read_text(encoding='utf8'))
        rust = json.loads((notices_dir / 'native-rust-source-materials.json').read_text(encoding='utf8'))
        recipes = json.loads((notices_dir / 'native-patch-materials.json').read_text(encoding='utf8'))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError('metadata ledger load failed: ' + str(exc)) from exc

    selected, counts = _collect_selected(native, rust, recipes, notices_dir, evidence)

    destination.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation claims the report; keep this handle for every update.
    # A competing writer can never be overwritten through a later path open.
    stream = report_path.open('x+', encoding='utf8')
    inventory = []
    stage = 'claim-output'
    try:
        _write_failure_report(stream, destination, stage, 'build not completed', inventory, counts)
        with zipfile.ZipFile(destination, 'x', compression=zipfile.ZIP_STORED) as archive:
            stage = 'build-entries'
            for source, name, expected in selected:
                raw = source.read_bytes()
                digest = hashlib.sha256(raw).hexdigest()
                if expected and digest != expected:
                    raise ValueError('material checksum mismatch: ' + str(source))
                archive.writestr(name, raw)
                inventory.append({'path': name, 'sha256': digest, 'bytes': len(raw)})
            stage = 'build-manifest'
            manifest = _manifest(counts, inventory)
            archive.writestr(_MANIFEST_NAME, json.dumps(manifest, indent=2) + '\n')
        stage = 'verify-entries'
        _verify_bundle(destination, inventory)
        stage = 'verify-archive'
        with destination.open('rb') as archive_stream:
            digest = hashlib.file_digest(archive_stream, 'sha256').hexdigest()
        report = {
            'passed': True,
            'status': 'internal_material_bundle_verified_not_release_clearance',
            'archive': str(destination.resolve()),
            'sha256': digest,
            'bytes': destination.stat().st_size,
            'counts': counts,
            'verified_entries': len(inventory),
            'remaining': list(_REMAINING),
        }
        stage = 'report-write'
        _save_report(stream, report)
        return report
    except Exception as exc:
        try:
            _write_failure_report(stream, destination, stage, str(exc), inventory, counts)
        except Exception as report_error:
            exc.add_note("Failure report could not be saved: " + str(report_error))
        raise
    finally:
        stream.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--destination', type=Path, required=True)
    args = parser.parse_args()
    try:
        report = build(args.evidence.resolve(strict=True), args.destination)
    except Exception as exc:
        print('build_native_source_materials: ' + str(exc), file=sys.stderr)
        return 1
    print(json.dumps(report))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
