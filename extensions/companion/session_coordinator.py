"""The single companion session owner in the host process (delivery package P2).

Owns the one question service (history, bindings, generation), the proactive
scheduler and the voice request registry. Voice workers only report VAD states,
transcripts and playback lifecycle; generated answers always come from the
host, so text questioning and proactive discussion work without a microphone.
On failure the coordinator stops new dispatch, cancels in-flight requests and
reports the error; a restarted session starts empty and never replays unknown
calls.
"""
import threading
import time

from extensions.models.cancellation import CancellationToken
from .contracts import ObservationBundle, PerceptionService
from .reading_behavior import ReadingBehaviorTracker
from .study_extras import DanmakuBuffer
from .observation_scheduler import ObservationScheduler
from .qa import CompanionQuestionService

DISCUSSION_PROMPT = ('请结合当前内容，用一句简短的话提出一个值得一起讨论的学习点；'
                     '资料不足时不要猜测。')


class FusionPerception(PerceptionService):
    """Present the host context fusion as the scheduler's capture provider.

    The scheduler drives capture; here the fused observation is already
    collected by authorized platform workers, so the collector only projects
    the current bundle for the selected target.
    """

    def __init__(self, current):
        super().__init__(lambda target: self._projection())
        self._current = current

    def _projection(self):
        bundle = self._current()
        if bundle is None:
            raise RuntimeError('learning context is not available')
        return bundle


class CoordinatorStopped(RuntimeError):
    """Raised when dispatch is attempted on a failed or stopped coordinator."""


class _VoiceRequest:
    __slots__ = ('request', 'turn', 'token', 'binding', 'phase')

    def __init__(self, request, turn, token, binding):
        self.request = request
        self.turn = turn
        self.token = token
        self.binding = binding
        self.phase = 'model'


class BackgroundBudget:
    """Cap background model starts (proactive discussions, summaries).

    The frozen delivery plan bounds background analysis at two starts per
    minute; user questions never draw from this budget.
    """

    def __init__(self, *, max_per_minute=2, clock=time.monotonic):
        if type(max_per_minute) is not int or not 1 <= max_per_minute <= 60:
            raise ValueError('background budget must be 1-60 per minute')
        self.max_per_minute = max_per_minute
        self._clock = clock
        self._lock = threading.Lock()
        self._starts = []

    def allow(self):
        now = self._clock()
        with self._lock:
            self._starts = [stamp for stamp in self._starts if now - stamp < 60]
            if len(self._starts) >= self.max_per_minute:
                return False
            self._starts.append(now)
            return True


class StudySessionCoordinator:
    def __init__(self, *, chat, current, on_event=None,
                 include_images=None, proactive_interval=120.0,
                 proactive_enabled=True, pending_ttl=180.0,
                 scheduler_thread=True, behavior_tracker=None,
                 behavior_note_cooldown=60.0):
        """``chat`` is the shared RoleChat callable; ``current`` projects the
        latest fused observation; ``on_event`` receives coordinator/UI events.
        ``scheduler_thread=False`` serves deterministic tests that drive ticks.
        """
        if not callable(current):
            raise ValueError('current projection must be callable')
        self._on_event = on_event or (lambda name, detail: None)
        self._include_images = include_images or (lambda: False)
        self._scheduler_thread = scheduler_thread
        self._service = CompanionQuestionService(chat, include_images=True)
        self._behavior = behavior_tracker or ReadingBehaviorTracker()
        if not isinstance(self._behavior, ReadingBehaviorTracker):
            raise TypeError('behavior tracker required')
        # The published service bundle stays authoritative for scheduling; the
        # host projection is only a backstop for paths that bypass publish.
        self._perception = FusionPerception(
            lambda: (self._service.latest if self._service.latest is not None
                     else current()))
        self._scheduler = ObservationScheduler(self._perception,
            on_observation=self._observe,
            on_proactive=self._dispatch_proactive,
            on_error=lambda error: self._emit('proactive_error', {'error': error['type'],
                                                                  'target': error.get('target')}),
            proactive_interval=proactive_interval, settled_seconds=3,
            pending_ttl=pending_ttl)
        self._proactive_enabled = proactive_enabled
        self._lock = threading.RLock()
        self._request_sequence = 0
        self._active = {}
        self._voice_bindings = {}
        self._speaker = None
        self._scheduler_target = None
        self._proactive_thread = None
        self._failed = None
        # Frozen delivery plan P5: background model analysis at most twice a
        # minute; user questions never consume this budget.
        self._background_budget = BackgroundBudget(max_per_minute=2)
        if (type(behavior_note_cooldown) not in (int, float)
                or not 0 <= behavior_note_cooldown <= 3600):
            raise ValueError('invalid behavior note cooldown')
        self._behavior_note_cooldown = behavior_note_cooldown
        self._behavior_note_at = None
        self._queued_behavior_report = None
        # Local-rule danmaku dedup: scrolling comments collapse per window and
        # never trigger model calls on their own.
        self.danmaku = DanmakuBuffer()

    # -- events ------------------------------------------------------------
    def _emit(self, name, detail):
        try:
            self._on_event(name, detail)
        except Exception:
            pass

    # -- observation context -------------------------------------------------
    @property
    def service(self):
        return self._service

    @property
    def failed(self):
        with self._lock:
            return self._failed

    def _observe(self, observation):
        """Scheduler tick path: update the service, then feed page behavior."""
        result = self._service.update(observation)
        self._behavior_feed(observation)
        return result

    def _behavior_feed(self, observation):
        page = observation.metadata.get('page')
        if page is None:
            context = observation.metadata.get('reader_context')
            page = context.get('page') if isinstance(context, dict) else None
        report = self._behavior.feed(
            page if type(page) is int and page >= 1 else None,
            valid=observation.valid)
        if report is None:
            # A report blocked by a busy background thread retries on later
            # ticks instead of being lost; it stays relevant for a short
            # window only.
            with self._lock:
                queued = self._queued_behavior_report
                if queued is not None:
                    if time.monotonic() - queued[0] <= 15.0:
                        report = queued[1]
                    else:
                        self._queued_behavior_report = None
        if report is not None:
            self._maybe_behavior_note(report)

    def _maybe_behavior_note(self, report):
        """Dispatch one behavior note; shares the proactive thread and budget.

        Gated like proactive discussion: off when proactive is disabled, and
        never while a user question is bound or in flight — a spoken answer
        must not be talked over by a comment about page flipping. A report
        blocked by the busy thread or the budget is queued (latest wins) and
        retried on later ticks; one dispatched note silences further notes
        for the cooldown window.
        """
        with self._lock:
            if self._failed is not None or not self._proactive_enabled:
                return
            if self._active or self._voice_bindings:
                return
            now = time.monotonic()
            # One flurry of navigation is one comment: a second pattern
            # detected inside the cooldown joins the same moment, not a new
            # interruption.
            if (self._behavior_note_at is not None
                    and now - self._behavior_note_at < self._behavior_note_cooldown):
                return
            self._queued_behavior_report = (now, report)
            thread = self._proactive_thread
            if thread is not None and thread.is_alive():
                return
            if not self._background_budget.allow():
                return
            self._queued_behavior_report = None
            self._behavior_note_at = now
            self._proactive_thread = threading.Thread(
                target=self._generate_behavior_note, args=(report,),
                name='sumika-behavior-note', daemon=True)
            self._proactive_thread.start()

    def _generate_behavior_note(self, report):
        try:
            result = self._service.behavior_note(report)
        except Exception as error:
            self._emit('proactive_error', {'error': type(error).__name__})
            return
        if not isinstance(result, dict) or result.get('status') != 'behavior_note':
            return
        text = result.get('text')
        if not isinstance(text, str) or not text.strip() or text.strip() == '暂不提示':
            return
        with self._lock:
            if (self._failed is not None or self._scheduler_target is None
                    or self._active or self._voice_bindings):
                return
            speaker = self._speaker
        self._emit('proactive_text', {'text': text, 'kind': 'behavior',
                                      'behavior': dict(report)})
        if speaker is not None:
            try:
                speaker(text)
            except Exception as error:
                self._emit('proactive_error', {'error': type(error).__name__})

    def publish_observation(self, bundle):
        """Feed one fused observation to the single service and scheduler."""
        if not isinstance(bundle, ObservationBundle):
            raise TypeError('observation must be ObservationBundle')
        self._ensure_scheduler(bundle)
        danmaku = bundle.metadata.get('danmaku')
        if isinstance(danmaku, list) and danmaku:
            fresh = self.danmaku.observe(danmaku)
            if fresh:
                self._emit('danmaku_new', {'texts': fresh[:20],
                                           'window_total': len(self.danmaku.snapshot_texts())})
        return self._service.update(bundle)

    def _ensure_scheduler(self, bundle):
        with self._lock:
            if self._failed is not None:
                return
            if self._scheduler_target == bundle.target and self._perception.state == 'running':
                return
            self._scheduler_target = bundle.target
            # A new target is a new reading session; old page patterns,
            # reported episodes and a queued note must not leak across
            # documents.
            self._behavior.reset()
            self._queued_behavior_report = None
        try:
            self._scheduler.stop()
        except Exception:
            pass
        self._perception.select_target(bundle.target)
        self._perception.start()
        self._scheduler.resume()
        if self._scheduler_thread:
            self._scheduler.start()

    def context_cleared(self):
        """The fused learning context ended; stop scheduling, keep the error none."""
        with self._lock:
            self._scheduler_target = None
            self._queued_behavior_report = None
        self._behavior.reset()
        try:
            self._scheduler.stop()
        except Exception:
            pass

    def set_proactive(self, *, enabled, interval_seconds):
        if type(enabled) is not bool:
            raise ValueError('proactive enabled must be boolean')
        if type(interval_seconds) not in (int, float) or not 120 <= interval_seconds <= 86400:
            raise ValueError('explicit discussion interval of at least 120 seconds required')
        with self._lock:
            self._proactive_enabled = enabled
            self._scheduler.proactive_interval = interval_seconds

    def cancel_voice_requests(self):
        """Cancel tracked voice requests without touching the shared context."""
        with self._lock:
            requests = list(self._active.values())
            self._active.clear()
            self._voice_bindings.clear()
        for request in requests:
            request.token.cancel()

    def revoke(self):
        """User-visible stop: cancel dispatch, discard context and history."""
        self.cancel_voice_requests()
        self.context_cleared()
        return self._service.revoke()

    # -- text mode (no microphone required) ----------------------------------
    def ask_text(self, question, *, session_id='companion', on_delta=None,
                 cancellation_token=None):
        self._require_ready()
        binding = self._service.bind_question()
        return self._service.ask(question, session_id=session_id, on_delta=on_delta,
            binding=binding, cancellation_token=cancellation_token,
            include_images=bool(self._include_images()))

    # -- voice transport -----------------------------------------------------
    def attach_speaker(self, speaker):
        """Register the open voice worker's discussion transport."""
        with self._lock:
            self._speaker = speaker

    def detach_speaker(self):
        with self._lock:
            self._speaker = None

    def voice_user_started(self, turn):
        """Freeze the question binding at speech start; supersede older turns."""
        self._require_ready()
        with self._lock:
            self._voice_bindings.clear()
            self._voice_bindings[turn] = self._service.bind_question()
        self._cancel_proactive_generation()
        self._scheduler.notify_user_activity()

    def voice_request(self, *, request, turn, text, record_history, on_delta=None):
        """Run a transcribed voice question through the one service (host thread).

        The request stays tracked through the worker's playback phase so a
        context change can still stop the spoken answer.
        """
        self._require_ready()
        with self._lock:
            binding = self._voice_bindings.pop(turn, None)
            if binding is None:
                raise CoordinatorStopped('voice turn binding missing or superseded')
            token = CancellationToken()
            self._active[request] = _VoiceRequest(request, turn, token, binding)
        try:
            result = self._service.ask(text, session_id='companion', binding=binding,
                cancellation_token=token, record_history=record_history,
                include_images=bool(self._include_images()), on_delta=on_delta)
        except BaseException:
            with self._lock:
                self._active.pop(request, None)
            raise
        return result

    def voice_request_delivered(self, request):
        """The verdict reached the worker; the request is in its playback phase."""
        with self._lock:
            active = self._active.get(request)
            if active is not None:
                active.phase = 'playback'

    def voice_request_cancelled(self, request):
        with self._lock:
            active = self._active.get(request)
        if active is not None:
            active.token.cancel()

    def voice_request_finished(self, request):
        with self._lock:
            self._active.pop(request, None)

    def finish_turn_requests(self, turn):
        """Playback ended or was interrupted; release the turn's requests."""
        with self._lock:
            requests = [item.request for item in self._active.values() if item.turn == turn]
            for request in requests:
                self._active.pop(request, None)
        return requests

    def voice_event(self, event, turn):
        """Existing playback/interruption lifecycle gating for the scheduler."""
        self._scheduler.voice_event(event, turn)

    # -- proactive -----------------------------------------------------------
    def _cancel_proactive_generation(self):
        with self._lock:
            thread = self._proactive_thread
        if thread is not None and thread.is_alive():
            # The generated result is discarded by the service's own
            # generation/revision checks once user activity is registered.
            self._scheduler.notify_user_activity(1.1)

    def _dispatch_proactive(self, observation):
        with self._lock:
            if self._failed is not None or not self._proactive_enabled:
                return
            if not self._background_budget.allow():
                return
            thread = self._proactive_thread
            if thread is not None and thread.is_alive():
                return
            self._proactive_thread = threading.Thread(
                target=self._generate_proactive, args=(observation,),
                name='sumika-proactive', daemon=True)
            self._proactive_thread.start()

    def _generate_proactive(self, observation):
        try:
            result = self._service.proactive(expected_observation=observation,
                                             prompt=DISCUSSION_PROMPT)
        except Exception as error:
            self._emit('proactive_error', {'error': type(error).__name__})
            return
        if not isinstance(result, dict) or result.get('status') != 'proactive':
            return
        text = result.get('text')
        if not isinstance(text, str) or not text.strip():
            return
        self._emit('proactive_text', {'text': text,
            'observation_at': result.get('observation_at'),
            'observation_source': result.get('observation_source'),
            'observation_target': result.get('observation_target')})
        with self._lock:
            speaker = self._speaker
        if speaker is not None:
            try:
                speaker(text)
            except Exception as error:
                self._emit('proactive_error', {'error': type(error).__name__})

    def summarize_danmaku(self, *, summarize):
        """Budget-gated asynchronous danmaku summary; never blocks the loop.

        ``summarize(content, source)`` is the auxiliary/local summary callable
        (default off). Runs on a daemon thread, consumes the current deduped
        buffer, and only emits an event; any failure drops the summary while
        the question loop continues untouched.
        """
        if not callable(summarize):
            raise ValueError('summary callable required')
        with self._lock:
            if self._failed is not None or not self._background_budget.allow():
                return {'status': 'skipped', 'reason': 'background budget or failure state'}
            texts = self.danmaku.snapshot_texts()
            if not texts:
                return {'status': 'empty'}
        def run():
            try:
                result = summarize(chr(10).join(texts), source='danmaku')
                text = result.get('text') if isinstance(result, dict) else None
                if isinstance(text, str) and text.strip():
                    self._emit('danmaku_summary', {'text': text[:2000]})
            except Exception as error:
                self._emit('danmaku_summary_error', {'error': type(error).__name__})
        threading.Thread(target=run, name='sumika-danmaku-summary', daemon=True).start()
        return {'status': 'started', 'entries': len(texts)}

    # -- failure -------------------------------------------------------------
    def fail(self, reason):
        """Stop new dispatch, cancel everything in flight, surface the error."""
        with self._lock:
            self._failed = str(reason)
            requests = list(self._active.values())
            self._active.clear()
            self._voice_bindings.clear()
        for request in requests:
            request.token.cancel()
            self._emit('answer_invalidated', {'request': request.request})
        self.context_cleared()
        self._service.revoke()
        self._emit('coordinator_failed', {'reason': str(reason)})

    def reset(self):
        """Explicit session start clears a previous failure; nothing replays."""
        with self._lock:
            self._failed = None

    def _require_ready(self):
        with self._lock:
            if self._failed is not None:
                raise CoordinatorStopped('companion coordinator failed: ' + self._failed)

    # -- introspection -------------------------------------------------------
    def status(self):
        with self._lock:
            return {'failed': self._failed,
                    'scheduler': self._perception.state,
                    'active_requests': len(self._active),
                    'speaker_attached': self._speaker is not None,
                    'proactive_enabled': self._proactive_enabled}

    def close(self):
        self.context_cleared()
