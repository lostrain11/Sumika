"""Isolated UI acceptance host; test injection never changes the daily runtime."""
import json
import sys
import uuid
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sumika_next.dsh import Dsh
from ui.server import serve
from ui.workbench import ensure_skin


def main():
    base = ROOT / '.sumika-next' / ('ui-candidate-' + uuid.uuid4().hex)
    base.mkdir()
    runtime = ROOT / '.sumika-next/dsh-upgrade/0.2.0-rc.2'
    home = base / 'home'
    home.mkdir()
    ensure_skin(home, root=ROOT)
    rows = json.loads((home / 'cordis.patch.yml').read_text(encoding='utf8'))
    for row in rows:
        for entry in row.get('insert', []):
            if entry['id'] == 'sumika-brand':
                entry['config']['release'] = '0.2.0-rc.2'
    rows.extend([{'id': 'session-title-llm', 'disabled': True},
                 {'id': 'session-telemetry-otel', 'disabled': True}])
    (home / 'cordis.patch.yml').write_text(json.dumps(rows), encoding='utf8')
    release = json.loads((runtime / 'release.json').read_text(encoding='utf8'))
    with patch('ui.workbench.default_home', return_value=home), \
            patch('sumika_next.daily.default_home', return_value=home), \
            patch('ui.workbench.ensure_skin', return_value={'registered': True}), \
            patch('ui.workbench.Dsh', side_effect=lambda root, profile: Dsh(root, profile, runtime=runtime)), \
            patch('ui.workbench.WorkbenchController.release', return_value={
                'installed': True, 'version': release['version'], 'verified': True}):
        server = serve(base / 'settings.json', port=8765,
                       capability_database=base / 'capabilities.sqlite3',
                       schedule_directory=base / 'schedules')
        try:
            server.sumika_bridge.workbench.start()
            server.sumika_bridge.workbench.create_session(base)
            (base / 'host.json').write_text(json.dumps({'runtime': str(runtime),
                'profile': str(home), 'bridge': 'http://127.0.0.1:8765',
                'test_injection': True, 'daily_changed': False}), encoding='utf8')
            print(json.dumps({'ready': True, 'artifact': str(base)}), flush=True)
            server.serve_forever()
        finally:
            server.server_close()


if __name__ == '__main__':
    main()
