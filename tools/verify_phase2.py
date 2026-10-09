"""Fail-closed release gate; run in the DSH verification virtualenv on Windows."""
from pathlib import Path
import argparse
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime', type=Path)
    parser.add_argument('--repair-fixture-acl', action='store_true')
    args = parser.parse_args()
    checks = [
        ['-m', 'unittest', 'discover', '-s', 'tests_next', '-v'],
        ['-m', 'sumika_next.cli', 'check'],
        ['tools/probe_dsh_next.py'],
        ['tools/verify_dsh_p2.py'],
        ['tools/verify_dsh_recovery.py'],
    ]
    for check in checks:
        if args.runtime and check[0].startswith('tools/'):
            check = [*check, '--runtime', str(args.runtime.resolve())]
            if args.repair_fixture_acl and check[0].endswith('verify_dsh_p2.py'):
                check.append('--repair-fixture-acl')
        subprocess.run([sys.executable, '-X', 'utf8', '-B', *check], cwd=ROOT, check=True)
    print('P2 RELEASE GATE PASSED (loopback model; no model-quality claim)')


if __name__ == '__main__':
    main()
