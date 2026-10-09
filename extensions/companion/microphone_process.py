"""Own the continuous microphone worker and its playback descendants."""
import json
from collections import deque
from contextlib import contextmanager
import os
from pathlib import Path
import subprocess
import threading

from extensions.desktop.runtime import capability_python
from sumika_next.child_job import ChildJob
from extensions.models.cancellation import CancellationToken
from .microphone_worker import observation, require_configuration


class MicrophoneProcess:
    def __init__(self, *, root, on_event):
        self.root = Path(root)
        self.on_event = on_event
        self._lock = threading.RLock()
        self._condition = threading.Condition(self._lock)
        self._lifecycle = threading.RLock()
        self._ready = threading.Event()
        self._epoch = 0
        self._process = self._job = self._reader = self._writer = None
        self._pending = None
        self._controls = deque()
        self._control_sequence = 0
        self._control_ack = 0
        self._text_lock = threading.Lock()
        self._text_token = None
        self._state, self._target, self._error = 'stopped', None, None

    def admission_token(self):
        with self._lock:
            return self._epoch

    def status(self):
        with self._lock:
            return {'status':self._state, 'target':self._target, 'error':self._error,
                    'alive':self._process is not None and self._process.poll() is None}

    @staticmethod
    def _encode(packet):
        line = json.dumps(packet, ensure_ascii=True)+'\n'
        if len(line) > 8_000_000:
            raise ValueError('study voice packet exceeds pipe budget')
        return line

    def start(self, config, *, admission_token=None):
        with self._lock:
            token = self._epoch if admission_token is None else admission_token
            if type(token) is not int or token != self._epoch:
                raise RuntimeError('study voice start was revoked')
        # Freeze caller-owned dictionaries before a concurrent settings/UI change.
        config = json.loads(json.dumps(config))
        config['root'] = str(self.root.resolve())
        require_configuration(config)
        initial = observation(config['observation'])
        if not initial.valid:
            raise ValueError('valid learning observation required')
        interpreter = capability_python('voice', root=self.root)
        if interpreter is None or not Path(config['model']).is_dir():
            raise RuntimeError('study voice runtime or model unavailable')
        encoded = self._encode(config)
        with self._lifecycle:
            with self._lock:
                if token != self._epoch:
                    raise RuntimeError('study voice start was revoked')
                if self._process is not None:
                    raise RuntimeError('stop study voice before restarting')
                self._epoch += 1
                epoch = self._epoch
                self._ready.clear()
                self._control_sequence = self._control_ack = 0
                self._controls.clear()
                self._state, self._target, self._error = 'starting', initial.target, None
            try:
                process = subprocess.Popen([interpreter, '-X', 'utf8', '-B', '-m',
                    'extensions.companion.microphone_worker'], cwd=self.root,
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                    text=True, encoding='utf8',
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
                with self._lock:
                    self._process = process
                    self._job = ChildJob()
                    self._job.assign(process)
                    if epoch != self._epoch:
                        raise RuntimeError('study voice start was revoked')
                    self._writer = threading.Thread(target=self._write,
                        args=(process, epoch, encoded), daemon=True, name='sumika-mic-control')
                    self._reader = threading.Thread(target=self._read,
                        args=(process, epoch), daemon=True, name='sumika-mic-events')
                    self._writer.start()
                    self._reader.start()
                if not self._ready.wait(30):
                    raise RuntimeError('study voice startup timed out')
                with self._lock:
                    if epoch != self._epoch:
                        raise RuntimeError('study voice start was revoked')
                    if self._state != 'listening':
                        raise RuntimeError('study voice worker failed to start')
                    return self.status()
            except BaseException:
                self.stop()
                raise

    def observe(self, value):
        line = self._encode({'action':'observe', 'observation':value})
        current = observation(value)
        with self._condition:
            invalid = not current.valid or current.target != self._target
            if not invalid and self._state in ('starting', 'listening'):
                self._pending = line
                self._condition.notify_all()
                return True
        if invalid:
            self.stop()
        return False

    def _control(self, action, epoch):
        with self._condition:
            if epoch != self._epoch or self._state != 'listening':
                raise RuntimeError('study voice control was revoked')
            self._control_sequence += 1
            request = self._control_sequence
            self._controls.append(self._encode({'action':action, 'request':request}))
            self._condition.notify_all()
            acknowledged = self._condition.wait_for(
                lambda: epoch != self._epoch or self._control_ack >= request, timeout=10)
            if not acknowledged or epoch != self._epoch:
                raise RuntimeError('study voice control did not complete')

    def post(self, packet):
        """Queue one ordered, fire-and-forget host action for the worker.

        Answer stream and discussion deliveries must never wait on an
        acknowledgement: model latency would stall the control queue.
        """
        if not isinstance(packet, dict) or packet.get('action') not in (
                'answer_delta', 'answer_done', 'answer_error',
                'answer_invalidated', 'discuss'):
            raise ValueError('unsupported study voice host action')
        with self._condition:
            if self._state != 'listening':
                raise RuntimeError('study voice control was revoked')
            self._controls.append(self._encode(packet))
            self._condition.notify_all()

    @contextmanager
    def text_question(self):
        with self._text_lock:
            token = CancellationToken()
            with self._lock:
                epoch = self._epoch if self._state == 'listening' else None
            if epoch is None:
                yield token
                return
            with self._lock:
                self._text_token = token
            try:
                self._control('text_begin', epoch)
            except Exception:
                self.stop()
                with self._lock:
                    self._text_token = None
                raise
            try:
                yield token
            finally:
                with self._lock:
                    self._text_token = None
                    active = epoch == self._epoch
                if active:
                    try:
                        self._control('text_end', epoch)
                    except Exception:
                        self.stop()
                        raise

    def _write(self, process, epoch, initial):
        try:
            line = initial
            while True:
                with self._condition:
                    if epoch != self._epoch:
                        return
                # Never hold the state lock during a possibly blocked pipe write.
                process.stdin.write(line)
                process.stdin.flush()
                with self._condition:
                    self._condition.wait_for(lambda: epoch != self._epoch or self._controls or self._pending is not None)
                    if epoch != self._epoch:
                        return
                    if self._controls:
                        line = self._controls.popleft()
                    else:
                        line, self._pending = self._pending, None
        except Exception as error:
            self._fail(process, epoch, error)

    def _read(self, process, epoch):
        try:
            while True:
                line = process.stdout.readline(80001)
                if not line or len(line) > 80000 or not line.endswith('\n'):
                    raise RuntimeError('study voice event pipe failed')
                packet = json.loads(line)
                if not isinstance(packet, dict) or packet.get('event') not in (
                    'listening','delta','user_started','proactive_started','transcribed','empty_transcript',
                    'playback_started','playback_ended','segment_started','segment_ended',
                    'interrupted','text_interrupted','error','control_ack',
                    'answer_request','answer_cancel','discuss_started','discuss_rejected'):
                    raise ValueError('invalid study voice event')
                with self._lock:
                    if epoch != self._epoch:
                        return
                    if packet['event'] == 'text_interrupted' and self._text_token is not None:
                        self._text_token.cancel()
                    if packet['event'] == 'control_ack':
                        request = packet.get('request')
                        if type(request) is not int or request != self._control_ack + 1 or request > self._control_sequence:
                            raise ValueError('invalid study voice control acknowledgement')
                        self._control_ack = request
                        self._condition.notify_all()
                        continue
                    if packet['event'] == 'listening':
                        if packet.get('target') != self._target:
                            raise ValueError('study voice target mismatch')
                        self._state = 'listening'
                        self._ready.set()
                    # Callbacks must be quick; this lock fences publication on stop.
                    self.on_event(packet)
                    if packet['event'] == 'error' and packet.get('fatal') is True:
                        raise RuntimeError('study voice worker reported failure')
        except Exception as error:
            self._fail(process, epoch, error)

    def _fail(self, process, epoch, error):
        with self._condition:
            if epoch != self._epoch:
                return
            self._epoch += 1
            self._state, self._error = 'error', type(error).__name__
            self._pending = None
            self._controls.clear()
            if self._text_token is not None:
                self._text_token.cancel()
            self._ready.set()
            self._condition.notify_all()
            try:
                if self._job is not None:
                    self._job.close()
                    self._job = None
            finally:
                if process.poll() is None:
                    process.kill()
        process.wait(timeout=5)

    def stop(self):
        with self._condition:
            self._epoch += 1
            self._state = 'stopping'
            self._pending = None
            self._controls.clear()
            if self._text_token is not None:
                self._text_token.cancel()
            self._ready.set()
            self._condition.notify_all()
        with self._lifecycle:
            with self._lock:
                process, job = self._process, self._job
                threads = (self._writer, self._reader)
                # Close the job first: a blocked stdin writer must not prevent
                # releasing capture, model calls or owned playback descendants.
                if job is not None:
                    job.close()
                    self._job = None
            if process is not None:
                if process.poll() is None:
                    process.kill()
                process.wait(timeout=5)
                for thread in threads:
                    if thread is not None and thread is not threading.current_thread():
                        thread.join(timeout=3)
                        if thread.is_alive():
                            raise RuntimeError('study voice pipe thread did not stop')
                process.stdin.close()
                process.stdout.close()
            with self._lock:
                self._process = self._reader = self._writer = None
                self._state, self._target = 'stopped', None
                return self.status()
