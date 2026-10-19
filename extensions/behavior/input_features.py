"""Pure InputFeatureFrame aggregation (P11, behavior-memory-plan §2.3).

No OS imports: the Win32 worker translates raw input into the calls below.
Every persisted field is an anonymous count, bucket or grid cell — no key
strings, no ToUnicode text, no per-key timestamps, no absolute pointer
trails, no clipboard/IME content. A frame is at most 16 KiB of JSON and at
most 32 merged semantic operations; overflow keeps totals plus a truncated
flag instead of dropping silently.
"""
import json
import math
import re
from datetime import datetime

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


INTERVALS = ('0-50', '50-120', '120-300', '300-1000', '1000+')
KEY_NAMES = {'text_entry', 'navigation', 'editing', 'function', 'modifier', 'other'}
SHORTCUTS = set(SHORTCUT_WHITELIST.values()) | {'other_shortcut'}
SEMANTICS = SHORTCUTS | {'shortcut', 'typing_burst', 'enter', 'navigation',
                         'editing', 'function', 'left_click', 'right_click',
                         'middle_click', 'scroll_burst', 'drag'}
IDENTITY = {'user_scope', 'worker_epoch', 'foreground_epoch', 'focus_epoch', 'window_instance'}
FIELDS = IDENTITY | {'schema', 'sequence', 'observed_from', 'observed_to', 'keys',
    'shortcuts', 'mouse', 'scroll', 'drag', 'bursts', 'semantic_ops', 'semantic_total',
    'focus_quality', 'input_source_coverage', 'dropped_count', 'truncated'}


def _integer(value, *, maximum=2**63-1, signed=False):
    if type(value) is not int or not (-maximum if signed else 0) <= value <= maximum:
        raise ValueError('bounded integer required')


def _object(value, allowed, required=()):
    if not isinstance(value, dict) or set(value) - set(allowed) or set(required) - set(value):
        raise ValueError('closed frame object required')


def _time(value):
    if isinstance(value, str) and len(value) <= 40:
        try:
            number = float(value)
        except ValueError:
            try:
                stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
                if stamp.tzinfo is None:
                    raise ValueError('timezone required')
                number = stamp.timestamp()
            except ValueError as error:
                raise ValueError('frame timestamp required') from error
    elif type(value) in (int, float):
        number = value
    else:
        raise ValueError('frame timestamp required')
    if not math.isfinite(number) or number < 0:
        raise ValueError('finite frame timestamp required')
    return number


def validate_frame(frame, user_scope=None):
    """Closed, recursively typed IPC/storage schema; accepts empty legacy buckets."""
    _object(frame, FIELDS | {'received_at'}, FIELDS)
    if frame['schema'] != SCHEMA:
        raise ValueError('unknown input schema')
    scope = frame['user_scope']
    if not isinstance(scope, str) or not re.fullmatch(r'[A-Za-z0-9_.:@-]{1,128}', scope):
        raise ValueError('opaque user scope required')
    if user_scope is not None and scope != user_scope:
        raise ValueError('input scope mismatch')
    for key in IDENTITY - {'user_scope'} | {'sequence', 'semantic_total', 'dropped_count'}:
        _integer(frame[key])
    if _time(frame['observed_to']) < _time(frame['observed_from']):
        raise ValueError('frame time reversed')
    if 'received_at' in frame:
        _time(frame['received_at'])
    if type(frame['truncated']) is not bool:
        raise ValueError('truncated must be boolean')
    quality = frame['focus_quality']
    if quality not in ('ok', 'privacy_context_unknown', 'password_paused'):
        raise ValueError('unknown focus quality')
    if frame['input_source_coverage'] not in ('raw_input', 'full', 'coarse_only', 'none'):
        raise ValueError('unknown input coverage')
    keys = frame['keys']; _object(keys, {'counts', 'repeat', 'interval_buckets'}, {'counts', 'repeat', 'interval_buckets'})
    for name, allowed in (('counts', KEY_NAMES), ('interval_buckets', INTERVALS)):
        _object(keys[name], allowed)
        for count in keys[name].values(): _integer(count)
    _integer(keys['repeat'])
    _object(frame['shortcuts'], SHORTCUTS)
    for count in frame['shortcuts'].values(): _integer(count)
    mouse = frame['mouse']
    _object(mouse, {'left', 'right', 'middle', 'moves', 'double_click_candidates', 'grid'},
            {'left', 'right', 'middle', 'moves', 'double_click_candidates', 'grid'})
    for key, count in mouse.items():
        if key != 'grid': _integer(count)
    grid = mouse['grid']
    if grid is not None and (not isinstance(grid, list) or len(grid) != 16 or any(
            not isinstance(row, str) or not re.fullmatch('[0-9a-f]{16}', row) for row in grid)):
        raise ValueError('bounded mouse grid required')
    _object(frame['scroll'], {'vertical', 'horizontal'})
    for scroll in frame['scroll'].values():
        _object(scroll, {'count', 'delta', 'reversed'}, {'count', 'delta', 'reversed'})
        for key, count in scroll.items(): _integer(count, signed=key == 'delta')
    drag = frame['drag']; _object(drag, {'candidates', 'cells', 'duration_buckets', 'distance_buckets'})
    if 'candidates' in drag: _integer(drag['candidates'])
    for key, bound in (('cells', 255), ('duration_buckets', 12), ('distance_buckets', 4)):
        if key in drag:
            values = drag[key]
            if not isinstance(values, list) or len(values) > (256 if key == 'cells' else 64):
                raise ValueError('bounded drag buckets required')
            for value in values: _integer(value, maximum=bound)
    ops = frame['semantic_ops']
    if not isinstance(ops, list) or len(ops) > MAX_SEMANTIC_OPS:
        raise ValueError('bounded semantic operations required')
    for op in ops:
        _object(op, {'kind', 'count'}, {'kind', 'count'})
        if op['kind'] not in SEMANTICS: raise ValueError('unknown semantic operation')
        _integer(op['count'])
    if sum(op['count'] for op in ops) > frame['semantic_total']:
        raise ValueError('semantic total mismatch')
    bursts = frame['bursts']
    if not isinstance(bursts, list) or len(bursts) > MAX_SEMANTIC_OPS:
        raise ValueError('bounded bursts required')
    for burst in bursts:
        _object(burst, {'kind', 'id', 'events'}, {'kind', 'id', 'events'})
        if burst['kind'] not in ('typing_burst', 'scroll_burst') or not isinstance(burst['id'], str) or not re.fullmatch(r'(typing_burst|scroll_burst)-[0-9]{1,20}', burst['id']):
            raise ValueError('anonymous burst required')
        _integer(burst['events'])
    if quality != 'ok':
        if (frame['shortcuts'] or ops or bursts or frame['semantic_total'] or drag.get('candidates', 0)
                or any(drag.get(key) for key in ('cells', 'duration_buckets', 'distance_buckets'))
                or any(mouse[key] for key in ('left', 'right', 'middle', 'double_click_candidates'))
                or grid is not None or keys['repeat'] or any(keys['interval_buckets'].values())
                or set(keys['counts']) - {'other'}):
            raise ValueError('private focus contains fine features')
        if frame['input_source_coverage'] not in ('coarse_only', 'none'):
            raise ValueError('private focus coverage mismatch')
        if quality == 'privacy_context_unknown' and any(
                value['reversed'] or value['delta'] < 0 for value in frame['scroll'].values()):
            raise ValueError('unknown focus permits scroll quantity only')
        if quality == 'password_paused' and (any(keys['counts'].values()) or mouse['moves']
                or any(any(v.values()) for v in frame['scroll'].values())):
            raise ValueError('password input must be suspended')
    if len(json.dumps(frame, ensure_ascii=False, allow_nan=False).encode('utf8')) > MAX_FRAME_BYTES:
        raise ValueError('input frame exceeds budget')
    return frame


class BurstState:
    """One anonymous running burst, shared across adjacent second frames."""
    def __init__(self):
        self.counter = 0
        self.kind = self.last = self.identifier = None

    def reset(self):
        self.kind = self.last = self.identifier = None

    def event(self, kind, at):
        if self.kind != kind or self.last is None or at - self.last > .5 or at < self.last:
            self.counter += 1
            self.identifier = f'{kind}-{self.counter}'
        self.kind, self.last = kind, at
        return self.identifier


class FrameAggregator:
    """Constant-space counters; private focus gates events before aggregation."""
    def __init__(self, *, identity, observed_from, sequence, burst_state=None):
        _object(identity, IDENTITY, IDENTITY)
        self._identity = dict(identity)
        self._observed_from, self._sequence = observed_from, sequence
        self._burst_state = burst_state or BurstState()
        self._focus_quality, self._coverage = 'ok', 'raw_input'
        self._dropped, self._truncated = 0, False
        self._reset_features()

    def _reset_features(self):
        self._keys, self._shortcuts = {}, {}
        self._intervals = dict.fromkeys(INTERVALS, 0)
        self._repeat = 0
        self._last_key_at = None
        self._mouse = dict.fromkeys(('left', 'right', 'middle', 'double_click_candidates', 'moves'), 0)
        self._grid = [0] * 256
        self._scroll = {axis: {'count': 0, 'delta': 0, 'reversed': 0} for axis in ('vertical', 'horizontal')}
        self._direction = {}
        self._drag = {'candidates': 0, 'cells': set(), 'durations': [], 'distances': []}
        self._semantic, self._bursts = [], {}
        self._semantic_total = 0

    def key(self, vk, at, *, down=True, repeat=False, semantic=True):
        if not down or self._focus_quality == 'password_paused': return
        if self._focus_quality != 'ok':
            self._keys['other'] = self._keys.get('other', 0) + 1
            return
        klass = classify_key(vk)
        self._keys[klass] = self._keys.get(klass, 0) + 1
        if self._last_key_at is not None:
            gap = max(0, (at - self._last_key_at) * 1000)
            self._intervals[INTERVALS[next((i for i, n in enumerate((50,120,300,1000)) if gap < n), 4)]] += 1
        self._repeat += int(repeat)
        self._last_key_at = at
        if not semantic: return
        if klass == 'text_entry': self._note_burst('typing_burst', at)
        elif vk == 0x0D: self._note_semantic('enter')
        elif klass in ('navigation', 'editing', 'function'): self._note_semantic(klass)

    def shortcut(self, vk, modifiers):
        if self._focus_quality != 'ok': return
        name = classify_shortcut(vk, modifiers)
        self._shortcuts[name] = self._shortcuts.get(name, 0) + 1
        self._note_semantic(name)

    def click(self, button, x_ratio, y_ratio, *, double_candidate=False):
        if button not in ('left', 'right', 'middle'): raise ValueError('unknown mouse button')
        if self._focus_quality != 'ok':
            self.move()
            return
        self._mouse[button] += 1
        self._mouse['double_click_candidates'] += int(double_candidate)
        self._grid[grid_cell(x_ratio, y_ratio)] += 1
        self._note_semantic(f'{button}_click')

    def move(self):
        if self._focus_quality != 'password_paused': self._mouse['moves'] += 1

    def scroll(self, axis, delta, at=None):
        if axis not in ('vertical', 'horizontal'): raise ValueError('unknown scroll axis')
        if self._focus_quality == 'password_paused' or not delta: return
        bucket = self._scroll[axis]
        if self._focus_quality != 'ok':
            bucket['count'] += 1
            bucket['delta'] += abs(int(delta))
            return
        direction = 1 if delta > 0 else -1
        bucket['reversed'] += int(axis in self._direction and self._direction[axis] != direction)
        self._direction[axis] = direction
        bucket['count'] += 1
        bucket['delta'] += int(delta)
        if self._focus_quality == 'ok': self._note_burst('scroll_burst', at if at is not None else 0)

    def drag(self, x_ratio, y_ratio, duration_seconds, *, start=None):
        if type(duration_seconds) not in (int, float) or not math.isfinite(duration_seconds) or duration_seconds < 0:
            raise ValueError('bounded drag duration required')
        if self._focus_quality != 'ok': return
        cell = grid_cell(x_ratio, y_ratio)
        self._drag['candidates'] += 1
        self._drag['cells'].add(cell)
        if start is not None: self._drag['cells'].add(grid_cell(*start))
        if len(self._drag['durations']) < 64:
            self._drag['durations'].append(min(int(duration_seconds), 60) // 5)
            distance = 0 if start is None else math.hypot(x_ratio-start[0], y_ratio-start[1])
            self._drag['distances'].append(min(int(distance * 4), 4))
        else: self._truncated = True
        self._note_semantic('drag')

    def focus(self, quality):
        if quality not in ('ok', 'password_paused', 'privacy_context_unknown'): raise ValueError('unknown focus quality')
        if quality != self._focus_quality:
            self._reset_features()
            self._burst_state.reset()
        self._focus_quality = quality
        self._coverage = {'ok': 'raw_input', 'privacy_context_unknown': 'coarse_only', 'password_paused': 'none'}[quality]

    def _note_semantic(self, name, *, burst=False):
        if not burst: self._burst_state.reset()
        self._semantic_total += 1
        if self._semantic and self._semantic[-1]['kind'] == name and not self._truncated:
            self._semantic[-1]['count'] += 1
        elif len(self._semantic) < MAX_SEMANTIC_OPS:
            self._semantic.append({'kind': name, 'count': 1})
        else: self._truncated = True

    def _note_burst(self, kind, at):
        identifier = self._burst_state.event(kind, at)
        entry = self._bursts.get(identifier)
        if entry is None:
            if len(self._bursts) >= MAX_SEMANTIC_OPS:
                self._truncated = True
                self._note_semantic(kind, burst=True)
                return
            entry = self._bursts[identifier] = {'kind': kind, 'id': identifier, 'events': 0}
        entry['events'] += 1
        self._note_semantic(kind, burst=True)

    def seal(self, observed_to, *, privacy_paused=False):
        if privacy_paused: self.focus('password_paused')
        return {'schema': SCHEMA, **self._identity, 'sequence': self._sequence,
            'observed_from': self._observed_from, 'observed_to': observed_to,
            'keys': {'counts': dict(self._keys), 'repeat': self._repeat, 'interval_buckets': dict(self._intervals)},
            'shortcuts': dict(self._shortcuts),
            'mouse': {**self._mouse, 'grid': _pack_grid(self._grid) if self._focus_quality == 'ok' else None},
            'scroll': {key: dict(value) for key, value in self._scroll.items()},
            'drag': {'candidates': self._drag['candidates'], 'cells': sorted(self._drag['cells']),
                     'duration_buckets': list(self._drag['durations']), 'distance_buckets': list(self._drag['distances'])},
            'bursts': [dict(item) for item in self._bursts.values()],
            'semantic_ops': [dict(item) for item in self._semantic], 'semantic_total': self._semantic_total,
            'focus_quality': self._focus_quality, 'input_source_coverage': self._coverage,
            'dropped_count': self._dropped, 'truncated': self._truncated}

    def note_dropped(self, count=1):
        _integer(count)
        self._dropped += count


def frame_nonempty(frame):
    return bool(frame['dropped_count'] or any(frame['keys']['counts'].values())
        or any(frame['mouse'][k] for k in ('left', 'right', 'middle', 'moves'))
        or any(v['count'] for v in frame['scroll'].values())
        or frame['shortcuts'] or frame['drag'].get('candidates'))


def _pack_grid(grid):
    alphabet = '0123456789abcdef'
    return [''.join(alphabet[min(count, 15)] for count in grid[row*GRID:(row+1)*GRID]) for row in range(GRID)]
