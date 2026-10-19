"""User-defined companion profiles (P14, companion-profiles-plan §2).

A profile is a NAMED BUNDLE of preferences — never an authorization: the
schema is closed, so credentials, provider/endpoint, config paths,
executable code, tool permissions and auto long-term-write switches are
structurally impossible. The store is an independent JSON document in the
personal directory with atomic saves and a server-computed revision. A
corrupt file is kept beside itself for recovery and the store stands by
NEUTRAL (no profiles, manual, no selection) — never silently rebuilt with
permissions on. Manual selection persists across restarts until the user
explicitly switches to auto; deleting the current manual profile leaves
manual with a null selection, never a sneaky auto.
"""
import json
import secrets
import threading
import time
from pathlib import Path

SCHEMA_VERSION = 1
CONTEXT_SOURCES = ('text', 'image', 'application_audio')
MAX_PROFILES = 32
MAX_AUTO_ENABLED = 16
SETTINGS_FIELDS = ('proactive_enabled', 'proactive_interval_seconds',
                   'behavior_prompts_enabled', 'context_sources')
PROFILE_FIELDS = ('id', 'name', 'enabled_for_auto',
                  'scenario_description', 'response_instructions', 'settings')


class ProfileError(ValueError):
    pass


def _utc(clock):
    from datetime import datetime, timezone
    return datetime.fromtimestamp(clock(), tz=timezone.utc).isoformat()


def _validate_profile(profile):
    if not isinstance(profile, dict):
        raise ProfileError('profile must be an object')
    unknown = set(profile) - set(PROFILE_FIELDS)
    if unknown:
        raise ProfileError(f'unknown profile fields: {sorted(unknown)}')
    if 'id' in profile and (not isinstance(profile['id'], str)
                            or not profile['id'].strip()):
        raise ProfileError('profile id must be a non-empty string')
    name = profile.get('name')
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80:
        raise ProfileError('profile name must be 1..80 characters')
    for field in ('scenario_description', 'response_instructions'):
        value = profile.get(field)
        if value is not None and (not isinstance(value, str)
                                  or len(value) > 2000):
            raise ProfileError(f'{field} must be text within 2000 characters')
    if type(profile.get('enabled_for_auto')) is not bool:
        raise ProfileError('enabled_for_auto must be boolean')
    settings = profile.get('settings')
    if not isinstance(settings, dict) or set(settings) != set(SETTINGS_FIELDS):
        raise ProfileError('profile settings must carry exactly the '
                           'known switches')
    interval = settings['proactive_interval_seconds']
    if type(interval) is not int or not 120 <= interval <= 86400:
        raise ProfileError('proactive interval must be 120..86400 seconds')
    if type(settings['proactive_enabled']) is not bool or \
            type(settings['behavior_prompts_enabled']) is not bool:
        raise ProfileError('proactive switches must be boolean')
    sources = settings['context_sources']
    if not isinstance(sources, list) or \
            any(source not in CONTEXT_SOURCES for source in sources):
        raise ProfileError(f'context sources must be within {CONTEXT_SOURCES}')
    settings['context_sources'] = list(dict.fromkeys(sources))


def study_template(profile_id):
    return {'id': profile_id, 'name': '学习', 'enabled_for_auto': True,
            'scenario_description': '教学视频或教材的讲解理解与建议',
            'response_instructions': '结合当前内容解释知识点并给出学习建议。',
            'settings': {'proactive_enabled': True,
                         'proactive_interval_seconds': 300,
                         'behavior_prompts_enabled': True,
                         'context_sources': ['text', 'image',
                                             'application_audio']}}


def game_template(profile_id):
    return {'id': profile_id, 'name': '游戏', 'enabled_for_auto': True,
            'scenario_description': '游戏过程的简短情境吐槽',
            'response_instructions': '简短、轻松，不干扰操作。',
            'settings': {'proactive_enabled': True,
                         'proactive_interval_seconds': 180,
                         'behavior_prompts_enabled': True,
                         'context_sources': ['text', 'image']}}


def quiet_template(profile_id):
    return {'id': profile_id, 'name': '安静', 'enabled_for_auto': False,
            'scenario_description': '安静陪伴，不主动发言',
            'response_instructions': '',
            'settings': {'proactive_enabled': False,
                         'proactive_interval_seconds': 300,
                         'behavior_prompts_enabled': False,
                         'context_sources': []}}


class CompanionProfileStore:
    """Atomic JSON store in the personal directory; revision per write."""

    def __init__(self, personal_root, *, clock=time.time, new_user=False):
        self.path = Path(personal_root)/'companion-profiles.json'
        self._clock = clock
        self._lock = threading.Lock()
        self._new_user = new_user
        self._loaded_once = False

    # -- persistence ----------------------------------------------------------
    def _neutral(self):
        return {'schema_version': SCHEMA_VERSION, 'revision': 1,
                'selection_policy': 'manual', 'manual_profile_id': None,
                'profiles': []}

    def _templates(self):
        ids = [secrets.token_hex(8) for _ in range(3)]
        return {'schema_version': SCHEMA_VERSION, 'revision': 1,
                'selection_policy': 'manual',
                'manual_profile_id': ids[0],
                'profiles': [study_template(ids[0]), game_template(ids[1]),
                             quiet_template(ids[2])]}

    def load(self):
        """Load with fail-closed semantics; first init plants templates.

        New installations start with auto armed (the suggestion option);
        an upgrading installation keeps its old behavior: manual selection
        on the study template. A corrupt file is preserved beside itself
        and the store stands by NEUTRAL — no profiles, no selection, no
        permissions granted.
        """
        if not self.path.exists():
            state = self._templates()
            if self._new_user and not self._loaded_once:
                state['selection_policy'] = 'auto'
                state['manual_profile_id'] = None
            self._write(state)
            self._loaded_once = True
            return state
        if self.path.is_symlink() or self.path.is_junction():
            raise ProfileError('profile file must be a physical file')
        try:
            state = json.loads(self.path.read_text(encoding='utf8'))
        except (json.JSONDecodeError, OSError) as error:
            stamp = time.strftime('%Y%m%d-%H%M%S')
            corrupt = self.path.with_name(self.path.name + f'.corrupt-{stamp}')
            try:
                self.path.replace(corrupt)
            except OSError:
                pass
            neutral = self._neutral()
            self._write(neutral)
            self._loaded_once = True
            raise ProfileError(
                f'profile file corrupt; kept for recovery at {corrupt.name}; '
                'store is neutral (no profiles, no selection)') from error
        if (not isinstance(state, dict)
                or state.get('schema_version') != SCHEMA_VERSION
                or type(state.get('revision')) is not int
                or not isinstance(state.get('profiles'), list)
                or state.get('selection_policy') not in ('auto', 'manual')):
            raise ProfileError('profile schema unknown; failing closed')
        enabled = 0
        for profile in state['profiles']:
            _validate_profile(profile)
            enabled += 1 if profile['enabled_for_auto'] else 0
        if enabled > MAX_AUTO_ENABLED:
            raise ProfileError('more than 16 profiles enabled for auto')
        self._loaded_once = True
        return state

    def _write(self, state):
        temporary = self.path.with_suffix('.tmp')
        with temporary.open('w', encoding='utf8') as out:
            json.dump(state, out, ensure_ascii=False, indent=1)
            out.flush()
        temporary.replace(self.path)

    # -- mutations ------------------------------------------------------------
    def _mutate(self, expected_revision, mutation):
        """Revision-guarded mutation under the store lock."""
        with self._lock:
            state = self.load()
            if type(expected_revision) is not int or \
                    expected_revision != state['revision']:
                raise ProfileError(
                    f'revision conflict: stored {state["revision"]}, '
                    f'expected {expected_revision}')
            result = mutation(state)
            state['revision'] += 1
            self._write(state)
            return result

    def _find(self, state, profile_id):
        for profile in state['profiles']:
            if profile['id'] == profile_id:
                return profile
        raise ProfileError('profile not found')

    def create(self, profile, *, expected_revision):
        candidate = {key: value for key, value in profile.items()
                     if key != 'id'}  # the server always mints the id
        _validate_profile(candidate)
        candidate['id'] = secrets.token_hex(8)

        def mutate(state):
            if len(state['profiles']) >= MAX_PROFILES:
                raise ProfileError('profile limit (32) reached')
            enabled = sum(1 for item in state['profiles']
                          if item['enabled_for_auto'])
            if candidate['enabled_for_auto'] and enabled >= MAX_AUTO_ENABLED:
                raise ProfileError('auto-enabled profile limit (16) reached')
            state['profiles'].append(candidate)
            return {'status': 'created', 'id': candidate['id']}
        return self._mutate(expected_revision, mutate)

    def update(self, profile_id, changes, *, expected_revision):
        changes = dict(changes)

        def mutate(state):
            profile = self._find(state, profile_id)
            merged = {field: changes.get(field, profile.get(field))
                      for field in PROFILE_FIELDS}
            _validate_profile(merged)
            profile.update(merged)
            # Editing the current profile keeps the manual lock; the caller
            # stops the old proactive generation.
            return {'status': 'updated', 'id': profile_id}
        return self._mutate(expected_revision, mutate)

    def duplicate(self, profile_id, *, expected_revision):
        def mutate(state):
            profile = dict(self._find(state, profile_id))
            if len(state['profiles']) >= MAX_PROFILES:
                raise ProfileError('profile limit (32) reached')
            profile['id'] = secrets.token_hex(8)
            profile['name'] = (profile['name'] + ' 副本')[:80]
            profile['enabled_for_auto'] = False
            state['profiles'].append(profile)
            return {'status': 'duplicated', 'id': profile['id']}
        return self._mutate(expected_revision, mutate)

    def delete(self, profile_id, *, expected_revision):
        def mutate(state):
            self._find(state, profile_id)
            state['profiles'] = [item for item in state['profiles']
                                 if item['id'] != profile_id]
            if state.get('manual_profile_id') == profile_id:
                # Deleting the current manual selection never sneaks into
                # auto: manual with a null selection, normal chat still fine.
                state['manual_profile_id'] = None
            return {'status': 'deleted', 'id': profile_id}
        return self._mutate(expected_revision, mutate)

    def select(self, selection_policy, profile_id=None, *,
               expected_revision=None):
        if selection_policy not in ('auto', 'manual'):
            raise ProfileError('selection policy must be auto or manual')
        if selection_policy == 'manual':
            if not isinstance(profile_id, str) or not profile_id.strip():
                raise ProfileError('manual selection requires a profile id')
            profile_id = profile_id.strip()
        else:
            profile_id = None

        def mutate(state):
            if profile_id is not None:
                self._find(state, profile_id)
            state['selection_policy'] = selection_policy
            state['manual_profile_id'] = profile_id
            return {'status': 'selected',
                    'selection_policy': selection_policy,
                    'profile_id': profile_id}
        return self._mutate(expected_revision, mutate)

    # -- views ----------------------------------------------------------------
    def runtime(self):
        """P14 view: manual wins; auto reports honest match ambiguity (the
        P15 scorer fills candidate and score). A manual selection whose
        profile was deleted reports unknown with a null selection."""
        state = self.load()
        if state['selection_policy'] == 'manual':
            profile_id = state.get('manual_profile_id')
            if profile_id is None:
                return {'effective_profile_id': None, 'reason': 'unknown',
                        'profile_revision': state['revision']}
            try:
                self._find(state, profile_id)
            except ProfileError:
                return {'effective_profile_id': None, 'reason': 'unknown',
                        'profile_revision': state['revision']}
            return {'effective_profile_id': profile_id, 'reason': 'manual',
                    'profile_revision': state['revision']}
        # A store has no screen evidence. Only RoutingEngine can report a
        # matched/ambiguous scene; the number of enabled profiles proves neither.
        return {'effective_profile_id': None, 'reason': 'unknown',
                'profile_revision': state['revision']}
