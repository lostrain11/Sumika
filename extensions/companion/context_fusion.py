"""Bounded audio references augment, rather than replace, the visible content."""
from collections import deque
from dataclasses import replace
import threading
import time
import math

from .contracts import ObservationBundle


class ContextFusion:
    def __init__(self, *, ttl_seconds=120, max_chars=6000, max_segments=12, clock=time.monotonic):
        if (type(ttl_seconds) not in (int, float) or not 0 < ttl_seconds <= 600
                or type(max_chars) is not int or not 20 <= max_chars <= 6000
                or type(max_segments) is not int or not 1 <= max_segments <= 32):
            raise ValueError('invalid audio reference budget')
        self.ttl_seconds, self.max_chars, self.max_segments = ttl_seconds, max_chars, max_segments
        self.clock = clock
        self._visual = None
        self._audio = deque()
        self._player_clock = None
        self._lock = threading.RLock()

    def bind_player_clock(self, clock):
        """Adapter supplies a independently verified player/audio binding."""
        from .media_clock import PlayerClockCorrelation
        if not isinstance(clock, PlayerClockCorrelation):
            raise TypeError('verified player clock correlation required')
        with self._lock:
            visual = self._visual
            if (visual is None or not visual.valid or clock.target != visual.target
                    or clock.identity != visual.metadata.get('media_identity')):
                raise PermissionError('player clock must own the current visual target')
            if self._player_clock is not None and self._player_clock is not clock:
                self._player_clock.revoke()
            self._player_clock = clock

    def visual(self, bundle):
        if not isinstance(bundle, ObservationBundle):
            raise TypeError('observation required')
        with self._lock:
            previous = self._visual
            if previous is not None and bundle.observed_at < previous.observed_at:
                return self.current()
            media_changed = False
            if previous is not None and bundle.media_time_seconds is not None and previous.media_time_seconds is not None:
                delta = bundle.media_time_seconds - previous.media_time_seconds
                elapsed = max(0.0, (bundle.observed_at - previous.observed_at).total_seconds())
                # Normal playback advances roughly with wall time. A backward
                # move or a large jump is seek/navigation and fences audio.
                rate = previous.metadata.get('playback_rate')
                if type(rate) in (int, float) and math.isfinite(rate) and 0 < rate <= 16:
                    expected = 0 if previous.metadata.get('paused') is True else elapsed * rate
                    media_changed = abs(delta - expected) > 2.0
                else:
                    # Without a verified playback rate retain conservative
                    # seek detection; this is not an exact media-clock binding.
                    media_changed = delta < -0.25 or delta > max(8.0, elapsed * 6.0 + 3.0)
            if previous is None or (previous.target != bundle.target or previous.source != bundle.source
                    or previous.metadata.get('media_identity') != bundle.metadata.get('media_identity')
                    or media_changed or bundle.metadata.get('seeking') is True
                    or not bundle.valid):
                self._audio.clear()
            if self._player_clock is not None and (not bundle.valid
                    or bundle.target != self._player_clock.target
                    or previous is not None and previous.source != bundle.source
                    or bundle.metadata.get('media_identity') != self._player_clock.identity):
                self._player_clock.revoke()
                self._player_clock = None
            elif self._player_clock is not None and (media_changed
                    or any(bundle.metadata.get(key) is True for key in ('paused','seeking','ended'))
                    or previous is not None and previous.metadata.get('playback_rate') != bundle.metadata.get('playback_rate')):
                self._player_clock.discard_samples()
            self._visual = bundle
            return self.current()

    def audio(self, bundle):
        if not isinstance(bundle, ObservationBundle) or bundle.source != 'application-audio-transcript':
            raise TypeError('application transcript observation required')
        with self._lock:
            if self._visual is None or not self._visual.valid or bundle.target != self._visual.target:
                return None
            audio_identity = bundle.metadata.get('media_identity')
            visual_identity = self._visual.metadata.get('media_identity')
            if audio_identity != visual_identity:
                return None
            audio_time = bundle.metadata.get('media_time_seconds')
            visual_time = self._visual.media_time_seconds
            if (bundle.metadata.get('media_position_known') is True
                    and type(audio_time) in (int, float)
                    and type(visual_time) in (int, float)
                    and abs(audio_time - visual_time) > 15.0):
                return None
            if not bundle.valid or not bundle.text.strip():
                return None
            self._audio.append((self.clock(), replace(bundle, text=bundle.text[:self.max_chars])))
            while len(self._audio) > self.max_segments or sum(len(b.text) for _, b in self._audio) > self.max_chars:
                self._audio.popleft()
            return self.current()

    def clear_audio(self):
        with self._lock:
            self._audio.clear()
            return self._visual

    def clear(self):
        with self._lock:
            self._visual = None
            self._audio.clear()
            if self._player_clock is not None:
                self._player_clock.revoke()
                self._player_clock = None

    def current(self):
        with self._lock:
            now = self.clock()
            while self._audio and now - self._audio[0][0] >= self.ttl_seconds:
                self._audio.popleft()
            visual = self._visual
            if visual is None or not self._audio:
                return visual
            references = [{'observed_at': b.observed_at.isoformat(), 'source': b.source,
                           'text': b.text, 'metadata': dict(b.metadata)} for _, b in self._audio]
            if self._player_clock is not None:
                for item in references:
                    item['metadata']['player_clock_span'] = self._player_clock.correlate(
                        item['metadata'].get('capture_clock_span'), target=visual.target,
                        media_identity=item['metadata'].get('media_identity'))
            audio_text = '\n[Application audio reference; capture offset is not video time]\n'
            audio_text += '\n'.join(item['text'] for item in references)
            text = visual.text[:max(0, 12000-len(audio_text))] + audio_text
            return replace(visual, text=text,
                observed_at=max([visual.observed_at] + [b.observed_at for _, b in self._audio]),
                metadata={**dict(visual.metadata), 'visual_observed_at': visual.observed_at.isoformat(),
                          'application_audio': references})
