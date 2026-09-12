import argparse
import sys
from pathlib import Path

from .continuity import handoff, validate


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Sumika portable project continuity")
    parser.add_argument("command", choices=("check", "handoff"))
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    if args.command == "check":
        validate(args.root)
        print("continuity records: ok")
    else:
        print(handoff(args.root), end="")


if __name__ == "__main__":
    main()
