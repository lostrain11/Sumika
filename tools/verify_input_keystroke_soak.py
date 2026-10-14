"""P11 real keystroke soak: start the Raw Input worker, let the user
interact normally, then verify InputFeatureFrames are produced with
anonymous counts (no raw keys, no text, no coordinates).

Usage:
  python -B tools/verify_input_keystroke_soak.py --seconds 60 --output DIR

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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds', type=int, default=60,
                        help='soak duration (default 60)')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--user-scope', default='keystroke-soak')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)

    library = BehaviorLibrary(args.output/'behavior.sqlite3')
    process = InputFeatureProcess(root=args.output, library=library,
                                  user_scope=args.user_scope,
                                  runtime_root=str(ROOT))

    print(f'[{args.seconds}s] starting Raw Input worker; '
          'please type, click, scroll, and switch windows normally.', flush=True)
    status = process.start()
    print(f'  worker: {status}', flush=True)
    started = time.monotonic()
    deadline = started + args.seconds
    try:
        while time.monotonic() < deadline:
            time.sleep(5)
            remaining = int(deadline - time.monotonic())
            s = process.status()
            print(f'  {remaining}s left: status={s["status"]} '
                  f'queued={s["queued"]} frames={s["frames"]}', flush=True)
            if s['status'] == 'failed':
                print(f'  WORKER FAILED: {s["error"]}', flush=True)
                break
    except KeyboardInterrupt:
        print('  interrupted', flush=True)
    print('  stopping worker...', flush=True)
    stopped = process.stop()
    print(f'  stopped: {stopped}', flush=True)

    # Check the library for frames.
    status = library.status()
    frames_by_epoch = {}
    with library._connection() as db:
        rows = db.execute('SELECT worker_epoch, sequence, frame FROM frames '
                          'ORDER BY worker_epoch, sequence').fetchall()
    report = {'passed': False, 'duration_seconds': args.seconds,
              'worker_status': stopped, 'library_status': status,
              'frames_total': len(rows), 'checks': {}}
    if rows:
        frames = [json.loads(row[2]) for row in rows]
        report['frames_sample'] = frames[:3]
        # Checks: anonymous fields only, no raw content.
        has_counts = any(f.get('keys', {}).get('counts') for f in frames)
        has_mouse = any(f.get('mouse', {}).get('moves', 0) > 0
                        or f.get('mouse', {}).get('left', 0) > 0 for f in frames)
        no_text = all('text' not in f and 'pcm' not in f and 'screenshot' not in f
                      for f in frames)
        no_raw_keys = all('raw_keys' not in f and 'key_sequence' not in f
                          for f in frames)
        sequences_ok = all(
            frames[i]['sequence'] < frames[i+1]['sequence']
            for i in range(len(frames)-1)
            if frames[i]['worker_epoch'] == frames[i+1]['worker_epoch'])
        report['checks'] = {
            'frames_produced': len(frames) > 0,
            'key_counts_present': has_counts,
            'mouse_activity_present': has_mouse,
            'no_text_or_pcm_or_screenshot': no_text,
            'no_raw_key_sequences': no_raw_keys,
            'sequences_monotonic': sequences_ok,
        }
        report['passed'] = all(report['checks'].values())
    else:
        report['checks']['frames_produced'] = False
        report['error'] = 'no frames produced; worker may not have started'
    (args.output/'report.json').write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str) + '\n',
        encoding='utf8')
    print(json.dumps({'passed': report['passed'],
                      'frames': report['frames_total'],
                      'checks': report['checks']}), flush=True)
    return 0 if report['passed'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
