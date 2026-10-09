"""Bounded player/QPC correlation; requires an independently verified owner.

The adapter brackets a player read between two native QPC samples. No browser
wall clock, audio byte count, or page-provided permission establishes ownership.
All times are intervals, and missing brackets remain unknown.
"""
from collections import deque
import copy
import math
import threading


class PlayerClockCorrelation:
    def __init__(self, *, target, media_identity, owner_verified=False,
                 max_gap_seconds=1.0, max_read_seconds=0.1):
        if owner_verified is not True:
            raise PermissionError('independently verified player/audio owner required')
        if not isinstance(target, str) or not target.strip() or not isinstance(media_identity, dict):
            raise ValueError('player target and media identity required')
        for value in (max_gap_seconds, max_read_seconds):
            if type(value) not in (int, float) or not math.isfinite(value) or not 0 < value <= 2:
                raise ValueError('bounded clock tolerances required')
        self.target = target
        self.identity = copy.deepcopy(media_identity)
        self.max_gap = max_gap_seconds * 10000000
        self.max_read = max_read_seconds * 10000000
        self._samples = deque(maxlen=256)
        self._lock = threading.RLock()
        self._active = True

    def revoke(self):
        with self._lock:
            self._active = False
            self._samples.clear()

    def discard_samples(self):
        """Pause/buffering/rate changes need fresh brackets on the same owner."""
        with self._lock:
            self._samples.clear()

    def observe(self, *, target, media_identity, qpc_before, qpc_after,
                media_time_seconds, playback_rate, paused, seeking, ended):
        with self._lock:
            if not self._active:
                raise PermissionError('player clock owner revoked')
            if target != self.target or media_identity != self.identity:
                self.revoke()
                raise PermissionError('player identity changed; new binding required')
            numbers = (media_time_seconds, playback_rate)
            if (any(type(v) not in (int, float) or not math.isfinite(v) for v in numbers)
                    or media_time_seconds < 0 or not 0 < playback_rate <= 16
                    or any(type(v) is not bool for v in (paused, seeking, ended))
                    or any(type(v) is not int or not 0 <= v < 2**64 for v in (qpc_before,qpc_after))
                    or not 0 <= qpc_after-qpc_before <= self.max_read):
                self._samples.clear()
                raise ValueError('invalid bracketed player clock')
            if paused or seeking or ended:
                self._samples.clear()
                return False
            sample = (qpc_before, qpc_after, media_time_seconds, playback_rate)
            if self._samples:
                previous = self._samples[-1]
                if qpc_before <= previous[1]:
                    self._samples.clear()
                    raise ValueError('nonmonotonic player clock')
                elapsed = ((qpc_before+qpc_after)-(previous[0]+previous[1]))/20000000
                uncertainty = ((qpc_after-qpc_before)+(previous[1]-previous[0]))/20000000 * playback_rate
                if (playback_rate != previous[3] or qpc_after-previous[0] > self.max_gap
                        or abs(media_time_seconds-previous[2]-elapsed*playback_rate) > uncertainty+0.05):
                    # Buffering, rate change, a seek without an event or a long
                    # read gap starts a new run; no segment crosses the gap.
                    self._samples.clear()
            self._samples.append(sample)
            return True

    def correlate(self, span, *, target, media_identity):
        unknown = {'known':False, 'clock_scope':'player-media-interval',
                   'method':'bracketed-owning-player-qpc'}
        with self._lock:
            if not self._active or target != self.target or media_identity != self.identity:
                return {**unknown, 'reason':'owner_or_identity_unavailable'}
            if not isinstance(span, dict) or span.get('known') is not True:
                return {**unknown, 'reason':'native_segment_clock_unknown'}
            if span.get('clock_scope') != 'native-segment-audio' or span.get('qpc_unit') != '100ns':
                return {**unknown, 'reason':'native_clock_scope_invalid'}
            start, end = span.get('start_qpc_position'), span.get('end_qpc_position')
            if any(type(v) is not int or v < 0 for v in (start,end)) or end <= start:
                return {**unknown, 'reason':'native_clock_range_invalid'}
            bounds = []
            for point in (start,end):
                before = next((s for s in reversed(self._samples) if s[1] <= point),None)
                after = next((s for s in self._samples if s[0] >= point),None)
                if before is None or after is None:
                    return {**unknown, 'reason':'player_samples_do_not_bracket_segment'}
                rate = before[3]
                if rate != after[3] or after[1]-before[0] > self.max_gap:
                    return {**unknown, 'reason':'player_sample_gap'}
                intervals = [sorted((s[2]+(point-s[1])/10000000*rate,
                                     s[2]+(point-s[0])/10000000*rate)) for s in (before,after)]
                # Include browser currentTime rounding/render scheduling. Both
                # endpoint projections must agree; never return a false point.
                lower = max(i[0]-0.05 for i in intervals)
                upper = min(i[1]+0.05 for i in intervals)
                if upper < lower or lower < 0:
                    return {**unknown, 'reason':'player_clock_projections_disagree'}
                bounds.append([lower,upper])
            return {**unknown, 'known':True, 'start_seconds_bounds':bounds[0],
                    'end_seconds_bounds':bounds[1], 'playback_rate':rate,
                    'uncertainty_note':'Player read/rounding interval; not sample-exact video synchronization'}
