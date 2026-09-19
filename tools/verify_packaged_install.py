"""Archive, install and launch an internal candidate; never publish or replace it.

Keeps all artifacts under the candidate parent on D:. This exercises the real
installer and EXE on the current host, not clean-machine or license acceptance.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import uuid
import zipfile

from verify_portable_staging import verify, digest

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('candidate', type=Path)
    args = parser.parse_args()
    candidate = args.candidate.resolve(strict=True)
    original = verify(candidate)
    base = candidate.parent/('packaged-install-'+uuid.uuid4().hex)
    base.mkdir()
    archive, installed = base/'Sumika-internal.zip', base/'installed product'
    report = {'passed': False, 'scope': 'Current-host archive/install/EXE acceptance only',
              'checks': {}, 'source_inventory': original}

    def run(label, command):
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True,
                                encoding='utf8', errors='replace', timeout=600)
        (base/(label+'.txt')).write_text(result.stdout+'\n'+result.stderr, encoding='utf8')
        if result.returncode:
            raise RuntimeError(label+' failed; inspect retained log')
        return result.stdout

    try:
        manifest = (candidate/'package-manifest.json').read_bytes()
        inventory = json.loads(manifest)['files']
        with zipfile.ZipFile(archive, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=1) as output:
            output.writestr('package-manifest.json', manifest)
            for row in inventory:
                output.write(candidate/row['path'], row['path'])
        # Check archived bytes, not just the source that was previously checked.
        with zipfile.ZipFile(archive) as payload:
            assert len(payload.infolist()) == len(inventory)+1
            for row in inventory:
                with payload.open(row['path']) as stream:
                    actual = hashlib.file_digest(stream, 'sha256').hexdigest()
                assert actual == row['sha256'], 'source changed while archiving'
                assert payload.getinfo(row['path']).file_size == row['size']
        checksum = digest(archive)
        report.update(archive=str(archive), sha256=checksum)
        report['checks']['archived_bytes_match_inventory'] = True
        print('Archive verified; installing isolated candidate', flush=True)
        run('install', ['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass',
                        '-File', str(ROOT/'packaging/install_sumika.ps1'),
                        '-Archive', str(archive), '-Destination', str(installed), '-Sha256', checksum])
        report['installed_inventory'] = verify(installed)
        report['checks']['real_installer_and_installed_inventory'] = True
        output = run('exe', [sys.executable, '-B', str(ROOT/'tools/verify_portable_exe.py'), str(installed)])
        # The child verifier writes its evidence under this unique directory.
        evidence = list(base.glob('exe-startup-*/report.json'))
        assert len(evidence) == 1, 'missing or ambiguous EXE evidence'
        result = json.loads(evidence[0].read_text(encoding='utf8'))
        assert result['passed'] and result.get('test_bridge_stopped'), 'EXE lifecycle incomplete'
        report['exe_evidence'] = str(evidence[0])
        report['checks']['installed_exe_launch_reuse_conflict_and_stop'] = True
        report['passed'] = True
    finally:
        (base/'report.json').write_text(json.dumps(report, indent=2), encoding='utf8')
        print('ARTIFACT', base, json.dumps(report), flush=True)


if __name__ == '__main__':
    main()
