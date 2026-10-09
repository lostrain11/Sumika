"""Supervise application transcription in its packaged voice interpreter."""
import json
import math
import os
from pathlib import Path
import subprocess
import threading

from extensions.desktop.runtime import capability_python, process_audio_helper
from sumika_next.child_job import ChildJob
from sumika_next.runtime_ownership import process_identity
from .application_audio_worker import require_asr, snapshot_media_identity


class ApplicationAudioProcess:
    def __init__(self, *, root, on_observation, on_clear):
        self.root = Path(root)
        self.on_observation, self.on_clear = on_observation, on_clear
        self._lock = threading.RLock()
        self._lifecycle = threading.RLock()
        self._ready = threading.Event()
        self._process = self._reader = self._job = None
        self._state, self._error = 'stopped', None
        self._error_progress = None
        self._epoch = 0
        self._target = None
        self._media_identity = None
        self._paused = False

    def status(self):
        with self._lock:
            state = 'paused' if self._paused and self._state == 'stopped' else self._state
            return {'status': state, 'error': self._error, 'target': self._target,
                    'media_identity': snapshot_media_identity(self._media_identity),
                    'error_progress': self._error_progress,
                    'alive': self._process is not None and self._process.poll() is None}

    def admission_token(self):
        with self._lock:
            return self._epoch

    def start(self, *, process_id, creation, target, model, capabilities=None, asr=None,
              approved=False, admission_token=None, media_identity=None,
              media_time_seconds=None, playback_rate=1.0):
        if (media_time_seconds is not None and
                (type(media_time_seconds) not in (int, float)
                 or not math.isfinite(media_time_seconds) or media_time_seconds < 0)):
            raise ValueError('invalid media time anchor')
        if (type(playback_rate) not in (int, float)
                or not math.isfinite(playback_rate) or not 0 < playback_rate <= 16):
            raise ValueError('invalid media playback rate')
        media_identity = snapshot_media_identity(media_identity)
        with self._lock:
            admission_epoch = self._epoch if admission_token is None else admission_token
            if type(admission_epoch) is not int or admission_epoch != self._epoch:
                raise RuntimeError('application audio start was revoked')
        if approved is not True:
            raise PermissionError('explicit application audio consent required')
        if type(process_id) is not int or process_id <= 0 or process_id == os.getpid():
            raise ValueError('external process target required')
        if not isinstance(target, str) or not target.strip() or len(target) > 512:
            raise ValueError('bounded observation target required')
        if not isinstance(creation, str) or process_identity(process_id) != creation:
            raise ValueError('application process identity changed')
        interpreter = capability_python('voice', root=self.root)
        helper = process_audio_helper(root=self.root)
        model = Path(model).resolve()
        if interpreter is None or helper is None or not model.is_dir():
            raise RuntimeError('application audio runtime or model unavailable')
        require_asr({'capabilities': str(capabilities), 'asr': asr})
        with self._lifecycle:
            if self._process is not None:
                raise RuntimeError('stop application audio before restarting')
            with self._lock:
                if admission_epoch != self._epoch:
                    raise RuntimeError('application audio start was revoked')
                self._ready.clear()
                self._epoch += 1
                epoch = self._epoch
                self._target, self._state, self._error = target, 'starting', None
                self._paused = False
                self._media_identity = media_identity
                self._error_progress = None
            process = subprocess.Popen([interpreter, '-X', 'utf8', '-B', '-m',
                'extensions.companion.application_audio_worker'], cwd=self.root,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                text=True, encoding='utf8',
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            self._process = process
            try:
                self._job = ChildJob()
                self._job.assign(process)
                config = {'helper': helper, 'process_id': process_id, 'creation': creation,
                          'model': str(model), 'target': target, 'consent': True,
                          'capabilities': str(Path(capabilities).resolve()), 'asr': asr,
                          'media_identity': media_identity,
                          'media_time_seconds': media_time_seconds,
                          'playback_rate': playback_rate}
                with self._lock:
                    if epoch != self._epoch:
                        raise RuntimeError('application audio start was revoked')
                    process.stdin.write(json.dumps(config) + '\n')
                    process.stdin.flush()
                self._reader = threading.Thread(target=self._read,
                    args=(process, epoch, config), name='sumika-app-audio-pipe', daemon=True)
                self._reader.start()
                if not self._ready.wait(15):
                    raise RuntimeError('application audio startup timed out')
                with self._lock:
                    if epoch != self._epoch:
                        raise RuntimeError('application audio start was revoked')
                    if self._state != 'running':
                        raise RuntimeError('application audio worker failed to start')
                    return self.status()
            except BaseException:
                self.stop()
                raise

    def _read(self, process, epoch, config):
        try:
            while True:
                line = process.stdout.readline(80001)
                if not line:
                    raise RuntimeError('application audio worker exited')
                if len(line) > 80000 or not line.endswith('\n'):
                    raise ValueError('application transcript exceeds pipe budget')
                packet = json.loads(line)
                with self._lock:
                    if epoch != self._epoch:
                        return
                    if isinstance(packet.get('error'), str):
                        progress = packet.get('progress')
                        if isinstance(progress, dict):
                            self._error_progress = {key:progress.get(key) for key in (
                                'capture_seconds', 'decoded_seconds', 'pending_segments',
                                'decode_elapsed_seconds') if type(progress.get(key)) in (int, float)}
                        reason = packet.get('reason')
                        self._error = packet['error'][:128] + (
                            ':' + reason[:128] if isinstance(reason, str) else '')
                        raise RuntimeError('application audio worker failed')
                    if packet.get('status') == 'running' and packet.get('target') == config['target']:
                        self._state = 'running'
                        self._ready.set()
                        continue
                    value = packet.get('observation')
                    if (not isinstance(value, dict) or value.get('target') != config['target']
                            or value.get('source') != 'application-audio-transcript'
                            or value.get('metadata', {}).get('process_id') != config['process_id']
                            or value.get('metadata', {}).get('process_creation') != config['creation']
                            or value.get('metadata', {}).get('media_identity') != config.get('media_identity')):
                        raise ValueError('application transcript identity mismatch')
                    self.on_observation(value)
        except Exception as error:
            try:
                with self._lock:
                    if epoch == self._epoch:
                        self._state = 'error'
                        self._error = self._error or type(error).__name__
                        self._ready.set()
                        self.on_clear()
            finally:
                # Closing the job reclaims the native helper even if its worker
                # crashed before it could close its own nested job handle.
                try:
                    with self._lock:
                        if self._process is process and self._job is not None:
                            self._job.close()
                            self._job = None
                finally:
                    if process.poll() is None:
                        process.kill()
                    process.wait(timeout=5)

    def stop(self):
        # Fence startup/readers before waiting for the lifecycle owner to settle.
        clear_error = None
        with self._lock:
            self._epoch += 1
            self._state = 'stopping'
            self._ready.set()
            try:
                self.on_clear()
            except Exception as error:
                clear_error = error
        with self._lifecycle:
            with self._lock:
                process, reader, job = self._process, self._reader, self._job
            if process is not None:
                process.stdin.close()
                try:
                    process.wait(timeout=7)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=3)
                if reader is not None:
                    reader.join(timeout=3)
                    if reader.is_alive():
                        raise RuntimeError('application transcription consumer did not stop')
                process.stdout.close()
            if job is not None:
                job.close()
            with self._lock:
                self._process = self._reader = self._job = None
                self._state, self._target = 'stopped', None
                self._media_identity = None
                self._paused = False
            if clear_error is not None:
                raise RuntimeError('audio stopped but context cleanup failed') from clear_error
            return self.status()

    def pause(self):
        """Fence the current media audio stream and allow a later fresh start.

        Loopback capture does not necessarily emit zero PCM while a player is
        paused, so waiting for VAD silence is insufficient. Pausing explicitly
        stops and clears the worker, preserving a distinct resumable state.
        """
        result = self.stop()
        with self._lock:
            self._paused = True
        return self.status()
