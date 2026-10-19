"""Publish one owned skill through DSH's existing profile filesystem provider."""
from pathlib import Path
import sys
import uuid

MARKER = '<!-- sumika-managed-screenshot-skill:v1 -->'
NAME = 'sumika-screenshot-translation'


def _quote(value):
    return "'" + str(value).replace("'", "''") + "'"


def publish(home, *, root, capabilities):
    root, home = Path(root).resolve(), Path(home).resolve()
    target = home/'skills'/NAME/'SKILL.md'
    if any(path.is_symlink() or path.is_junction() for path in (target, target.parent, target.parent.parent)):
        return {'registered': False, 'reason': 'skill target is linked'}
    if target.exists() and MARKER not in target.read_text(encoding='utf8'):
        return {'registered': False, 'reason': 'user skill with same name preserved'}
    template = root/'extensions/desktop/screenshot-skill.md'
    runner = root/'tools/run_module.py'
    if capabilities is None or not Path(capabilities).is_file() or not template.is_file() or not runner.is_file():
        if target.is_file():
            target.unlink()  # Only our marked generated file; preserve sibling resources.
        return {'registered': False, 'reason': 'configured OCR service unavailable'}
    python = root/'runtime/python/python.exe'
    if not python.is_file():
        python = Path(sys.executable)
    content = template.read_text(encoding='utf8')
    for token, value in {'PYTHON':python,'RUNNER':runner,'CAPABILITIES':Path(capabilities).resolve()}.items():
        content = content.replace('{{'+token+'}}', _quote(value))
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists() or target.read_text(encoding='utf8') != content:
        temporary = target.with_name('SKILL.'+uuid.uuid4().hex+'.tmp')
        try:
            temporary.write_text(content, encoding='utf8')
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
    return {'registered': True, 'name': NAME, 'path': str(target)}
