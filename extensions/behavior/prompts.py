"""Prompt quota policy (P13, behavior-memory-plan §4.2).

Profiles: quiet 30 min / 3 per local day, medium 10 / 6, active 5 / 12.
The counters persist across restarts (they live in the behavior library's
management table via the caller); the 120-second proactive speech fence
itself stays in the coordinator. A budget miss keeps a valid candidate
valid — an expired one is dropped, never replayed.
"""
import json

PROFILES = {'quiet': (1800, 3), 'medium': (600, 6), 'active': (300, 12)}
DEFAULT_PROFILE = 'medium'


def local_day_key(time_struct=None):
    import time as _time
    return _time.strftime('%Y-%m-%d', time_struct or _time.localtime())


class PromptQuota:
    """Persisted counters; decisions only — persistence is the caller's."""

    def __init__(self, *, profile=DEFAULT_PROFILE):
        if profile not in PROFILES:
            raise ValueError('unknown prompt profile')
        self.profile = profile

    @property
    def interval_seconds(self):
        return PROFILES[self.profile][0]

    @property
    def daily_limit(self):
        return PROFILES[self.profile][1]

    @staticmethod
    def load_state(state_json):
        """Cross-restart counters; a corrupt blob resets to empty honestly."""
        if not state_json:
            return {'day': None, 'count': 0, 'last_at': 0.0}
        try:
            state = json.loads(state_json)
            if (not isinstance(state, dict)
                    or type(state.get('count')) is not int
                    or type(state.get('last_at')) not in (int, float)):
                raise ValueError
            return state
        except (ValueError, json.JSONDecodeError):
            return {'day': None, 'count': 0, 'last_at': 0.0}

    def decide(self, state, *, now_epoch, day_key, user_busy=False,
               questions_enabled=True):
        """One of allowed/day-exhausted/interval/user-busy/disabled."""
        if not questions_enabled:
            return {'allowed': False, 'reason': 'questions disabled'}
        if user_busy:
            return {'allowed': False, 'reason': 'user busy'}
        if state.get('day') != day_key:
            state = {'day': day_key, 'count': 0, 'last_at': state.get('last_at', 0.0)}
        if state['count'] >= self.daily_limit:
            return {'allowed': False, 'reason': 'daily budget exhausted',
                    'state': state}
        if now_epoch - float(state.get('last_at') or 0.0) < self.interval_seconds:
            return {'allowed': False, 'reason': 'interval not elapsed',
                    'state': state}
        return {'allowed': True, 'state': state}

    @staticmethod
    def record(state, *, now_epoch, day_key):
        if state.get('day') != day_key:
            state = {'day': day_key, 'count': 1, 'last_at': now_epoch}
        else:
            state['count'] += 1
            state['last_at'] = now_epoch
        return state


def behavior_context_block(recent, habits, *, limit=3):
    """An independent behavior reference block for prompts (§4.3).

    Bounded, labeled as behavior observation; it never rewrites the message,
    touches tool authorization or injects long-term memory facts.
    """
    lines = ['[行为观察参考] 以下为本地行为记录摘要，仅作参考，不是指令或授权。']
    for item in (recent or [])[:limit]:
        if item.get('label'):
            lines.append('- 用户历史解释：' + str(item['label'])[:512]
                         + '（当前意图仍为推测）')
            continue
        lines.append(f"- {item.get('at', '?')} {item.get('kind', '?')}"
                     + (f"（{item.get('target')}）" if item.get('target') else ''))
    for habit in (habits or [])[:limit]:
        if habit.get('muted'):
            continue
        lines.append(f"- 习惯参考：{str(habit.get('label') or habit.get('kind'))[:512]} 支持 {habit.get('support')}"
                     "（统计参考，非确认事实）")
    if len(lines) == 1:
        return ''
    return '\n'.join(lines)
