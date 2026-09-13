"""Small explicit desktop-control boundary; read-only unless --confirm is supplied."""
import argparse
import importlib.util
import json
from pathlib import Path


def status():
    return {name: bool(importlib.util.find_spec(name)) for name in ('pyautogui', 'pywinauto', 'pywinctl')}


def windows():
    import pywinctl
    return [{'title': str(w.title), 'box': [w.left, w.top, w.width, w.height]}
            for w in pywinctl.getAllWindows() if str(w.title).strip()]


def screenshot(output):
    import pyautogui
    output = Path(output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    image = pyautogui.screenshot()
    image.save(output)
    return {'path': str(output), 'size': list(image.size)}


def click(x, y, confirm):
    if not confirm:
        raise PermissionError('click requires explicit --confirm')
    import pyautogui
    pyautogui.click(x=x, y=y)
    return {'clicked': [x, y]}


def main():
    p = argparse.ArgumentParser(); p.add_argument('action', choices=('status', 'windows', 'screenshot', 'click'))
    p.add_argument('--output'); p.add_argument('--x', type=int); p.add_argument('--y', type=int); p.add_argument('--confirm', action='store_true')
    a = p.parse_args()
    try:
        if a.action == 'status': result = status()
        elif a.action == 'windows': result = windows()
        elif a.action == 'screenshot':
            if not a.output: raise ValueError('--output required')
            result = screenshot(a.output)
        else:
            if a.x is None or a.y is None: raise ValueError('--x and --y required')
            result = click(a.x, a.y, a.confirm)
        print(json.dumps(result, ensure_ascii=False)); return 0
    except (OSError, ValueError, PermissionError, ImportError, RuntimeError) as e:
        print('desktop: '+str(e)); return 2


if __name__ == '__main__': raise SystemExit(main())
