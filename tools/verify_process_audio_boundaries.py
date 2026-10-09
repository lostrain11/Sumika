"""Verify native rejection paths without creating an audio recorder."""
import argparse
import json
import os
from pathlib import Path
import subprocess

from extensions.desktop.process_audio import ProcessAudioCapture


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('helper', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    helper = args.helper.resolve()
    if args.output.exists():
        raise FileExistsError(args.output)
    report = {'capability': ProcessAudioCapture.capability(helper),
              'actual_capture_tested': False, 'checks': []}
    # Deliberately wrong FILETIME: native validation precedes recorder creation.
    result = subprocess.run([str(helper), '--process-id', str(os.getpid()),
                             '--creation', '1', '--consent'], input='',
                            text=True, encoding='utf-8', capture_output=True, timeout=10)
    assert result.returncode == 1 and not result.stdout
    assert json.loads(result.stderr)['reason'] == 'InvalidOperationException'
    report['checks'].append('closed_stdin_before_START_rejected')
    capture = ProcessAudioCapture(helper, process_id=os.getpid(), creation_time='1', approved=True)
    try:
        try:
            capture.start(lambda pcm: (_ for _ in ()).throw(AssertionError('unexpected PCM')))
        except RuntimeError:
            pass
        else:
            raise AssertionError('wrong process identity accepted')
        assert capture.status()['state'] == 'error'
        assert capture.error['reason'] == 'InvalidOperationException'
        assert capture._process is None and capture._job is None and capture._reader is None
        report['rejected_state'] = capture.status()
        report['checks'].append('wrong_creation_rejected_and_job_reclaimed')
    finally:
        capture.stop()
    report['status'] = 'passed'
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
