"""Parent-side supervision for the Raw Input worker (P11 §2.2/2.3).

Spawns the packaged desktop interpreter with the hidden input worker,
streams InputFeatureFrames through a bounded queue (120 frames or 1 MiB),
and commits them transactionally to the behavior library every 10 seconds
or 256 frames. A worker failure isolates and stops the channel with its
reason — no restart, no replay; a normal stop flushes the pending batch,
and a crash loses at most the uncommitted batch. Closing the IPC removes
the raw-input registration with the worker process.
"""
import json
import os
import queue
import subprocess
import threading
import time
from pathlib import Path

from extensions.desktop.runtime import capability_python

QUEUE_FRAMES = 120
QUEUE_BYTES = 1024 * 1024
COMMIT_SECONDS = 10
COMMIT_FRAMES = 256


class InputFeatureProcess:
    """Supervised worker channel; frames land in the behavior library."""

    def __init__(self, *, root, library, user_scope, runtime_root=None):
        self.root = Path(root)
        # The child imports the product package from the runtime/workspace
        # root; data (logs, db) stays in the behavior root.
        self.runtime_root = Path(runtime_root or root)
        self.library = library
        self.user_scope = user_scope
        self._process = None
        self._reader = None
        self._commit = None
        self._stop = threading.Event()
        self._queue = queue.Queue(maxsize=QUEUE_FRAMES)
        self._queued_bytes = 0
        # RLock: start() holds it across the status() read at return.
        self._lock = threading.RLock()
        self._state, self._error = 'stopped', None
        self._worker_epoch = 0
        self._frames = 0

    def status(self):
        with self._lock:
            return {'status': self._state, 'error': self._error,
                    'worker_epoch': self._worker_epoch,
                    'queued': self._queue.qsize(), 'frames': self._frames}

    def start(self):
        with self._lock:
            if self._process is not None:
                raise RuntimeError('stop the input worker before restarting')
            interpreter = capability_python('desktop', root=self.runtime_root)
            if interpreter is None:
                raise RuntimeError('packaged desktop runtime unavailable')
            self._stop.clear()
            self._worker_epoch += 1
            self._error = None
            self._state = 'starting'
            self._child_log = open(self.root/'input-worker.log', 'ab')
            self._process = subprocess.Popen(
                [str(interpreter), '-X', 'utf8', '-B', '-m',
                 'extensions.behavior.windows_input_worker'],
                cwd=str(self.runtime_root), stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=self._child_log,
                text=True, encoding='utf8',
                creationflags=subprocess.CREATE_NO_WINDOW
                if os.name == 'nt' else 0)
            config = {'user_scope': self.user_scope,
                      'worker_epoch': self._worker_epoch}
            self._process.stdin.write(json.dumps(config) + '\n')
            self._process.stdin.flush()
            # The config handoff is done; the log belongs to the child now.
            self._child_log.close()
            self._reader = threading.Thread(target=self._read, daemon=True,
                name='sumika-input-frames')
            self._reader.start()
            self._commit = threading.Thread(target=self._commit_loop,
                daemon=True, name='sumika-input-commit')
            self._commit.start()
            return self.status()

    def stop(self):
        """Bounded flush and orderly teardown; idempotent."""
        with self._lock:
            process, reader, commit = self._process, self._reader, self._commit
            self._process = None
        if process is None:
            return self.status()
        self._stop.set()
        try:
            process.stdin.write(json.dumps({'action': 'stop'}) + '\n')
            process.stdin.flush()
        except OSError:
            pass
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
        reader.join(timeout=5)
        self._commit_batch()
        with self._lock:
            self._state = 'stopped'
        return self.status()

    def _read(self):
        """Reader thread: parse frames, enforce the bounded queue."""
        process = self._process
        try:
            for line in process.stdout:
                line = line.strip()
                if not line:
                    continue
                message = json.loads(line)
                if 'frame' in message:
                    self._enqueue(message['frame'])
                elif 'error' in message:
                    self._fail(message['error'])
                    return
        except (OSError, ValueError, json.JSONDecodeError) as error:
            self._fail(f'{type(error).__name__}: {error}')

    def _enqueue(self, frame):
        encoded = len(json.dumps(frame, ensure_ascii=False).encode('utf8'))
        while not self._stop.is_set():
            try:
                self._queue.put_nowait(frame)
                self._queued_bytes += encoded
                return
            except queue.Full:
                # Both bounds are hard caps: the OLDEST frame is dropped
                # (bounded RAM and bounded backlog), never an unbounded pile.
                try:
                    self._queue.get_nowait()
                    self._queued_bytes = max(0, self._queued_bytes - encoded)
                except queue.Empty:
                    return

    def _commit_loop(self):
        while not self._stop.wait(COMMIT_SECONDS):
            self._commit_batch()

    def _commit_batch(self):
        batch = []
        total = 0
        while total < COMMIT_FRAMES:
            try:
                frame = self._queue.get_nowait()
            except queue.Empty:
                break
            batch.append(frame)
            total += 1
        if not batch:
            return
        try:
            self.library.record_frames(batch, scope={'user': self.user_scope,
                                                     'session': None})
            self._frames += len(batch)
        except Exception as error:  # isolation: stop the channel with reason
            self._fail(f'commit failed: {error}')

    def _fail(self, reason):
        with self._lock:
            if self._state == 'stopped':
                return
            self._error = str(reason)[:256]
            self._state = 'failed'
            process = self._process
            self._process = None
        if process is not None:
            try:
                process.stdin.close()
            except OSError:
                pass
            if process.poll() is None:
                process.kill()
            process.wait(timeout=5)
        self._stop.set()
