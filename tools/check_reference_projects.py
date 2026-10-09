"""Run the read-only reference-project revision check."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from extensions.desktop.reference_monitor import ReferenceMonitor
from sumika_next.paths import user_data_directory


def default_registry(root=None):
    root = Path(root) if root is not None else Path(__file__).resolve().parents[1]
    source = root/'docs/project/reference-projects.json'
    return source if source.is_file() else root/'extensions/desktop/reference-projects.json'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--registry', type=Path)
    parser.add_argument('--database', type=Path)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--pending', action='store_true', help='Read queued evidence without network or model calls')
    mode.add_argument('--analyze', action='store_true', help='Analyze queued changes using the enabled auxiliary model')
    parser.add_argument('--settings', type=Path)
    parser.add_argument('--force', action='store_true')
    parser.add_argument('--limit', type=int)
    args = parser.parse_args()
    monitor = ReferenceMonitor(args.registry or default_registry(),
                               args.database or user_data_directory()/'reference-projects.sqlite3')
    if args.analyze:
        from extensions.desktop.reference_analysis import ConfiguredReferenceAnalyzer
        from extensions.models.settings import default_path
        result = monitor.analyze_pending(ConfiguredReferenceAnalyzer(args.settings or default_path()))
    else:
        result = ({'status':'pending', 'model_calls':0, 'pending_reviews':monitor.pending_reviews()}
                  if args.pending else monitor.check(force=args.force, limit=args.limit))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 2 if (any(row['status'] == 'error' for row in result.get('projects', []))
                 or any(row['status'] != 'complete' for row in result.get('reports', []))) else 0


if __name__ == '__main__':
    raise SystemExit(main())
