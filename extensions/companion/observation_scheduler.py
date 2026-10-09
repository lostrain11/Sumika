"""Bounded observation and proactive-discussion scheduler.

The scheduler never calls the model for unchanged content. Capture remains an
injected provider, so platform permissions and WGC/WASAPI stay outside it.
"""
import threading
import time

from .contracts import ObservationBundle, PerceptionService
from .content import ContentChangeTracker


class ObservationScheduler:
    def __init__(self, perception: PerceptionService, *, on_observation=None,
                 on_proactive=None, on_error=None, capture_interval=1.0, proactive_interval=120.0,
                 clock=time.monotonic, sleeper=time.sleep, pending_ttl=180.0,
                 playback_gap=2.0, settled_seconds=0):
        if not isinstance(perception, PerceptionService):
            raise TypeError('perception service required')
        if type(capture_interval) not in (int, float) or capture_interval < .1:
            raise ValueError('invalid capture interval')
        if type(proactive_interval) not in (int, float) or proactive_interval < 1:
            raise ValueError('invalid proactive interval')
        if on_observation is not None and not callable(on_observation):
            raise ValueError('observation callback must be callable')
        if on_proactive is not None and not callable(on_proactive):
            raise ValueError('proactive callback must be callable')
        if on_error is not None and not callable(on_error):
            raise ValueError('error callback must be callable')
        if type(pending_ttl) not in (int, float) or pending_ttl <= 0:
            raise ValueError('invalid pending TTL')
        if type(playback_gap) not in (int, float) or playback_gap < 0:
            raise ValueError('invalid playback gap')
        if type(settled_seconds) not in (int, float) or not 0 <= settled_seconds <= 120:
            raise ValueError('invalid content settling interval')
        self.perception = perception
        self.on_observation = on_observation or (lambda observation: None)
        self.on_proactive = on_proactive or (lambda observation: None)
        self.on_error = on_error or (lambda error: None)
        self.capture_interval, self.proactive_interval = capture_interval, proactive_interval
        self.clock, self.sleeper = clock, sleeper
        self.tracker = ContentChangeTracker()
        self._last_proactive = None
        self._latest = None
        self._pending = None
        self._pending_since = None
        self._pending_ttl = pending_ttl
        self._playback_gap = playback_gap
        self._settled_seconds = settled_seconds
        self._playback_token = None
        self._playback_busy_until = 0
        self._user_busy_until = 0
        self._stop = threading.Event()
        self._thread = None
        self._lock = threading.RLock()
        self._tick_lock = threading.Lock()
        self._question_service = None
        self._error = None

    def bind_question_service(self, question_service, *, session_id='companion'):
        """Use the existing ephemeral question service for proactive turns."""
        if not callable(getattr(question_service, 'proactive', None)):
            raise TypeError('question service must provide proactive')
        if not isinstance(session_id, str) or not session_id.strip():
            raise ValueError('session id required')
        self.on_proactive = lambda observation: question_service.proactive(
            session_id=session_id, expected_observation=observation)
        self.on_observation = question_service.update
        self._question_service = question_service
        return {'status': 'bound', 'session_id': session_id}

    @property
    def latest(self):
        with self._lock:
            return self._latest

    @property
    def error(self):
        with self._lock:
            return self._error

    def notify_user_activity(self, seconds=5):
        if type(seconds) not in (int, float) or seconds < 0:
            raise ValueError('invalid user activity duration')
        with self._lock:
            self._user_busy_until = max(self._user_busy_until, self.clock() + seconds)

    def playback_started(self, token):
        if token is None:
            raise ValueError('playback token required')
        with self._lock:
            self._playback_token = token

    def playback_ended(self, token):
        with self._lock:
            if self._playback_token != token or token is None:
                return {'status': 'rejected', 'reason': 'playback was superseded'}
            self._playback_token = None
            self._playback_busy_until = self.clock() + self._playback_gap
            return {'status': 'ended'}

    def voice_event(self, event, token):
        """Bind the existing voice coordinator's playback lifecycle to this gate."""
        if event == 'playback_started':
            self.playback_started(token)
        elif event in ('playback_ended', 'interrupted', 'stopped', 'error'):
            return self.playback_ended(token)
        elif event == 'user_started':
            self.notify_user_activity()

    def tick(self):
        """Perform one bounded capture; convenient for tests and host loops."""
        with self._tick_lock:
            return self._tick()

    def _tick(self):
        if self._stop.is_set():
            return {'status': 'stopped', 'changed': False, 'proactive': False}
        try:
            observation = self.perception.observe()
        except Exception:
            with self._lock:
                self._latest = self._pending = None
                self._pending_since = None
                if self._question_service is not None:
                    self._question_service.revoke()
            raise
        if not isinstance(observation, ObservationBundle):
            raise TypeError('collector must return ObservationBundle')
        with self._lock:
            if self._stop.is_set() or self.perception.state != 'running':
                return {'status': 'stopped', 'changed': False, 'proactive': False}
            change = self.tracker.accept(observation)
            if not change['accepted']:
                return {'status': 'rejected', 'changed': False, 'proactive': False}
            self._latest = observation
            if not observation.valid:
                self._pending = None
                self._pending_since = None
            elif change['changed']:
                self._pending = observation
                self._pending_since = self.clock()
            self.on_observation(observation)
        now = self.clock()
        with self._lock:
            if self._pending_since is not None and now - self._pending_since >= self._pending_ttl:
                self._pending = self._pending_since = None
            pending = self._pending
            busy = (now < self._user_busy_until or self._playback_token is not None or
                    now < self._playback_busy_until or
                    (self._pending_since is not None and now - self._pending_since < self._settled_seconds))
            allowed = (not self._stop.is_set() and pending is not None and pending.valid and not busy and
                       (self._last_proactive is None or now - self._last_proactive >= self.proactive_interval))
            if allowed:
                self._pending = None
                self._pending_since = None
                self._last_proactive = now
        if allowed:
            try:
                self.on_proactive(pending)
            except Exception as error:
                with self._lock:
                    self._error = {'type': type(error).__name__,
                                   'target': pending.target}
                try:
                    self.on_error(dict(self._error))
                except Exception:
                    pass
                return {'changed': change['changed'], 'proactive': False,
                        'status': 'proactive_error', 'error': dict(self._error),
                        'source': observation.source, 'target': observation.target}
        return {'changed': change['changed'], 'proactive': allowed,
                'source': observation.source, 'target': observation.target}

    def start(self):
        with self._lock:
            if self._thread and self._thread.is_alive():
                return {'status': 'running'}
            if self.perception.state != 'running':
                raise RuntimeError('perception must be running before scheduler starts')
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, name='sumika-observation', daemon=True)
            self._thread.start()
            return {'status': 'running'}

    def resume(self):
        """Clear a previous stop without spawning the tick thread.

        Hosts that drive ticks from their own loop (delivery package P2) use
        this instead of ``start``; ``start`` remains the thread-based mode.
        """
        with self._lock:
            if self.perception.state != 'running':
                raise RuntimeError('perception must be running before the scheduler resumes')
            self._stop.clear()
            self._error = None
        return {'status': 'ready'}

    def stop(self):
        with self._lock:
            self._stop.set()
            self.perception.stop()
            self._pending = self._latest = None
            self._error = None
            self._pending_since = self._playback_token = None
            self._playback_busy_until = self._user_busy_until = 0
            self.tracker = ContentChangeTracker()
            if self._question_service is not None:
                self._question_service.revoke()
        thread = self._thread
        if thread and thread is not threading.current_thread():
            thread.join(timeout=max(1.0, self.capture_interval * 2))
        alive = bool(thread and thread.is_alive())
        return {'status': 'stopping' if alive else 'stopped', 'alive': alive}

    def _run(self):
        while not self._stop.is_set():
            try:
                self.tick()
            except (RuntimeError, OSError, ValueError):
                # A revoked target or unavailable capture must not spin or call
                # the model; the host can inspect state and restart explicitly.
                self._stop.wait(self.capture_interval)
            else:
                self._stop.wait(self.capture_interval)
