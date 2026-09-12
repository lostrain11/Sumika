from __future__ import annotations

import json
import os
import sys

from ..development.processes import ManagedProcess


def main():
    line = sys.stdin.readline(16385)
    if len(line) > 16384 or not line.endswith("\n"):
        raise ValueError("invalid managed process frame")
    command = json.loads(line)
    if (not isinstance(command, list) or not command or len(command) > 64 or
            any(not isinstance(value, str) or not value or "\x00" in value for value in command)):
        raise ValueError("invalid managed command")
    with ManagedProcess(command, cwd=os.getcwd(), env=dict(os.environ), output=sys.stdout) as child:
        return child.wait()


if __name__ == "__main__":
    raise SystemExit(main())
