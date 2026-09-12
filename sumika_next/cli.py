import argparse
import sys
from pathlib import Path

from .continuity import handoff, validate
from .receipts import ReceiptError, create_receipt


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Sumika portable project continuity")
    parser.add_argument("command", choices=("check", "handoff", "run", "receipt"))
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--input", type=Path,
                        help="Project-relative JSON report for 'receipt'; relative to --root")
    parser.add_argument("--home", type=Path, help="Explicit DSH profile; defaults to isolated versioned daily home")
    parser.add_argument("--workspace", type=Path, help="Create one native session in this workspace; omit to resume history")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    if args.input is not None and args.command != "receipt":
        parser.error("--input is only valid with 'receipt'")
    if args.command == "check":
        validate(args.root)
        print("continuity records: ok")
    elif args.command == "handoff":
        print(handoff(args.root), end="")
    elif args.command == "receipt":
        if args.input is None:
            parser.error("receipt requires --input")
        try:
            path = create_receipt(args.root, args.input)
        except ReceiptError as error:
            parser.error(str(error))
        print("receipt: " + path.relative_to(Path(args.root).resolve()).as_posix())
    else:
        from .daily import run, default_home
        run(args.root.resolve(), (args.home or default_home(args.root)).resolve(),
            args.workspace, browser=not args.no_browser)


if __name__ == "__main__":
    main()
