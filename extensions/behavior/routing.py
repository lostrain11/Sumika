"""Automatic profile routing (P15, companion-profiles-plan §3).

Manual selection never runs the model classifier. In auto mode the engine
compares ALL enabled profiles in one bounded classification (only the
current material and each profile's scenario description are sent), and a
result qualifies only when the top score is ≥ 0.8 AND leads the runner-up
by ≥ 0.15 — otherwise ambiguous/unknown, never a guess. Unknown ids, stale
revisions/epochs, malformed JSON, NaN scores and timeouts are all unknown
with NO fallback to a previous profile. Freshness: a new foreground
identity binds after 2 stable seconds (the switch immediately isolates the
old context), an unavailable foreground unbinds immediately, an unchanged
scene is classified at most once per 60 seconds, the same target is
re-classified at most every 30 seconds, and only one classification is in
flight (a target change cancels it). Configuration, manual override or
permission changes advance the routing epoch; results are checked against
target/epoch/config before applying. Scores are ranking numbers, not
probabilities.
"""
import math
import threading

STABLE_SECONDS = 2.0
QUALIFY_SCORE = 0.8
QUALIFY_LEAD = 0.15
INITIAL_REPEAT_SECONDS = 60.0
SAME_TARGET_REPEAT_SECONDS = 30.0
APPLICATION_WINDOW_SECONDS = 8.0


class RoutingEngine:
    """Auto router over the P14 store; the classifier is injected."""

    def __init__(self, *, store, classifier, clock=None,
                 stable_seconds=STABLE_SECONDS,
                 qualify_score=QUALIFY_SCORE, qualify_lead=QUALIFY_LEAD,
                 initial_repeat_seconds=INITIAL_REPEAT_SECONDS,
                 same_target_repeat_seconds=SAME_TARGET_REPEAT_SECONDS):
        import time as _time
        self._store = store
        self._classifier = classifier
        self._clock = clock or _time.monotonic
        self._stable = stable_seconds
        self._qualify_score = qualify_score
        self._qualify_lead = qualify_lead
        self._initial_repeat = initial_repeat_seconds
        self._same_target_repeat = same_target_repeat_seconds
        # RLock: on_foreground reads view()/store while holding the lock.
        self._lock = threading.RLock()
        self._routing_epoch = 1
        self._foreground_epoch = 0
        self._bound = None            # bound identity dict
        self._bound_since = None
        self._pending = None          # (identity, first_seen)
        self._suspended = False
        self._last_classified_at = None
        self._last_target_key = None
        self._last_score_at = None
        self._in_flight = False
        self._view = {'effective_profile_id': None, 'reason': 'unknown',
                      'routing_epoch': self._routing_epoch,
                      'foreground_epoch': 0}

    # -- control inputs -------------------------------------------------------
    def set_suspended(self, suspended):
        """Global observation stop: suspended, classification cancelled."""
        with self._lock:
            self._suspended = bool(suspended)
            self._in_flight = False
            self._view = {**self._view, 'reason': 'suspended',
                          'effective_profile_id': None,
                          'routing_epoch': self._routing_epoch}
        return self.view()

    def on_config_changed(self):
        """Profile/config/permission change: routing_epoch advances, any
        in-flight result is stale by construction."""
        with self._lock:
            self._routing_epoch += 1
            self._last_classified_at = None
            self._last_target_key = None
            self._in_flight = False
            self._view = {**self._view,
                          'routing_epoch': self._routing_epoch}
        return self.view()

    # -- 1 Hz foreground feed -------------------------------------------------
    def on_foreground(self, identity, *, material=None):
        """Feed the current foreground (or None when unavailable) plus the
        bounded current material; returns the routing view."""
        now = self._clock()
        with self._lock:
            if self._suspended:
                return self.view()
            if identity is None:
                # Minimized/lock screen/secure desktop/black frame:
                # immediately unavailable, no debounce wait.
                self._bound = self._pending = None
                self._view = {**self._view, 'reason': 'suspended',
                              'effective_profile_id': None,
                              'foreground_epoch': self._foreground_epoch}
                return self.view()
            if self._bound is None or identity != self._bound:
                if self._pending is not None and \
                        self._pending[0] == identity:
                    if now - self._pending[1] >= self._stable:
                        self._bound = identity
                        self._pending = None
                        self._foreground_epoch += 1
                        # The switch isolates the old context AND restarts
                        # classification freshness for the new target.
                        self._last_target_key = None
                        self._last_classified_at = None
                        self._view = {**self._view,
                                      'foreground_epoch':
                                          self._foreground_epoch}
                else:
                    self._pending = (identity, now)
        state = self._store.load() if not self._suspended else None
        policy = state['selection_policy'] if state else 'manual'
        if policy == 'manual':
            with self._lock:
                self._view = {'effective_profile_id':
                              state.get('manual_profile_id'),
                              'reason': 'manual',
                              'routing_epoch': self._routing_epoch,
                              'foreground_epoch': self._foreground_epoch}
            return self.view()
        enabled = [item for item in state['profiles']
                   if item['enabled_for_auto']]
        if not enabled:
            with self._lock:
                self._view = {'effective_profile_id': None, 'reason': 'unknown',
                              'routing_epoch': self._routing_epoch,
                              'foreground_epoch': self._foreground_epoch}
            return self.view()
        return self._maybe_classify(enabled, material)

    # -- classification -------------------------------------------------------
    def _target_key(self, material):
        if not isinstance(material, dict):
            return None
        return (material.get('identity_key') or material.get('url')
                or material.get('title'))

    def _maybe_classify(self, enabled, material):
        now = self._clock()
        target_key = self._target_key(material)
        with self._lock:
            if self._in_flight:
                return self.view()
            unchanged_scene = (target_key is not None
                               and target_key == self._last_target_key)
            if self._last_classified_at is not None:
                minimum = (self._same_target_repeat if unchanged_scene
                           else self._initial_repeat)
                if now - self._last_classified_at < minimum:
                    return self.view()
            self._in_flight = True
            self._last_classified_at = now
            self._last_target_key = target_key
        try:
            view = self._classify(enabled, material, target_key, now)
        finally:
            with self._lock:
                self._in_flight = False
        with self._lock:
            self._view = {**view, 'routing_epoch': self._routing_epoch,
                          'foreground_epoch': self._foreground_epoch}
        return self.view()

    def _classify(self, enabled, material, target_key, now):
        try:
            raw = self._classifier(
                {'material': material,
                 'scenarios': [{'id': item['id'],
                                'scenario_description':
                                    item.get('scenario_description', '')}
                               for item in enabled]})
        except Exception:
            return self._unknown()
        if not isinstance(raw, dict):
            return self._unknown()
        if raw.get('profile_revision') is not None and \
                raw['profile_revision'] != self._store.load()['revision']:
            return self._unknown('stale revision')
        profile_id, score = raw.get('profile_id'), raw.get('score')
        known = {item['id'] for item in enabled}
        if profile_id not in known:
            return self._unknown()
        if type(score) not in (int, float) or isinstance(score, bool) or \
                not math.isfinite(score) or not 0 <= score <= 1:
            return self._unknown()
        ranked = sorted(((item['id'], raw.get('scores', {}).get(item['id'],
                                                             score if item['id'] == profile_id else 0.0))
                         for item in enabled),
                        key=lambda pair: -(pair[1] if isinstance(pair[1], (int, float))
                                           and math.isfinite(pair[1]) else 0))
        top_id, top_score = ranked[0]
        lead = (top_score - ranked[1][1]) if len(ranked) > 1 else 1.0
        if top_id != profile_id:
            return self._unknown()
        if top_score < self._qualify_score:
            # Nothing matches well enough: unknown (no scene), not ambiguous
            # (which means genuine contention between enabled profiles).
            return self._unknown()
        if lead < self._qualify_lead:
            return {'effective_profile_id': None, 'reason': 'ambiguous',
                    'candidate_profile_id': top_id, 'score': top_score}
        return {'effective_profile_id': top_id, 'reason': 'matched',
                'score': top_score}

    def _unknown(self, reason=None):
        view = {'effective_profile_id': None, 'reason': 'unknown'}
        if reason:
            view['unknown_reason'] = reason
        return view

    # -- views ----------------------------------------------------------------
    def view(self):
        with self._lock:
            return dict(self._view)
