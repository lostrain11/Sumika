"""Exercise the real managed DSH child in an isolated profile, without models."""
import json
from pathlib import Path
import sys
from unittest.mock import patch
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ui.workbench import WorkbenchController, WorkbenchError
from ui.runtime_ownership import process_identity
from sumika_next.daily import run as run_cli


def main():
    base = ROOT / '.sumika-next' / ('ownership-probe-' + uuid.uuid4().hex)
    home = base / 'profile'
    home.mkdir(parents=True)
    controller = WorkbenchController(ROOT)
    competitor = WorkbenchController(ROOT)
    checks = []
    report = {'status': 'failed', 'model_requests': 0, 'personal_data_touched': False}
    try:
        with patch('ui.workbench.default_home', return_value=home), \
                patch('sumika_next.daily.default_home', return_value=home):
            for generation in range(2):
                state = controller.start()
                process = controller.adapter.process
                record = json.loads((home / 'sumika-instance.json').read_text())
                assert state['running'] and record['pid'] == process.pid
                assert record['creation'] == process_identity(process.pid)
                try:
                    competitor.start()
                except WorkbenchError:
                    pass
                else:
                    raise AssertionError('second profile writer started')
                assert process.poll() is None
                try:
                    run_cli(ROOT, home, None, browser=False)
                except (OSError, ValueError):
                    pass
                else:
                    raise AssertionError('CLI bypassed the profile lease')
                assert process.poll() is None
                controller.stop()
                assert process.poll() is not None
                assert json.loads((home / 'sumika-instance.json').read_text()) == {}
                checks.append(f'generation {generation}: identity bound, UI and CLI writers denied, exit confirmed, lease released')
            report['status'] = 'passed'
    finally:
        controller.stop()
        competitor.stop()
        report['checks'] = checks
        (base / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf8')
    print(json.dumps({'directory': str(base), **report}))


if __name__ == '__main__':
    main()
