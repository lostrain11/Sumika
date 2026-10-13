"""Behavior root locator: one pointer, one owner, one lease (P09 §3.2).

The personal data root holds exactly one locator file naming the ACTIVE
behavior root. The default root is the personal directory's own ``behavior``
child; an explicit selection must be a new, physical, dedicated directory —
never a link, never a reused non-empty directory, never inside the product
source tree, never nested inside (or containing) the current root. Only the
library's own files live there; unrelated data is never touched.
"""
import json
import secrets
import time
from pathlib import Path

LOCATOR_NAME = 'behavior-locator.json'
OWNER_NAME = 'behavior-root.json'
_LEASE_NAME = 'behavior-root.lock'


def _physical(path):
    path = Path(path)
    if path.is_symlink() or path.is_junction():
        raise ValueError('behavior roots must be physical directories')
    return path


def _product_source_roots():
    import sys
    root = Path(__file__).resolve().parents[2]
    roots = {root.resolve()}
    frozen = getattr(sys, 'frozen', False)
    if frozen:
        roots.add(Path(sys.executable).resolve().parent)
    return roots


class BehaviorLocator:
    """Resolve and switch the active behavior root; atomic, journalled."""

    def __init__(self, personal_root, *, clock=time.time):
        self.personal_root = Path(personal_root).absolute()
        self._clock = clock

    @property
    def locator_path(self):
        return self.personal_root/LOCATOR_NAME

    def resolve(self):
        """The active behavior root (default: personal ``behavior`` child)."""
        locator = self.locator_path
        if not locator.is_file():
            return self.personal_root/'behavior'
        if locator.is_symlink() or locator.is_junction():
            raise ValueError('behavior locator must be a physical file')
        state = json.loads(locator.read_text(encoding='utf8'))
        if (not isinstance(state, dict) or state.get('schema_version') != 1
                or not isinstance(state.get('root'), str)
                or not isinstance(state.get('owner_id'), str)):
            raise ValueError('invalid behavior locator')
        return Path(state['root'])

    def owner_id(self):
        locator = self.locator_path
        if not locator.is_file():
            return None
        return json.loads(locator.read_text(encoding='utf8')).get('owner_id')

    def _validate_destination(self, destination, current):
        destination = _physical(Path(destination).absolute())
        if destination.exists():
            own = {OWNER_NAME, 'behavior.sqlite3', 'behavior.sqlite3-wal',
                   'behavior.sqlite3-shm', 'behavior-root.lock'}
            children = {entry.name for entry in destination.iterdir()}
            if children - own:
                raise ValueError('behavior root must be a new dedicated '
                                 'directory (only its own files may exist)')
        parent = destination.parent
        while parent != parent.parent:
            if parent.is_symlink() or parent.is_junction():
                raise ValueError('behavior root must not live under a link')
            parent = parent.parent
        resolved = destination.resolve()
        for source_root in _product_source_roots():
            if resolved.is_relative_to(source_root):
                raise ValueError('behavior root must stay outside the '
                                 'product source tree')
        if current is not None:
            current = _physical(Path(current).absolute()).resolve()
            if resolved == current:
                raise ValueError('destination is the active behavior root')
            if resolved.is_relative_to(current) or current.is_relative_to(resolved):
                raise ValueError('behavior roots must not nest')
        return destination

    def select(self, destination, *, confirmed=False, current=None):
        """Validate a new dedicated root, mark ownership, switch atomically.

        ``current`` overrides the auto-resolved active root for callers that
        own the transition (the library's migration passes its live root).
        """
        if confirmed is not True:
            raise ValueError('root selection requires explicit confirmation')
        if current is None and self.locator_path.is_file():
            current = self.resolve()
        if current is not None and _physical(Path(destination).absolute()).resolve()                 == Path(current).resolve():
            # Re-selecting the active root is an idempotent no-op.
            marker = Path(current)/OWNER_NAME
            return {'status': 'selected', 'root': str(Path(current).resolve()),
                    'owner_id': json.loads(
                        marker.read_text(encoding='utf8'))['owner_id']}
        destination = self._validate_destination(destination, current)
        destination.mkdir(parents=True, exist_ok=True)
        marker = destination/OWNER_NAME
        if marker.exists():
            state = json.loads(marker.read_text(encoding='utf8'))
            if state.get('owner_id') != (self.owner_id() or state.get('owner_id')):
                raise ValueError('destination carries a different behavior owner')
        else:
            owner_id = self.owner_id() or secrets.token_hex(16)
            marker.write_text(json.dumps(
                {'schema_version': 1, 'owner_id': owner_id,
                 'created_at': _utc(self._clock)}, ensure_ascii=False),
                encoding='utf8')
        owner_id = json.loads(marker.read_text(encoding='utf8'))['owner_id']
        locator = self.locator_path
        temporary = locator.with_suffix('.tmp')
        temporary.write_text(json.dumps(
            {'schema_version': 1, 'root': str(destination.resolve()),
             'owner_id': owner_id, 'updated_at': _utc(self._clock)},
            ensure_ascii=False, indent=1), encoding='utf8')
        temporary.replace(locator)
        return {'status': 'selected', 'root': str(destination.resolve()),
                'owner_id': owner_id}

    def lease(self, root=None):
        from ui.data_lease import DataLease
        return DataLease(root if root is not None else self.resolve(),
                         filename=_LEASE_NAME)


def _utc(clock):
    from datetime import datetime, timezone
    return datetime.fromtimestamp(clock(), tz=timezone.utc).isoformat()
