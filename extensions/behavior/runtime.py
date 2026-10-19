"""Harness-neutral composition of existing capture, routing and behavior assets.

The host supplies platform adapters and scope. No OS input, audio or model is
started by construction; only an explicit current grant or saved startup grant
arms the foreground follower. Persisted feedback never comes from model output.
"""
import hashlib
import math
import threading
import time
import uuid
from collections import deque
from datetime import datetime, timezone

from .prompts import PromptQuota, local_day_key
from .sequences import EpisodeTracker, robust_anomaly, select_ask_candidate


class BehaviorRuntime:
    def __init__(self, *, library, permissions, profiles, router, coordinator,
                 scope, foreground, capture_start, capture_stop, input_factory=None,
                 clock=time.monotonic, wall_clock=time.time):
        self.library, self.permissions = library, permissions
        self.profiles, self.router, self.coordinator = profiles, router, coordinator
        self._scope, self._foreground = scope, foreground
        self._capture_start, self._capture_stop = capture_start, capture_stop
        self._input_factory = input_factory
        self._clock, self._wall = clock, wall_clock
        self._lock = threading.RLock()
        self._lifecycle = threading.RLock()
        self._stop = threading.Event()
        self._thread = self._input = None
        self._armed = False
        self._seen = self._binding = None
        self._seen_at = 0
        self._latest = None
        self._error = None
        self._input_failed = False
        self._applied = None
        self._candidate = None
        self._shown = set()
        self._tracker = EpisodeTracker(clock=clock, same_session=lambda a, b: a == b)
        self._episode_started = None
        self._episode_scene = None
        self._episode_id = uuid.uuid4().hex
        self._episode_refs = deque(maxlen=6)
        self._episode_seconds = 0.0
        self._episode_end = None
        self._last_frame = None
        self._frame_seen = deque(maxlen=256)
        self._progress_seen = None
        self._app_hint = ''
        self._scene_material = None
        self._quota = PromptQuota()
        self._activity_previous = None
        self._activity_slice = None
        self._activity_slice_scope = None
        self._activity_switch = 0
        self._current_query = None
        self._query_at = None
        self._last_activity_at = None

    def start(self, *, startup=False):
        with self._lifecycle:
            state = self.permissions.load()
            effective = self.permissions.effective(state)
            with self._lock:
                self._armed = bool(effective['can_record'] and
                                   (not startup or effective['startup_resume']))
            self.router.set_suspended(bool(state['paused'] or state['revoked']))
            self.sync_profile()
            if self._armed and (self._thread is None or not self._thread.is_alive()):
                self._thread = threading.Thread(target=self._run,
                    name='sumika-behavior-runtime', daemon=True)
                self._thread.start()
            return self.status()

    def _run(self):
        while not self._stop.wait(1):
            try:
                self.tick()
            except Exception as error:
                try:
                    self.suspend(reason=type(error).__name__)
                except Exception:
                    # A disappeared root cannot persist an episode. Keep the
                    # in-memory failure visible, then stop polling.
                    with self._lock:
                        self._armed = False
                        self._error = type(error).__name__
                    return

    @staticmethod
    def _identity(value):
        if not isinstance(value, dict):
            return None
        return {key: value.get(key) for key in ('handle', 'process_id', 'process_creation')}

    def tick(self):
        with self._lifecycle:
            state = self.permissions.load()
            effective = self.permissions.effective(state)
            with self._lock:
                armed = self._armed and effective['can_record']
            if state['paused'] or state['revoked']:
                self.suspend(reason='permission paused or revoked')
                return
            if armed:
                live = self._foreground()
                image = str((live or {}).get('image', '')).lower()
                self._app_hint = image[:128]
                if not image or image == 'unknown' or any(
                        item in image for item in state['excluded_apps']):
                    live = None
                identity = self._identity(live)
                now = self._clock()
                with self._lock:
                    with self.permissions.recording_lease(state['revision']) as allowed:
                        if allowed:
                            self._activity_tick(live)
                        else:
                            self._discard_activity()
                with self._lock:
                    if identity != self._seen:
                        self._seen, self._seen_at = identity, now
                    old = self._binding
                if identity != old:
                    self._release_capture()
                    self.router.on_foreground(identity)
                    if identity is not None and now - self._seen_at >= 2:
                        self._capture_start(live)
                        with self._lock:
                            self._binding = identity
                            self._error = None
                if self._input is not None and self._input.status()['status'] == 'failed':
                    with self._lock:
                        self._error = self._input.status().get('error') or 'input channel failed'
                        self._candidate = None
                        self._finish_episode()
                    self._stop_input()
                    self._input_failed = True
                if self._input is None and not self._input_failed and self._input_factory is not None:
                    self._input = self._input_factory(self.observe_frames)
                    self._input.start(permission=state)
            else:
                with self._lock:
                    self._discard_activity()
                self._release_capture()
                self._stop_input()
            with self._lock:
                latest, binding = self._latest, self._binding
            if latest is not None:
                bundle, stamp = latest
                if self._clock() - stamp <= 3:
                    self._route(bundle, binding)
                else:
                    self.router.on_foreground(None)
                    self._finish_episode()
                    with self._lock:
                        self._latest = None
                        self._current_query = None
            self.sync_profile()
            with self._lock:
                finished = self._tracker.idle()
                if finished is not None:
                    self._save_episode(finished)
            self._maybe_prompt()

    def _scene(self):
        import ntpath
        profile = self._applied[1] if self._applied else None
        return {'app_name': ntpath.basename(self._app_hint)[:128],
                'profile_id': profile or ''}

    def current_query(self):
        with self._lock:
            return (dict(self._current_query) if self._current_query
                    and self._query_at is not None and 0 <= self._clock() - self._query_at <= 120 else None)

    def _discard_activity(self):
        self._activity_previous = self._activity_slice = None
        self._activity_slice_scope = None
        self._activity_switch = 0
        self._current_query = None

    def _flush_activity(self):
        item, self._activity_slice = self._activity_slice, None
        if item is None:
            return
        scope, self._activity_slice_scope = self._activity_slice_scope, None
        self.library.observe(item, scope=scope)
        self._last_activity_at = item['features']['ended_at']

    def _activity_tick(self, live):
        """Verified foreground time; no claim about attention or presence."""
        from .activity import split_interval
        now, wall = self._clock(), self._wall()
        identity = self._identity(live)
        scope = self._scope()
        key = (tuple(identity.values()), scope['user'], scope.get('session'),
               self._scene()['profile_id']) if identity else None
        previous = self._activity_previous
        if previous and previous['key'] != key:
            self._flush_activity()
            self._current_query = None
        if key is None:
            self._activity_previous = None
            self._activity_switch = 0
            return
        if previous and previous['key'] != key:
            # Count only observed identity transitions, never 60s seals or
            # mode changes. Unobserved gaps do not manufacture switches.
            if previous['identity'] != identity and 0 < now - previous['now'] <= 3:
                self._activity_switch = 1
        if previous and previous['key'] == key:
            delta, wall_delta = now - previous['now'], wall - previous['wall']
            if delta == 0 and wall_delta == 0:
                return  # Re-projecting this foreground probe changes nothing.
            if (0 < delta <= 3 and 0 < wall_delta <= 3
                    and abs(delta - wall_delta) <= .25):
                for start, end, day, hour, offset in split_interval(previous['wall'], wall):
                    scene = self._scene()
                    bucket = (day, hour, offset, scene['app_name'], scene['profile_id'])
                    item = self._activity_slice
                    if item:
                        f = item['features']
                        old_bucket = (f['local_date'], f['local_hour'], f['utc_offset_minutes'], f['app_name'], f['profile_id'])
                        if old_bucket != bucket or f['effective_seconds'] + end - start > 60:
                            self._flush_activity()
                            item = None
                    if item is None:
                        item = {'event_id': uuid.uuid4().hex, 'kind': 'app_focus',
                            'source': 'foreground-v1', 'features': {
                                'slice_version': 1, 'started_at': datetime.fromtimestamp(start, timezone.utc).isoformat(),
                                'ended_at': datetime.fromtimestamp(end, timezone.utc).isoformat(),
                                'effective_seconds': 0., **scene, 'local_date': day, 'local_hour': hour,
                                'utc_offset_minutes': offset, 'quality': 'verified_foreground',
                                'switch_count': self._activity_switch}}
                        self._activity_switch = 0
                        self._activity_slice = item
                        self._activity_slice_scope = dict(scope)
                    item['features']['ended_at'] = datetime.fromtimestamp(end, timezone.utc).isoformat()
                    item['features']['effective_seconds'] += end - start
                    if item['features']['effective_seconds'] >= 60:
                        self._flush_activity()
            else:
                self._flush_activity()
                self._activity_switch = 0
        self._activity_previous = {'key': key, 'identity': identity, 'now': now, 'wall': wall}

    def _route(self, bundle, identity=None):
        if not bundle.valid:
            with self._lock:
                self._current_query = None
            self.router.on_foreground(None)
            return
        # Text and title are ephemeral classifier data, never library fields.
        import json
        reader = bundle.metadata.get('reader_context')
        media = bundle.metadata.get('media_identity')
        navigation = ({key: reader.get(key) for key in ('document_path', 'document', 'page')}
                      if isinstance(reader, dict) else
                      {key: media.get(key) for key in ('url', 'part')}
                      if isinstance(media, dict) else {})
        material = {'identity_key': hashlib.sha256(bundle.target.encode()).hexdigest(),
                    'title': str(bundle.metadata.get('title', '') or self._app_hint)[:256],
                    'text': bundle.text[:2400],
                    'navigation': hashlib.sha256(json.dumps(navigation, sort_keys=True).encode()).hexdigest(),
                    'permission_revision': self.permissions.load()['revision']}
        # Advancing captions and moving game pixels do not change the scene.
        # A video/navigation identity change does; keep its first bounded text.
        key = (material['identity_key'], material['title'], material['navigation'], material['permission_revision'])
        if isinstance(media, dict) and not isinstance(reader, dict):
            if self._scene_material and self._scene_material[0] == key:
                material['text'] = self._scene_material[1]
            else:
                self._scene_material = (key, material['text'])
        if bundle.image is not None and len(bundle.text.strip()) < 80:
            material['image'] = bundle.image
        self.router.on_foreground(identity or {'target': bundle.target}, material=material)

    def observation(self, bundle):
        state = self.permissions.load()
        if state['paused'] or state['revoked']:
            return
        with self._lock:
            previous = self._latest[0] if self._latest else None
            if previous is not None and previous.target != bundle.target:
                self._finish_episode()
                self._candidate = None
                self._current_query = None
            self._latest = (bundle, self._clock())
            binding = self._binding
            with self.permissions.recording_lease(state['revision']) as allowed:
                if allowed:
                    self._record_progress(bundle)
        self._route(bundle, binding)
        self.sync_profile()

    def _record_progress(self, bundle):
        """Only reliable positions and fresh adjacent verifications count."""
        from pathlib import Path
        from urllib.parse import urlparse, parse_qs
        identity, position = None, None
        reader = bundle.metadata.get('reader_context')
        if bundle.valid and isinstance(reader, dict) and reader.get('document_identity') == 'file-url':
            path = reader.get('document_path')
            page = reader.get('page')
            if isinstance(path, str) and type(page) is int and page >= 1:
                try:
                    file = Path(path).resolve(strict=True)
                    stat = file.stat()
                    if file.is_file() and file.suffix.lower() == '.pdf':
                        identity = f'pdf:{str(file).casefold()}:{stat.st_size}:{stat.st_mtime_ns}'
                        position = page
                except (OSError, ValueError):
                    pass
        media = bundle.metadata.get('media_identity')
        if bundle.valid and identity is None and isinstance(media, dict):
            raw = media.get('url')
            parsed = urlparse(raw) if isinstance(raw, str) else None
            value = bundle.media_time_seconds
            if (parsed and parsed.scheme == 'https' and parsed.hostname in ('bilibili.com', 'www.bilibili.com')
                    and parsed.path.startswith('/video/') and type(value) in (int, float)
                    and math.isfinite(value) and value >= 0):
                part = parse_qs(parsed.query).get('p', ['1'])[0]
                if part.isdigit() and 1 <= int(part) <= 999999:
                    identity = f'bilibili:{parsed.path}:part={int(part)}'
                    position = value
        if identity is None:
            self._progress_seen = None
            return
        now = self._clock()
        stamp = bundle.observed_at.timestamp()
        if not 0 <= self._wall() - stamp <= 3:
            self._progress_seen = None
            return
        verification = (bundle.metadata.get('observation_id') or bundle.observed_at.isoformat(), bundle.target)
        previous = self._progress_seen
        if previous and previous['verification'] == verification:
            return
        increment = 0.
        if previous and previous['identity'] == identity:
            gap = now - previous['at']
            capture_gap = stamp - previous['stamp']
            if 0 < gap <= 3 and 0 < capture_gap <= 3:
                increment = min(gap, capture_gap)
        scope = self._scope()
        old = self.library.progress_for(identity, scope=scope)
        total = (old or {}).get('effective_seconds') or 0.
        self.library.record_progress(identity, position, effective_seconds=total + increment,
                                     source=bundle.source, scope=scope)
        self._progress_seen = {'verification': verification, 'identity': identity, 'at': now, 'stamp': stamp}

    def sync_profile(self):
        state = self.profiles.load()
        view = self.router.view()
        selected = (state['manual_profile_id'] if state['selection_policy'] == 'manual'
                    else view.get('effective_profile_id'))
        profile = next((p for p in state['profiles'] if p['id'] == selected), None)
        key = (state['revision'], selected)
        with self._lock:
            if key == self._applied:
                return
            self._finish_episode()
            self._candidate = None
            self._applied = key
        self.coordinator.apply_profile(profile)

    def config_changed(self):
        self.router.on_config_changed()
        self.coordinator.invalidate_background()
        self.sync_profile()

    def permissions_changed(self, *, activate=False):
        with self._lifecycle:
            self.coordinator.invalidate_background()
            self.router.on_config_changed()
            state = self.permissions.load()
            if state['paused'] or state['revoked']:
                self.suspend(reason='permission paused or revoked')
            else:
                self.router.set_suspended(False)
                with self._lock:
                    if activate:
                        self._armed = self.permissions.effective(state)['can_record']
                    self._input_failed = False
                    self._candidate = None
                    self._latest = None
                    self._progress_seen = None
                    self._discard_activity()
                    self._finish_episode()
                # Recreate the input channel with the new exclusion/permission epoch.
                self._stop_input()
                self._release_capture()
                if activate and self._armed and (self._thread is None or not self._thread.is_alive()):
                    self.start()
            return self.status()


    def observe_event(self, event):
        """Reading detector sink; True suppresses the old ungoverned note path."""
        with self._lock:
            state = self.permissions.load()
            with self.permissions.recording_lease(state['revision']) as allowed:
                if not allowed:
                    return True
                event = {**event, 'features': {**(event.get('features') or {}), **self._scene()}}
                result = self.library.observe(event, scope=self._scope())
                self._current_query = {'kind': event['kind'], **self._scene()}
                self._query_at = self._clock()
            if result.get('status') != 'duplicate':
                matches = self.library.habit_summaries(event['kind'], scope=self._scope(), query=self._current_query)
                self._candidate = (None if any(m['stable'] for m in matches) else
                    {'kind': event['kind'], 'event_id': event['event_id'], 'expires': self._clock() + 120})
        self._maybe_prompt()
        return True

    def observe_frames(self, batch):
        if not self.permissions.effective()['can_record']:
            return
        with self._lock:
            for frame in batch:
                if frame.get('user_scope') != self._scope()['user']:
                    raise ValueError('input frame belongs to a different user/project scope')
                target = (frame['worker_epoch'], frame['foreground_epoch'],
                          frame['window_instance'])
                ref = (frame['worker_epoch'], frame['sequence'])
                if ref in self._frame_seen:
                    continue
                self._frame_seen.append(ref)
                start, finish = float(frame['observed_from']), float(frame['observed_to'])
                previous = self._last_frame
                if previous and (previous['target'] != target or start - previous['to'] > 3
                        or start < previous['to'] or frame['sequence'] != previous['sequence'] + 1):
                    self._finish_episode()
                self._last_frame = {'target': target, 'to': finish, 'sequence': frame['sequence']}
                if frame['focus_quality'] != 'ok' or frame['dropped_count'] or frame['truncated']:
                    self._finish_episode()
                    continue
                # Only verified contiguous input frames contribute effective
                # time. The pump's monotonic timestamps are never wall dates.
                duration = max(0., min(3., finish - start))
                end = datetime.fromisoformat(frame['received_at']).timestamp()
                for action in frame['semantic_ops']:
                    before = self._tracker.episode_count
                    kind = {'typing_burst': 'typing', 'scroll_burst': 'scroll'}.get(action['kind'], action['kind'])
                    finished = self._tracker.observe(kind, target=target, at=finish)
                    if finished or self._tracker.episode_count != before:
                        self._save_episode(finished)
                    if self._episode_started is None:
                        self._episode_started = end - duration
                        self._episode_scene = self._scene()
                    if ref not in self._episode_refs:
                        self._episode_refs.append(ref)
                if self._episode_started is not None:
                    self._episode_seconds += duration
                    self._episode_end = end

    def _finish_episode(self):
        candidates = self._tracker.end()
        try:
            allowed = self.permissions.effective()['can_record']
        except Exception:
            allowed = False
        if allowed:
            self._save_episode(candidates)
        else:
            self._episode_started = None
            self._episode_id = uuid.uuid4().hex
            self._episode_refs.clear()
            self._episode_seconds = 0.0

    def _save_episode(self, candidates):
        state = self.permissions.load()
        with self.permissions.recording_lease(state['revision']) as allowed:
            if not allowed:
                candidates = []
            self._persist_episode(candidates)

    def _persist_episode(self, candidates):
        if not candidates or self._episode_started is None:
            self._episode_started = None
            self._episode_refs.clear()
            self._episode_seconds = 0.0
            return
        scope = self._scope()
        episode = self._episode_id
        scene = self._episode_scene or self._scene()
        supported = []
        for item in candidates:
            stored_id = episode + '-' + hashlib.sha256(item['signature'].encode()).hexdigest()[:12]
            seconds = min(self._episode_seconds, max(0., self._episode_end - self._episode_started))
            baseline = self.library.episode_baseline(item['signature'], scope=scope, detector_version='sequence-v1')
            anomaly = robust_anomaly(baseline, seconds, baseline='sequence-v1')
            self.library.record_episode({'episode_id': stored_id, 'session': scope['session'],
                'pattern': item['signature'], 'started_at': datetime.fromtimestamp(
                    self._episode_started, timezone.utc).isoformat(),
                'ended_at': datetime.fromtimestamp(self._episode_end, timezone.utc).isoformat(),
                'effective_seconds': seconds,
                'features': {'duration_outlier': bool(anomaly), 'base_episode_id': episode,
                             **scene}, 'detector_version': 'sequence-v1',
                'frame_refs': list(self._episode_refs)}, scope=scope)
            counts = self.library.pattern_candidates(item['signature'], scope=scope)
            sufficient = counts['episodes'] >= 3 and counts['sessions'] >= 2
            if sufficient:
                self.library.promote_pattern(item['signature'], scope=scope, derived_version='sequence-v1',
                    supports=self.library.pattern_supports(item['signature'], scope=scope))
            supported.append({**item, 'episode_id': stored_id,
                              'anomaly': bool(anomaly), 'supported': sufficient})
        stable = []
        for item in supported:
            query = {'kind': item['signature'], 'detector_version': 'sequence-v1', **scene}
            matches = self.library.habit_summaries(item['signature'], scope=scope, query=query)
            if any(m['stable'] and m['match_quality'] == 'exact' for m in matches):
                stable.append(item['signature'])
        chosen = select_ask_candidate(confirmed_patterns=stable,
                                     candidates=supported, episode_id=episode)
        self._episode_started = None
        self._episode_refs.clear()
        self._episode_seconds = 0.0
        self._episode_id = uuid.uuid4().hex
        if chosen:
            self._current_query = {'kind': chosen['signature'], 'detector_version': 'sequence-v1', **scene}
            self._query_at = self._clock()
        if chosen and chosen['reason'] != 'confirmed':
            source_id = next(item['episode_id'] for item in supported
                             if item['signature'] == chosen['signature'])
            self._candidate = {'kind': chosen['signature'], 'episode_id': source_id,
                               'expires': self._clock() + 120}

    def _maybe_prompt(self):
        with self._lock:
            candidate = self._candidate
            if candidate is None or candidate['expires'] < self._clock():
                self._candidate = None
                return
            effective = self.permissions.effective()
            self._quota.profile = self.permissions.load().get('question_profile', 'medium')
            if not effective['can_record'] or not effective['can_answer_questions']:
                return
            state = self.profiles.load()
            view = self.router.view()
            if state['selection_policy'] == 'auto' and view['reason'] != 'matched':
                return
            scope, now = self._scope(), self._wall()
            day = local_day_key(time.localtime(now))
            identity = candidate.get('event_id') or candidate.get('episode_id')
            if identity in self._shown or self.library.kind_muted_today(candidate['kind'], scope=scope, day=day):
                self._candidate = None
                return
            quota = self.library.prompt_quota(scope=scope)
            if not self._quota.decide(quota, now_epoch=now, day_key=day,
                    user_busy=self.coordinator.background_busy())['allowed']:
                return
            def prepare():
                state_now = self.permissions.load()
                with self.permissions.recording_lease(state_now['revision']) as allowed:
                    if not allowed or not self.permissions.effective(state_now)['can_answer_questions']:
                        return None
                    next_quota = self._quota.record(dict(quota), now_epoch=now, day_key=day)
                    prompt = self.library.record_prompt(candidate['kind'], scope=scope,
                        event_id=candidate.get('event_id'), episode_id=candidate.get('episode_id'),
                        reason='本地操作规律；意图尚未确认', quota=next_quota)
                text = {'long_dwell': '你在这页停留了一会儿，是在思考某个内容，还是在做别的事？',
                        'flip_burst': '看到你快速翻了几页，是在找内容，还是比较不同的说明？',
                        'revisit': '看到你在几处内容间来回查看，是在比较说明，还是找某个内容？'
                        }.get(candidate['kind'], '刚才这组操作是在做什么？可以写下自己的解释，也可以暂不回答。')
                return {**prompt, 'text': text}
            if self.coordinator.emit_behavior_prompt(prepare):
                self._shown.add(identity)
                if len(self._shown) > 256:
                    self._shown.pop()
                self._candidate = None

    def _release_capture(self):
        with self._lock:
            owned, self._binding = self._binding, None
        if owned is not None:
            self._capture_stop()
            with self._lock:
                self._latest = self._candidate = None
                self._current_query = None
                self._finish_episode()

    def _stop_input(self):
        process, self._input = self._input, None
        if process is not None:
            process.stop()

    def suspend(self, *, reason=None):
        with self._lifecycle:
            with self._lock:
                if reason == 'closed' and self._activity_slice is not None:
                    from .permission import PermissionClosed
                    try:
                        state = self.permissions.load()
                        with self.permissions.recording_lease(state['revision']) as allowed:
                            if allowed:
                                self._flush_activity()
                    except (PermissionClosed, OSError, ValueError):
                        pass  # A broken/revoked grant can never authorize flush.
                self._discard_activity()
                self._armed = False
                self._candidate = self._latest = None
                self._progress_seen = None
                self._error = reason
                self._finish_episode()
            self.coordinator.invalidate_background()
            self.router.set_suspended(True)
            self._release_capture()
            self._stop_input()
            with self._lock:
                self._finish_episode()

    def status(self):
        with self._lock:
            return {'armed': self._armed, 'following': self._binding is not None,
                    'last_activity_at': self._last_activity_at,
                    'coverage': 'verified_foreground; input coverage reported separately',
                    'error': self._error,
                    'input': self._input.status() if self._input else {'status': 'stopped'}}

    def close(self):
        self._stop.set()
        self.suspend(reason='closed')
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(timeout=15)
            if self._thread.is_alive():
                raise RuntimeError('behavior runtime stop outcome unknown')
