"""Foreground profile routing; capture and model permissions remain host-owned."""
import hashlib
import json
import math
import threading
import time

from extensions.models.cancellation import CancellationToken

STABLE_SECONDS = 2.0
QUALIFY_SCORE = 0.8
QUALIFY_LEAD = 0.15
INITIAL_REPEAT_SECONDS = 60.0
SAME_TARGET_REPEAT_SECONDS = 30.0
APPLICATION_WINDOW_SECONDS = 8.0


class ClassificationDeferred(Exception):
    """No provider was started (shared budget, disabled or user priority)."""


class RoutingEngine:
    def __init__(self, *, store, classifier, clock=None,
                 stable_seconds=STABLE_SECONDS, qualify_score=QUALIFY_SCORE,
                 qualify_lead=QUALIFY_LEAD,
                 initial_repeat_seconds=INITIAL_REPEAT_SECONDS,
                 same_target_repeat_seconds=SAME_TARGET_REPEAT_SECONDS,
                 application_seconds=APPLICATION_WINDOW_SECONDS,
                 asynchronous=False):
        self._store, self._classifier = store, classifier
        self._clock = clock or time.monotonic
        self._stable, self._application = stable_seconds, application_seconds
        self._qualify_score, self._qualify_lead = qualify_score, qualify_lead
        self._same_target_repeat = same_target_repeat_seconds
        self._lock = threading.RLock()
        self._routing_epoch, self._foreground_epoch = 1, 0
        self._suspended = False
        self._identity = self._bound = None
        self._seen_at = None
        self._evidence = None
        self._candidate = self._request = None
        self._last_classified = {}
        self._completed = set()
        self._revision = None
        self._asynchronous = asynchronous
        self._view = self._neutral('unknown')

    @staticmethod
    def _neutral(reason):
        return {'effective_profile_id': None, 'reason': reason}

    def _cancel_locked(self):
        if self._request is not None:
            self._request['token'].cancel()
        # Keep the physical request registered until it exits, even when a
        # provider ignores cancellation: never start a second request over it.
        self._candidate = None
        self._routing_epoch += 1

    def set_suspended(self, suspended):
        with self._lock:
            if self._suspended != bool(suspended):
                self._cancel_locked()
                self._suspended = bool(suspended)
                self._identity = self._bound = self._evidence = None
                self._seen_at = None
                self._completed.clear()
            self._view = self._neutral('suspended' if suspended else 'unknown')
        return self.view()

    def on_config_changed(self):
        with self._lock:
            self._cancel_locked()
            self._completed.clear()
            self._revision = None
            self._view = self._neutral('suspended' if self._suspended else 'unknown')
        return self.view()

    @staticmethod
    def _target_key(material):
        if not isinstance(material, dict):
            return None
        return material.get('identity_key') or material.get('url') or material.get('title')

    def _evidence_key(self, material):
        # Pixel motion in a game is not a scene change. The host supplies a
        # bounded semantic summary, navigation and permission revision.
        stable = {key: material.get(key) for key in
                  ('identity_key', 'title', 'text', 'page', 'navigation', 'permission_revision')}
        return hashlib.sha256(json.dumps(stable, sort_keys=True,
            ensure_ascii=False).encode('utf8')).hexdigest()

    def on_foreground(self, identity, *, material=None):
        state = self._store.load()
        now = self._clock()
        with self._lock:
            if state['revision'] != self._revision:
                self._cancel_locked()
                self._completed.clear()
                self._revision = state['revision']
                self._view = self._neutral('unknown')
            if self._suspended:
                self._view = self._neutral('suspended')
                return self.view()
            if identity is None:
                if self._identity is not None:
                    self._cancel_locked()
                self._identity = self._bound = self._evidence = None
                self._seen_at = None
                self._view = self._neutral('suspended')
                return self.view()
            if identity != self._identity:
                self._cancel_locked()
                self._identity = dict(identity)
                self._bound = None
                self._seen_at = now
                self._evidence = None
                self._view = self._neutral('unknown')
            if state['selection_policy'] == 'manual':
                self._view = {'effective_profile_id': state.get('manual_profile_id'), 'reason': 'manual'}
                return self.view()
            if self._bound is None:
                if now - self._seen_at < self._stable:
                    return self.view()
                self._bound = dict(identity)
                self._foreground_epoch += 1
            if not isinstance(material, dict) or not self._target_key(material):
                self._view = self._neutral('unknown')
                return self.view()
            evidence = self._evidence_key(material)
            if evidence != self._evidence:
                self._cancel_locked()
                self._evidence = evidence
                self._view = self._neutral('unknown')
            enabled = [p for p in state['profiles'] if p['enabled_for_auto']]
            if not enabled:
                self._view = self._neutral('unknown')
                return self.view()
            if self._candidate is not None:
                if now - self._candidate['since'] >= self._application:
                    self._view = dict(self._candidate['view'])
                return self.view()
            completed_key = (self._revision, repr(self._identity), evidence)
            if completed_key in self._completed or self._request is not None:
                return self.view()
            target = self._target_key(material)
            if now - self._last_classified.get(target, float('-inf')) < self._same_target_repeat:
                return self.view()
            self._last_classified[target] = now
            if len(self._last_classified) > 128:
                self._last_classified.pop(next(iter(self._last_classified)))
            if len(self._completed) >= 128:
                self._completed.clear()
            request = {'epoch': self._routing_epoch, 'foreground': self._foreground_epoch,
                       'revision': self._revision, 'identity': dict(identity),
                       'evidence': evidence, 'completed_key': completed_key,
                       'token': CancellationToken(), 'enabled': enabled,
                       'material': dict(material)}
            self._request = request
        if self._asynchronous:
            threading.Thread(target=self._classify, args=(request,),
                name='sumika-scene-classifier', daemon=True).start()
        else:
            self._classify(request)
        return self.view()

    def _classify(self, request):
        deferred = False
        try:
            with request['token'].activate():
                request['token'].check()
                raw = self._classifier({'material': request['material'],
                    'scenarios': [{'id': p['id'], 'scenario_description':
                                   p.get('scenario_description', '')}
                                  for p in request['enabled']],
                    'cancellation_token': request['token']})
                request['token'].check()
            view = self._qualify(raw, request)
        except ClassificationDeferred:
            deferred = True
            view = self._neutral('unknown')
        except Exception:
            view = self._neutral('unknown')
        with self._lock:
            if self._request is request:
                self._request = None
            try:
                state = self._store.load()
            except Exception:
                self._view = self._neutral('unknown')
                return
            if (self._suspended or request['epoch'] != self._routing_epoch
                    or request['foreground'] != self._foreground_epoch
                    or request['revision'] != state['revision']
                    or state['selection_policy'] != 'auto'
                    or request['identity'] != self._identity
                    or request['evidence'] != self._evidence):
                return
            if deferred:
                self._last_classified.pop(self._target_key(request['material']), None)
                return
            self._completed.add(request['completed_key'])
            if view['reason'] == 'matched':
                self._candidate = {'since': self._clock(), 'view': view}
                self._view = {**view, 'reason': 'unknown',
                    'candidate_profile_id': view['effective_profile_id'],
                    'effective_profile_id': None, 'unknown_reason': '等待场景持续稳定'}
            else:
                self._view = view

    def _qualify(self, raw, request):
        unknown = self._neutral('unknown')
        if not isinstance(raw, dict):
            return unknown
        if raw.get('profile_revision', request['revision']) != request['revision']:
            return unknown
        known = {p['id'] for p in request['enabled']}
        scores = raw.get('scores')
        if not isinstance(scores, dict) or set(scores) != known or any(
                type(score) not in (int, float) or not math.isfinite(score)
                or not 0 <= score <= 1 for score in scores.values()):
            return unknown
        ranked = sorted(scores.items(), key=lambda pair: (-pair[1], pair[0]))
        top, score = ranked[0]
        if raw.get('profile_id', top) != top or score < self._qualify_score:
            return unknown
        if len(ranked) > 1 and score - ranked[1][1] < self._qualify_lead:
            return {**unknown, 'reason': 'ambiguous', 'candidate_profile_id': top, 'score': score}
        return {'effective_profile_id': top, 'reason': 'matched', 'score': score}

    def view(self):
        with self._lock:
            return {**self._view, 'routing_epoch': self._routing_epoch,
                    'foreground_epoch': self._foreground_epoch,
                    'profile_revision': self._revision,
                    'target_identity': dict(self._bound) if self._bound else None}

    def close(self):
        self.set_suspended(True)
