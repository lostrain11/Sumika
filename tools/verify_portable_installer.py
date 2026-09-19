"""Exercise the installer with bounded fixtures; retain evidence on D:."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
import uuid
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    base = ROOT / '.sumika-next/package' / ('installer-check-' + uuid.uuid4().hex)
    base.mkdir(parents=True)
    script = ROOT / 'packaging/install_sumika.ps1'
    archive = base / 'fixture.zip'
    files = {name: b'fixture-not-executable' for name in (
        'Sumika.exe', 'tools/start_sumika.ps1', 'tools/start_ui_bridge.ps1',
        'ui/server.py', 'sumika_next/cli.py', 'runtime/dsh/release.json')}
    files['tools/nested/file.txt'] = b'exact contents'
    # Exceeds MAX_PATH even under a short checkout. Do not shorten destinations
    # or rely on host registry LongPathsEnabled for this regression.
    long_member = 'runtime/dsh/' + '/'.join(['long-component-' + str(i) + '-' + 'x' * 35 for i in range(5)]) + '/file.txt'
    files[long_member] = b'long path contents'
    for name in ('context.js', 'auxiliary.py', 'COM10.txt', '\u4e2d\u6587.png'):
        files['ui/'+name] = b'valid filename'
    manifest = {'kind': 'portable-staging', 'schema_version': 2, 'files': [
        {'path': name, 'size': len(body), 'sha256': hashlib.sha256(body).hexdigest()}
        for name, body in files.items()]}
    with zipfile.ZipFile(archive, 'x') as z:
        for name, body in files.items():
            z.writestr(name, body)
        z.writestr('package-manifest.json', json.dumps(manifest))
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()

    def run(src, dest, sha, *options):
        return subprocess.run(['powershell.exe', '-NoProfile', '-File', str(script),
                               '-Archive', str(src), '-Destination', str(dest),
                               '-Sha256', sha, *options], capture_output=True,
                              encoding='utf8', errors='replace', timeout=30)

    preview = base / 'preview'
    result = run(archive, preview, digest, '-WhatIf')
    assert result.returncode == 0 and not preview.exists(), result.stderr
    dest = base / 'installed'
    result = run(archive, dest, digest)
    assert result.returncode == 0, result.stderr
    assert (dest / 'tools/nested/file.txt').read_text() == 'exact contents'
    assert all((dest/name).read_bytes() == value for name, value in files.items())
    # Instrument only a retained test copy at the boundary after hashing.
    # A second writer or rename must be refused until extraction completes.
    guarded_script = base / 'verify-held-archive.ps1'
    guard = r'''
$writerBlocked = $false
try {
    $probe = [IO.File]::Open($archivePath, [IO.FileMode]::Open, [IO.FileAccess]::Write, [IO.FileShare]::ReadWrite)
    $probe.Dispose()
} catch [IO.IOException] { $writerBlocked = $true }
if (-not $writerBlocked) { throw 'Verified archive admitted a writer' }
$renameBlocked = $false
try { [IO.File]::Move($archivePath, $archivePath + '.moved') }
catch [IO.IOException] { $renameBlocked = $true }
if (-not $renameBlocked) {
    [IO.File]::Move($archivePath + '.moved', $archivePath)
    throw 'Verified archive admitted replacement by rename'
}
'''
    original_script = script
    source = script.read_text(encoding='utf8')
    marker = '# Stage beside the destination'
    assert source.count(marker) == 1
    guarded_script.write_text(source.replace(marker, guard+'\n'+marker), encoding='utf8')
    script = guarded_script
    try:
        guarded_destination = base / 'held-archive-install'
        result = run(archive, guarded_destination, digest)
        assert result.returncode == 0, result.stderr
        assert all((guarded_destination/name).read_bytes() == body for name, body in files.items())
    finally:
        script = original_script
    with archive.open('r+b'):
        pass  # Installer released its handle after completion.
    assert run(archive, dest, digest).returncode != 0
    empty_destination = base / 'existing-empty'
    empty_destination.mkdir()
    before = set(base.glob('sumika-install-*'))
    result = run(archive, empty_destination, digest)
    assert result.returncode != 0
    assert not list(empty_destination.iterdir())
    assert set(base.glob('sumika-install-*')) == before
    assert run(archive, base / 'bad-hash', '0' * 64).returncode != 0
    for name in ('../escape.txt', 'C:/escape.txt', '.sumika-next/personal.txt'):
        bad = base / (uuid.uuid4().hex + '.zip')
        with zipfile.ZipFile(bad, 'x') as z:
            z.writestr('Sumika.exe', b'fixture')
            z.writestr('package-manifest.json', '{}')
            z.writestr(name, 'blocked')
        rejected = base / ('rejected-' + uuid.uuid4().hex)
        assert run(bad, rejected, hashlib.sha256(bad.read_bytes()).hexdigest()).returncode != 0
        assert not rejected.exists()
    for scenario in ('legacy', 'tampered', 'extra', 'missing', 'duplicate', 'hierarchy', 'nested-data', 'credentials', 'updater-residue'):
        bad = base / (scenario + '.zip')
        bad_files = dict(files)
        bad_manifest = json.loads(json.dumps(manifest))
        if scenario == 'legacy':
            bad_manifest = {'kind': 'portable-staging', 'status': 'smoke-tested'}
        elif scenario == 'tampered':
            bad_files['Sumika.exe'] = b'X' * len(files['Sumika.exe'])
        elif scenario == 'extra':
            bad_files['ui/extra.py'] = b'not in inventory'
        elif scenario == 'missing':
            bad_files.pop('ui/server.py')
        elif scenario == 'duplicate':
            bad_manifest['files'].append(dict(bad_manifest['files'][0]))
        elif scenario == 'hierarchy':
            for name in ('ui/Asset', 'ui/asset/icon.png'):
                body = b'conflicting file tree'
                bad_files[name] = body
                bad_manifest['files'].append({'path':name, 'size':len(body), 'sha256':hashlib.sha256(body).hexdigest()})
        else:
            name = 'runtime/dsh/.sumika-next/personal.json' if scenario == 'nested-data' else 'runtime/dsh/.env.local'
            if scenario == 'updater-residue':
                name = 'runtime/browserskill/bsk.exe.update-1.cmd'
            body = b'synthetic'
            bad_files[name] = body
            bad_manifest['files'].append({'path': name, 'size': len(body), 'sha256': hashlib.sha256(body).hexdigest()})
        with zipfile.ZipFile(bad, 'x') as z:
            for name, body in bad_files.items():
                z.writestr(name, body)
            z.writestr('package-manifest.json', json.dumps(bad_manifest))
        rejected = base / ('rejected-' + scenario)
        before = set(base.glob('sumika-install-*'))
        result = run(bad, rejected, hashlib.sha256(bad.read_bytes()).hexdigest())
        assert result.returncode != 0, scenario
        assert not rejected.exists(), scenario
        assert set(base.glob('sumika-install-*')) == before, scenario
    rejected_names = ('CON.txt', 'CON .txt', 'COM\u00b9.txt', 'LPT\u00b2.txt',
                      'CONIN$', 'CONOUT$.txt', 'a\x01b', 'a\x7fb', 'a?b')
    for index, component in enumerate(rejected_names):
        bad = base/('windows-name-'+str(index)+'.zip')
        name, body = 'ui/'+component, b'must-not-extract'
        bad_manifest = json.loads(json.dumps(manifest))
        bad_manifest['files'].append({'path': name, 'size': len(body), 'sha256': hashlib.sha256(body).hexdigest()})
        with zipfile.ZipFile(bad, 'x') as z:
            for valid, value in files.items():
                z.writestr(valid, value)
            z.writestr(name, body)
            z.writestr('package-manifest.json', json.dumps(bad_manifest))
        rejected = base/('windows-rejected-'+str(index))
        before = set(base.glob('sumika-install-*'))
        result = run(bad, rejected, hashlib.sha256(bad.read_bytes()).hexdigest())
        (base/('windows-rejection-'+str(index)+'.txt')).write_text(result.stdout+result.stderr, encoding='utf8')
        assert result.returncode != 0, index
        assert not rejected.exists() and set(base.glob('sumika-install-*')) == before, index
    # Interrupt the real installer during extraction, after inventory validation.
    # Only this retained Popen handle is stopped; no port/PID discovery or deletion.
    personal = base/'personal-data'
    personal.mkdir()
    (personal/'sentinel.txt').write_text('private data must stay unchanged', encoding='utf8')
    interrupted_archive = base/'interruption-fixture.zip'
    block = os.urandom(1024 * 1024)
    large_files = dict(files)
    large_files.update({f'ui/payload-{index:03}.bin':block for index in range(64)})
    large_manifest = {'kind':'portable-staging','schema_version':2,'files':[
        {'path':name,'size':len(body),'sha256':hashlib.sha256(body).hexdigest()}
        for name,body in large_files.items()]}
    with zipfile.ZipFile(interrupted_archive,'x') as z:
        for name,body in large_files.items():
            z.writestr(name,body)
        z.writestr('package-manifest.json',json.dumps(large_manifest))
    checksum=hashlib.sha256(interrupted_archive.read_bytes()).hexdigest()
    interrupted_destination=base/'interrupted-destination'
    prior_staging=set(base.glob('sumika-install-*'))
    stopped_during_extraction=False
    with (base/'interrupted-install.txt').open('w',encoding='utf8') as log:
        process=subprocess.Popen(['powershell.exe','-NoProfile','-File',str(script),
            '-Archive',str(interrupted_archive),'-Destination',str(interrupted_destination),
            '-Sha256',checksum],stdout=log,stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        try:
            deadline=time.monotonic()+60
            while process.poll() is None and time.monotonic()<deadline:
                staging=set(base.glob('sumika-install-*'))-prior_staging
                if any((folder/'Sumika.exe').exists() for folder in staging):
                    process.terminate()
                    process.wait(timeout=10)
                    stopped_during_extraction=True
                    break
                time.sleep(.005)
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=10)
    assert stopped_during_extraction, 'extraction interruption was not observed'
    assert not interrupted_destination.exists(), 'partial destination published'
    retained_staging=set(base.glob('sumika-install-*'))-prior_staging
    assert len(retained_staging)==1
    def hashes(directory):
        return {str(p.relative_to(directory)):hashlib.sha256(p.read_bytes()).hexdigest()
                for p in directory.rglob('*') if p.is_file()}
    interrupted_hashes={str(p):hashes(p) for p in retained_staging}
    result=run(interrupted_archive,interrupted_destination,checksum)
    (base/'retry-install.txt').write_text(result.stdout+result.stderr,encoding='utf8')
    assert result.returncode==0, result.stderr
    assert all((interrupted_destination/name).read_bytes()==body for name,body in large_files.items())
    assert interrupted_hashes=={str(p):hashes(p) for p in retained_staging}
    assert all((dest/name).read_bytes()==body for name,body in files.items())
    assert (personal/'sentinel.txt').read_text(encoding='utf8')=='private data must stay unchanged'
    # A concurrent actor claims the destination after extraction starts.
    # The installer must not merge any release files into that directory.
    raced_destination = base / 'concurrent-destination'
    prior_staging = set(base.glob('sumika-install-*'))
    destination_claimed = False
    with (base/'publication-conflict.txt').open('w', encoding='utf8') as log:
        process = subprocess.Popen(['powershell.exe', '-NoProfile', '-File', str(script),
            '-Archive', str(interrupted_archive), '-Destination', str(raced_destination),
            '-Sha256', checksum], stdout=log, stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        try:
            deadline = time.monotonic() + 60
            while process.poll() is None and time.monotonic() < deadline:
                staging = set(base.glob('sumika-install-*')) - prior_staging
                if any((folder/'Sumika.exe').exists() for folder in staging):
                    raced_destination.mkdir()
                    (raced_destination/'owner.txt').write_text('other owner', encoding='utf8')
                    destination_claimed = True
                    break
                time.sleep(.005)
            returncode = process.wait(timeout=30)
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=10)
    assert destination_claimed, 'publication conflict was not injected'
    assert returncode != 0, 'conflicting destination accepted'
    assert hashes(raced_destination) == {
        'owner.txt': hashlib.sha256(b'other owner').hexdigest()}
    conflict_staging = set(base.glob('sumika-install-*')) - prior_staging
    assert len(conflict_staging) == 1
    staged = next(iter(conflict_staging))
    assert all((staged/name).read_bytes() == body for name, body in large_files.items())
    assert all((dest/name).read_bytes() == body for name, body in files.items())
    assert (personal/'sentinel.txt').read_text(encoding='utf8') == 'private data must stay unchanged'
    report = {'status': 'passed', 'scope': 'synthetic installer boundary fixtures and actual extraction interruption; no executable product startup',
              'interruption': {'observed_after_first_file':True,'partial_destination_absent':True,
                               'retry_complete':True,'failed_staging_preserved':True,
                               'old_install_and_personal_data_unchanged':True},
              'windows_name_rejections': len(rejected_names), 'valid_unicode_and_similar_names': True,
              'archive_identity': {'write_and_rename_refused_after_hash': True,
                                   'same_handle_extracts_exact_files': True,
                                   'handle_released_after_completion': True},
              'publication': {'existing_empty_refused_before_staging': True,
                              'concurrent_destination_untouched': True,
                              'complete_conflict_staging_retained': True},
              'long_path': {'member': long_member, 'installed_path_length': len(str(dest/long_member)), 'contents_verified': (dest/long_member).read_bytes() == files[long_member]},
              'checks': ['exact extraction', 'extended length path extraction', 'what-if has no writes', 'no overwrite',
                         'hash mismatch', 'path traversal', 'absolute path', 'runtime-data root',
                         'legacy manifest', 'tampered entry', 'unlisted entry', 'missing entry',
                         'duplicate inventory', 'file-ancestor conflict before extraction', 'nested runtime data', 'credential file', 'updater residue']}
    (base / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf8')
    print(base)
    print(json.dumps(report))


if __name__ == '__main__':
    main()
