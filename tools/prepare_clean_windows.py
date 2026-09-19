"""Prepare an opt-in Windows Sandbox acceptance bundle; never enable or launch it."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import uuid
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]


def configuration(inputs, results):
    root = ET.Element('Configuration')
    for key, value in {'Networking':'Disable', 'ClipboardRedirection':'Disable',
                       'AudioInput':'Disable', 'VideoInput':'Disable',
                       'PrinterRedirection':'Disable', 'MemoryInMB':'4096'}.items():
        ET.SubElement(root, key).text = value
    folders = ET.SubElement(root, 'MappedFolders')
    for source, destination, readonly in (
        (inputs, r'C:\SumikaAcceptanceInput', True),
        (results, r'C:\SumikaAcceptanceResults', False),
    ):
        item = ET.SubElement(folders, 'MappedFolder')
        for key, value in {'HostFolder':str(source), 'SandboxFolder':destination,
                           'ReadOnly':str(readonly).lower()}.items():
            ET.SubElement(item, key).text = value
    command = ET.SubElement(root, 'LogonCommand')
    ET.SubElement(command, 'Command').text = (
        'powershell.exe -NoProfile -ExecutionPolicy Bypass -File '
        'C:\\SumikaAcceptanceInput\\verify_clean_windows.ps1')
    ET.indent(root)
    return ET.tostring(root, encoding='unicode')


def prepare(archive, expected, destination):
    archive = archive.resolve(strict=True)
    if destination.exists():
        raise ValueError('Use a new bundle directory; existing evidence is preserved')
    with archive.open('rb') as stream:
        actual = hashlib.file_digest(stream, 'sha256').hexdigest()
    if actual != expected.lower():
        raise ValueError('Archive SHA256 mismatch')
    destination.mkdir(parents=True)
    inputs, results = destination/'input', destination/'results'
    inputs.mkdir(); results.mkdir()
    copied = inputs/'Sumika-internal.zip'
    shutil.copyfile(archive, copied)
    with copied.open('rb') as stream:
        if hashlib.file_digest(stream, 'sha256').hexdigest() != actual:
            raise ValueError('Archive changed during preparation; bundle is not ready')
    assets = ['packaging/install_sumika.ps1', 'packaging/verify_clean_windows.ps1',
              'tools/verify_portable_staging.py', 'tools/verify_portable_exe.py']
    hashes = {}
    for asset in assets:
        target = inputs/Path(asset).name
        shutil.copyfile(ROOT/asset, target)
        hashes[target.name] = hashlib.sha256(target.read_bytes()).hexdigest()
    spec = {'archive_sha256':actual, 'verifiers':hashes,
            'status':'prepared_not_executed',
            'limits':'Requires Windows Sandbox. No feature activation, launch, clean-machine result or redistribution clearance implied.'}
    (inputs/'input.json').write_text(json.dumps(spec, indent=2)+'\n', encoding='utf8')
    (destination/'acceptance.wsb').write_text(configuration(inputs.resolve(), results.resolve()), encoding='utf8')
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive', type=Path)
    parser.add_argument('--sha256', required=True)
    parser.add_argument('--destination', type=Path)
    args = parser.parse_args()
    target = args.destination or ROOT/'.sumika-next/package'/('clean-windows-'+uuid.uuid4().hex)
    print(prepare(args.archive, args.sha256, target))


if __name__ == '__main__':
    main()
