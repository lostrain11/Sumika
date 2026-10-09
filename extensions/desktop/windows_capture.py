"""Window-only WGC capture using the existing windows-capture native library."""
import os
import ctypes
import threading
from pathlib import Path


def capability():
    if os.name != 'nt':
        return {'supported': False, 'provider': 'windows-graphics-capture',
                'reason': 'Windows is required'}
    try:
        from winrt.windows.graphics.capture import GraphicsCaptureSession
        from windows_capture import WindowsCapture
        supported = bool(GraphicsCaptureSession.is_supported())
    except (ImportError, AttributeError, OSError) as error:
        return {'supported': False, 'provider': 'windows-graphics-capture',
                'reason': f'WinRT binding unavailable: {error}'}
    return {'supported': supported, 'provider': 'windows-graphics-capture',
            'reason': None if supported else 'OS capture support is disabled'}


def _identity(handle, process_id):
    if os.name != 'nt':
        raise RuntimeError('Windows is required')
    user32 = ctypes.WinDLL('user32', use_last_error=True)
    user32.IsWindow.argtypes = [ctypes.c_void_p]
    user32.IsWindowVisible.argtypes = [ctypes.c_void_p]
    user32.IsIconic.argtypes = [ctypes.c_void_p]
    user32.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
    user32.GetAncestor.argtypes = [ctypes.c_void_p, ctypes.c_uint]
    user32.GetAncestor.restype = ctypes.c_void_p
    user32.GetPropW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]
    user32.GetPropW.restype = ctypes.c_void_p
    current = ctypes.c_ulong()
    if not user32.IsWindow(handle) or not user32.IsWindowVisible(handle) or user32.IsIconic(handle):
        raise RuntimeError('capture target is not a visible window')
    user32.GetWindowThreadProcessId(handle, ctypes.byref(current))
    if current.value != process_id or current.value == os.getpid():
        raise RuntimeError('capture target process changed or is the capture host')
    root = user32.GetAncestor(handle, 2) or handle
    if user32.GetPropW(root, 'Sumika.Companion.CaptureHost'):
        raise RuntimeError('companion host cannot be a learning capture target')


def capture_frame(*, handle, process_id, approved=False, timeout=5):
    """Return copied BGRA pixels in memory; never capture a desktop fallback."""
    if type(handle) is not int or handle <= 0:
        raise ValueError('positive window handle required')
    if type(process_id) is not int or process_id <= 0:
        raise ValueError('positive process id required')
    if approved is not True:
        raise PermissionError('explicit window capture consent required')
    if type(timeout) not in (int, float) or not .1 <= timeout <= 15:
        raise ValueError('invalid capture timeout')
    status = capability()
    if not status['supported']:
        raise RuntimeError(status['reason'])
    _identity(handle, process_id)
    from windows_capture import WindowsCapture
    capture = WindowsCapture(window_hwnd=handle, cursor_capture=False, draw_border=True)
    ready = threading.Event()
    outcome = {}

    @capture.event
    def on_frame_arrived(frame, control):
        try:
            _identity(handle, process_id)
            outcome['pixels'] = frame.frame_buffer.copy()
            outcome['timespan'] = frame.timespan
        except Exception as error:
            outcome['error'] = error
        finally:
            control.stop()
            ready.set()

    @capture.event
    def on_closed():
        ready.set()

    control = capture.start_free_threaded()
    try:
        if not ready.wait(timeout):
            raise RuntimeError('WGC capture timed out without a frame')
    finally:
        control.stop()
        control.wait()
    if 'error' in outcome:
        raise outcome['error']
    if 'pixels' not in outcome:
        raise RuntimeError('capture window closed without a frame')
    _identity(handle, process_id)
    pixels = outcome['pixels']
    from .capture import frame_is_usable
    validity = frame_is_usable((float(pixels[:, :, :3].mean()), float(pixels[:, :, :3].std())))
    return {'pixels': pixels, 'width': pixels.shape[1], 'height': pixels.shape[0],
            'valid': validity['usable'], 'reason': validity.get('reason'),
            'provider': 'windows-graphics-capture', 'handle': handle, 'process_id': process_id,
            'timespan': outcome['timespan']}


class WindowCaptureSession:
    """One native WGC session, retaining only its latest copied frame in memory."""

    def __init__(self, *, handle, process_id, approved=False):
        if type(handle) is not int or handle <= 0 or type(process_id) is not int or process_id <= 0:
            raise ValueError('positive window handle and process id required')
        if approved is not True:
            raise PermissionError('explicit window capture consent required')
        self.handle, self.process_id = handle, process_id
        self._lock = threading.Lock()
        self._ready = threading.Event()
        self._control = None
        self._capture = None
        self._pixels = None
        self._timespan = None
        self._error = None
        self._stopped = False
        self.frames_copied = 0

    def start(self):
        with self._lock:
            if self._capture is not None or self._stopped:
                raise RuntimeError('capture session cannot be restarted')
        status = capability()
        if not status['supported']:
            raise RuntimeError(status['reason'])
        _identity(self.handle, self.process_id)
        from windows_capture import WindowsCapture
        capture = WindowsCapture(window_hwnd=self.handle, cursor_capture=False, draw_border=True)

        @capture.event
        def on_frame_arrived(frame, control):
            try:
                _identity(self.handle, self.process_id)
                with self._lock:
                    if self._stopped:
                        control.stop()
                        return
                    # Keep the trailing frame too: static windows may never emit
                    # another callback after a short burst of content changes.
                    self._pixels = frame.frame_buffer.copy()
                    self._timespan = frame.timespan
                    self.frames_copied += 1
                    self._ready.set()
            except Exception as error:
                with self._lock:
                    self._error = error
                    self._pixels = None
                    self._ready.set()
                control.stop()

        @capture.event
        def on_closed():
            with self._lock:
                self._pixels = None
                if not self._stopped:
                    self._error = RuntimeError('capture window closed')
                self._ready.set()

        self._capture = capture
        self._control = capture.start_free_threaded()
        return self

    def snapshot(self, *, timeout=5):
        if type(timeout) not in (int, float) or not .1 <= timeout <= 15:
            raise ValueError('invalid capture timeout')
        if not self._ready.wait(timeout):
            raise RuntimeError('WGC capture timed out without a frame')
        _identity(self.handle, self.process_id)
        with self._lock:
            if self._stopped:
                raise RuntimeError('capture session stopped')
            if self._error is not None:
                raise self._error
            if self._pixels is None:
                raise RuntimeError('capture frame unavailable')
            pixels, timespan = self._pixels.copy(), self._timespan
        from .capture import frame_is_usable
        validity = frame_is_usable((float(pixels[:,:,:3].mean()), float(pixels[:,:,:3].std())))
        return {'pixels': pixels, 'width': pixels.shape[1], 'height': pixels.shape[0],
                'valid': validity['usable'], 'reason': validity.get('reason'),
                'provider': 'windows-graphics-capture', 'handle': self.handle,
                'process_id': self.process_id, 'timespan': timespan}

    def stop(self):
        with self._lock:
            self._stopped = True
            self._pixels = None
            self._ready.set()
            control = self._control
        if control is not None:
            control.stop()
            control.wait()
        with self._lock:
            self._control = self._capture = None


def capture_window(*, handle, output, process_id=None, approved=False, timeout=5):
    """Explicitly save a diagnostic frame; ordinary collection uses memory only."""
    if type(handle) is not int or handle <= 0:
        raise ValueError('positive window handle required')
    destination = Path(output).resolve()
    if destination.exists():
        raise FileExistsError(destination)
    result = capture_frame(handle=handle, process_id=process_id, approved=approved, timeout=timeout)
    from PIL import Image
    pixels = result.pop('pixels')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open('xb') as stream:
        Image.fromarray(pixels[:, :, [2, 1, 0, 3]]).save(stream, format='PNG')
    return {**result, 'path': str(destination)}
