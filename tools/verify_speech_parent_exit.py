"""Kill an owned fixture parent; verify actual SpeechInput job child reclamation.

No microphone, model calls, daily Bridge, permissions changes or file deletion.
"""
import json
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from extensions.roles.speech_input import SpeechInput
from sumika_next.runtime_ownership import process_identity


def parent(base):
    def spawn(argv, **options):
        code = """import json,sys,time,os
from pathlib import Path
config=json.load(sys.stdin)
Path(config['output']).with_name('started.json').write_text(json.dumps({'pid':os.getpid()}))
time.sleep(60)
Path(config['output']).write_text('unexpected late write')
print(json.dumps({'text':'late result'}))
"""
        return subprocess.Popen([sys.executable, '-B', '-c', code], **options)
    service = SpeechInput(base/'speech', lambda role: {'python': sys.executable, 'root': str(base)}, spawn=spawn)
    record = service.start('fixture', approved=True)
    marker = base/'speech'/record['id']/'started.json'
    deadline = time.monotonic()+10
    while not marker.exists():
        if time.monotonic()>deadline:
            service.close()
            raise RuntimeError('worker did not start')
        time.sleep(.05)
    child = service.process
    print(json.dumps({'pid':child.pid, 'creation':process_identity(child.pid), 'request':record['id']}), flush=True)
    try:
        time.sleep(90)
    finally:
        service.close()


def main():
    base = ROOT/'.sumika-next'/('speech-parent-exit-'+uuid.uuid4().hex)
    base.mkdir()
    report = {'passed': False, 'microphone_opened': False}
    child_identity = None
    owner = subprocess.Popen([sys.executable, '-B', str(Path(__file__).resolve()), '--parent', str(base)],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf8',
                             creationflags=subprocess.CREATE_NO_WINDOW)
    lines = queue.Queue()
    threading.Thread(target=lambda:lines.put(owner.stdout.readline()), daemon=True).start()
    try:
        child_identity = json.loads(lines.get(timeout=20))
        assert process_identity(child_identity['pid']) == child_identity['creation']
        report['worker_observed_alive'] = True
        owner.kill()
        owner.wait(timeout=10)
        deadline = time.monotonic()+10
        while process_identity(child_identity['pid']) == child_identity['creation']:
            assert time.monotonic()<deadline, 'voice child survived parent exit'
            time.sleep(.1)
        assert not (base/'speech'/child_identity['request']/'capture.wav').exists()
        report.update(passed=True, owned_parent_exited=True, worker_reclaimed=True, late_output_absent=True)
    finally:
        if owner.poll() is None:
            owner.kill()
            owner.wait(timeout=10)
        if child_identity and process_identity(child_identity['pid']) == child_identity['creation']:
            subprocess.run(['taskkill','/PID',str(child_identity['pid']),'/F'], capture_output=True, check=True)
            report['emergency_cleanup_required'] = True
        (base/'report.json').write_text(json.dumps(report,indent=2),encoding='utf8')
        print('ARTIFACT',base,json.dumps(report))
    if not report['passed']:
        raise SystemExit(1)


if __name__ == '__main__':
    if len(sys.argv)==3 and sys.argv[1]=='--parent':
        parent(Path(sys.argv[2]).resolve(strict=True))
    else:
        main()
