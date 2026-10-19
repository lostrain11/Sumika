"""P11 real keystroke soak: start the Raw Input worker, let the user
interact normally, then verify InputFeatureFrames are produced with
anonymous counts (no raw keys, no text, no coordinates).

Usage:
  python -B tools/verify_input_keystroke_soak.py --allow-recording --seconds 60 --output DIR

The user just uses the computer normally. The tool starts the worker,
waits, then checks the produced frames.
"""
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from extensions.behavior.library import BehaviorLibrary
from extensions.behavior.input_process import InputFeatureProcess
from extensions.behavior.input_features import validate_frame


def assess_frames(frames, *, user_scope, stopped, completed):
    """Use the product's closed schema; activity alone cannot prove a clean soak."""
    schema_ok = True
    for frame in frames:
        try:
            validate_frame(frame, user_scope=user_scope)
        except (ValueError, TypeError, KeyError):
            schema_ok = False
    sequences_ok = True
    sequences = {}
    for frame in frames:
        epoch, sequence = frame.get('worker_epoch'), frame.get('sequence')
        if type(epoch) is not int or type(sequence) is not int:
            sequences_ok = False
            continue
        if sequence != sequences.get(epoch, -1) + 1:
            sequences_ok = False
        sequences[epoch] = sequence
    return {
        'duration_completed': completed,
        'worker_stopped_cleanly': stopped.get('status') == 'stopped'
            and stopped.get('error') is None and stopped.get('alive') is False,
        'frames_produced': bool(frames),
        'closed_anonymous_schema': schema_ok,
        'key_counts_present': any(any(f.get('keys', {}).get('counts', {}).values()) for f in frames),
        'mouse_activity_present': any(any(f.get('mouse', {}).get(k, 0) > 0
            for k in ('moves', 'left', 'right', 'middle')) for f in frames),
        'sequences_contiguous': sequences_ok,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds', type=int, default=60,
                        help='soak duration (default 60)')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--user-scope', default='keystroke-soak')
    parser.add_argument('--allow-recording', action='store_true', required=True,
                        help='authorize anonymous input collection for this isolated test only')
    args = parser.parse_args(argv)
    if not 1 <= args.seconds <= 3600:
        parser.error('--seconds must be between 1 and 3600')
    args.output.mkdir(parents=True, exist_ok=False)

    library = BehaviorLibrary(args.output/'behavior.sqlite3')
    process = InputFeatureProcess(root=args.output, library=library,
                                  user_scope=args.user_scope,
                                  runtime_root=str(ROOT))

    print(f'[{args.seconds}s] starting Raw Input worker; '
          'please type, click, scroll, and switch windows normally.', flush=True)
    started = time.monotonic()
    deadline = started + args.seconds
    completed, error = False, None
    try:
        status = process.start(permission={'recording': True, 'paused': False,
            'revoked': False, 'revision': 1, 'excluded_apps': []})
        print(f'  worker: {status}', flush=True)
        deadline = time.monotonic() + args.seconds
        while time.monotonic() < deadline:
            time.sleep(min(5, max(0, deadline - time.monotonic())))
            remaining = max(0, int(deadline - time.monotonic()))
            s = process.status()
            print(f'  {remaining}s left: status={s["status"]} '
                  f'queued={s["queued"]} frames={s["frames"]}', flush=True)
            if s['status'] == 'failed':
                print(f'  WORKER FAILED: {s["error"]}', flush=True)
                break
        else:
            completed = True
    except KeyboardInterrupt:
        error = 'interrupted'
        print('  interrupted', flush=True)
    except Exception as failure:
        error = f'{type(failure).__name__}: {failure}'
    finally:
        print('  stopping worker...', flush=True)
        stopped = process.stop()
    print(f'  stopped: {stopped}', flush=True)

    # Check the library for frames.
    status = library.status()
    with library._connection() as db:
        rows = db.execute('SELECT worker_epoch, sequence, frame FROM frames '
                          'ORDER BY worker_epoch, sequence').fetchall()
    report = {'passed': False, 'duration_seconds': args.seconds,
              'elapsed_seconds': time.monotonic() - started,
              'error': error,
              'worker_status': stopped, 'library_status': status,
              'frames_total': len(rows), 'checks': {}}
    frames = [json.loads(row[2]) for row in rows]
    report['checks'] = assess_frames(frames, user_scope=args.user_scope,
                                    stopped=stopped, completed=completed)
    report['passed'] = error is None and all(report['checks'].values())
    if not rows and error is None:
        report['error'] = 'no frames observed; check interactive desktop, activity and exclusions; hardware outcome unverified'
    (args.output/'report.json').write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str) + '\n',
        encoding='utf8')
    print(json.dumps({'passed': report['passed'],
                      'frames': report['frames_total'],
                      'checks': report['checks']}), flush=True)
    return 0 if report['passed'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
