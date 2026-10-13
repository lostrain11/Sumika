"""Pure InputFeatureFrame aggregation (P11, behavior-memory-plan §2.3).

No OS imports: the Win32 worker translates raw input into the calls below.
Every persisted field is an anonymous count, bucket or grid cell — no key
strings, no ToUnicode text, no per-key timestamps, no absolute pointer
trails, no clipboard/IME content. A frame is at most 16 KiB of JSON and at
most 32 merged semantic operations; overflow keeps totals plus a truncated
flag instead of dropping silently.
"""
import json

SCHEMA = 'input-frame-v1'
MAX_FRAME_BYTES = 16 * 1024
MAX_SEMANTIC_OPS = 32
GRID = 16
SHORTCUT_WHITELIST = {
    (0x46, 'ctrl'): 'find', (0x43, 'ctrl'): 'copy', (0x56, 'ctrl'): 'paste',
    (0x58, 'ctrl'): 'cut', (0x5A, 'ctrl'): 'undo', (0x59, 'ctrl'): 'redo',
    (0x53, 'ctrl'): 'save', (0x41, 'ctrl'): 'select_all',
    (0x50, 'ctrl'): 'print',
}
KEY_CLASSES = {
    0x08: 'editing', 0x0D: 'navigation', 0x09: 'navigation',
    0x1B: 'navigation', 0x20: 'text_entry', 0x2E: 'editing', 0x2D: 'editing',
    0x24: 'navigation', 0x23: 'navigation', 0x25: 'navigation',
    0x26: 'navigation', 0x27: 'navigation', 0x28: 'navigation',
    0x21: 'navigation', 0x22: 'navigation', 0x70: 'function',
    0x71: 'function', 0x72: 'function', 0x73: 'function', 0x74: 'function',
    0x75: 'function', 0x76: 'function', 0x77: 'function', 0x78: 'function',
    0x79: 'function', 0x7A: 'function', 0x7B: 'function', 0x7C: 'function',
    0x7D: 'function', 0x7E: 'function', 0x7F: 'function', 0x80: 'function',
    0x81: 'function', 0x82: 'function', 0x83: 'function', 0x90: 'modifier',
    0x91: 'modifier', 0x14: 'modifier',
}


def classify_key(vk):
    """One Virtual-Key code into a coarse class; never the character."""
    vk = int(vk) & 0xFF
    if vk in (0x10, 0x11, 0x12, 0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5):
        return 'modifier'
    if 0x30 <= vk <= 0x39 or 0x41 <= vk <= 0x5A or vk in (0xBA, 0xBB, 0xBC,
                                                          0xBD, 0xBE, 0xBF,
                                                          0xC0, 0xDB, 0xDC,
                                                          0xDD, 0xDE):
        return 'text_entry'
    return KEY_CLASSES.get(vk, 'other')


def classify_shortcut(vk, modifiers):
    """Whitelisted shortcut name or other_shortcut; never the document."""
    vk = int(vk) & 0xFF
    mods = frozenset(modifiers or ())
    if mods == {'ctrl'}:
        return SHORTCUT_WHITELIST.get((vk, 'ctrl'), 'other_shortcut')
    return 'other_shortcut'


def grid_cell(x_ratio, y_ratio):
    """16×16 grid cell index; the absolute pointer position never persists."""
    for value in (x_ratio, y_ratio):
        if type(value) not in (int, float) or not 0 <= value <= 1:
            raise ValueError('pointer ratios must be within the window')
    return min(int(y_ratio * GRID), GRID - 1) * GRID + \
        min(int(x_ratio * GRID), GRID - 1)


class FrameAggregator:
    """Aggregates one second of anonymous input features into a frame."""

    def __init__(self, *, identity, observed_from, sequence):
        for key in ('user_scope', 'worker_epoch', 'foreground_epoch',
                    'focus_epoch', 'window_instance'):
            if key not in identity:
                raise ValueError(f'frame identity missing {key}')
        self._identity = dict(identity)
        self._observed_from = observed_from
        self._sequence = sequence
        self._keys = {}
        self._intervals = []
        self._last_key_at = None
        self._shortcuts = {}
        self._mouse = {'left': 0, 'right': 0, 'middle': 0,
                       'double_click_candidates': 0, 'moves': 0}
        self._grid = [0] * (GRID * GRID)
        self._scroll = {'vertical': {'count': 0, 'delta': 0, 'reversed': 0},
                        'horizontal': {'count': 0, 'delta': 0, 'reversed': 0}}
        self._drag = {'candidates': 0, 'cells': set(), 'durations': []}
        self._semantic = []
        self._bursts = {}
        self._dropped = 0
        self._truncated = False
        self._focus_quality = 'ok'
        self._coverage = 'full'

    # -- events ---------------------------------------------------------------
    def key(self, vk, at, *, down=True):
        if not down:
            return
        klass = classify_key(vk)
        self._keys[klass] = self._keys.get(klass, 0) + 1
        if self._last_key_at is not None:
            self._intervals.append(max(0, int((at - self._last_key_at) * 1000)))
        self._last_key_at = at
        self._note_burst('typing_burst', at,
                         new_semantic=klass == 'text_entry')

    def shortcut(self, vk, modifiers):
        name = classify_shortcut(vk, modifiers)
        self._shortcuts[name] = self._shortcuts.get(name, 0) + 1
        self._note_semantic(name if name != 'other_shortcut' else 'shortcut')

    def click(self, button, x_ratio, y_ratio, *, double_candidate=False):
        if button not in ('left', 'right', 'middle'):
            raise ValueError('unknown mouse button')
        self._mouse[button] += 1
        if double_candidate:
            self._mouse['double_click_candidates'] += 1
        cell = grid_cell(x_ratio, y_ratio)
        self._grid[cell] += 1
        self._note_semantic(f'{button}_click')

    def move(self):
        self._mouse['moves'] += 1

    def scroll(self, axis, delta):
        if axis not in ('vertical', 'horizontal'):
            raise ValueError('unknown scroll axis')
        bucket = self._scroll[axis]
        bucket['count'] += 1
        bucket['delta'] += int(delta)
        if delta < 0:
            bucket['reversed'] += 1
        self._note_burst('scroll_burst', self._intervals[-1] if
                         self._intervals else 0,
                         new_semantic=axis == 'vertical')

    def drag(self, x_ratio, y_ratio, duration_seconds):
        if type(duration_seconds) not in (int, float) or duration_seconds < 0:
            raise ValueError('drag duration must be a non-negative number')
        self._drag['candidates'] += 1
        self._drag['cells'].add(grid_cell(x_ratio, y_ratio))
        bucket = min(int(duration_seconds), 60) // 5
        self._drag['durations'].append(bucket)
        self._note_semantic('drag')

    def focus(self, quality):
        if quality not in ('ok', 'password_paused', 'privacy_context_unknown'):
            raise ValueError('unknown focus quality')
        self._focus_quality = quality
        if quality == 'password_paused':
            # Fine-grained input is fully suspended; counters stop here.
            self._keys.clear()
            self._intervals.clear()
            self._shortcuts.clear()
            self._mouse.update({'left': 0, 'right': 0, 'middle': 0,
                                'double_click_candidates': 0, 'moves': 0})
            self._grid = [0] * (GRID * GRID)
            self._drag = {'candidates': 0, 'cells': set(), 'durations': []}
            self._semantic.clear()
            self._bursts.clear()
        if quality == 'privacy_context_unknown':
            self._coverage = 'coarse_only'

    def _note_semantic(self, name):
        if self._semantic and self._semantic[-1]['kind'] == name:
            self._semantic[-1]['count'] += 1
            return
        self._semantic.append({'kind': name, 'count': 1})

    def _note_burst(self, kind, at, *, new_semantic):
        entry = self._bursts.get(kind)
        if entry is None or new_semantic:
            entry = {'kind': kind, 'id': f'{kind}-{len(self._bursts)}',
                     'events': 0}
            self._bursts[kind] = entry
        entry['events'] += 1

    # -- frame ----------------------------------------------------------------
    def seal(self, observed_to, *, privacy_paused=False):
        semantic = self._semantic[:MAX_SEMANTIC_OPS]
        overflow = sum(item['count'] for item in self._semantic[MAX_SEMANTIC_OPS:])
        frame = {
            'schema': SCHEMA,
            **self._identity,
            'sequence': self._sequence,
            'observed_from': self._observed_from,
            'observed_to': observed_to,
            'keys': {
                'counts': dict(self._keys),
                'repeat': sum(1 for gap in self._intervals if gap < 60),
                'interval_buckets': _bucket_intervals(self._intervals),
            },
            'shortcuts': dict(self._shortcuts),
            'mouse': {**self._mouse, 'grid': _pack_grid(self._grid)},
            'scroll': self._scroll,
            'drag': {'candidates': self._drag['candidates'],
                     'cells': sorted(self._drag['cells']),
                     'duration_buckets': sorted(self._drag['durations'])},
            'bursts': list(self._bursts.values()),
            'semantic_ops': semantic,
            'semantic_total': sum(item['count'] for item in self._semantic),
            'focus_quality': self._focus_quality,
            'input_source_coverage': self._coverage,
            'dropped_count': self._dropped,
            'truncated': bool(overflow or self._truncated),
        }
        if privacy_paused or self._focus_quality == 'password_paused':
            frame['focus_quality'] = 'password_paused'
        encoded = json.dumps(frame, ensure_ascii=False)
        if len(encoded.encode('utf8')) > MAX_FRAME_BYTES:
            frame['semantic_ops'] = semantic[:8]
            frame['drag']['duration_buckets'] =                 frame['drag']['duration_buckets'][:64]
            frame['drag']['cells'] = frame['drag']['cells'][:64]
            frame['truncated'] = True
            encoded = json.dumps(frame, ensure_ascii=False)
        if len(encoded.encode('utf8')) > MAX_FRAME_BYTES:
            frame['mouse']['grid'] = None
            frame['truncated'] = True
        return frame

    def note_dropped(self, count=1):
        self._dropped += count


def _bucket_intervals(intervals):
    """Key-interval histogram in ms; never the individual timestamps."""
    buckets = {'0-50': 0, '50-120': 0, '120-300': 0, '300-1000': 0, '1000+': 0}
    for gap in intervals:
        if gap < 50:
            buckets['0-50'] += 1
        elif gap < 120:
            buckets['50-120'] += 1
        elif gap < 300:
            buckets['120-300'] += 1
        elif gap < 1000:
            buckets['300-1000'] += 1
        else:
            buckets['1000+'] += 1
    return buckets


def _pack_grid(grid):
    """16×16 counts as compact hex rows; one character per cell, capped at f."""
    alphabet = '0123456789abcdef'
    return [''.join(alphabet[min(count, 15)] for count in
                    grid[row * GRID:(row + 1) * GRID]) for row in range(GRID)]
