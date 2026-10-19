"""Configured UIA actions on a hidden owned window; no user app input/capture."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid


def window_worker(output):
    import win32api
    import win32con
    import win32gui
    wc = win32gui.WNDCLASS()
    wc.lpszClassName = 'SumikaOwnedTest' + str(os.getpid())
    wc.hInstance = win32api.GetModuleHandle(None)
    wc.lpfnWndProc = win32gui.DefWindowProc
    win32gui.RegisterClass(wc)
    window = win32gui.CreateWindowEx(win32con.WS_EX_NOACTIVATE | win32con.WS_EX_TOOLWINDOW,
        wc.lpszClassName, 'Sumika isolated test',
        win32con.WS_OVERLAPPEDWINDOW, 0, 0, 300, 200, 0, 0, wc.hInstance, None)
    edit = win32gui.CreateWindowEx(0, 'EDIT', 'before', win32con.WS_CHILD | win32con.WS_VISIBLE,
                                   0, 0, 200, 40, window, 100, 0, None)
    password = win32gui.CreateWindowEx(0, 'EDIT', '',
        win32con.WS_CHILD | win32con.WS_VISIBLE | win32con.ES_PASSWORD,
        0, 50, 200, 40, window, 101, 0, None)
    pending = output/'window.tmp'
    pending.write_text(json.dumps({'handle': edit, 'password_handle': password,
                                  'pid': os.getpid()}), encoding='utf8')
    pending.replace(output/'window.json')
    try:
        while not (output/'stop').exists():
            win32gui.PumpWaitingMessages()
            time.sleep(.02)
    finally:
        win32gui.DestroyWindow(window)


def run_check(product, output):
    sys.path.insert(0, str(product))
    import ctypes
    import hashlib
    from pywinauto import Desktop
    from extensions.capabilities import CapabilityStore
    from extensions.desktop.service import execute
    from extensions.desktop.control.uia import WindowsController
    from PIL import Image, ImageDraw, ImageFont
    report = {'passed': False, 'product': str(product), 'python': sys.executable,
              'checks': [], 'user_apps_modified': False, 'device_capture': False}
    worker = subprocess.Popen([sys.executable, '-X', 'utf8', '-B', __file__,
                               '--window-worker', '--output', str(output)],
                              creationflags=subprocess.CREATE_NO_WINDOW)
    store = CapabilityStore(output/'capabilities.sqlite3')
    foreground = ctypes.windll.user32.GetForegroundWindow
    foreground.restype = ctypes.c_void_p
    before_foreground = foreground()
    report['checker_pid'] = os.getpid()
    report['worker_pid'] = worker.pid
    try:
        deadline = time.monotonic()+15
        while not (output/'window.json').exists():
            if worker.poll() is not None or time.monotonic()>deadline:
                raise RuntimeError('hidden owned window did not start')
            time.sleep(.05)
        target = json.loads((output/'window.json').read_text(encoding='utf8'))
        handle, pid = target['handle'], target['pid']
        control = Desktop(backend='uia').window(handle=handle).wrapper_object()
        password = Desktop(backend='uia').window(handle=target['password_handle']).wrapper_object()
        assert not bool(control.element_info.element.CurrentIsPassword)
        assert bool(password.element_info.element.CurrentIsPassword)
        report['checks'].append('real_com_distinguishes_owned_plain_and_password_edits')
        report['password_scope'] = ('Hidden owned controls, no focus change or typing; '
                                    'does not prove real foreground focus transition handling')
        args = {'handle':handle, 'process_id':pid, 'action':'set_text',
                'approved':True, 'text':'Sumika owned test'}
        request = {'capability':'desktop', 'operation':'act', 'arguments':args}
        store.configure('desktop', 'windows-uia', enabled=False)
        try: execute(store, request)
        except PermissionError: pass
        else: raise AssertionError('disabled action accepted')
        assert control.get_value()=='before'
        report['checks'].append('disabled_service_zero_mutation')
        store.configure('desktop', 'windows-uia', enabled=True)
        for label, changes, error_type in [
            ('approval_rejection', {'approved':False}, PermissionError),
            ('verification_preflight', {'expected_text':'ok'}, ValueError),
            ('snapshot_rejection', {'expected_snapshot_hash':'stale'}, PermissionError)]:
            bad = dict(args, **changes)
            try: execute(store, dict(request, arguments=bad))
            except error_type: pass
            else: raise AssertionError(label+' accepted')
            assert control.get_value()=='before'
            report['checks'].append(label+'_zero_mutation')
        snapshot = WindowsController().inspect(handle,pid)
        args['expected_snapshot_hash'] = hashlib.sha256(json.dumps(snapshot, ensure_ascii=False,
            separators=(',',':')).encode()).hexdigest()
        result = execute(store,request)
        assert result['status']=='performed', result
        assert control.get_value()==args['text']
        report['checks'].append('configured_service_real_set_text_and_snapshot')
        image = output/'static.png'
        bitmap = Image.new('RGB',(800,150),'white')
        ImageDraw.Draw(bitmap).text((25,35),'SUMIKA STATIC IMAGE',
            font=ImageFont.truetype('C:/Windows/Fonts/msyh.ttc',40),fill='black')
        bitmap.save(image)
        args.pop('expected_snapshot_hash')
        args.update(text='after static evidence', expected_text='SUMIKA STATIC IMAGE',
                    verification_image=str(image), ocr_provider='windows', language='eng')
        result = execute(store,request)
        assert control.get_value()==args['text']
        assert result['post_verification']['status']=='verified',result
        assert result['post_verification']['freshness']=='not_established',result
        assert result['status']=='unknown' and result['retry_allowed'] is False,result
        report['checks'].append('real_static_ocr_match_does_not_prove_fresh_state')
        args.update(text='after OCR failure',language='zz-ZZ')
        result = execute(store,request)
        assert control.get_value()==args['text']
        assert result['status']=='unknown' and result['retry_allowed'] is False,result
        report['checks'].append('real_post_action_ocr_failure_keeps_executed_unknown')
        report['foreground_unchanged'] = foreground()==before_foreground
        foreground_pid = ctypes.c_ulong()
        ctypes.windll.user32.GetWindowThreadProcessId(ctypes.c_void_p(foreground()), ctypes.byref(foreground_pid))
        report['foreground_is_test_process'] = foreground_pid.value in (os.getpid(), worker.pid)
        report['foreground_pid_at_end'] = foreground_pid.value
        if report['foreground_is_test_process']:
            import win32gui
            report['test_foreground_class'] = win32gui.GetClassName(foreground())
        # User activity can legitimately change the foreground during testing.
        # Reject focus landing on our test processes, not a switch between user apps.
        assert not report['foreground_is_test_process'], 'test window took foreground'
        report['passed'] = True
    except Exception as error:
        report['error'] = repr(error)
    finally:
        store.close()
        (output/'stop').touch()
        try: worker.wait(timeout=10)
        except subprocess.TimeoutExpired: worker.terminate();worker.wait(timeout=5)
        report['worker_stopped'] = worker.poll() is not None
        (output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
        print(json.dumps(report,ensure_ascii=False))
    return 0 if report['passed'] else 1


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--product',type=Path,default=Path(__file__).resolve().parents[1])
    parser.add_argument('--output',type=Path,default=Path('.sumika-next/acceptance-20261018/owned-uia'))
    parser.add_argument('--window-worker',action='store_true',help=argparse.SUPPRESS)
    parser.add_argument('--run-check',action='store_true',help=argparse.SUPPRESS)
    args=parser.parse_args();product=args.product.resolve(strict=True)
    if args.window_worker:
        window_worker(args.output.resolve());return 0
    if args.run_check:
        return run_check(product,args.output.resolve())
    output=args.output.resolve()/uuid.uuid4().hex;output.mkdir(parents=True)
    bundled=product/'runtime/python/python.exe'
    primary=str(bundled) if bundled.is_file() else sys.executable
    selected=subprocess.run([primary,'-X','utf8','-B','-c',
        "from extensions.desktop.runtime import capability_python; import json; print(json.dumps(capability_python('desktop')))"] ,
        cwd=product,capture_output=True,text=True,encoding='utf8',timeout=15,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    if selected.returncode:raise RuntimeError(selected.stderr)
    desktop=json.loads(selected.stdout)
    if not desktop:raise RuntimeError('desktop runtime unavailable')
    result = subprocess.run([desktop,'-X','utf8','-B',__file__,'--run-check',
        '--product',str(product),'--output',str(output)],cwd=product,timeout=90,
        capture_output=True,text=True,encoding='utf8',
        creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    print(result.stdout or result.stderr)
    return result.returncode


if __name__=='__main__':
    raise SystemExit(main())
