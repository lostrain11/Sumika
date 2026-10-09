"""Bounded browser tab audio transport into the isolated recognizer.

The extension relays 100ms media-element PCM packets; this adapter enforces
the delivery contract (strict sequence inside one audio epoch, bounded queue,
identity binding, explicit failure instead of silent drops) and feeds the
packaged voice interpreter's recognizer. PCM exists only in RAM and pipes.
"""
import json
from base64 import b64decode, b64encode
from collections import deque
from pathlib import Path
import subprocess
import threading
import os

from extensions.desktop.runtime import capability_python
from sumika_next.child_job import ChildJob
from .application_audio_worker import require_asr, snapshot_media_identity

PACKET_BYTES = 3200
QUEUE_LIMIT = 20


class PassiveBrowserAudio:
    def __init__(self, *, root, on_observation, on_clear):
        self.root = Path(root)
        self.on_observation, self.on_clear = on_observation, on_clear
        self._lock = threading.RLock()
        self._condition = threading.Condition(self._lock)
        self._lifecycle = threading.RLock()
        self._ready = threading.Event()
        self._process = self._reader = self._writer = self._job = None
        self._state, self._error = 'stopped', None
        self._epoch = 0
        self._target = self._identity = None
        self._audio_epoch = None
        self._next_sequence = None
        self._queue = deque()
        self._consented = False

    def status(self):
        with self._lock:
            return {'status': self._state, 'error': self._error, 'target': self._target,
                    'audio_epoch': self._audio_epoch,
                    'media_identity': snapshot_media_identity(self._identity),
                    'queued': len(self._queue),
                    'alive': self._process is not None and self._process.poll() is None}

    def start(self, *, target, identity, model, capabilities=None, asr=None,
              audio_epoch=None):
        """Spawn the pipe-fed recognizer for one approved browser audio epoch."""
        identity = snapshot_media_identity(identity)
        if identity is None:
            raise ValueError('browser audio requires the bound media identity')
        if not isinstance(audio_epoch, str) or not audio_epoch.strip() or len(audio_epoch) > 64:
            raise ValueError('bounded audio epoch required')
        if not isinstance(target, str) or not target.strip() or len(target) > 512:
            raise ValueError('bounded observation target required')
        interpreter = capability_python('voice', root=self.root)
        model = Path(model).resolve()
        if interpreter is None or not model.is_dir():
            raise RuntimeError('study voice runtime or model unavailable')
        require_asr({'capabilities': str(capabilities), 'asr': asr})
        with self._lifecycle:
            if self._process is not None:
                raise RuntimeError('stop browser audio before restarting')
            config = {'source': 'pipe', 'model': str(model), 'target': target,
                      'consent': True, 'capabilities': str(Path(capabilities).resolve()),
                      'asr': asr, 'media_identity': identity}
            with self._lock:
                self._ready.clear()
                self._epoch += 1
                epoch = self._epoch
                self._target, self._state, self._error = target, 'starting', None
                self._identity = identity
                self._audio_epoch = audio_epoch
                self._next_sequence = 0
                self._queue.clear()
                self._consented = True
            process = subprocess.Popen([interpreter, '-X', 'utf8', '-B', '-m',
                'extensions.companion.application_audio_worker'], cwd=self.root,
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                text=True, encoding='utf8',
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            self._process = process
            try:
                self._job = ChildJob()
                self._job.assign(process)
                with self._lock:
                    if epoch != self._epoch:
                        raise RuntimeError('browser audio start was revoked')
                    process.stdin.write(json.dumps(config) + '\n')
                    process.stdin.flush()
                self._reader = threading.Thread(target=self._read,
                    args=(process, epoch), name='sumika-browser-audio-events', daemon=True)
                self._writer = threading.Thread(target=self._write,
                    args=(process, epoch), name='sumika-browser-audio-feed', daemon=True)
                self._reader.start()
                self._writer.start()
                if not self._ready.wait(15):
                    raise RuntimeError('browser audio startup timed out')
                with self._lock:
                    if epoch != self._epoch:
                        raise RuntimeError('browser audio start was revoked')
                    if self._state != 'running':
                        raise RuntimeError('browser audio worker failed to start')
                    return self.status()
            except BaseException:
                self.stop()
                raise

    def receive(self, token, extension_origin, payload, *, grant):
        """Validate one relayed packet against the grant and enqueue it.

        ``grant`` is the connection's live authorization view (token, tab,
        origin, audio consent, audio epoch). Sequence gaps, wrong identity,
        oversized queues or unknown states stop the track explicitly instead
        of silently dropping tutorial speech.
        """
        with self._lock:
            if (self._state not in ('running', 'starting') or self._audio_epoch is None
                    or not self._consented):
                raise PermissionError('browser audio session is not active')
            expected = {'tab_id', 'audio_epoch', 'sequence', 'media_identity',
                        'sample_rate', 'channels', 'format', 'sample_offset', 'pcm_base64'}
            if not isinstance(payload, dict) or set(payload) != expected:
                raise ValueError('invalid browser audio packet')
            if (not isinstance(token, str) or token != grant['token']
                    or extension_origin != 'chrome-extension://' + grant['extension_id']
                    or grant.get('audio') is not True
                    or payload['tab_id'] != grant['tab_id']):
                raise PermissionError('browser audio grant unavailable')
            if (payload['audio_epoch'] != self._audio_epoch
                    or payload['sample_rate'] != 16000 or payload['channels'] != 1
                    or payload['format'] != 'pcm_s16le'
                    or type(payload['sequence']) is not int
                    or type(payload['sample_offset']) is not int):
                raise ValueError('browser audio packet outside the active epoch')
            if payload['sequence'] != self._next_sequence:
                raise PermissionError('browser audio sequence gap; restart required')
            identity = snapshot_media_identity(payload['media_identity'])
            if identity != self._identity:
                raise PermissionError('browser audio media identity changed')
            try:
                pcm = b64decode(payload['pcm_base64'], validate=True)
            except Exception as error:
                raise ValueError('invalid browser audio encoding') from error
            if len(pcm) != PACKET_BYTES:
                raise ValueError('browser audio packet must be exactly 100ms')
            if len(self._queue) >= QUEUE_LIMIT:
                self._fail('browser audio queue overflow')
                raise RuntimeError('browser audio queue overflow; track stopped')
            self._queue.append(pcm)
            self._next_sequence += 1
            self._condition.notify_all()
            return {'status': 'accepted', 'queued': len(self._queue),
                    'sequence': payload['sequence']}

    def stop(self):
        with self._condition:
            self._epoch += 1
            self._state = 'stopping'
            self._queue.clear()
            self._consented = False
            self._ready.set()
            self._condition.notify_all()
        with self._lifecycle:
            with self._lock:
                process, job = self._process, self._job
                threads = (self._reader, self._writer)
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
                try:
                    process.stdin.close()
                    process.stdout.close()
                except OSError:
                    pass
            with self._lock:
                self._process = self._reader = self._writer = None
                self._state, self._target = 'stopped', None
                self._audio_epoch = self._identity = None
                self._next_sequence = None
                existed_error = self._error
                self._error = None
                result = self.status()
                result['previous_error'] = existed_error
                return result

    def _fail(self, message):
        with self._condition:
            if self._state == 'stopped':
                return
            self._error = message
        self.stop()

    def _read(self, process, epoch):
        try:
            while True:
                line = process.stdout.readline(16001)
                if not line or len(line) > 16000 or not line.endswith('\n'):
                    raise RuntimeError('browser audio event pipe failed')
                packet = json.loads(line)
                if not isinstance(packet, dict):
                    raise ValueError('invalid browser audio event')
                with self._lock:
                    if epoch != self._epoch:
                        return
                    if packet.get('observation') is not None:
                        self.on_observation(packet['observation'])
                        continue
                    if packet.get('status') == 'running':
                        self._state = 'running'
                        self._ready.set()
                        continue
                    if packet.get('error') is not None:
                        self._error = str(packet.get('reason') or packet['error'])[:128]
                        raise RuntimeError('browser audio worker reported failure')
        except Exception as error:
            self._fail(type(error).__name__ if self._error is None else self._error)

    def _write(self, process, epoch):
        try:
            while True:
                with self._condition:
                    if epoch != self._epoch:
                        return
                    if not self._queue:
                        self._condition.wait_for(
                            lambda: epoch != self._epoch or self._queue, timeout=0.5)
                        if epoch != self._epoch or not self._queue:
                            continue
                    pcm = self._queue.popleft()
                # Never hold the state lock during a possibly blocked pipe write.
                process.stdin.write(json.dumps({'pcm': b64encode(pcm).decode('ascii')}) + '\n')
                process.stdin.flush()
        except Exception as error:
            self._fail(type(error).__name__)
