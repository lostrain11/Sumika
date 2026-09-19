import argparse
import sys
import json
from pathlib import Path

from .continuity import handoff, validate
from .receipts import ReceiptError, create_receipt


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Sumika portable project continuity")
    parser.add_argument("command", choices=("check", "handoff", "run", "receipt", "diagnostics", "native-diagnostics", "evidence"))
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--input", type=Path,
                        help="Project-relative JSON report for 'receipt'; relative to --root")
    parser.add_argument("--home", type=Path, help="Explicit DSH profile; defaults to isolated versioned daily home")
    parser.add_argument("--workspace", type=Path, help="Create one native session in this workspace; omit to resume history")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--port", type=int, default=0, help="Managed Web port; 0 picks a free port")
    parser.add_argument("--extensions-config",type=Path,help="Explicit trusted host configuration for run; never auto-discovered in projects")
    parser.add_argument("--task", help="Task id for diagnostics/evidence")
    parser.add_argument("--out", type=Path, help="Output JSON/ZIP for diagnostics/evidence")
    parser.add_argument("--call-id", help="Operation call id for diagnostics")
    parser.add_argument("--error-kind", help="Error marker for diagnostics")
    parser.add_argument('--before',type=int,help='Exclusive diagnostic record sequence cursor')
    parser.add_argument('--limit',type=int,default=50,help='Diagnostic result limit, 1-100')
    parser.add_argument('--session',help='Diagnostic session filter')
    parser.add_argument('--through',type=int,help='Native DSH snapshot cursor; omit to read a fresh snapshot')
    args = parser.parse_args()
    if args.extensions_config is not None and args.command!='run':parser.error('--extensions-config is only valid for run')
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
    elif args.command in ("diagnostics", "evidence"):
        if not args.task:
            parser.error("--task is required")
        from extensions.diagnostics.query import timeline, evidence_bundle
        if args.command == "diagnostics":
            from extensions.diagnostics.query import query
            result = query(args.root.resolve(), task=args.task, session=args.session, call_id=args.call_id, error_kind=args.error_kind, before=args.before, limit=args.limit)
            if args.out:
                with args.out.open('x',encoding='utf8') as output:
                    json.dump(result,output,ensure_ascii=False,indent=2)
            if args.out is None:
                print(json.dumps(result, ensure_ascii=False, indent=2))
            else:
                print("diagnostics: " + str(args.out))
        else:
            if not args.out:
                parser.error("evidence requires --out")
            print("evidence: " + evidence_bundle(args.root.resolve(), args.task, args.out)["path"])
    elif args.command == "native-diagnostics":
        if args.home is None or not args.session:
            parser.error("native-diagnostics requires --home and --session")
        from .contracts import WorkBinding
        from .dsh import Dsh
        from .runtime_ownership import ProfileLease
        if not args.home.is_dir():
            parser.error('native-diagnostics requires an existing stopped profile')
        if not 1 <= args.limit <= 100 or (args.before is not None and args.through is None):
            parser.error('invalid diagnostic range or missing --through for pagination')
        if any(cursor is not None and cursor < 0 for cursor in (args.before, args.through)):
            parser.error('diagnostic cursors must be nonnegative')
        if args.out is not None and args.out.exists():
            parser.error('output already exists')
        lease = ProfileLease(args.home.resolve()).acquire()
        adapter = None
        try:
            adapter = Dsh(args.root.resolve(), args.home.resolve())
            adapter.start(port=args.port)
            lease.bind(adapter.process)
            adapter.adopt_existing_session(args.session)
            binding = WorkBinding(adapter.instance.instance_id, "diagnostic", 1, args.session, "read")
            result = adapter.diagnostic_page(binding, through_seq=args.through, before_seq=args.before,
                                              max_messages=args.limit)
            if args.out:
                with args.out.open('x', encoding='utf8') as output:
                    json.dump(result, output, ensure_ascii=False, indent=2)
                print("native diagnostics: " + str(args.out))
            else:
                print(json.dumps(result, ensure_ascii=False, indent=2))
        finally:
            if adapter is None:
                lease.release()
            else:
                process = adapter.process
                adapter.close()
                if process is not None and process.poll() is None:
                    raise RuntimeError('process exit not confirmed; profile remains fenced')
                lease.release()
    else:
        from .daily import run, default_home
        run(args.root.resolve(), (args.home or default_home(args.root)).resolve(),
            args.workspace, browser=not args.no_browser,extensions_config=args.extensions_config,
            port=args.port)


if __name__ == "__main__":
    main()
