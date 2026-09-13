"""Launch office scripts in a separately installed environment; no Harness imports."""
import argparse
import json
from pathlib import Path
import subprocess
import sys


CONFIG = Path(__file__).resolve().parents[1] / 'runtime.json'
PACKAGES = ('python-docx', 'openpyxl', 'python-pptx', 'pypdf', 'reportlab')


def read_config(path):
    config = json.loads(Path(path).read_text(encoding='utf-8'))
    if (not isinstance(config, dict) or config.get('schema_version') != 1
            or type(config.get('enabled')) is not bool
            or config.get('provider') != 'python-libraries'
            or not isinstance(config.get('python'), str)):
        raise ValueError('Invalid office configuration or unsupported provider')
    python = Path(config['python'])
    if not python.is_absolute() or not python.is_file():
        raise ValueError('Office Python environment is missing; reinstall or rebind it')
    return config


def execute(config, script, arguments):
    if not config['enabled']:
        raise ValueError('Office module is disabled; no script was started')
    script = Path(script).resolve(strict=True)
    if not script.is_file() or script.suffix.lower() != '.py':
        raise ValueError('Expected an existing Python script')
    return subprocess.run([config['python'], '-X', 'utf8', '-B', str(script), *arguments]).returncode


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=CONFIG)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('status')
    run = commands.add_parser('exec')
    run.add_argument('script', type=Path)
    run.add_argument('arguments', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    try:
        config = read_config(args.config)
        if args.command == 'exec':
            return execute(config, args.script, args.arguments)
        result = {'enabled': config['enabled'], 'provider': config['provider'],
                  'python': config['python'], 'versions': {}}
        if config['enabled']:
            probe = ('import importlib.metadata as m,json; '
                     f'print(json.dumps({{p:m.version(p) for p in {PACKAGES!r}}}))')
            process = subprocess.run([config['python'], '-X', 'utf8', '-B', '-c', probe],
                                     capture_output=True, text=True, encoding='utf-8', timeout=30)
            if process.returncode:
                raise ValueError('Office dependency probe failed; reinstall the locked environment')
            result['versions'] = json.loads(process.stdout)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (OSError, ValueError, KeyError, subprocess.TimeoutExpired) as error:
        print(f'office: {error}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
