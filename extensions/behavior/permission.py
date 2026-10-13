"""Persistent behavior-capture permission and foreground rebinding (P10 §2.1).

The permission file lives inside the behavior root: a missing directory or a
corrupt file fails closed and is never relocated. An explicitly saved
permission may follow Sumika starts (``startup_resume``); a paused or
revoked one never resumes by itself. A fresh process rebinds to the CURRENT
foreground window with a new session/epoch — no stored HWND/PID/grant is
ever reused, because none is stored. There is no OS autostart here and no
automatic microphone, application-audio or TTS consent.
"""
import json
import os
import threading
import time
from pathlib import Path

SCHEMA_VERSION = 1
DEFAULT_EXCLUSIONS = ('sumika', 'sumikapet', 'sumikaprocessaudio')
_SWITCHES = ('recording', 'use_memory', 'questions', 'startup_resume')
_LOCK = threading.Lock()


class PermissionClosed(Exception):
    """The stored permission is missing, unreadable or the root is gone."""


def _utc(clock):
    from datetime import datetime, timezone
    return datetime.fromtimestamp(clock(), tz=timezone.utc).isoformat()


class BehaviorPermissions:
    """Revision-guarded persistent permission inside the behavior root."""

    def __init__(self, behavior_root, *, clock=time.time):
        self.root = Path(behavior_root)
        self.path = self.root/'permission.json'
        self._clock = clock

    def _defaults(self):
        return {'schema_version': SCHEMA_VERSION, 'revision': 1,
                'excluded_apps': list(DEFAULT_EXCLUSIONS),
                'recording': False, 'use_memory': False, 'questions': False,
                'startup_resume': False, 'paused': False, 'revoked': False,
                'updated_at': _utc(self._clock)}

    def load(self):
        """Load with fail-closed semantics; a fresh root gets safe defaults."""
        if not self.root.is_dir():
            raise PermissionClosed('behavior root directory is missing; '
                                   'permission cannot be relocated')
        if not self.path.exists():
            return self._defaults()
        if self.path.is_symlink() or self.path.is_junction():
            raise PermissionClosed('permission file must be a physical file')
        try:
            state = json.loads(self.path.read_text(encoding='utf8'))
        except (json.JSONDecodeError, OSError) as error:
            raise PermissionClosed('permission file unreadable; failing '
                                   'closed instead of relocating') from error
        if (not isinstance(state, dict)
                or state.get('schema_version') != SCHEMA_VERSION
                or type(state.get('revision')) is not int):
            raise PermissionClosed('permission schema unknown; failing closed')
        return state

    def _write(self, state):
        temporary = self.path.with_suffix('.tmp')
        with temporary.open('w', encoding='utf8') as out:
            json.dump(state, out, ensure_ascii=False, indent=1)
            out.flush()
        temporary.replace(self.path)

    @staticmethod
    def _validate(state):
        for key in _SWITCHES:
            if type(state.get(key)) is not bool:
                raise ValueError(f'{key} must be boolean')
        if type(state.get('paused')) is not bool or \
                type(state.get('revoked')) is not bool:
            raise ValueError('paused/revoked must be boolean')
        apps = state.get('excluded_apps')
        if (not isinstance(apps, list) or len(apps) > 64 or any(
                not isinstance(name, str) or not name.strip()
                or len(name) > 128 or name != name.lower()
                for name in apps)):
            raise ValueError('excluded apps must be lowercase bounded names')
        for name in DEFAULT_EXCLUSIONS:
            if name not in apps:
                raise ValueError('own-process exclusions cannot be removed')

    def effective(self, state=None):
        state = state or self.load()
        active = (state['recording'] and not state['paused']
                  and not state['revoked'])
        return {'can_record': active,
                'can_use_memory': (state['use_memory'] and active),
                'can_answer_questions': (state['questions'] and not state['paused']
                                         and not state['revoked']),
                'startup_resume': state['startup_resume'] and active,
                'paused': state['paused'], 'revoked': state['revoked']}

    def save(self, mutations, *, revision):
        """Revision-guarded mutation; switches and pauses are exclusive."""
        if type(revision) is not int:
            raise ValueError('revision required for permission mutations')
        with _LOCK:
            state = self.load()
            if state['revision'] != revision:
                raise ValueError(f'revision conflict: stored {state["revision"]}, '
                                 f'requested {revision}')
            unknown = set(mutations) - set(_SWITCHES) - {'excluded_apps',
                                                         'paused', 'revoked'}
            if unknown:
                raise ValueError(f'unknown permission fields: {sorted(unknown)}')
            state.update(mutations)
            self._validate(state)
            if state['revoked'] and (state['recording'] or state['use_memory']
                                     or state['questions']):
                raise ValueError('a revoked permission cannot grant switches')
            # Pausing KEEPS the saved switches: it is a runtime suppression
            # that persists across restarts until an explicit resume.
            state['revision'] += 1
            state['updated_at'] = _utc(self._clock)
            self.root.mkdir(parents=True, exist_ok=True)
            self._write(state)
            return self.effective(state)

    def pause(self, *, revision):
        return self.save({'paused': True}, revision=revision)

    def resume(self, *, revision):
        return self.save({'paused': False}, revision=revision)

    def revoke(self, *, revision):
        """Terminal: switches off, stays off across restarts."""
        effective = self.save({'revoked': True, 'recording': False,
                               'use_memory': False, 'questions': False,
                               'startup_resume': False, 'paused': False},
                              revision=revision)
        return effective

    def exclusion_add(self, name, *, revision):
        name = str(name).strip().lower()
        if not name or len(name) > 128:
            raise ValueError('bounded exclusion name required')
        state = self.load()
        apps = list(state['excluded_apps'])
        if name not in apps:
            apps.append(name)
        return self.save({'excluded_apps': apps}, revision=revision)

    def exclusion_remove(self, name, *, revision):
        name = str(name).strip().lower()
        if name in DEFAULT_EXCLUSIONS:
            raise ValueError('own-process exclusions cannot be removed')
        state = self.load()
        apps = [item for item in state['excluded_apps'] if item != name]
        return self.save({'excluded_apps': apps}, revision=revision)

    # -- startup rebinding ----------------------------------------------------
    def startup_binding(self, resolver):
        """Fresh current-foreground binding, or None with a reason.

        ``resolver`` returns the live foreground identity (handle, process
        id, creation, image name); the stored permission never carries one.
        Excluded images and unavailable foregrounds fail closed.
        """
        state = self.load()
        if not self.effective(state)['startup_resume']:
            return None, 'startup resume not granted or not active'
        if not callable(resolver):
            raise ValueError('foreground resolver required')
        binding = resolver()
        if binding is None:
            return None, ('no usable foreground window (lock screen, '
                          'secure desktop or minimized target)')
        image = str(binding.get('image', '')).lower()
        if any(name in image for name in state['excluded_apps']):
            return None, f'foreground is an excluded application: {image}'
        return binding, None


def current_foreground():
    """Live foreground identity via user32; excludes our own process.

    Returns None when there is no usable foreground window. ``creation`` is
    the process creation identity the perception start path revalidates.
    """
    import ctypes
    if os.name != 'nt':
        return None
    user32 = ctypes.WinDLL('user32', use_last_error=True)
    handle = user32.GetForegroundWindow()
    if not handle:
        return None
    from extensions.desktop.windows_capture import _identity
    process_id = ctypes.c_ulong()
    user32.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p,
                                                ctypes.POINTER(ctypes.c_ulong)]
    user32.GetWindowThreadProcessId(ctypes.c_void_p(handle),
                                    ctypes.byref(process_id))
    try:
        _identity(handle, process_id.value)
    except RuntimeError:
        return None  # minimized, invisible, own process or capture host
    from sumika_next.runtime_ownership import process_identity
    image = _process_image(process_id.value)
    return {'handle': int(handle), 'process_id': process_id.value,
            'process_creation': process_identity(process_id.value),
            'image': image}


def _process_image(process_id):
    import ctypes
    from ctypes import wintypes
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    psapi = ctypes.WinDLL('psapi', use_last_error=True)
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION,
                                  False, process_id)
    if not handle:
        return 'unknown'
    try:
        buffer = ctypes.create_unicode_buffer(260)
        size = wintypes.DWORD(260)
        if psapi.GetModuleFileNameExW(handle, None, buffer, size):
            from pathlib import Path as _Path
            return _Path(buffer.value).name.lower()
        return 'unknown'
    finally:
        kernel32.CloseHandle(handle)
