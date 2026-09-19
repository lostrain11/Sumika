"""Cache Cargo.lock source archives without installing or executing Rust code.

The complete lock is a conservative source-material superset, not a list of
libraries proven to be linked into the shipped Windows binary.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
import re
import tarfile
import tomllib
import urllib.request


def registry_packages(lock):
    result = []
    identities = set()
    for row in lock['package']:
        source = row.get('source')
        if source is None:
            continue
        if source != 'registry+https://github.com/rust-lang/crates.io-index':
            raise ValueError('Unsupported Cargo source; inspect before fetching')
        name, version, checksum = row['name'], row['version'], row.get('checksum', '')
        if (not re.fullmatch(r'[A-Za-z0-9_-]+', name)
                or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.+_-]*', version)
                or not re.fullmatch(r'[a-f0-9]{64}', checksum)):
            raise ValueError('Invalid Cargo source identity')
        if (name, version) in identities:
            raise ValueError('Duplicate Cargo source identity')
        identities.add((name, version))
        result.append({'name': name, 'version': version, 'sha256': checksum})
    return result


def fetch(row, destination):
    result = dict(row)
    stem = row['name']+'-'+row['version']
    archive = destination/(stem+'.crate')
    url = 'https://static.crates.io/crates/'+row['name']+'/'+stem+'.crate'
    result['url'] = url
    try:
        if not archive.exists():
            with urllib.request.urlopen(url, timeout=30) as response, archive.open('xb') as output:
                while chunk := response.read(1024*1024):
                    output.write(chunk)
        with archive.open('rb') as stream:
            actual = hashlib.file_digest(stream, 'sha256').hexdigest()
        if actual != row['sha256']:
            raise ValueError('Source checksum mismatch; retained without acceptance')
        result['bytes'] = archive.stat().st_size
        with tarfile.open(archive) as content:
            member = content.getmember(stem+'/Cargo.toml')
            if not member.isfile() or member.size > 4*1024*1024:
                raise ValueError('Invalid source manifest')
            package = tomllib.loads(content.extractfile(member).read().decode('utf8'))['package']
            if package['name'] != row['name'] or package['version'] != row['version']:
                raise ValueError('Manifest identity mismatch')
            result['declared_license'] = package.get('license')
            result['declared_license_file'] = package.get('license-file')
            result['notice_members'] = [m.name for m in content.getmembers()
                if m.isfile() and Path(m.name).name.upper().startswith(
                    ('LICENSE', 'LICENCE', 'COPYING', 'COPYRIGHT', 'NOTICE', 'PATENTS'))]
        result['verified'] = True
    except Exception as error:
        result.update(verified=False, error=str(error))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('lock', type=Path)
    parser.add_argument('destination', type=Path)
    args = parser.parse_args()
    raw = args.lock.read_bytes()
    rows = registry_packages(tomllib.loads(raw.decode('utf8')))
    args.destination.mkdir(parents=True, exist_ok=True)
    results = []
    report = {'lock_sha256': hashlib.sha256(raw).hexdigest(),
              'scope': 'All registry entries in exact lock; includes optional/build/test dependencies; no linked-runtime claim',
              'packages': results, 'complete': False}
    def save():
        (args.destination/'report.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf8')
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = [pool.submit(fetch, row, args.destination) for row in rows]
        for future in as_completed(futures):
            results.append(future.result())
            if len(results) % 25 == 0:
                save()
                print(f'{len(results)}/{len(rows)} source archives inspected', flush=True)
    results.sort(key=lambda r: (r['name'], r['version']))
    report['complete'] = len(results) == len(rows) and all(r['verified'] for r in results)
    save()
    print(json.dumps({'complete':report['complete'], 'verified':sum(r['verified'] for r in results),
                      'total':len(rows), 'report':str(args.destination/'report.json')}))
    if not report['complete']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
