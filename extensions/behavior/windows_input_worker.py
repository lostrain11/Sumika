"""Hidden, bounded Raw Input adapter. Only anonymous frames leave this process."""
import ctypes
from ctypes import wintypes
import json
import os
import queue
import sys
import threading
import time
from collections import deque

from .input_features import BurstState, FrameAggregator, frame_nonempty, validate_frame

WM_INPUT, WM_QUIT = 0x00FF, 0x0012
RIM_TYPEMOUSE, RIM_TYPEKEYBOARD = 0, 1
RIDEV_REMOVE, RIDEV_INPUTSINK = 1, 0x100
EVENT_SYSTEM_FOREGROUND, EVENT_OBJECT_FOCUS = 3, 0x8005
WINEVENT_OUTOFCONTEXT = 0
DWORD, WORD = ctypes.c_uint32, ctypes.c_uint16


class RAWINPUTDEVICE(ctypes.Structure):
    _fields_ = [('usUsagePage', WORD), ('usUsage', WORD), ('dwFlags', DWORD),
                ('hwndTarget', ctypes.c_void_p)]


class RAWINPUTHEADER(ctypes.Structure):
    _fields_ = [('dwType', DWORD), ('dwSize', DWORD),
                ('hDevice', ctypes.c_void_p), ('wParam', ctypes.c_size_t)]


class RAWKEYBOARD(ctypes.Structure):
    _fields_ = [('MakeCode', WORD), ('Flags', WORD), ('Reserved', WORD),
                ('VKey', WORD), ('Message', DWORD), ('ExtraInformation', DWORD)]


class _MouseButtons(ctypes.Structure):
    _fields_ = [('usButtonFlags', WORD), ('usButtonData', WORD)]


class _MouseUnion(ctypes.Union):
    _anonymous_ = ('buttons',)
    _fields_ = [('ulButtons', DWORD), ('buttons', _MouseButtons)]


class RAWMOUSE(ctypes.Structure):
    _anonymous_ = ('button_union',)
    _fields_ = [('usFlags', WORD), ('button_union', _MouseUnion),
                ('ulRawButtons', DWORD), ('lLastX', ctypes.c_int32),
                ('lLastY', ctypes.c_int32), ('ulExtraInformation', DWORD)]


class _RawData(ctypes.Union):
    _fields_ = [('keyboard', RAWKEYBOARD), ('mouse', RAWMOUSE)]


class RAWINPUT(ctypes.Structure):
    _anonymous_ = ('data',)
    _fields_ = [('header', RAWINPUTHEADER), ('data', _RawData)]


def register_raw_input(hwnd, user32=None, *, remove=False):
    """INPUTSINK requires an actual hidden window; REMOVE requires NULL."""
    if not remove and not hwnd:
        raise ValueError('Raw Input sink requires a window')
    user32 = user32 or ctypes.WinDLL('user32', use_last_error=True)
    function = user32.RegisterRawInputDevices
    function.argtypes = [ctypes.POINTER(RAWINPUTDEVICE), wintypes.UINT, wintypes.UINT]
    function.restype = wintypes.BOOL
    flags, target = (RIDEV_REMOVE, None) if remove else (RIDEV_INPUTSINK, hwnd)
    devices = (RAWINPUTDEVICE * 2)(RAWINPUTDEVICE(1, 6, flags, target),
                                         RAWINPUTDEVICE(1, 2, flags, target))
    if not function(devices, 2, ctypes.sizeof(RAWINPUTDEVICE)):
        raise OSError('raw input registration failed')
    return True


class PasswordProbe:
    """One COM daemon and one in-flight request, including hung UIA calls.

    Results expire after 200ms; a hung provider never creates another thread.
    The probe only reads CurrentIsPassword. No names or text are requested.
    """
    def __init__(self, query=None):
        self._query = query
        self._requests, self._results = queue.Queue(1), queue.Queue(1)
        self._pending = None
        self._next = 0
        self._serial = 0
        self._minimum_serial = 1
        self._quality = 'privacy_context_unknown'
        self._quality_at = None
        self._target = None
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name='sumika-password-probe')
        self._thread.start()

    def _run(self):
        com = None
        query = self._query
        try:
            if query is None:
                # comtypes initializes the importing thread automatically.
                # Select MTA before its first import; later imports need an
                # explicit initialization on this dedicated thread.
                imported = 'comtypes' in sys.modules
                if not imported: sys.coinit_flags = 0
                import comtypes as com
                if imported: com.CoInitializeEx(0)
                from comtypes.client import CreateObject, GetModule
                module = GetModule('UIAutomationCore.dll')
                automation = CreateObject(module.CUIAutomation, interface=module.IUIAutomation)
                def query():
                    value = automation.GetFocusedElement().CurrentIsPassword
                    if type(value) is bool: return value
                    if type(value) is int and value in (-1, 0, 1): return value != 0
                    return None
            while not self._stop.is_set():
                try: serial, target, at = self._requests.get(timeout=.1)
                except queue.Empty: continue
                try:
                    value = query()
                    quality = ('password_paused' if value else 'ok') if type(value) is bool else 'privacy_context_unknown'
                except Exception:
                    quality = 'privacy_context_unknown'
                self._results.put_nowait((serial, target, at, quality))
        except Exception:
            pass  # unavailable UIA always leaves the channel coarse
        finally:
            if com is not None: com.CoUninitialize()

    def invalidate(self):
        self._target = None
        self._quality = 'privacy_context_unknown'
        self._quality_at = None
        # Keep the one in-flight request, but never trust its old focus sample.
        self._minimum_serial = self._serial + 1

    def poll(self, target, now):
        if target != self._target:
            self.invalidate()
            self._target = target
        try:
            serial, sampled_target, at, quality = self._results.get_nowait()
            if self._pending and serial == self._pending[0]:
                self._pending = None
                if (serial >= self._minimum_serial and target == sampled_target
                        and 0 <= now - at <= .2):
                    self._quality = quality
                    self._quality_at = at
        except queue.Empty:
            pass
        if self._quality_at is None or not 0 <= now - self._quality_at <= .2:
            self._quality = 'privacy_context_unknown'
        if target is not None and self._pending is None and now >= self._next:
            self._serial += 1
            self._pending = (self._serial, target, now)
            self._requests.put_nowait(self._pending)
            self._next = now + .25
        return self._quality

    def close(self):
        self._stop.set()
        self._thread.join(timeout=.25)


class InputSession:
    """Single pump-thread state. Events aggregate immediately without a raw queue."""
    def __init__(self, config, emit, *, clock=time.monotonic):
        if (config.get('recording') is not True or type(config.get('permission_revision')) is not int
                or config['permission_revision'] < 1):
            raise PermissionError('active permission required')
        self.config, self.emit, self.clock = config, emit, clock
        self.identity = {'user_scope': config['user_scope'], 'worker_epoch': config['worker_epoch'],
                         'foreground_epoch': 0, 'focus_epoch': 0, 'window_instance': 0}
        self.sequence = 0
        self.target = None
        self.burst = BurstState()
        self.aggregator = None
        self.started = self.clock()
        self.modifiers, self.held, self.drags = set(), set(), {}
        self.last_click = None
        self.quality = 'privacy_context_unknown'

    def _new(self, at, *, restart_interval=True):
        if restart_interval:
            self.started = at
        self.aggregator = FrameAggregator(identity=self.identity, observed_from=str(at),
                                         sequence=self.sequence, burst_state=self.burst)
        self.aggregator.focus(self.quality)

    def seal(self, at=None):
        at = self.clock() if at is None else at
        if self.aggregator is not None:
            frame = self.aggregator.seal(str(at))
            if frame_nonempty(frame):
                self.emit(frame)
                self.sequence += 1
        self.aggregator = None
        if self.target is not None: self._new(at)

    def foreground(self, target, *, force=False):
        if not force and target == self.target: return
        at = self.clock()
        self.seal(at)
        self.modifiers.clear(); self.held.clear(); self.drags.clear()
        self.last_click = None
        self.burst.reset()
        self.identity['foreground_epoch'] += 1
        self.identity['focus_epoch'] += 1
        self.identity['window_instance'] += 1
        self.target, self.aggregator = target, None
        self.quality = 'privacy_context_unknown'
        if target is not None: self._new(at)

    def focus(self, quality):
        if quality != self.quality:
            self.identity['focus_epoch'] += 1
            # Conservatively discard this partial frame when privacy changes.
            self.modifiers.clear(); self.held.clear(); self.drags.clear()
            self.last_click = None
            self.burst.reset()
            self.quality = quality
            # Privacy changes discard the partial frame, not the periodic
            # flush deadline. Probe freshness can legitimately oscillate at
            # subsecond intervals; resetting both would starve all output.
            if self.target is not None: self._new(self.clock(), restart_interval=False)

    def key(self, vk, at, *, down=True):
        if self.aggregator is None: return
        if self.quality != 'ok':
            self.aggregator.key(vk, at, down=down)
            return
        names = {0x10:'shift', 0xA0:'shift', 0xA1:'shift', 0x11:'ctrl', 0xA2:'ctrl',
                 0xA3:'ctrl', 0x12:'alt', 0xA4:'alt', 0xA5:'alt', 0x5B:'win', 0x5C:'win'}
        modifier = names.get(vk)
        if not down:
            self.held.discard(vk)
            self.modifiers = {names[key] for key in self.held if key in names}
            return
        repeat = vk in self.held
        self.held.add(vk)
        if modifier: self.modifiers.add(modifier)
        shortcut = bool(self.modifiers - {'shift'}) and not modifier
        self.aggregator.key(vk, at, repeat=repeat, semantic=not shortcut)
        if shortcut: self.aggregator.shortcut(vk, self.modifiers)

    def mouse(self, raw, at, ratios):
        aggregator = self.aggregator
        if aggregator is None: return
        if raw.lLastX or raw.lLastY: aggregator.move()
        flags = raw.usButtonFlags
        delta = ctypes.c_int16(raw.usButtonData).value
        if flags & 0x400: aggregator.scroll('vertical', delta, at)
        if flags & 0x800: aggregator.scroll('horizontal', delta, at)
        if self.quality != 'ok':
            if flags & 0x3f: aggregator.move()
            return
        if ratios is None: return
        for button, down, up in (('left', 1, 2), ('right', 4, 8), ('middle', 16, 32)):
            if flags & down:
                cell = (int(ratios[0]*15), int(ratios[1]*15))
                double = bool(self.last_click and self.last_click[:2] == (button, cell)
                              and at-self.last_click[2] <= .5)
                aggregator.click(button, *ratios, double_candidate=double)
                self.last_click = (button, cell, at)
                self.drags[button] = (ratios, at)
            if flags & up and button in self.drags:
                start, began = self.drags.pop(button)
                if start != ratios: aggregator.drag(*ratios, max(0, at-began), start=start)

    def tick(self):
        if self.clock() - self.started >= 1: self.seal()


def worker_loop(config, emit, *, stop_event=None, probe=None, clock=None):
    """Fake-event adapter retained for deterministic tests; final stop seals too."""
    now = clock or time.monotonic
    config = dict(config, recording=config.get('recording', True),
                  permission_revision=config.get('permission_revision', 1))
    session = InputSession(config, emit, clock=now)
    session.foreground(1)
    while not (stop_event and stop_event.is_set()):
        pending = probe() if probe else None
        if pending:
            event, value, at = pending
            if event == 'foreground': session.foreground(value)
            elif event == 'focus': session.focus(value)
            elif session.aggregator is not None:
                if event == 'key': session.key(value, at)
                elif event in ('shortcut', 'click', 'scroll', 'drag'):
                    getattr(session.aggregator, event)(*value)
                elif event == 'move': session.aggregator.move()
        session.tick()
        time.sleep(.001)
    session.seal()


def _signatures(user32, kernel32, wndproc_type, hook_type):
    signatures = {
        'DefWindowProcW': ([wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM], ctypes.c_ssize_t),
        'RegisterClassW': ([ctypes.c_void_p], WORD),
        'UnregisterClassW': ([wintypes.LPCWSTR, wintypes.HINSTANCE], wintypes.BOOL),
        'CreateWindowExW': ([DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, DWORD] + [ctypes.c_int]*4 +
                            [wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, ctypes.c_void_p], wintypes.HWND),
        'DestroyWindow': ([wintypes.HWND], wintypes.BOOL),
        'GetRawInputData': ([ctypes.c_void_p, wintypes.UINT, ctypes.c_void_p,
                            ctypes.POINTER(wintypes.UINT), wintypes.UINT], wintypes.UINT),
        'PeekMessageW': ([ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT, wintypes.UINT], wintypes.BOOL),
        'TranslateMessage': ([ctypes.POINTER(wintypes.MSG)], wintypes.BOOL),
        'DispatchMessageW': ([ctypes.POINTER(wintypes.MSG)], ctypes.c_ssize_t),
        'SetWinEventHook': ([DWORD, DWORD, wintypes.HMODULE, hook_type, DWORD, DWORD, DWORD], wintypes.HANDLE),
        'UnhookWinEvent': ([wintypes.HANDLE], wintypes.BOOL),
        'GetForegroundWindow': ([], wintypes.HWND),
        'GetMessageTime': ([], ctypes.c_int32),
        'GetCursorPos': ([ctypes.POINTER(wintypes.POINT)], wintypes.BOOL),
        'ScreenToClient': ([wintypes.HWND, ctypes.POINTER(wintypes.POINT)], wintypes.BOOL),
        'GetClientRect': ([wintypes.HWND, ctypes.POINTER(wintypes.RECT)], wintypes.BOOL),
        'OpenInputDesktop': ([DWORD, wintypes.BOOL, DWORD], wintypes.HANDLE),
        'CloseDesktop': ([wintypes.HANDLE], wintypes.BOOL),
        'GetUserObjectInformationW': ([wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, DWORD, ctypes.POINTER(DWORD)], wintypes.BOOL),
    }
    for name, (args, result) in signatures.items():
        function = getattr(user32, name)
        function.argtypes, function.restype = args, result
    kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
    kernel32.GetModuleHandleW.restype = wintypes.HMODULE
    kernel32.GetTickCount64.argtypes = []
    kernel32.GetTickCount64.restype = ctypes.c_uint64


def _desktop_available(user32):
    desktop = user32.OpenInputDesktop(0, False, 1)
    if not desktop: return False
    try:
        name, needed = ctypes.create_unicode_buffer(128), DWORD()
        return bool(user32.GetUserObjectInformationW(desktop, 2, name, ctypes.sizeof(name),
                    ctypes.byref(needed))) and name.value.lower() == 'default'
    finally:
        user32.CloseDesktop(desktop)


def main():
    if os.name != 'nt': return 1
    handles, handle, registered, window_class = [], None, False, False
    focus_probe = None
    emit_lock = threading.Lock()
    def emit(message):
        with emit_lock:
            sys.stdout.write(json.dumps(message, ensure_ascii=False) + '\n')
            sys.stdout.flush()
    try:
        line = sys.stdin.buffer.readline(32769)
        if not line or len(line) > 32768 or not line.endswith(b'\n'):
            raise ValueError('worker config')
        config = json.loads(line)
        user32 = ctypes.WinDLL('user32', use_last_error=True)
        kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
        wndproc_type = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND,
                                          wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
        hook_type = ctypes.WINFUNCTYPE(None, wintypes.HANDLE, DWORD, wintypes.HWND,
                                       ctypes.c_long, ctypes.c_long, DWORD, DWORD)
        _signatures(user32, kernel32, wndproc_type, hook_type)
        pending = deque()
        def record(frame):
            # 60 * maximum 16KiB is below the 1MiB cap; callbacks never encode JSON.
            if len(pending) >= 60: raise RuntimeError('worker frame overflow')
            pending.append(frame)
        session = InputSession(config, record)
        stop = threading.Event()
        callback_error = []
        focus_probe = PasswordProbe()
        excluded = {str(value).lower().removesuffix('.exe') for value in config['excluded_apps']}
        excluded_pids = set(config['excluded_pids']) | {os.getpid()}
        from .permission import current_foreground
        boundary = [int(kernel32.GetTickCount64()) & 0xffffffff]
        foreground_handle = [None]
        focus_token = [0]
        def refresh(*, force=False):
            target = current_foreground() if _desktop_available(user32) else None
            if target:
                image = target.get('image', '').lower().removesuffix('.exe')
                if (target['process_id'] in excluded_pids or image in excluded or image == 'unknown'
                        or not target.get('process_creation')): target = None
            identity = None if target is None else (target['handle'], target['process_id'], target['process_creation'])
            if force or identity != session.target:
                session.foreground(identity, force=force)
                boundary[0] = int(kernel32.GetTickCount64()) & 0xffffffff
                focus_token[0] += 1
                focus_probe.invalidate()
            # Cache the identity we actually validated. A window switch while
            # resolving must be observed again before its first raw event.
            foreground_handle[0] = identity[0] if identity else user32.GetForegroundWindow()
            return target
        initial = refresh(force=True)
        expected = config.get('expected_target')
        if expected is not None and (initial is None or any(initial.get(key) != expected.get(key)
                for key in ('handle', 'process_id', 'process_creation'))):
            raise RuntimeError('initial foreground identity changed')
        def ratios():
            if session.target is None: return None
            point, rect = wintypes.POINT(), wintypes.RECT()
            hwnd = session.target[0]
            if (not user32.GetCursorPos(ctypes.byref(point)) or not user32.ScreenToClient(hwnd, ctypes.byref(point))
                    or not user32.GetClientRect(hwnd, ctypes.byref(rect))): return None
            width, height = rect.right-rect.left, rect.bottom-rect.top
            if width <= 0 or height <= 0 or not 0 <= point.x <= width or not 0 <= point.y <= height: return None
            return point.x/width, point.y/height
        def wndproc(hwnd, message, wparam, lparam):
            try:
                if message == WM_INPUT and not stop.is_set():
                    if user32.GetForegroundWindow() != foreground_handle[0]: refresh(force=True)
                    session.focus(focus_probe.poll((session.target, focus_token[0]) if session.target else None, time.monotonic()))
                    if ((int(user32.GetMessageTime()) & 0xffffffff) - boundary[0]) & 0xffffffff >= 0x80000000:
                        if session.aggregator: session.aggregator.note_dropped()
                    elif session.aggregator is not None:
                        size = wintypes.UINT()
                        header_size = ctypes.sizeof(RAWINPUTHEADER)
                        result = user32.GetRawInputData(lparam, 0x10000003, None, ctypes.byref(size), header_size)
                        if result == 0xffffffff or not header_size <= size.value <= 65536:
                            raise RuntimeError('raw input size')
                        buffer = ctypes.create_string_buffer(size.value)
                        result = user32.GetRawInputData(lparam, 0x10000003, buffer, ctypes.byref(size), header_size)
                        if result == 0xffffffff or result != size.value or size.value < header_size:
                            raise RuntimeError('raw input read')
                        header = ctypes.cast(buffer, ctypes.POINTER(RAWINPUTHEADER)).contents
                        required = header_size + (ctypes.sizeof(RAWKEYBOARD) if header.dwType == RIM_TYPEKEYBOARD else ctypes.sizeof(RAWMOUSE))
                        if header.dwType in (RIM_TYPEKEYBOARD, RIM_TYPEMOUSE):
                            if size.value < required or header.dwSize != size.value: raise RuntimeError('raw input layout')
                            raw = ctypes.cast(buffer, ctypes.POINTER(RAWINPUT)).contents
                            at = time.monotonic()
                            if header.dwType == RIM_TYPEKEYBOARD:
                                if raw.keyboard.VKey < 256: session.key(raw.keyboard.VKey, at, down=not bool(raw.keyboard.Flags & 1))
                            else:
                                relative = ratios() if session.quality == 'ok' and raw.mouse.usButtonFlags & 0x3f else None
                                session.mouse(raw.mouse, at, relative)
            except Exception:
                callback_error.append(True) if not callback_error else None
                stop.set()
            return user32.DefWindowProcW(hwnd, message, wparam, lparam)
        wndproc_ref = wndproc_type(wndproc)
        class WNDCLASS(ctypes.Structure):
            _fields_ = [('style', wintypes.UINT), ('lpfnWndProc', wndproc_type),
                        ('cbClsExtra', ctypes.c_int), ('cbWndExtra', ctypes.c_int),
                        ('hInstance', wintypes.HINSTANCE), ('hIcon', wintypes.HICON),
                        ('hCursor', wintypes.HANDLE), ('hbrBackground', wintypes.HBRUSH),
                        ('lpszMenuName', wintypes.LPCWSTR), ('lpszClassName', wintypes.LPCWSTR)]
        instance = kernel32.GetModuleHandleW(None)
        class_name = 'SumikaInputWorker'
        wc = WNDCLASS(0, wndproc_ref, 0, 0, instance, None, None, None, None, class_name)
        if not user32.RegisterClassW(ctypes.byref(wc)): raise RuntimeError('window class')
        window_class = True
        handle = user32.CreateWindowExW(0, class_name, class_name, 0, 0, 0, 0, 0,
                                        None, None, instance, None)
        if not handle: raise RuntimeError('hidden window')
        register_raw_input(handle, user32)
        registered = True
        def on_event(_hook, event, hwnd, _object, _child, _thread, _time):
            try:
                if event == EVENT_SYSTEM_FOREGROUND:
                    refresh(force=True)
                else:
                    focus_token[0] += 1
                    focus_probe.invalidate()
                    session.focus('privacy_context_unknown')
            except Exception:
                if not callback_error: callback_error.append(True)
                stop.set()
        hook_ref = hook_type(on_event)
        for event in (EVENT_SYSTEM_FOREGROUND, EVENT_OBJECT_FOCUS):
            hook = user32.SetWinEventHook(event, event, None, hook_ref, 0, 0, WINEVENT_OUTOFCONTEXT)
            if not hook: raise RuntimeError('event hook')
            handles.append(hook)
        def reader():
            try:
                while True:
                    command = sys.stdin.buffer.readline(1025)
                    if not command: break
                    if len(command) > 1024 or json.loads(command) != {'action':'stop'}: break
                    break
            finally: stop.set()
        threading.Thread(target=reader, daemon=True, name='sumika-input-control').start()
        emit({'status':'ready', 'worker_epoch':config['worker_epoch']})
        next_refresh = 0
        while not stop.is_set():
            message = wintypes.MSG()
            # A bounded dispatch slice prevents continuous 1000Hz input starving seals.
            for _ in range(256):
                if not user32.PeekMessageW(ctypes.byref(message), None, 0, 0, 1): break
                if message.message == WM_QUIT: stop.set(); break
                user32.TranslateMessage(ctypes.byref(message)); user32.DispatchMessageW(ctypes.byref(message))
            now = time.monotonic()
            if now >= next_refresh:
                refresh(); next_refresh = now + .25
            target = (session.target, focus_token[0]) if session.target else None
            session.focus(focus_probe.poll(target, now))
            session.tick()
            while pending:
                frame = pending.popleft(); validate_frame(frame); emit({'frame':frame})
            stop.wait(.005)
        if callback_error: raise RuntimeError('input callback failed')
        session.seal()
        while pending:
            frame = pending.popleft(); validate_frame(frame); emit({'frame':frame})
        return 0
    except Exception:
        try: emit({'error':'input_worker_failed'})
        except (OSError, ValueError): pass
        return 1
    finally:
        if focus_probe is not None: focus_probe.close()
        if registered:
            try: register_raw_input(handle, user32, remove=True)
            except OSError: pass
        for hook in handles: user32.UnhookWinEvent(hook)
        if handle: user32.DestroyWindow(handle)
        if window_class: user32.UnregisterClassW(class_name, instance)


if __name__ == '__main__':
    raise SystemExit(main())
