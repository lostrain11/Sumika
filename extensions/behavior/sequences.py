"""Generic semantic sequence detection (P12, behavior-memory-plan §4.1).

Pure rules over semantic action categories — never characters, never
absolute positions, never fine-grained timestamps. Signatures are n-grams
(2–6) of merged action kinds; each episode counts a signature once; a
signature becomes a candidate only after 3 independent episodes across 2
real sessions (a page turn or a profile switch is not a new session); at
most 5 new candidates per episode. Overlapping occurrences never inflate
counts (one per episode), and freshness is explicit: 60 seconds without a
semantic action, a target/profile change, a pause or a capture gap ends the
episode. Robust anomaly scoring (median/MAD, z>3.5) needs 20 valid episodes
across 3 sessions per class; MAD=0 or thin data refuses to guess, and
"novel" is never "abnormal".
"""
import statistics

NGRAM_MIN = 2
NGRAM_MAX = 6
TAIL_WINDOW = 6
MAX_NEW_CANDIDATES = 5
EPISODE_IDLE_SECONDS = 60.0
ANOMALY_MIN_EPISODES = 20
ANOMALY_MIN_SESSIONS = 3
ANOMALY_Z = 3.5


def merge_actions(actions):
    """Collapse consecutive same-kind actions; typing/scroll runs merge too."""
    merged = []
    for action in actions:
        if not isinstance(action, str) or not action.strip() or \
                len(action) > 64:
            raise ValueError('semantic actions are bounded kind names')
        kind = action.strip()
        if kind in ('typing', 'scroll') and merged and \
                merged[-1] in (kind, kind + '_run'):
            merged[-1] = kind + '_run'
            continue
        if merged and merged[-1] == kind:
            continue
        merged.append(kind)
    return merged


class EpisodeTracker:
    """One stream of semantic actions -> episodes -> signature candidates.

    ``clock`` returns monotonic seconds. ``same_session(old, new)`` decides
    whether a target change still belongs to the same session (page turns
    and profile switches are not new sessions; the host decides).
    """

    def __init__(self, *, clock=None,
                 idle_seconds=EPISODE_IDLE_SECONDS,
                 same_session=None):
        import time as _time
        self._clock = clock or _time.monotonic
        self._idle = idle_seconds
        self._same_session = same_session or (lambda old, new: True)
        self._actions = []
        self._signatures = set()
        self._target = None
        self._last_at = None
        self._episodes = 0

    def observe(self, action, *, target, paused=False, gap=False):
        """Feed one semantic action; returns finished-candidate dicts when an
        episode ends. A paused stream or a capture gap ends the episode
        without recording the action."""
        now = self._clock()
        finished = []
        if paused or gap:
            finished.extend(self._end())
            return finished
        if self._actions and (now - self._last_at > self._idle
                              or not self._same_session(self._target, target)):
            finished.extend(self._end())
        if not self._actions:
            self._episodes += 1
        self._target = target
        self._last_at = now
        self._actions.append(action)
        return finished

    def end(self):
        """Explicit episode end (stop, revoke, target loss)."""
        return self._end()

    def _end(self):
        finished = []
        if self._actions:
            finished.extend(self._candidates(self._actions))
        self._actions = []
        self._signatures = set()
        self._target = None
        self._last_at = None
        return finished

    def _candidates(self, actions):
        """New signature candidates from one episode, tail-bounded."""
        merged = merge_actions(actions)
        found = []
        seen_here = set()
        for length in range(NGRAM_MIN, min(NGRAM_MAX, TAIL_WINDOW,
                                           len(merged)) + 1):
            tail = merged[-length:]
            signature = '|'.join(tail)
            if signature in self._signatures or signature in seen_here:
                continue  # one count per episode, overlaps never inflate
            seen_here.add(signature)
            found.append({'signature': signature, 'length': length,
                          'actions': tail})
        return found[:MAX_NEW_CANDIDATES]

    @property
    def episode_count(self):
        return self._episodes


def select_ask_candidate(*, confirmed_patterns, candidates, episode_id):
    """One ask candidate per episode: a confirmed pattern first, then the
    longest supported candidate, stable id breaking ties."""
    signatures = {item['signature'] for item in candidates}
    for pattern in confirmed_patterns or []:
        if pattern in signatures:
            return {'signature': pattern, 'reason': 'confirmed'}
    supported = [item for item in candidates or [] if item.get('supported')]
    if supported:
        best = max(supported, key=lambda item: (item['length'],
                                                item['signature']))
        return {'signature': best['signature'], 'reason': 'supported'}
    return None


def robust_anomaly(values, value, *, baseline='v1'):
    """Robust z-score against prior samples; refuses to guess on thin data.

    Requires ANOMALY_MIN_EPISODES values across ANOMALY_MIN_SESSIONS
    sessions. MAD=0 (or too few) returns None — novel is not abnormal, and
    detector versions keep separate baselines.
    """
    sessions = {item.get('session') for item in values
                if isinstance(item, dict)}
    if len(values) < ANOMALY_MIN_EPISODES or \
            len([s for s in sessions if s]) < ANOMALY_MIN_SESSIONS:
        return None
    numbers = [item['value'] if isinstance(item, dict) else item
               for item in values]
    median = statistics.median(numbers)
    mad = statistics.median(abs(number - median) for number in numbers)
    if mad == 0:
        return None
    z = (value - median) / (1.4826 * mad)
    if abs(z) > ANOMALY_Z:
        return {'z': round(z, 3), 'median': median, 'mad': mad,
                'baseline': baseline}
    return None
