"""Bounded, fail-closed supervision of the isolated input feature worker."""
import json
import os
import queue
import secrets
import subprocess
import threading
import time
import uuid
from contextlib import nullcontext
from datetime import datetime, timezone
from pathlib import Path

from extensions.desktop.runtime import capability_python
from .input_features import MAX_FRAME_BYTES, validate_frame

QUEUE_FRAMES = 120
QUEUE_BYTES = 1024 * 1024
COMMIT_SECONDS = 10
COMMIT_FRAMES = 256
WIRE_BYTES = MAX_FRAME_BYTES + 256


class InputFeatureProcess:
    def __init__(self, root, library, user_scope, session_id=None, runtime_root=None,
                 on_frames=None, excluded_apps=None, can_commit=None, commit_guard=None):
        self.root = Path(root)
        self.runtime_root = Path(runtime_root or root)
        self.library, self.user_scope = library, user_scope
        self.session_id = session_id or uuid.uuid4().hex
        self.on_frames = on_frames
        self.can_commit, self.commit_guard = can_commit, commit_guard
        self.excluded_apps = list(excluded_apps or ())
        self._process = self._reader = self._commit = None
        self._stop, self._ready = threading.Event(), threading.Event()
        self._queue = queue.Queue(maxsize=QUEUE_FRAMES)
        self._queued_bytes = 0
        self._lock = threading.RLock()
        self._commit_lock = threading.Lock()
        self._lifecycle = threading.RLock()
        self._reaper = None
        self._reaper_epoch = None
        self._state, self._error = 'stopped', None
        self._worker_epoch = self._frames = self._sequence = 0
        self._ready_seen = False
        self._stopping = False
        self._permission_closed = False

    def status(self):
        with self._lock:
            return {'status': self._state, 'error': self._error,
                    'worker_epoch': self._worker_epoch, 'session_id': self.session_id,
                    'queued': self._queue.qsize(), 'queued_bytes': self._queued_bytes,
                    'frames': self._frames,
                    'alive': self._process is not None and self._process.poll() is None}

    def start(self, *, permission=None, expected_target=None):
        if (not isinstance(permission, dict) or permission.get('recording') is not True
                or permission.get('paused') is not False or permission.get('revoked') is not False
                or type(permission.get('revision')) is not int or permission['revision'] < 1):
            raise PermissionError('explicit active input permission required')
        if not self.root.is_dir():
            raise RuntimeError('input data root unavailable')
        interpreter = capability_python('desktop', root=self.runtime_root)
        if interpreter is None:
            raise RuntimeError('packaged desktop runtime unavailable')
        apps = permission.get('excluded_apps', [])
        if not isinstance(apps, list):
            raise ValueError('bounded application exclusions required')
        exclusions = self.excluded_apps + apps + ['sumika', 'sumikapet', 'sumikaprocessaudio']
        if len(exclusions) > 256 or any(not isinstance(v, str) or not v or len(v) > 128 for v in exclusions):
            raise ValueError('bounded application exclusions required')
        exclusions = sorted(set(exclusions))
        if len(exclusions) > 128:
            raise ValueError('bounded application exclusions required')
        if expected_target is not None and (not isinstance(expected_target, dict)
                or set(expected_target) != {'handle', 'process_id', 'process_creation'}
                or any(type(expected_target[key]) is not int or expected_target[key] <= 0
                       for key in ('handle', 'process_id'))
                or not isinstance(expected_target['process_creation'], str)
                or not expected_target['process_creation'].isdigit()
                or len(expected_target['process_creation']) > 32):
            raise ValueError('live target identity required')
        with self._lifecycle:
            with self._lock:
                if self._process is not None:
                    raise RuntimeError('stop the input worker before restarting')
                self._stop.clear(); self._ready.clear()
                while not self._queue.empty(): self._queue.get_nowait()
                self._queued_bytes = 0
                self._worker_epoch = secrets.randbits(62) + 1
                epoch = self._worker_epoch
                self._sequence = self._frames = 0
                self._ready_seen = self._stopping = False
                self._permission_closed = False
                self._error, self._state = None, 'starting'
            config = {'user_scope': self.user_scope, 'session_id': self.session_id,
                      'worker_epoch': epoch, 'permission_revision': permission['revision'],
                      'recording': True, 'excluded_apps': exclusions,
                      'excluded_pids': [os.getpid()], 'expected_target': expected_target}
            try:
                process = subprocess.Popen([str(interpreter), '-X', 'utf8', '-B', '-m',
                    'extensions.behavior.windows_input_worker'], cwd=str(self.runtime_root),
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
                with self._lock: self._process = process
                process.stdin.write((json.dumps(config) + '\n').encode('utf8'))
                process.stdin.flush()
                self._reader = threading.Thread(target=self._read, args=(process, epoch),
                    daemon=True, name='sumika-input-frames')
                self._commit = threading.Thread(target=self._commit_loop, daemon=True,
                    name='sumika-input-commit')
                self._reader.start(); self._commit.start()
            except Exception:
                self._fail('worker_start_failed', epoch=epoch)
                self.stop()
                raise RuntimeError('input worker failed to start') from None
        if not self._ready.wait(5): self._fail('worker_ready_timeout', epoch=epoch)
        with self._lock:
            if self._process is not None and self._process.poll() is not None and self._error is None:
                self._fail('worker_unexpected_eof', epoch=epoch)
        if self.status()['status'] != 'running':
            self.stop()
            raise RuntimeError('input worker did not become ready')
        return self.status()

    def stop(self):
        """Orderly stop accepts the child's final seal, then commits once."""
        with self._lifecycle:
            return self._stop_worker()

    def _stop_worker(self):
        with self._lock:
            self._stopping = True
            process, reader, commit = self._process, self._reader, self._commit
            if self._state != 'failed': self._state = 'stopping'
            self._ready.set()
        if process is not None and process.poll() is None:
            try:
                process.stdin.write(b'{"action":"stop"}\n'); process.stdin.flush()
            except (OSError, ValueError): pass
            try: process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                try: process.kill(); process.wait(timeout=3)
                except (OSError, subprocess.TimeoutExpired): pass
                self._fail('worker_stop_timeout')
        if reader is not None and reader is not threading.current_thread():
            reader.join(timeout=3)
            if reader.is_alive(): self._fail('worker_reader_did_not_stop')
        self._stop.set()
        if commit is not None and commit is not threading.current_thread():
            # The library's SQLite busy timeout is 10s. Let the single writer
            # finish its current transaction and the final seal in that bound.
            commit.join(timeout=12)
            if commit.is_alive(): self._fail('worker_commit_did_not_stop')
        if self._error is None and commit is None: self._commit_batch()
        for stream in (getattr(process, 'stdin', None), getattr(process, 'stdout', None)):
            if stream is not None:
                try: stream.close()
                except (OSError, ValueError): pass
        with self._lock:
            if not ((reader and reader.is_alive()) or (commit and commit.is_alive())):
                self._process = self._reader = self._commit = None
            if self._error is None: self._state = 'stopped'
        return self.status()

    def _read(self, process=None, epoch=None):
        process = process or self._process
        epoch = self._worker_epoch if epoch is None else epoch
        try:
            while True:
                line = process.stdout.readline(WIRE_BYTES + 1)
                if not line:
                    if not self._stopping: self._fail('worker_unexpected_eof', epoch=epoch)
                    return
                raw = line.encode('utf8') if isinstance(line, str) else line
                if len(raw) > WIRE_BYTES or not raw.endswith(b'\n'):
                    raise ValueError('wire budget')
                message = json.loads(raw.decode('utf8'))
                if not isinstance(message, dict): raise ValueError('wire object')
                with self._lock:
                    if epoch != self._worker_epoch or self._error is not None: return
                if set(message) == {'status', 'worker_epoch'} and message['status'] == 'ready':
                    if self._ready_seen or message['worker_epoch'] != epoch: raise ValueError('ready identity')
                    with self._lock:
                        self._ready_seen = True
                        if not self._stopping: self._state = 'running'
                        self._ready.set()
                elif set(message) == {'frame'} and self._ready_seen:
                    self._enqueue(message['frame'])
                elif set(message) == {'error'}:
                    self._fail('worker_reported_error', epoch=epoch); return
                else: raise ValueError('wire schema')
        except Exception:
            self._fail('invalid_worker_protocol', epoch=epoch)

    def _enqueue(self, frame):
        try:
            validate_frame(frame, user_scope=self.user_scope)
            frame = dict(frame, received_at=datetime.now(timezone.utc).isoformat())
            size = len(json.dumps(frame, ensure_ascii=False).encode('utf8'))
            if size > MAX_FRAME_BYTES: raise ValueError('frame budget')
            with self._lock:
                if self._error is not None or self._permission_closed: return False
                if frame['worker_epoch'] != self._worker_epoch or frame['sequence'] != self._sequence:
                    raise ValueError('frame ordering')
                if self._queue.full() or self._queued_bytes + size > QUEUE_BYTES:
                    self._fail('input_queue_overflow'); return False
                self._queue.put_nowait((size, frame))
                self._queued_bytes += size
                self._sequence += 1
                return True
        except Exception:
            self._fail('invalid_input_frame')
            return False

    def _commit_loop(self):
        while not self._stop.wait(COMMIT_SECONDS): self._commit_batch()
        if self._error is None: self._commit_batch()

    def _commit_batch(self):
        with self._commit_lock:
            batch = []
            with self._lock:
                if self._error is not None or self._permission_closed: return
                while len(batch) < COMMIT_FRAMES:
                    try: size, frame = self._queue.get_nowait()
                    except queue.Empty: break
                    self._queued_bytes -= size
                    batch.append(frame)
            if not batch: return
            try:
                # The host can hold its permission revision lock over the
                # transaction. Revocation and commit then have one ordering.
                guard = self.commit_guard() if self.commit_guard is not None else nullcontext(True)
                with guard as allowed:
                    if allowed is not True or (self.can_commit is not None and self.can_commit() is not True):
                        self._discard_for_permission()
                        return
                    self.library.record_frames(batch, scope={'user': self.user_scope, 'session': self.session_id})
                with self._lock: self._frames += len(batch)
                # Release the permission lock before callbacks, which may
                # themselves inspect settings or stop the capture runtime.
                if self.on_frames is not None and self._error is None: self.on_frames(batch)
            except Exception:
                self._fail('input_commit_failed')

    def _discard_for_permission(self):
        with self._lock:
            self._permission_closed = self._stopping = True
            self._state = 'permission_stopped'
            self._stop.set(); self._ready.set()
            while True:
                try: self._queue.get_nowait()
                except queue.Empty: break
            self._queued_bytes = 0
            epoch = self._worker_epoch
            if self._process is not None and (self._reaper_epoch != epoch
                    or self._reaper is None or not self._reaper.is_alive()):
                self._reaper_epoch = epoch
                self._reaper = threading.Thread(target=self._reap_failed, args=(epoch,),
                    daemon=True, name='sumika-input-permission-stop')
                self._reaper.start()

    def _fail(self, reason, *, epoch=None):
        with self._lock:
            if epoch is not None and epoch != self._worker_epoch: return
            self._error = self._error or reason
            self._state = 'failed'
            process = self._process
            failed_epoch = self._worker_epoch
            self._stop.set(); self._ready.set()
            while True:
                try: self._queue.get_nowait()
                except queue.Empty: break
            self._queued_bytes = 0
        if process is not None and process.poll() is None:
            try: process.kill(); process.wait(timeout=3)
            except (OSError, subprocess.TimeoutExpired): pass
        # The reader/committer cannot join itself. One reaper owns the same
        # serialized stop path, including pipe close and both thread joins.
        with self._lock:
            if process is not None and (self._reaper_epoch != failed_epoch
                    or self._reaper is None or not self._reaper.is_alive()):
                self._reaper_epoch = failed_epoch
                self._reaper = threading.Thread(target=self._reap_failed,
                    args=(failed_epoch,), daemon=True,
                    name='sumika-input-reaper')
                self._reaper.start()

    def _reap_failed(self, epoch):
        with self._lifecycle:
            with self._lock:
                if epoch != self._worker_epoch: return
            self._stop_worker()
