"""Install a portable Office Skill. Dependency installation is a separate explicit step."""
import argparse
import json
from pathlib import Path
import shutil


TEMPLATE = Path(__file__).resolve().parent / 'skills/sumika-office'


def install(root, python):
    root = Path(root).resolve(strict=True)
    python = Path(python).resolve(strict=True)
    if not root.is_dir() or not python.is_file():
        raise ValueError('Expected an existing workspace and Python executable')
    destination = root / '.agents/skills/sumika-office'
    if not destination.resolve().is_relative_to(root):
        raise ValueError('Skill destination escapes workspace')
    files = [p for p in TEMPLATE.rglob('*') if p.is_file() and '__pycache__' not in p.parts]
    # Preflight every existing file before changing anything; retain local edits and settings.
    for source in files:
        target = destination / source.relative_to(TEMPLATE)
        if not target.resolve().is_relative_to(root):
            raise ValueError('Skill file escapes workspace')
        if target.exists() and target.read_bytes() != source.read_bytes():
            raise ValueError(f'Existing Skill differs: {target}; merge it explicitly')
    config = destination / 'runtime.json'
    if not config.resolve().is_relative_to(root):
        raise ValueError('Runtime configuration escapes workspace')
    settings = {'schema_version': 1, 'enabled': True, 'provider': 'python-libraries',
                'python': str(python)}
    if config.exists():
        current = json.loads(config.read_text(encoding='utf-8'))
        if (not isinstance(current, dict) or current.get('schema_version') != 1
                or type(current.get('enabled')) is not bool
                or current.get('provider') != 'python-libraries'
                or current.get('python') != str(python)):
            raise ValueError('Existing runtime settings differ; rebind or merge explicitly')
    destination.mkdir(parents=True, exist_ok=True)
    for source in files:
        target = destination / source.relative_to(TEMPLATE)
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            shutil.copyfile(source, target)
    if not config.exists():
        with config.open('x', encoding='utf-8') as f:
            json.dump(settings, f, ensure_ascii=False, indent=2)
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--python', type=Path, required=True)
    args = parser.parse_args()
    try:
        print(install(args.root, args.python))
    except (OSError, ValueError) as error:
        parser.exit(1, str(error) + '\n')


if __name__ == '__main__':
    main()
