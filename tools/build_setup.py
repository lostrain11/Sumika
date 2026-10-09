"""Build an internal Inno Setup wizard from a verified portable candidate."""
import argparse
import hashlib
import json
import re
from pathlib import Path
import subprocess
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.verify_portable_staging import verify


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('candidate', type=Path)
    parser.add_argument('--compiler', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--version', help='Explicit internal build version, e.g. 2026.10.08-f')
    args = parser.parse_args()
    if args.version is not None and not re.fullmatch(r'[0-9][A-Za-z0-9.-]{0,63}', args.version):
        raise ValueError('Invalid build version')
    candidate = args.candidate.resolve(strict=True)
    compiler = args.compiler.resolve(strict=True)
    output = args.output.absolute()
    if output.exists():
        raise ValueError('Output must be a new directory; existing installers are preserved')
    inventory = verify(candidate)
    output.mkdir(parents=True)
    source = Path(__file__).resolve().parents[1] / 'packaging/Sumika.iss'
    report = {'passed': False, 'inventory': inventory, 'scope': 'Internal installer build, not installation acceptance'}
    try:
        command = [str(compiler), '/Qp', '/DProductDir='+str(candidate), '/DOutputDir='+str(output)]
        if args.version:
            command.append('/DBuildVersion='+args.version)
        command.append(str(source))
        result = subprocess.run(command,
                                capture_output=True, timeout=600)
        (output/'compiler.log').write_bytes(result.stdout + b'\n' + result.stderr)
        if result.returncode != 0:
            raise RuntimeError('Compiler failed; see compiler.log')
        files = list(output.glob('Sumika-Setup-*.exe'))
        if len(files) != 1:
            raise ValueError('Expected one installer')
        with files[0].open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        report.update(passed=True, installer=str(files[0]), sha256=digest,
                      requested_version=args.version,
                      script_sha256=hashlib.sha256(source.read_bytes()).hexdigest())
    finally:
        (output/'build-report.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
