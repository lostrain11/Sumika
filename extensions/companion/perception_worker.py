"""Isolated WGC worker; JSONL observations stay in a parent-owned pipe."""
import argparse
from dataclasses import asdict
import json
import sys
import threading

from .contracts import PerceptionService
from .windows_learning import WindowsLearningCollector


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--handle', type=int, required=True)
    parser.add_argument('--process-id', type=int, required=True)
    parser.add_argument('--expected-document')
    args = parser.parse_args()
    stop = threading.Event()
    perception = PerceptionService(WindowsLearningCollector(approved=True, expected_document=args.expected_document))
    perception.select_target(f'window:{args.handle}:pid:{args.process_id}')
    perception.start()
    try:
        # Start native capture before a blocking stdin reader: the native Rust
        # startup can wait for a Python callback while another thread reads.
        first = perception.observe()
        def input_closed():
            sys.stdin.read()
            stop.set()
        threading.Thread(target=input_closed, daemon=True).start()
        while not stop.is_set():
            value = asdict(first if first is not None else perception.observe())
            first = None
            value['observed_at'] = value['observed_at'].isoformat()
            if not stop.is_set():
                print(json.dumps({'observation': value}), flush=True)
            stop.wait(1)
    except Exception as error:
        print(json.dumps({'error': type(error).__name__}), flush=True)
        return 1
    finally:
        perception.stop()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
