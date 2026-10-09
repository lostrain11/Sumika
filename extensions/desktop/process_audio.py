"""Process-isolated WASAPI loopback bridge.

The native helper is a separate process because WGC/OpenCV and ONNX/Silero have
incompatible native DLL load order in one interpreter. PCM remains a bounded
memory stream and is never written to a recording file.
"""
import base64
import json
import subprocess
import threading
from pathlib import Path
from sumika_next.child_job import ChildJob


class ProcessAudioCapture:
    def __init__(self, helper, *, process_id, creation_time, approved=False):
        if approved is not True:
            raise PermissionError('explicit application audio consent required')
        if type(process_id) is not int or process_id <= 0:
            raise ValueError('positive process id required')
        if (not isinstance(creation_time, str) or not creation_time.isascii()
                or not creation_time.isdigit() or not 0 < int(creation_time) < 2**63):
            raise ValueError('process creation identity required')
        self.helper = str(Path(helper).resolve())
        if not Path(self.helper).is_file():
            raise FileNotFoundError(self.helper)
        self.process_id, self.creation_time = process_id, creation_time
        self._process = None
        self._reader = None
        self._lock = threading.Lock()
        self._job = None
        self._diagnostics = None
        self._lifecycle = threading.RLock()
        self._ready = threading.Event()
        self._stopping = threading.Event()
        self._state = 'idle'
        self.error = None

    @staticmethod
    def capability(helper):
        path = Path(helper).resolve()
        if not path.is_file():
            return {'supported': False, 'provider': 'wasapi-process-loopback',
                    'process_isolation': None, 'reason': 'native helper unavailable'}
        result = subprocess.run([str(path), '--probe'], capture_output=True, text=True,
                                encoding='utf-8', timeout=10, check=True)
        return json.loads(result.stdout)

    def status(self):
        with self._lock:
            return {'state': self._state, 'error': self.error,
                    'process_id': self.process_id, 'creation': self.creation_time}

    def _fail(self, reason):
        with self._lock:
            if not self._stopping.is_set() and self.error is None:
                self.error = reason
                self._state = 'error'
        self._ready.set()

    def start(self, on_pcm, *, on_timing=None, timeout=10):
        if not callable(on_pcm):
            raise TypeError('PCM callback required')
        if on_timing is not None and not callable(on_timing):
            raise TypeError('timing callback must be callable')
        if type(timeout) not in (int, float) or not 0 < timeout <= 30:
            raise ValueError('invalid process audio startup timeout')
        with self._lifecycle:
            if self._process is not None:
                raise RuntimeError('process audio capture already active')
            self._ready.clear()
            self._stopping.clear()
            with self._lock:
                self.error = None
                self._state = 'starting'
            try:
                self._process = subprocess.Popen(
                    [self.helper, '--process-id', str(self.process_id), '--creation',
                     self.creation_time, '--consent'], stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                    encoding='utf-8', bufsize=1)
            except OSError:
                self._fail('helper_launch_failed')
                raise
            process = self._process
            try:
                self._job = ChildJob()
                self._job.assign(process)
                process.stdin.write('START\n')
                process.stdin.flush()
            except BaseException:
                process.kill()
                process.wait(timeout=5)
                if self._job is not None:
                    self._job.close()
                    self._job = None
                for stream in (process.stdin, process.stdout, process.stderr):
                    stream.close()
                self._process = None
                self._fail('ownership_failed')
                raise
            self._diagnostics = threading.Thread(target=self._read_errors, args=(process,),
                                                 name='sumika-process-audio-errors', daemon=True)
            self._reader = threading.Thread(target=self._read, args=(process, on_pcm, on_timing),
                                            name='sumika-process-audio', daemon=True)
            self._diagnostics.start()
            self._reader.start()
            if not self._ready.wait(timeout):
                self._fail('startup_timeout')
            state = self.status()
            if state['state'] != 'recording':
                self.stop()
                raise RuntimeError(f"process audio startup failed: {state['error']}")
            return state

    def _read_errors(self, process):
        try:
            while True:
                line = process.stderr.readline(4097)
                if not line:
                    return
                if len(line) > 4096 or not line.endswith('\n'):
                    raise ValueError('invalid helper diagnostic')
                packet = json.loads(line)
                if packet.get('status') != 'error':
                    raise ValueError('unknown helper diagnostic')
                self._fail({'reason': str(packet.get('reason', 'helper_failed'))[:128],
                            'hresult': packet.get('hresult')})
        except Exception:
            self._fail('invalid_helper_diagnostic')

    def _read(self, process, on_pcm, on_timing=None):
        try:
            started = False
            while True:
                line = process.stdout.readline(90001)
                if not line:
                    break
                if len(line) > 90000 or not line.endswith('\n'):
                    raise ValueError('oversized or incomplete process audio packet')
                packet = json.loads(line)
                if packet.get('status') == 'error':
                    raise RuntimeError(packet.get('reason', 'process audio failed'))
                if packet.get('status') == 'started':
                    if (started or packet.get('process_id') != self.process_id
                            or packet.get('creation') != self.creation_time
                            or packet.get('sample_rate') != 16000 or packet.get('channels') != 1
                            or packet.get('sample_width') != 2 or packet.get('process_isolation') is not True):
                        raise ValueError('process audio handshake mismatch')
                    started = True
                    with self._lock:
                        if self._stopping.is_set():
                            break
                        self._state = 'recording'
                    self._ready.set()
                    continue
                if packet.get('status') != 'pcm' or not started:
                    raise ValueError('unexpected process audio packet')
                if packet.get('process_id') != self.process_id:
                    raise ValueError('process audio target mismatch')
                raw = base64.b64decode(packet.get('pcm', ''), validate=True)
                if len(raw) == 0 or len(raw) > 64000 or len(raw) % 2:
                    raise ValueError('invalid process audio PCM packet')
                if not self._stopping.is_set():
                    if on_timing is not None and ('device_position' in packet or 'qpc_position' in packet):
                        device_position, qpc_position = packet.get('device_position'), packet.get('qpc_position')
                        if (type(device_position) is not int or device_position < 0
                                or device_position >= 2**64
                                or type(qpc_position) is not int or not 0 <= qpc_position < 2**64):
                            raise ValueError('invalid process audio clock metadata')
                        flags = packet.get('capture_flags', 0)
                        if type(flags) is not int or not 0 <= flags <= 7:
                            raise ValueError('invalid process audio clock flags')
                        on_timing({'device_position': device_position,
                                   'qpc_position': qpc_position, 'sample_rate': 16000,
                                   'timestamp_valid': not bool(flags & 4),
                                   'data_discontinuity': bool(flags & 1),
                                   'clock_scope': 'native-packet-start', 'qpc_unit': '100ns'})
                    elif on_timing is not None:
                        on_timing(None)
                    on_pcm(raw)
            process.wait(timeout=5)
            if self._diagnostics is not None:
                self._diagnostics.join(timeout=5)
            if not self._stopping.is_set():
                self._fail('unexpected_helper_exit')
        except Exception as error:
            self._fail(type(error).__name__)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)

    def stop(self):
        with self._lifecycle:
            self._stop()

    def _stop(self):
        with self._lock:
            process, reader, job, diagnostics = (self._process, self._reader,
                                               self._job, self._diagnostics)
            self._stopping.set()
        if process is None:
            return
        try:
            if process.stdin:
                process.stdin.close()
            process.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            process.kill()
            process.wait(timeout=5)
        if reader is not None:
            if reader is threading.current_thread():
                raise RuntimeError('PCM consumer must request stop from its owner thread')
            reader.join(timeout=5)
            if reader.is_alive():
                raise RuntimeError('process audio consumer did not settle')
        if diagnostics is not None:
            diagnostics.join(timeout=5)
            if diagnostics.is_alive():
                raise RuntimeError('process audio diagnostics did not settle')
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream is not None and not stream.closed:
                stream.close()
        if job is not None:
            job.close()
        with self._lock:
            self._process = self._reader = self._job = None
            self._diagnostics = None
            if self.error is None:
                self._state = 'stopped'
