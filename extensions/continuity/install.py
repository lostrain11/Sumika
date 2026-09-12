"""Install the standalone extension into one DSH profile and opted-in workspace."""
import argparse
import json
from pathlib import Path
import sys

from continuity import initialize


def install(root, home, runtime, python=sys.executable):
    root, home, runtime = Path(root).resolve(), Path(home).resolve(), Path(runtime).resolve()
    entry = (runtime/'node_modules/@deepseek-ai/dsh/package.json').resolve(strict=True)
    if json.loads(entry.read_text())['version'] != '0.1.5-rc.2':
        raise ValueError('DSH version needs adapter acceptance before installation')
    package = Path(__file__).resolve().parent
    patch = home/'cordis.patch.yml'
    original = patch.read_bytes() if patch.exists() else None
    try:
        patches = json.loads(original.decode('utf-8-sig')) if original else []
    except ValueError as e:
        raise ValueError('Existing patch is YAML: merge the documented plugin entry manually; '
                         'installer will not rewrite unknown YAML configuration') from e
    if not isinstance(patches, list):
        raise ValueError('DSH patch must be an array')
    plugin = None
    for item in patches:
        for candidate in item.get('insert', []):
            if candidate.get('id') == 'sumika-continuity':
                if plugin is not None:
                    raise ValueError('duplicate continuity plugin configuration')
                plugin = candidate
    if plugin is None:
        plugin = {'id': 'sumika-continuity'}
        patches.append({'insert': [plugin]})
    projects = plugin.get('config', {}).get('projects', [])
    projects = sorted(set([*projects, str(root)]))
    plugin.update(name=str(package/'dsh.mjs'), config={
        'enabled': plugin.get('config', {}).get('enabled', True),
        'projects': projects, 'python': str(Path(python).resolve(strict=True)),
        'core': str(package/'continuity.py'), 'runtimeEntry': str(entry)})
    skill = root/'.agents/skills/sumika-continuity/SKILL.md'
    if not skill.resolve().is_relative_to(root):
        raise ValueError('skill path escapes workspace')
    content = (package/'skill/SKILL.md').read_bytes()
    if skill.exists() and skill.read_bytes() != content:
        raise ValueError('Existing Skill differs; preserve and merge it explicitly before installation')
    initialize(root)
    skill.parent.mkdir(parents=True, exist_ok=True)
    skill.write_bytes(content)
    home.mkdir(parents=True, exist_ok=True)
    if original is not None and original != patch.read_bytes():
        raise ValueError('profile changed during installation')
    if original is not None:
        backup = home/'cordis.patch.before-continuity.yml'
        if not backup.exists():
            with backup.open('xb') as f:
                f.write(original)
    # Atomic profile replacement; all unrelated entries remain intact.
    temporary = home/'cordis.patch.continuity.tmp'
    with temporary.open('x', encoding='utf-8') as f:
        json.dump(patches, f, ensure_ascii=False, indent=2)
    temporary.replace(patch)
    return {'project': str(root), 'profile': str(home), 'plugin': plugin}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--home', type=Path, required=True)
    parser.add_argument('--runtime', type=Path, required=True)
    parser.add_argument('--python', default=sys.executable)
    args = parser.parse_args()
    try:
        result = install(args.root, args.home, args.runtime, args.python)
    except (OSError, ValueError) as error:
        parser.exit(1, str(error)+'\n')
    print(json.dumps({'project': result['project'], 'profile': result['profile']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
