"""Own the optional packaged pet executable; callers cannot select a program."""
import os
from pathlib import Path
import subprocess
import threading

from sumika_next.child_job import ChildJob


class PetHost:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self._lock = threading.RLock()
        self._process = self._job = None

    def _reap(self):
        if self._process is not None and self._process.poll() is not None:
            if self._job is not None:
                self._job.close()
            self._job = self._process = None

    def status(self):
        with self._lock:
            self._reap()
            executable = self.root/'SumikaPet.exe'
            available = os.name == 'nt' and executable.is_file() and not executable.is_symlink()
            return {'available':available, 'alive':self._process is not None,
                    'pid':self._process.pid if self._process is not None else None,
                    'status':'running' if self._process is not None else 'stopped'}

    def start(self, port):
        if type(port) is not int or not 1 <= port <= 65535:
            raise ValueError('valid bridge port required')
        with self._lock:
            state = self.status()
            if state['alive']:
                return state
            if not state['available']:
                raise RuntimeError('packaged Windows pet host unavailable')
            process = subprocess.Popen([str(self.root/'SumikaPet.exe'),
                f'http://127.0.0.1:{port}/?pet=1'], cwd=self.root,
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            job = None
            try:
                job = ChildJob()
                job.assign(process)
            except BaseException:
                try:
                    if job is not None:
                        job.close()
                finally:
                    if process.poll() is None:
                        process.kill()
                    process.wait(timeout=5)
                raise
            self._process, self._job = process, job
            return self.status()

    def stop(self):
        with self._lock:
            if self._job is not None:
                self._job.close()
                self._job = None
            if self._process is not None:
                if self._process.poll() is None:
                    self._process.kill()
                self._process.wait(timeout=5)
                self._process = None
            return self.status()
