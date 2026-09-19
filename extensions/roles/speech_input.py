"""Owned, cancellable one-shot speech input; never sends a model request."""
import json
from pathlib import Path
import subprocess
import threading
import uuid
from sumika_next.child_job import ChildJob


class SpeechInput:
    worker_module = 'extensions.roles.speech_input'
    pending_state = 'recording'

    def worker_payload(self, config, directory):
        return {**config, 'output': str(directory/'capture.wav')}

    def __init__(self, directory, configuration, *, spawn=subprocess.Popen):
        self.directory = Path(directory)
        self.configuration = configuration
        self.spawn = spawn
        self.lock = threading.RLock()
        self.process = None
        self.job = None
        self.thread = None
        self.closed = False
        self.record = None

    def start(self, role_id, *, approved=False):
        if approved is not True:
            raise PermissionError('confirm this speech operation first')
        with self.lock:
            if self.closed or self.process is not None or self.job is not None or (self.thread and self.thread.is_alive()):
                raise ValueError('speech input is closing or busy')
            config = self.configuration(role_id)
            identifier = uuid.uuid4().hex
            directory = self.directory/identifier
            directory.mkdir(parents=True)
            self.record = {'id': identifier, 'role_id': role_id, 'state': self.pending_state, 'text': ''}
            job = None
            child = None
            try:
                job = ChildJob()
                self.job = job
                child = self.spawn([config['python'], '-X', 'utf8', '-B', '-m', self.worker_module,
                                    '--worker'], cwd=config['root'], stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                   text=True, encoding='utf8',
                                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                self.process = child
                job.assign(child)
            except OSError:
                self.record['state'] = 'unknown'
                if self._reclaim():
                    if child is not None:
                        for stream in (child.stdin, child.stdout):
                            if stream is not None:
                                stream.close()
                    self.record['state'] = 'error'
                raise ValueError('speech runtime could not start') from None
            self.process = child
            payload = self.worker_payload(config, directory)
            self.thread = threading.Thread(target=self._finish, args=(child, payload, config, job), daemon=True)
            self.thread.start()
            return dict(self.record)

    def _finish(self, child, payload, config, job):
        transcript = None
        try:
            output, _ = child.communicate(json.dumps(payload), timeout=60)
            result = json.loads(output)
            if (child.returncode != 0 or not isinstance(result, dict)
                    or not isinstance(result.get('text'), str) or not result['text'].strip()):
                raise ValueError('no transcript')
            with self.lock:
                if self.record['state'] != self.pending_state:
                    return
                if self.configuration(self.record['role_id']) != config:
                    raise ValueError('speech settings changed')
                transcript = result['text'].strip()
        except (OSError, ValueError, subprocess.SubprocessError):
            with self.lock:
                if self.record['state'] == self.pending_state:
                    self.record.update(state='unknown', text='')
        finally:
            with self.lock:
                if not self._reclaim():
                    self.record.update(state='unknown', text='')
                elif transcript is not None and self.record['state'] == self.pending_state:
                    self.record.update(state='completed', text=transcript)

    def _reclaim(self):
        """Called under lock; retain ownership until exit and handle close succeed."""
        child = self.process
        try:
            if child is not None and child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait(timeout=5)
            if child is not None and child.poll() is None:
                return False
            if self.job is not None:
                self.job.close()
                self.job = None
        except (OSError, subprocess.SubprocessError):
            return False
        self.process = None
        return True

    def status(self, identifier):
        with self.lock:
            if not self.record or self.record['id'] != identifier:
                raise ValueError('speech request unavailable; do not replay')
            return dict(self.record)

    def cancel(self, identifier):
        with self.lock:
            self.status(identifier)
            self.record.update(state='cancelling', text='')
            if not self._reclaim():
                self.record.update(state='unknown', text='')
                raise RuntimeError('speech stop outcome unknown')
            self.record.update(state='cancelled', text='')
            return dict(self.record)

    def close(self):
        with self.lock:
            self.closed = True
            if self.record:
                self.cancel(self.record['id'])
        if self.thread:
            self.thread.join(timeout=6)
            if self.thread.is_alive():
                raise RuntimeError('speech worker did not settle')

    def cancel_active(self):
        with self.lock:
            if self.process is not None or self.job is not None or (self.thread and self.thread.is_alive()):
                return self.cancel(self.record['id'])
            return None


def worker(config):
    from extensions.capabilities import CapabilityStore
    from extensions.desktop.perception import capture_audio
    from extensions.roles.voice import transcribe
    store = CapabilityStore(config['capabilities'])
    try:
        microphone = store.resolve('microphone')
        asr = store.resolve('asr')
        if (microphone['provider'] != 'sounddevice' or microphone['options'].get('user_authorized') is not True
                or asr['provider'] != 'vosk'):
            raise PermissionError('speech permissions/provider unavailable')
        capture_audio(config['output'], seconds=5, device=config['device'],
                      sample_rate=config['sample_rate'], approved=True)
        if store.resolve('microphone') != microphone or store.resolve('asr') != asr:
            raise PermissionError('speech permissions changed')
        return transcribe(config['output'], model=config['model'])
    finally:
        store.close()


if __name__ == '__main__':
    import sys
    if sys.argv[1:] != ['--worker']:
        raise SystemExit('speech input requires managed worker invocation')
    print(json.dumps(worker(json.load(sys.stdin)), ensure_ascii=False))
