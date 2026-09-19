"""Inventory shipped dependency declarations and notices; never infer legal approval.

Reads the verified physical package, not the development dependency links. Output
is review evidence, not a complete source/provenance or redistribution clearance.

Exit codes: 0 for a completed inventory, and 0 as well when findings exist unless
--fail-on-findings was requested. With that flag a complete report is still written
first, and the process then returns 2 to mark a release-audit finding gate failure.
A 0 result never means the licenses were approved.
"""
import argparse
from collections import Counter
from email.parser import Parser
import json
import re
from pathlib import Path

try:
    from .verify_portable_staging import verify, digest
except ImportError:
    from verify_portable_staging import verify, digest


EMBEDDED_REVIEW_KIND = 'verbatim_complete_mit_readme_v1'
MIT_TERMS = '''Permission is hereby granted, free of charge, to any person obtaining
a copy of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights to use,
copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the
Software, and to permit persons to whom the Software is furnished to do so, subject
to the following conditions:
The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.
THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED,
INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A
PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT
HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE
SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.'''


def complete_mit_excerpt(text):
    """Recognize complete standard MIT terms, never keyword/length heuristics.

    Quote style and whitespace normalization here only classify terms. The
    separate README comparison retains every byte except CRLF line endings.
    Unrecognized variants remain candidates for human review.
    """
    copyright, separator, terms = text.partition('Permission is hereby granted')
    lines = [line.strip() for line in copyright.splitlines() if line.strip()]
    if not lines or not all(re.fullmatch(r'Copyright \(c\) \d{4}(?:-\d{4})? .+', line) for line in lines):
        return False
    normalize = lambda value: ' '.join(value.replace("'", '"').split())
    return bool(separator) and normalize(separator + terms) == normalize(MIT_TERMS)


def reviewed_embedded_notice(root, row, candidate, sources):
    """Match reviewed package identity, both hashes, exact path and full excerpt."""
    for source in sources:
        binding = source.get('dependency', {})
        if (source.get('review_kind') != EMBEDDED_REVIEW_KIND or source.get('unresolved')
                or any(binding.get(key) != row.get(key)
                       for key in ('ecosystem', 'name', 'version', 'manifest_sha256'))
                or source.get('source_artifact') != candidate['path']
                or source.get('source_sha256') != candidate['sha256']):
            continue
        file = source.get('file')
        if not isinstance(file, str) or file in ('', '.', '..') or '/' in file or '\\' in file:
            continue
        notice = root/'licenses'/file
        if (not notice.resolve().is_relative_to((root/'licenses').resolve())
                or not notice.is_file() or digest(notice) != source.get('sha256')):
            continue
        try:
            excerpt = notice.read_bytes().decode('utf8').replace('\r\n', '\n')
            readme = (root/candidate['path']).read_bytes().decode('utf8').replace('\r\n', '\n')
        except UnicodeDecodeError:
            continue
        if complete_mit_excerpt(excerpt) and excerpt in readme:
            return {'path': notice.relative_to(root).as_posix(), 'sha256': source['sha256'],
                    'review_kind': EMBEDDED_REVIEW_KIND,
                    'boundary': 'Exact previously reviewed excerpt; not redistribution clearance.'}
    return None


def notice_files(root):
    paths = []
    for folder in (root, root / 'licenses', root / 'LICENSES'):
        if not folder.is_dir():
            continue
        for file in folder.iterdir():
            name = file.name.lower()
            if file.is_file() and (name.startswith(('license', 'licence', 'notice', 'copying', 'copyright'))
                                   or folder != root):
                paths.append(file)
    return sorted(set(paths))


def sharp_component_coverage(text, versions):
    """Join the shipped sharp table in both directions; never infer a license."""
    aliases = {'libarchive':'archive', 'libexif':'exif', 'libffi':'ffi',
               'libheif':'heif', 'libimagequant':'imagequant', 'libpng':'png',
               'librsvg':'rsvg', 'libtiff':'tiff', 'libultrahdr':'uhdr',
               'libvips':'vips', 'libwebp':'webp', 'libxml2':'xml2'}
    declared = {}
    in_table = False
    for line in text.splitlines():
        cells = [cell.strip() for cell in line.strip().strip('|').split('|')]
        if line.strip().startswith('|') and len(cells) == 2 and cells[0] == 'Library':
            in_table = True
            continue
        if not in_table:
            continue
        if not line.strip().startswith('|'):
            break
        if len(cells) != 2 or re.fullmatch(r'[-: ]+', cells[0]):
            continue
        name, terms = cells
        key = aliases.get(name, name)
        if key in declared:
            raise ValueError('duplicate sharp component declaration')
        declared[key] = {'name': key, 'declared_name': name, 'terms': terms,
                         'version': versions.get(key)}
    return {'components': list(declared.values()),
            'declared_without_version': sorted(set(declared)-set(versions)),
            'version_without_declaration': sorted(set(versions)-set(declared)),
            'table_found': in_table,
            'boundary': 'Shipped metadata comparison only; not binary/source or license compliance verification.'}


def audit(root):
    inventory = verify(root)
    sources_path = root/'licenses/sources.json'
    supplemental = json.loads(sources_path.read_text(encoding='utf8')).get('sources', []) if sources_path.is_file() else []
    rows = []
    # Only package roots immediately under node_modules (including scoped and
    # nested installs); examples' package.json files are not installed packages.
    for manifest in (root / 'runtime/dsh/node_modules').rglob('package.json'):
        package = manifest.parent
        if package.parent.name != 'node_modules' and not (
                package.parent.name.startswith('@') and package.parent.parent.name == 'node_modules'):
            continue
        metadata = json.loads(manifest.read_text(encoding='utf8'))
        if not isinstance(metadata.get('name'), str) or not isinstance(metadata.get('version'), str):
            raise ValueError('installed package missing name/version: ' + str(manifest.relative_to(root)))
        rows.append({'ecosystem': 'npm', 'name': metadata['name'], 'version': metadata['version'],
                     'declaration': metadata.get('license', metadata.get('licenses')),
                     'manifest': manifest, 'notices': notice_files(package)})
    for metadata_file in (root / 'runtime/python/Lib/site-packages').glob('*.dist-info/METADATA'):
        metadata = Parser().parsestr(metadata_file.read_text(encoding='utf8'))
        declared = metadata.get('License-Expression') or metadata.get('License')
        classifiers = [value for value in metadata.get_all('Classifier', []) if value.startswith('License ::')]
        notices = notice_files(metadata_file.parent)
        for name in metadata.get_all('License-File', []):
            for file in (metadata_file.parent / name, metadata_file.parent / 'licenses' / name):
                if file.is_file() and file.resolve().is_relative_to(metadata_file.parent.resolve()):
                    notices.append(file)
        rows.append({'ecosystem': 'python', 'name': metadata['Name'], 'version': metadata['Version'],
                     'declaration': declared, 'classifiers': classifiers,
                     'manifest': metadata_file, 'notices': sorted(set(notices))})
    for row in rows:
        manifest = row['manifest']
        embedded = []
        for readme in manifest.parent.glob('README*'):
            if readme.is_file():
                text = readme.read_text(encoding='utf8', errors='replace')
                if 'Permission is hereby granted' in text and 'THE SOFTWARE IS PROVIDED' in text:
                    embedded.append({'path': readme.relative_to(root).as_posix(), 'sha256': digest(readme),
                                     'status': 'license_text_candidate_manual_review_required'})
        row['embedded_notice_candidates'] = embedded
        versions = manifest.parent / 'versions.json'
        if versions.is_file():
            row['bundled_components'] = json.loads(versions.read_text(encoding='utf8'))
            if row['name'] == '@img/sharp-win32-x64':
                readme = manifest.parent/'README.md'
                row['component_coverage'] = sharp_component_coverage(
                    readme.read_text(encoding='utf8') if readme.is_file() else '',
                    row['bundled_components'])
        row['manifest'] = manifest.relative_to(root).as_posix()
        row['manifest_sha256'] = digest(manifest)
        row['notices'] = [{'path': file.relative_to(root).as_posix(), 'sha256': digest(file)} for file in row['notices']]
        row['supplemental_notices'] = match_supplemental_notices(root, row, supplemental)
        for candidate in embedded:
            review = reviewed_embedded_notice(root, row, candidate, supplemental)
            if review:
                candidate.update(status='verified_reviewed_excerpt', review=review)
        row['findings'] = []
        if not row['declaration'] or str(row['declaration']).upper() in ('UNKNOWN', 'UNLICENSED'):
            row['findings'].append('missing_or_restricted_license_declaration')
        if not row['notices'] and not embedded and not row['supplemental_notices']:
            row['findings'].append('no_package_license_file_found')
        if any(candidate['status'] != 'verified_reviewed_excerpt' for candidate in embedded):
            row['findings'].append('embedded_license_text_requires_review')
        if any(item.get('unresolved') for item in row['supplemental_notices']):
            row['findings'].append('supplemental_notice_obligations_unresolved')
        if row.get('bundled_components'):
            row['findings'].append('native_component_licenses_require_review')
        coverage = row.get('component_coverage', {})
        if coverage and (not coverage['table_found'] or coverage['declared_without_version']
                         or coverage['version_without_declaration']):
            row['findings'].append('native_component_metadata_incomplete')
        # These are review priorities only. Even MIT requires preserving notices.
        declared = str(row['declaration']).upper()
        if any(term in declared for term in ('GPL', 'MPL', 'BUSL', 'SSPL', 'SEE LICENSE', 'CUSTOM')):
            row['findings'].append('terms_require_specific_review')
    rows.sort(key=lambda row: (row['ecosystem'], row['name'], row['version'], row['manifest']))
    return {'schema_version': 1, 'status': 'inventory_only_review_required', 'package': inventory,
            'counts': dict(Counter(row['ecosystem'] for row in rows)),
            'finding_counts': dict(Counter(finding for row in rows for finding in row['findings'])),
            'declarations': dict(Counter(str(row['declaration']) for row in rows)),
            'dependencies': rows,
            'boundary': 'Declarations and shipped notice files only. Does not verify rights, bundled transitive code, native binary contents, model/asset licenses, or source availability. No automatic license clearance.'}


def match_supplemental_notices(root, row, sources):
    """Only associate reviewed sidecar notices with the exact installed manifest."""
    matches = []
    for source in sources:
        binding = source.get('dependency', {})
        if not binding or any(binding.get(key) != row.get(key) for key in ('ecosystem', 'name', 'version', 'manifest_sha256')):
            continue
        file = source.get('file')
        if not isinstance(file, str) or '/' in file or '\\' in file or file in ('.', '..'):
            raise ValueError('invalid supplemental notice path')
        notice = root/'licenses'/file
        if not notice.resolve().is_relative_to((root/'licenses').resolve()) or not notice.is_file() or digest(notice) != source.get('sha256'):
            raise ValueError('supplemental notice missing or changed')
        matches.append({'path':notice.relative_to(root).as_posix(), 'sha256':source['sha256'],
                        'url':source.get('url'), 'commit':source.get('commit'),
                        'license_scope':source.get('license_scope'),
                        'unresolved':source.get('unresolved', []),
                        'boundary':'Source notice association only; not complete redistribution clearance.'})
    return matches


def finding_total(report):
    """Count dependency rows carrying at least one finding.

    Review priorities are per-dependency, so the release gate is derived from
    ``dependencies`` rather than from a summary field.
    """
    return sum(1 for row in report['dependencies'] if row.get('findings'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('package', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--fail-on-findings', action='store_true',
                        help='release-gate mode: after writing the complete report, return exit code 2 '
                             'when any dependency findings exist, otherwise 0. The default invocation '
                             'returns 0 even with findings because this is an inventory, not legal clearance.')
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError('output must be new; retain previous audit')
    report = audit(args.package.resolve(strict=True))
    # The report is complete evidence before the gate decides; a failing gate
    # must still leave the full inventory behind for review.
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf8') as output:
        json.dump(report, output, ensure_ascii=False, indent=2)
    print(json.dumps({key: report[key] for key in ('status', 'counts', 'finding_counts', 'declarations')}, indent=2))
    if args.fail_on_findings and finding_total(report):
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
