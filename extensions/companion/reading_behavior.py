"""Reading-behavior pattern tracking as a feedback signal, not content.

Flipping fast, staying on one page a long time and jumping back repeatedly
are deliberate reader actions. The tracker consumes only page numbers and
capture times — never page text — and reports a sustained pattern at most
once per episode, so the session can ask the model to respond to the
behavior itself instead of the page content. A single flip or one large
jump never reports: every pattern requires repetition inside its window.
"""
import threading
import time
from collections import deque

KINDS = ('flip_burst', 'long_dwell', 'revisit')


class ReadingBehaviorTracker:
    """Detect sustained page-navigation patterns from capture-fed page numbers.

    Captures arrive at roughly 1 Hz, so even a page-per-second skim yields
    one event per capture. Each episode reports once; it re-arms only after
    the behavior has stopped for ``calm_seconds``, and an invalid or
    page-less capture resets all state instead of guessing.
    """

    def __init__(self, *, clock=time.monotonic, burst_flips=6,
                 burst_window=12.0, calm_seconds=20.0, dwell_seconds=180.0,
                 revisit_backjumps=2, revisit_window=30.0):
        if not callable(clock):
            raise ValueError('clock must be callable')
        if type(burst_flips) is not int or burst_flips < 2:
            raise ValueError('burst flip threshold must be an integer >= 2')
        for name, value in (('burst window', burst_window),
                            ('calm seconds', calm_seconds),
                            ('dwell seconds', dwell_seconds),
                            ('revisit window', revisit_window)):
            if type(value) not in (int, float) or value <= 0:
                raise ValueError(f'invalid {name}')
        if type(revisit_backjumps) is not int or revisit_backjumps < 1:
            raise ValueError('revisit back-jump threshold must be an integer >= 1')
        if calm_seconds < burst_window:
            raise ValueError('calm seconds must cover the burst window')
        self._clock = clock
        self._burst_flips = burst_flips
        self._burst_window = burst_window
        self._calm_seconds = calm_seconds
        self._dwell_seconds = dwell_seconds
        self._revisit_backjumps = revisit_backjumps
        self._revisit_window = revisit_window
        self._lock = threading.Lock()
        self._events = deque()
        self._page = None
        self._page_since = None
        self._reported = set()

    def reset(self):
        with self._lock:
            self._events.clear()
            self._page = self._page_since = None
            self._reported.clear()

    def feed(self, page, *, valid=True):
        """Feed one capture's page number; return a behavior report or None."""
        now = self._clock()
        with self._lock:
            if not valid or type(page) is not int or page < 1:
                self._events.clear()
                self._page = self._page_since = None
                self._reported.clear()
                return None
            if self._page is None:
                self._page = page
                self._page_since = now
            elif page != self._page:
                self._events.append((now, page - self._page))
                self._page = page
                self._page_since = now
                self._reported.discard('long_dwell')
            horizon = max(self._burst_window, self._revisit_window, self._calm_seconds)
            while self._events and now - self._events[0][0] > horizon:
                self._events.popleft()
            return self._evaluate(now)

    def _evaluate(self, now):
        window = max(self._burst_window, self._revisit_window)
        recent = [item for item in self._events if now - item[0] <= window]
        burst_events = [item for item in recent
                        if now - item[0] <= self._burst_window]
        backjumps = [item for item in recent if item[1] < 0]
        page = self._page
        if len(burst_events) >= self._burst_flips:
            if 'flip_burst' not in self._reported:
                self._reported.update(('flip_burst', 'revisit'))
                return {'kind': 'flip_burst', 'page': page,
                        'flips': len(burst_events),
                        'backward_flips': sum(1 for item in burst_events if item[1] < 0),
                        'max_jump': max(abs(item[1]) for item in burst_events),
                        'window_seconds': self._burst_window}
        elif not self._events or now - self._events[-1][0] >= self._calm_seconds:
            self._reported.discard('flip_burst')
            self._reported.discard('revisit')
        if len(backjumps) >= self._revisit_backjumps:
            if 'revisit' not in self._reported:
                self._reported.add('revisit')
                return {'kind': 'revisit', 'page': page,
                        'flips': len(recent),
                        'backward_flips': len(backjumps),
                        'window_seconds': self._revisit_window}
        if 'long_dwell' not in self._reported and \
                now - self._page_since >= self._dwell_seconds:
            self._reported.add('long_dwell')
            return {'kind': 'long_dwell', 'page': page,
                    'dwell_seconds': round(now - self._page_since, 1)}
        return None
