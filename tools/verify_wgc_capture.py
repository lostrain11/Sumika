"""Owned WGC target/overlay, companion exclusion and repeated capture QA."""
import ctypes
import json
from pathlib import Path
import subprocess
import sys
import time
import uuid
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    from pywinauto import Desktop
    from extensions.desktop.windows_capture import capture_frame
    from extensions.companion.windows_visual import WindowsVisualCollector
    from extensions.companion.contracts import PerceptionService
    from extensions.companion.observation_scheduler import ObservationScheduler
    base = ROOT / '.sumika-next' / ('wgc-' + uuid.uuid4().hex)
    base.mkdir()
    marker = 'SumikaWgc-'+uuid.uuid4().hex
    class Fixture(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def do_GET(self):
            name = 'overlay' if self.path == '/overlay' else 'lesson'
            content = ('<body style="margin:0;background:#ee00ee;height:100vh">' if name == 'overlay' else
                '<body style="margin:0;background:white"><div style="display:flex">'
                '<div style="width:240px;height:300px;background:#ed2020"></div>'
                '<div style="width:240px;height:300px;background:#20d020"></div></div>')
            body = (f'<title>{marker}-{name}</title>'+content).encode()
            self.send_response(200); self.send_header('Content-Length', str(len(body)))
            self.send_header('Content-Type', 'text/html'); self.end_headers(); self.wfile.write(body)
    server = ThreadingHTTPServer(('127.0.0.1', 0), Fixture)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f'http://127.0.0.1:{server.server_port}'
    children, windows = [], []
    scheduler = None
    report = {'passed': False, 'scope': 'Owned Edge HWND occlusion and pet exclusion; no model/user content', 'raw_frames_saved': False}
    def wait_window(predicate):
        deadline = time.monotonic()+20
        while time.monotonic() < deadline:
            matches = [w for w in Desktop(backend='uia').windows() if predicate(w)]
            if len(matches) == 1:
                windows.append(matches[0]); return matches[0]
            time.sleep(.2)
        raise RuntimeError('owned fixture window missing')
    def browser(name):
        child = subprocess.Popen(['C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
            '--user-data-dir='+str(base/name), '--no-first-run', '--disable-sync', '--app='+url+'/'+name],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        children.append(child)
        return wait_window(lambda w: marker+'-'+name in w.window_text())
    def capture(window):
        return capture_frame(handle=window.handle, process_id=window.process_id(), approved=True)
    def colors(frame):
        p = frame['pixels'][:,:,:3].astype('int16')
        return {'red':int(((p[:,:,2]>170)&(p[:,:,1]<90)&(p[:,:,0]<90)).sum()),
            'green':int(((p[:,:,1]>150)&(p[:,:,2]<90)&(p[:,:,0]<90)).sum()),
            'magenta':int(((p[:,:,2]>170)&(p[:,:,0]>170)&(p[:,:,1]<90)).sum())}
    try:
        lesson = browser('lesson'); time.sleep(1)
        initial = colors(capture(lesson))
        assert initial['red'] > 1000 and initial['green'] > 1000, initial
        overlay = browser('overlay')
        user32 = ctypes.WinDLL('user32', use_last_error=True)
        user32.SetWindowPos.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int,
            ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint]
        r = lesson.rectangle()
        assert user32.SetWindowPos(overlay.handle, ctypes.c_void_p(-1), r.left, r.top, r.width(), r.height(), 0x40)
        time.sleep(1)
        foreground = colors(capture(overlay)); occluded = colors(capture(lesson))
        assert foreground['magenta'] > 10000, foreground
        assert occluded['red'] > 1000 and occluded['green'] > 1000 and occluded['magenta'] < 100, occluded
        report.update(occlusion_isolated=True, target_colors=occluded, overlay_colors=foreground)
        exe = ROOT/'.sumika-next/package/pet-host-20261008-i/SumikaPet.exe'
        pet = subprocess.Popen([str(exe), url+'/lesson']); children.append(pet)
        pet_window = wait_window(lambda w: w.process_id() == pet.pid)
        user32.GetPropW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]
        user32.GetPropW.restype = ctypes.c_void_p
        user32.GetWindowDisplayAffinity.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint)]
        affinity = ctypes.c_uint()
        deadline = time.monotonic()+10
        while time.monotonic() < deadline:
            if user32.GetPropW(pet_window.handle, 'Sumika.Companion.CaptureHost') and user32.GetWindowDisplayAffinity(pet_window.handle, ctypes.byref(affinity)) and affinity.value == 0x11:
                break
            time.sleep(.1)
        assert affinity.value == 0x11, affinity.value
        try: capture(pet_window)
        except RuntimeError as error: assert 'companion host cannot' in str(error), str(error)
        else: raise AssertionError('pet accepted as learning target')
        report.update(pet_affinity=affinity.value, pet_target_rejected=True)
        observations = []
        target = f'window:{lesson.handle}:pid:{lesson.process_id()}'
        collector = WindowsVisualCollector(approved=True)
        perception = PerceptionService(collector)
        perception.select_target(target); perception.start()
        scheduler = ObservationScheduler(perception, on_observation=observations.append)
        for index in range(3):
            assert user32.SetWindowPos(lesson.handle, None, r.left, r.top,
                r.width()+index*20, r.height()+index*20, 0x14)
            time.sleep(1.2)
            scheduler.tick()
        session = collector._session
        assert session is not None and session.frames_copied >= 3, 'native session did not receive changed frames'
        report['native_session_reused'] = True
        report['native_frames_copied'] = session.frames_copied
        assert len(observations) == 3 and all(o.valid and o.image and o.target == target for o in observations)
        perception.pause()
        assert collector._session is None and session._pixels is None
        try: perception.observe()
        except RuntimeError: pass
        else: raise AssertionError('paused collector ran')
        perception.start(); scheduler.tick(); scheduler.stop()
        assert scheduler.latest is None and perception.state == 'stopped'
        report.update(passed=True, repeated_observations=len(observations), pause_resume_stop=True)
    except Exception as error:
        report['failure'] = f'{type(error).__name__}: {error}'
        raise
    finally:
        if scheduler is not None: scheduler.stop()
        for window in reversed(windows):
            try: window.close()
            except Exception: pass
        for child in reversed(children):
            try: child.wait(timeout=5)
            except subprocess.TimeoutExpired: child.terminate(); child.wait(timeout=5)
        server.shutdown(); server.server_close()
        (base/'report.json').write_text(json.dumps(report, indent=2), encoding='utf8')
        print(json.dumps({**report, 'evidence': str(base/'report.json')}))


if __name__ == '__main__':
    main()
