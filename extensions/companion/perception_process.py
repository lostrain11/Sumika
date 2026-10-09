"""Own the isolated perception worker without persistent screen data."""
import json
import os
from pathlib import Path
import subprocess
import threading
from extensions.desktop.runtime import capability_python
from .windows_learning import WindowsLearningCollector


class PerceptionProcess:
    def __init__(self, *, on_observation, on_clear, root, python=None):
        self.root = Path(root)
        self.python = Path(python) if python else None
        self.on_observation, self.on_clear = on_observation, on_clear
        self._lock = threading.RLock()
        self._lifecycle = threading.RLock()
        self._process = self._reader = None
        self._epoch = 0
        self._state = 'stopped'
        self._target = None
        self._observations = 0
        self._error = None

    def status(self):
        with self._lock:
            alive = self._process is not None and self._process.poll() is None
            return {'status': self._state, 'alive': alive,
                    'target': dict(self._target) if self._target else None,
                    'observations': self._observations, 'error': self._error}

    def start(self, *, handle, process_id, approved=False, expected_document=None):
        if approved is not True:
            raise PermissionError('explicit window capture consent required')
        if type(handle) is not int or handle <= 0 or type(process_id) is not int or process_id <= 0:
            raise ValueError('positive window handle and process id required')
        expected_document = WindowsLearningCollector.validate_expected_document(expected_document)
        with self._lifecycle:
            self.stop()
            with self._lock:
                self._target = {'handle': handle, 'process_id': process_id}
                if expected_document is not None:
                    self._target['expected_document'] = expected_document
            self._launch()
            return self.status()

    def resume(self):
        with self._lifecycle:
            with self._lock:
                if self._state != 'paused' or not self._target:
                    raise RuntimeError('perception must be paused before resuming')
            self._launch()
            return self.status()

    def _launch(self):
        interpreter = self.python or capability_python('desktop', root=self.root)
        if interpreter is None or not Path(interpreter).is_file():
            raise RuntimeError('desktop capture environment is unavailable')
        with self._lock:
            target = self._target
            command = [str(interpreter), '-X', 'utf8', '-B', '-m',
                'extensions.companion.perception_worker', '--handle', str(target['handle']),
                '--process-id', str(target['process_id'])]
            if target.get('expected_document') is not None:
                command.extend(['--expected-document', target['expected_document']])
            process = subprocess.Popen(command, cwd=self.root,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                text=True, encoding='utf8', creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            self._epoch += 1
            epoch = self._epoch
            self._process, self._state = process, 'starting'
            self._observations, self._error = 0, None
            self._reader = threading.Thread(target=self._read, args=(process, epoch),
                                           name='sumika-perception-pipe', daemon=True)
            self._reader.start()

    def _read(self, process, epoch):
        try:
            while True:
                line = process.stdout.readline(8_000_001)
                if not line:
                    break
                if len(line) > 8_000_000:
                    raise RuntimeError('observation exceeds pipe budget')
                value = json.loads(line)
                if 'error' in value:
                    raise RuntimeError('window capture worker failed')
                observation = value['observation']
                with self._lock:
                    if epoch != self._epoch:
                        return
                    target = self._target
                    expected = f"window:{target['handle']}:pid:{target['process_id']}"
                    if observation.get('target') != expected or observation.get('source') != 'window-visual':
                        raise RuntimeError('worker observation target mismatch')
                    self.on_observation(observation)
                    self._observations += 1
                    self._state = 'running'
            raise RuntimeError('window capture worker exited')
        except Exception as error:
            with self._lock:
                if epoch == self._epoch:
                    self._state = 'error'
                    self._error = type(error).__name__
                    self.on_clear()
            # A malformed worker must not remain capturing after reader failure.
            if process.poll() is None:
                process.terminate()
            process.wait(timeout=5)

    def pause(self):
        return self._release(paused=True)

    def stop(self):
        return self._release(paused=False)

    def _release(self, *, paused):
        with self._lifecycle:
            with self._lock:
                self._epoch += 1
                process, reader = self._process, self._reader
                self._state = 'stopping'
                self.on_clear()
            if process is not None:
                if process.stdin is not None and not process.stdin.closed:
                    process.stdin.close()
                try:
                    process.wait(timeout=7)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=3)
                if reader is not None and reader is not threading.current_thread():
                    reader.join(timeout=3)
                if reader is not None and reader.is_alive():
                    raise RuntimeError('perception reader stop outcome unknown')
                if process.stdout is not None:
                    process.stdout.close()
            with self._lock:
                self._process = self._reader = None
                self._state = 'paused' if paused and self._target else 'stopped'
                if not paused:
                    self._target = None
                return self.status()
