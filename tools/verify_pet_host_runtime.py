"""Launch the published pet host and inspect its real WPF window."""
import json
import os
import argparse
import ctypes
from pathlib import Path
import socket
import subprocess
import time
import urllib.request


def main():
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('exe', type=Path)
    parser.add_argument('url', nargs='?')
    parser.add_argument('--product', type=Path)
    parser.add_argument('--via-api', action='store_true')
    parser.add_argument('--drag', action='store_true')
    parser.add_argument('--compact', action='store_true')
    parser.add_argument('--input', action='store_true')
    parser.add_argument('--allow-desktop-input', action='store_true',
                        help='Explicitly permit global mouse/keyboard input; use only on an idle test desktop')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if (args.input or args.drag or args.compact) and not args.allow_desktop_input:
        parser.error('input/drag/compact generate global desktop input; --allow-desktop-input is required on an idle test desktop')
    from pywinauto import Desktop
    exe = args.exe.resolve(strict=True)
    args.output.mkdir(parents=True, exist_ok=False)
    bridge = process = None
    api = None
    report = {'passed': False, 'exe': str(exe), 'checks': {},
              'scope': 'Real host and loaded UI; no model/audio/capture interaction'}
    log = (args.output/'bridge.log').open('wb')
    try:
        url = args.url
        if args.product:
            product = args.product.resolve(strict=True)
            from tools.verify_portable_staging import verify
            report['inventory_before'] = verify(product)
            with socket.socket() as sock:
                sock.bind(('127.0.0.1', 0))
                port = sock.getsockname()[1]
            bridge = subprocess.Popen([str(product/'runtime/python/python.exe'), '-X', 'utf8', '-B',
                '-m', 'ui.server', '--settings', str(args.output/'data/settings.json'),
                '--capabilities', str(args.output/'data/capabilities.db'),
                '--schedules', str(args.output/'data/schedules'), '--port', str(port)],
                cwd=product, stdout=log, stderr=log, creationflags=subprocess.CREATE_NO_WINDOW)
            url = f'http://127.0.0.1:{port}/?pet=1'
            deadline = time.monotonic()+20
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            while True:
                if bridge.poll() is not None:
                    raise RuntimeError('isolated bridge failed; inspect bridge.log')
                try:
                    with opener.open(url, timeout=1) as response:
                        if response.status == 200: break
                except OSError:
                    if time.monotonic() > deadline: raise RuntimeError('bridge startup timeout')
                    time.sleep(.2)
        if not url:
            raise ValueError('url or product required')
        if args.via_api:
            if not args.product:
                raise ValueError('API launch requires isolated product bridge')
            origin=f'http://127.0.0.1:{port}'
            with opener.open(origin+'/api/manage/session') as response:
                token=json.load(response)['csrf']
            def api(action):
                request=urllib.request.Request(origin+'/api/companion/pet',
                    data=json.dumps({'action':action}).encode(),
                    headers={'Content-Type':'application/json','X-Sumika-CSRF':token,'Origin':origin})
                with opener.open(request,timeout=10) as response:
                    return json.load(response)
            before=api('status')
            if before['alive']:
                raise RuntimeError('isolated bridge unexpectedly already owns a pet')
            first=api('start')
            second=api('start')
            if not first['alive'] or not first['pid'] or first['pid'] != second['pid']:
                raise RuntimeError('pet API did not retain single instance')
            pid=first['pid']
            report['checks']['authenticated_api_single_instance']=True
        else:
            environment = dict(os.environ, SUMIKA_PET_DIAGNOSTICS=str(args.output.resolve()))
            process = subprocess.Popen([str(exe), url], env=environment)
            pid=process.pid
        report['pid'] = pid
        deadline = time.monotonic() + 20
        windows = []
        while time.monotonic() < deadline:
            windows = [window for window in Desktop(backend='uia').windows()
                       if window.process_id() == pid]
            if windows:
                break
            if process is not None and process.poll() is not None:
                report['exit_code'] = process.returncode
                raise RuntimeError('pet process exited before a window appeared')
            time.sleep(.2)
        if len(windows) != 1:
            raise RuntimeError(f'expected one pet host window, found {len(windows)}')
        rectangle = windows[0].rectangle()
        report.update(window_count=1, title=windows[0].window_text(),
                      rectangle={'left': rectangle.left, 'top': rectangle.top,
                                 'width': rectangle.width(), 'height': rectangle.height()},
                      class_name=windows[0].class_name())
        if rectangle.width() < 300 or rectangle.height() < 400:
            raise RuntimeError('pet host window is unexpectedly small')
        user32 = ctypes.WinDLL('user32', use_last_error=True)
        user32.GetPropW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]
        user32.GetPropW.restype = ctypes.c_void_p
        user32.GetWindowDisplayAffinity.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint)]
        handle = windows[0].handle
        affinity = ctypes.c_uint()
        if not user32.GetWindowDisplayAffinity(handle, ctypes.byref(affinity)) or affinity.value != 0x11:
            raise RuntimeError('capture exclusion was not applied')
        if not user32.GetPropW(handle, 'Sumika.Companion.CaptureHost'):
            raise RuntimeError('capture host marker absent')
        user32.GetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int]
        style = user32.GetWindowLongW(handle, -20)
        if not style & 0x8 or not style & 0x80000:
            raise RuntimeError('topmost/layered styles missing')
        report['checks'].update(capture_exclusion=True, capture_marker=True, topmost=True, layered=True)
        deadline = time.monotonic()+20
        while True:
            rectangle = windows[0].rectangle()
            inputs = windows[0].descendants(control_type='Edit')
            visible = [entry for entry in inputs if entry.is_visible() and entry.rectangle().width() >= 50
                       and entry.rectangle().bottom <= rectangle.bottom and entry.rectangle().top >= rectangle.top]
            if visible: break
            if (process is not None and process.poll() is not None) or time.monotonic() > deadline:
                report['uia_controls']=[{'type':entry.element_info.control_type,
                    'name':entry.window_text()[:160], 'visible':entry.is_visible(),
                    'bounds':str(entry.rectangle())} for entry in windows[0].descendants()][:100]
                report['child_processes']=subprocess.run(['powershell.exe','-NoProfile','-Command',
                    f"Get-CimInstance Win32_Process -Filter \"ParentProcessId={pid}\" | Select-Object Name,ProcessId | ConvertTo-Json"],
                    capture_output=True,text=True,encoding='utf8',errors='replace',timeout=10).stdout
                raise RuntimeError('WebView pet composer did not load')
            time.sleep(.2)
        bounds = visible[0].rectangle()
        report['checks']['loaded_visible_composer'] = True
        report['composer'] = {'width':bounds.width(), 'height':bounds.height()}
        if args.input:
            from pywinauto import mouse, keyboard
            before=windows[0].rectangle()
            # WebView2 exposes the composer as a UIA Edit, but a mouse click
            # alone does not consistently transfer keyboard focus when the
            # host was started through the isolated API bridge.  Focus the
            # semantic control explicitly before sending the probe input.
            visible[0].set_focus()
            mouse.click(coords=(bounds.left+bounds.width()//2,bounds.top+bounds.height()//2))
            visible[0].set_focus()
            keyboard.send_keys('study fixture',with_spaces=True)
            time.sleep(.2)
            if visible[0].get_value() != 'study fixture':
                raise RuntimeError('native keyboard input did not reach composer')
            if windows[0].rectangle() != before:
                raise RuntimeError('composer input moved native window')
            keyboard.send_keys('^a{BACKSPACE}')
            report['checks']['native_keyboard_input_without_drag']=True
        if args.drag:
            from pywinauto import mouse
            images = [entry for entry in windows[0].descendants(control_type='Image')
                      if entry.is_visible() and entry.rectangle().left >= rectangle.left
                      and entry.rectangle().right <= rectangle.right
                      and entry.rectangle().top >= rectangle.top
                      and entry.rectangle().bottom <= rectangle.bottom]
            if images:
                target = images[-1].rectangle()
                start = (target.left+target.width()//2, target.top+target.height()//2)
                report['drag_target'] = str(target)
            else:
                # VRM canvas has no UIA Image node; use the character viewport
                # above the composer, not the full application's hidden stage.
                start = (bounds.left+bounds.width()//2, bounds.top-150)
                report['drag_target'] = 'character viewport above composer'
            try:
                mouse.move(coords=start)
                mouse.press(coords=start)
                time.sleep(.3)
                for step in range(1, 9):
                    mouse.move(coords=(start[0]+10*step, start[1]+int(7.5*step)))
                    time.sleep(.06)
            finally:
                mouse.release(coords=(start[0]+80, start[1]+60))
            time.sleep(.3)
            moved = windows[0].rectangle()
            report['drag_delta'] = [moved.left-rectangle.left, moved.top-rectangle.top]
            if abs(report['drag_delta'][0]-80)>5 or abs(report['drag_delta'][1]-60)>5:
                raise RuntimeError('page gesture did not move native pet window')
            report['checks']['native_window_drag'] = True
        if args.compact:
            from pywinauto import mouse
            def click_button(name):
                entries=[entry for entry in windows[0].descendants(control_type='Button')
                         if entry.window_text()==name and entry.is_visible()]
                if len(entries)!=1:
                    raise RuntimeError(f'expected one visible {name} button')
                bounds=entries[0].rectangle()
                mouse.click(coords=(bounds.left+bounds.width()//2,bounds.top+bounds.height()//2))
            original=windows[0].rectangle()
            click_button('收起')
            deadline=time.monotonic()+5
            while windows[0].rectangle().width()>=original.width() and time.monotonic()<deadline:
                time.sleep(.1)
            compact=windows[0].rectangle()
            if compact.width()>=original.width() or compact.height()>=original.height():
                raise RuntimeError('native pet did not compact')
            report['compact_size']=[compact.width(),compact.height()]
            mouse.click(coords=(compact.left+compact.width()//2,compact.top+compact.height()//2))
            deadline=time.monotonic()+5
            while windows[0].rectangle().width()!=original.width() and time.monotonic()<deadline:
                time.sleep(.1)
            restored=windows[0].rectangle()
            if restored!=original:
                raise RuntimeError('native expand did not restore original bounds')
            report['checks']['native_compact_restore']=True
        if api is not None:
            stopped=api('stop')
            if stopped['alive'] or stopped['pid'] is not None:
                raise RuntimeError('pet API stop did not reclaim process')
            if any(window.process_id()==pid for window in Desktop(backend='uia').windows()):
                raise RuntimeError('pet window survived API stop')
            report['checks']['api_stop_reclaims_window']=True
        report['passed'] = True
    finally:
        if api is not None and bridge is not None and bridge.poll() is None:
            api('stop')
        if process is not None:
            report['process_alive_before_cleanup'] = process.poll() is None
        for child in (process, bridge):
            if child is not None and child.poll() is None:
                child.terminate()
                child.wait(timeout=5)
        log.close()
        if args.product:
            try:
                report['inventory_after'] = verify(product)
                report['checks']['product_unchanged_after_host'] = True
            except Exception as error:
                report['passed'] = False
                report['inventory_error'] = str(error)
        (args.output/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')
        print(json.dumps(report, ensure_ascii=False))
        if not report['passed']:
            raise RuntimeError('pet host verification failed; inspect report.json')


if __name__ == '__main__':
    main()
