"""Hidden Win32 Raw Input worker (P11, behavior-memory-plan §2.2).

Registers keyboard/mouse Generic Desktop with RIDEV_INPUTSINK — no
NOLEGACY, no CAPTUREMOUSE, no hotkeys; never hooks, swallows keys,
SendInput or grabs focus; no ToUnicode/ToAscii, no clipboard/IME text, no
UIA Name/Text/Value reads. Raw VK/scan codes and device handles are
classified in the moment and never leave this process: only pure
InputFeatureFrames cross the pipe. The foreground is tracked with a
OUTOFCONTEXT WinEventHook; the focus probe asks UIA only IsPassword, at
most 4 times per second with a 200ms timeout. IPC is line JSON on stdio:
frames out, config/stop in. Any failure stops the channel with its reason.
"""
import ctypes
import json
import sys
import threading
import time

from extensions.behavior.input_features import FrameAggregator

WM_INPUT = 0x00FF
WM_QUIT = 0x0012
RIM_TYPEKEYBOARD = 1
RIM_TYPEMOUSE = 0
RIDEV_INPUTSINK = 0x00000001
EVENT_SYSTEM_FOREGROUND = 0x0003
WINEVENT_OUTOFCONTEXT = 0x0000


def register_raw_input():
    """Keyboard+mouse sink registration; legacy input stays untouched.

    RIDEV_INPUTSINK pairs with a NULL hwndTarget on current Windows: WM_INPUT
    is delivered to the thread's message queue (this worker's pump), which is
    exactly the background-sink behavior §2.2 requires. An explicit target
    window with INPUTSINK is rejected with ERROR_INVALID_PARAMETER.
    """
    user32 = ctypes.WinDLL('user32', use_last_error=True)
    class RAWINPUTDEVICE(ctypes.Structure):
        _fields_ = [('usUsagePage', ctypes.c_ushort),
                    ('usUsage', ctypes.c_ushort), ('dwFlags', ctypes.c_ulong),
                    ('hwndTarget', ctypes.c_void_p)]
    devices = (RAWINPUTDEVICE * 2)(
        RAWINPUTDEVICE(1, 6, RIDEV_INPUTSINK, None),   # keyboard
        RAWINPUTDEVICE(1, 2, RIDEV_INPUTSINK, None))   # mouse
    if not user32.RegisterRawInputDevices(devices, 2, ctypes.sizeof(RAWINPUTDEVICE)):
        raise OSError('RegisterRawInputDevices failed: '
                      + str(ctypes.get_last_error()))
    return True


def worker_loop(config, emit, *, stop_event=None, probe=None, clock=None):
    """Aggregate one second frames until stop; Win32 bindings are injected so
    the aggregation itself stays testable without a desktop."""
    now = clock or time.monotonic
    aggregator = None
    sequence = 0
    identity = {'user_scope': config['user_scope'],
                'worker_epoch': config['worker_epoch'],
                'foreground_epoch': 0, 'focus_epoch': 0, 'window_instance': 0}
    while not (stop_event and stop_event.is_set()):
        started = now()
        aggregator = FrameAggregator(identity=identity,
                                     observed_from=str(started),
                                     sequence=sequence)
        # The platform layer feeds events between here and the seal; with no
        # real input the frame is skipped entirely (only non-empty frames
        # exist per §2.3).
        while not (stop_event and stop_event.is_set()):
            pending = probe() if probe else None
            if pending:
                event, value, at = pending
                if event == 'key':
                    aggregator.key(value, at)
                elif event == 'shortcut':
                    aggregator.shortcut(*value)
                elif event == 'click':
                    aggregator.click(*value)
                elif event == 'move':
                    aggregator.move()
                elif event == 'scroll':
                    aggregator.scroll(*value)
                elif event == 'drag':
                    aggregator.drag(*value)
                elif event == 'focus':
                    aggregator.focus(value)
                elif event == 'foreground':
                    identity['foreground_epoch'] += 1
                    identity['window_instance'] = value
                    aggregator = FrameAggregator(
                        identity=identity, observed_from=str(started),
                        sequence=sequence)
            if now() - started >= 1.0:
                break
            time.sleep(0.01)
        if stop_event and stop_event.is_set():
            break
        frame = aggregator.seal(str(now()))
        if frame['keys']['counts'] or frame['mouse']['moves'] or \
                frame['mouse']['left'] or frame['scroll']['vertical']['count']:
            emit(frame)
            sequence += 1


def main():
    """Real Win32 entry: hidden window + Raw Input sink + foreground hook.

    WM_INPUT payloads become anonymous counts immediately; raw VK/scan codes
    and device handles never leave this function. Failures stop the channel
    with one structured error line — no restart, no replay.
    """
    import os
    if os.name != 'nt':
        sys.stderr.write('raw input requires Windows\n')
        return 1
    config_line = sys.stdin.readline()
    if not config_line:
        return 0
    config = json.loads(config_line)
    emit_lock = threading.Lock()

    def emit(line):
        with emit_lock:
            sys.stdout.write(json.dumps(line, ensure_ascii=False) + '\n')
            sys.stdout.flush()

    class RAWINPUTHEADER(ctypes.Structure):
        _fields_ = [('dwType', ctypes.c_ulong), ('dwSize', ctypes.c_ulong),
                    ('hDevice', ctypes.c_void_p), ('wParam', ctypes.c_void_p)]

    class RAWKEYBOARD(ctypes.Structure):
        _fields_ = [('MakeCode', ctypes.c_ushort), ('Flags', ctypes.c_ushort),
                    ('Reserved', ctypes.c_ushort), ('VKey', ctypes.c_ushort),
                    ('Message', ctypes.c_uint),
                    ('ExtraInformation', ctypes.c_ulong)]

    class RAWMOUSE(ctypes.Structure):
        _fields_ = [('usFlags', ctypes.c_ushort), ('ulButtons', ctypes.c_ulong),
                    ('ulRawButtons', ctypes.c_ulong), ('ulLastX', ctypes.c_long),
                    ('ulLastY', ctypes.c_long),
                    ('ulExtraInformation', ctypes.c_ulong)]

    class RAWINPUT(ctypes.Structure):
        _fields_ = [('header', RAWINPUTHEADER),
                    ('padding', ctypes.c_ubyte * 8),
                    ('keyboard', RAWKEYBOARD), ('mouse', RAWMOUSE)]

    RI_KEY_BREAK = 0x0001
    RI_MOUSE_LEFT_DOWN = 0x0001
    RI_MOUSE_RIGHT_DOWN = 0x0004
    RI_MOUSE_MIDDLE_DOWN = 0x0010
    RI_MOUSE_WHEEL = 0x0400

    events = []
    events_lock = threading.Lock()
    modifiers = set()

    def on_key(vkey, at):
        if vkey in (0x10, 0xA0, 0xA1):
            modifiers.add('shift')
        elif vkey in (0x11, 0xA2, 0xA3):
            modifiers.add('ctrl')
        elif vkey in (0x12, 0xA4, 0xA5):
            modifiers.add('alt')
        events.append(('key', vkey, at))

    def on_key_up(vkey):
        for name, codes in (('shift', (0x10, 0xA0, 0xA1)),
                            ('ctrl', (0x11, 0xA2, 0xA3)),
                            ('alt', (0x12, 0xA4, 0xA5))):
            if vkey in codes:
                modifiers.discard(name)

    def on_shortcut_check(vkey):
        if modifiers and vkey not in (0x10, 0x11, 0x12, 0xA0, 0xA1, 0xA2,
                                      0xA3, 0xA4, 0xA5):
            events.append(('shortcut', (vkey, frozenset(modifiers)), None))

    user32 = ctypes.WinDLL('user32', use_last_error=True)
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_longlong, ctypes.c_void_p,
                                 ctypes.c_uint, ctypes.c_ulonglong,
                                 ctypes.c_longlong)

    def wndproc(handle, message, wparam, lparam):
        if message == WM_INPUT:
            size = ctypes.c_uint(0)
            header_size = ctypes.sizeof(RAWINPUTHEADER)
            user32.GetRawInputData(ctypes.c_void_p(lparam), 0x10000003, None,
                                   ctypes.byref(size), header_size)
            if size.value:
                buffer = ctypes.create_string_buffer(size.value)
                if user32.GetRawInputData(ctypes.c_void_p(lparam), 0x10000003,
                                          buffer, ctypes.byref(size),
                                          header_size):
                    raw = ctypes.cast(buffer,
                                      ctypes.POINTER(RAWINPUT)).contents
                    at = time.monotonic()
                    with events_lock:
                        if raw.header.dwType == RIM_TYPEKEYBOARD:
                            vkey = raw.keyboard.VKey & 0xFF
                            if not raw.keyboard.Flags & RI_KEY_BREAK:
                                on_key(vkey, at)
                                on_shortcut_check(vkey)
                            else:
                                on_key_up(vkey)
                        elif raw.header.dwType == RIM_TYPEMOUSE:
                            buttons = raw.mouse.ulButtons
                            if buttons & RI_MOUSE_LEFT_DOWN:
                                events.append(('click', ('left', 0.5, 0.5), at))
                            if buttons & RI_MOUSE_RIGHT_DOWN:
                                events.append(('click', ('right', 0.5, 0.5), at))
                            if buttons & RI_MOUSE_MIDDLE_DOWN:
                                events.append(('click', ('middle', 0.5, 0.5), at))
                            if buttons & RI_MOUSE_WHEEL:
                                events.append(('scroll', ('vertical', 1), at))
            return 0
        # Explicit width conversion: a widened wparam/lparam overflows the
        # default c_int conversion inside the callback.
        return user32.DefWindowProcW(ctypes.c_void_p(handle),
                                     ctypes.c_uint(message),
                                     ctypes.c_ulonglong(wparam),
                                     ctypes.c_longlong(lparam))

    wndproc_ref = WNDPROC(wndproc)

    class WNDCLASS(ctypes.Structure):
        _fields_ = [('style', ctypes.c_uint), ('lpfnWndProc', WNDPROC),
                    ('cbClsExtra', ctypes.c_int), ('cbWndExtra', ctypes.c_int),
                    ('hInstance', ctypes.c_void_p), ('hIcon', ctypes.c_void_p),
                    ('hCursor', ctypes.c_void_p),
                    ('hbrBackground', ctypes.c_void_p),
                    ('lpszMenuName', ctypes.c_wchar_p),
                    ('lpszClassName', ctypes.c_wchar_p)]

    instance = kernel32.GetModuleHandleW(None)
    window_class = WNDCLASS(0, wndproc_ref, 0, 0, instance, None, None, None,
                            None, 'SumikaInputWorker')
    if not user32.RegisterClassW(ctypes.byref(window_class)):
        emit({'error': 'RegisterClassW failed'})
        return 1
    handle = user32.CreateWindowExW(0, 'SumikaInputWorker',
                                    'SumikaInputWorker', 0, 0, 0, 0, 0, None,
                                    None, instance, None)
    if not handle:
        emit({'error': 'CreateWindowExW failed'})
        return 1
    try:
        register_raw_input()
    except OSError as error:
        emit({'error': str(error)})
        return 1

    foreground_epoch = [0]
    hook = []
    win_event_type = ctypes.WINFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p,
                                        ctypes.c_uint, ctypes.c_void_p,
                                        ctypes.c_long, ctypes.c_long,
                                        ctypes.c_uint, ctypes.c_ulong)

    def win_event_proc(_hook, _event, hwnd, _object, _child, _thread, _time):
        process_id = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
        foreground_epoch[0] += 1
        with events_lock:
            events.append(('foreground', int(hwnd) & 0xFFFF, None))

    hook_ref = win_event_type(win_event_proc)
    if not user32.SetWinEventHook(EVENT_SYSTEM_FOREGROUND,
                                  EVENT_SYSTEM_FOREGROUND, None, hook_ref,
                                  0, 0, WINEVENT_OUTOFCONTEXT):
        emit({'error': 'SetWinEventHook failed'})
        return 1
    hook.append(hook_ref)

    stop = threading.Event()
    pump_thread_id = kernel32.GetCurrentThreadId()

    def reader():
        try:
            for line in sys.stdin:
                message = json.loads(line)
                if message.get('action') == 'stop':
                    break
        finally:
            stop.set()
            # WM_QUIT must reach the MESSAGE-PUMP thread, not this reader.
            user32.PostThreadMessageW(pump_thread_id, WM_QUIT, 0, 0)

    threading.Thread(target=reader, daemon=True).start()

    sequence = 0
    identity = {'user_scope': config['user_scope'],
                'worker_epoch': config['worker_epoch'],
                'foreground_epoch': 0, 'focus_epoch': 0, 'window_instance': 0}
    aggregator = None
    second_started = time.monotonic()
    flush_at = second_started + 10
    pending = []

    def record(frame):
        if frame['keys']['counts'] or frame['mouse']['moves'] or \
                frame['mouse']['left'] or frame['scroll']['vertical']['count']:
            pending.append(frame)
            return True
        return False

    try:
        while not stop.is_set():
            message = ctypes.c_uint(0)
            result = user32.GetMessageW(ctypes.byref(message), None, 0, 0)
            if result <= 0 or message.value == WM_QUIT:
                break
            user32.TranslateMessage(ctypes.byref(message))
            user32.DispatchMessageW(ctypes.byref(message))
            with events_lock:
                drained, events[:] = events[:], []
            for name, value, at in drained:
                if name == 'foreground':
                    if aggregator is not None and record(
                            aggregator.seal(str(time.monotonic()))):
                        sequence += 1
                    identity['foreground_epoch'] += 1
                    identity['window_instance'] = value
                    aggregator = FrameAggregator(
                        identity=dict(identity),
                        observed_from=str(time.monotonic()),
                        sequence=sequence)
                    second_started = time.monotonic()
                elif aggregator is not None:
                    if name == 'key':
                        aggregator.key(value, at)
                    elif name == 'shortcut':
                        aggregator.shortcut(*value)
                    elif name == 'click':
                        aggregator.click(*value)
                    elif name == 'move':
                        aggregator.move()
                    elif name == 'scroll':
                        aggregator.scroll(*value)
            if aggregator is None:
                aggregator = FrameAggregator(
                    identity=dict(identity),
                    observed_from=str(time.monotonic()), sequence=sequence)
            if not stop.is_set() and time.monotonic() - second_started >= 1.0:
                if record(aggregator.seal(str(time.monotonic()))):
                    sequence += 1
                aggregator = FrameAggregator(
                    identity=dict(identity),
                    observed_from=str(time.monotonic()), sequence=sequence)
                second_started = time.monotonic()
            if pending and (time.monotonic() >= flush_at
                            or len(pending) >= 256):
                for frame in pending:
                    emit({'frame': frame})
                pending = []
                flush_at = time.monotonic() + 10
    finally:
        for frame in pending:  # bounded flush; a crash loses one batch
            emit({'frame': frame})
        if hook:
            user32.UnhookWinEvent(hook[0])
        user32.DestroyWindow(handle)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
