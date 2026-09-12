"""Fail-closed release gate; run in the DSH verification virtualenv on Windows."""
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    checks = [
        ['-m', 'unittest', 'discover', '-s', 'tests_next', '-v'],
        ['-m', 'sumika_next.cli', 'check'],
        ['tools/probe_dsh_next.py'],
        ['tools/verify_dsh_p2.py'],
        ['tools/verify_dsh_recovery.py'],
    ]
    for check in checks:
        subprocess.run([sys.executable, '-X', 'utf8', '-B', *check], cwd=ROOT, check=True)
    print('P2 RELEASE GATE PASSED (loopback model; no model-quality claim)')


if __name__ == '__main__':
    main()
