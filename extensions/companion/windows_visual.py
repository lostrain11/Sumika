"""Collect an authorized HWND frame as a bounded, in-memory observation."""
import argparse
import base64
from dataclasses import asdict
import io
import json
import re
import threading

from .contracts import ObservationBundle


class WindowsVisualCollector:
    """Lifecycle-owned collector that reuses one native session per HWND/PID."""
    def __init__(self, *, approved=False, session_factory=None):
        if approved is not True:
            raise PermissionError('explicit window capture consent required')
        if session_factory is None:
            from extensions.desktop.windows_capture import WindowCaptureSession
            session_factory = WindowCaptureSession
        self._factory = session_factory
        self._session = None
        self._target = None
        self._active = True
        self._lock = threading.RLock()

    def __call__(self, target):
        match = re.fullmatch(r'window:([1-9][0-9]*):pid:([1-9][0-9]*)', target)
        if match is None:
            raise ValueError('exact window HWND/PID target required')
        handle, pid = map(int, match.groups())
        with self._lock:
            if not self._active:
                raise RuntimeError('visual collector is paused or stopped')
            if self._session is None or self._target != target:
                self._close_session()
                session = self._factory(handle=handle, process_id=pid, approved=True)
                try:
                    session.start()
                except Exception:
                    session.stop()
                    raise
                self._session, self._target = session, target
            session = self._session
        try:
            return collect_visual(handle=handle, process_id=pid, approved=True,
                                  collector=lambda **kwargs: session.snapshot())
        except Exception:
            with self._lock:
                if self._session is session:
                    self.stop()
            raise

    def stop(self):
        with self._lock:
            self._active = False
            self._close_session()

    def start(self):
        with self._lock:
            self._active = True

    def _close_session(self):
        with self._lock:
            session, self._session = self._session, None
            self._target = None
            if session is not None:
                session.stop()


def collect_visual(*, handle, process_id, approved=False, collector=None):
    if collector is None:
        from extensions.desktop.windows_capture import capture_frame
        collector = capture_frame
    frame = collector(handle=handle, process_id=process_id, approved=approved)
    image = None
    if frame['valid']:
        from PIL import Image
        pixels = frame['pixels']
        with Image.fromarray(pixels[:, :, [2, 1, 0]]) as bitmap:
            bitmap.thumbnail((1600, 1600))
            buffer = io.BytesIO()
            bitmap.save(buffer, format='JPEG', quality=85)
            image = {'media_type': 'image/jpeg',
                     'data_base64': base64.b64encode(buffer.getvalue()).decode('ascii')}
    return ObservationBundle.now(source='window-visual', target=f'window:{handle}:pid:{process_id}',
        valid=frame['valid'], image=image,
        metadata={'collector': frame['provider'], 'width': frame['width'], 'height': frame['height'],
                  'reason': frame.get('reason')})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--handle', type=int, required=True)
    parser.add_argument('--process-id', type=int, required=True)
    args = parser.parse_args()
    value = asdict(collect_visual(handle=args.handle, process_id=args.process_id, approved=True))
    value['observed_at'] = value['observed_at'].isoformat()
    print(json.dumps(value))


if __name__ == '__main__':
    main()
