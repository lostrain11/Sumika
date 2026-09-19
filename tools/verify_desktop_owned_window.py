"""UIA text edit on a hidden owned Win32 window, never user applications."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

if len(sys.argv)>1:
    import win32con,win32gui,win32api
    root=Path(sys.argv[1])
    wc=win32gui.WNDCLASS();wc.lpszClassName='SumikaOwnedTest';wc.hInstance=win32api.GetModuleHandle(None);wc.lpfnWndProc=win32gui.DefWindowProc
    win32gui.RegisterClass(wc)
    window=win32gui.CreateWindowEx(0,wc.lpszClassName,'Sumika isolated test',win32con.WS_OVERLAPPEDWINDOW,0,0,300,200,0,0,wc.hInstance,None)
    edit=win32gui.CreateWindowEx(0,'EDIT','before',win32con.WS_CHILD|win32con.WS_VISIBLE,0,0,200,40,window,100,0,None)
    (root/'window.json').write_text(json.dumps(dict(handle=edit,pid=os.getpid())),encoding='utf8')
    try:
        while not (root/'stop').exists():win32gui.PumpWaitingMessages();time.sleep(.02)
    finally:win32gui.DestroyWindow(window)
else:
    from extensions.desktop.control.uia import WindowsController
    with tempfile.TemporaryDirectory(prefix='sumika-uia-') as d:
        root=Path(d)
        process=subprocess.Popen([sys.executable,__file__,d],creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            deadline=time.monotonic()+10
            while not (root/'window.json').exists():
                if time.monotonic()>deadline:raise RuntimeError('owned window did not start')
                time.sleep(.05)
            w=json.loads((root/'window.json').read_text(encoding='utf8'))
            controller=WindowsController()
            controls=controller.inspect(w['handle'],w['pid'])
            edits=[c for c in controls if c['control_type']=='Edit']
            assert len(edits)==1,controls
            result=controller.act(w['handle'],w['pid'],'set_text',text='Sumika test',approved=True)
            from pywinauto import Desktop
            actual=Desktop(backend='uia').window(handle=w['handle']).wrapper_object().get_value()
            assert actual=='Sumika test',actual
            print(json.dumps({'owned_hidden_window':True,'uia_edit_verified':True,'user_apps_modified':False}))
        finally:
            (root/'stop').touch()
            try:process.wait(timeout=5)
            except subprocess.TimeoutExpired:process.terminate();process.wait(timeout=5)
