"""Create a verified offline directory snapshot; never activate or overwrite data.

Snapshots are private and may contain credentials. External model/role paths
are not copied. This is a filesystem snapshot, not a runnable relocation.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ui.data_lease import DataLease


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def prune_generated_dependencies(root, directory, dirs):
    relative = Path(directory).relative_to(root).parts
    if len(relative) == 3 and relative[0] == 'dsh-profiles' and relative[2] == 'profiles':
        # DSH rehydrates this dependency mount from the selected runtime.
        dirs[:] = [name for name in dirs if name != 'node_modules']


def inventory(root):
    root = Path(root)
    if root.is_symlink() or root.is_junction() or not root.is_dir():
        raise ValueError('inventory root must be a physical directory')
    files = {}
    for directory, dirs, names in os.walk(root, followlinks=False):
        prune_generated_dependencies(root, directory, dirs)
        for name in dirs + names:
            path = Path(directory)/name
            if path.is_symlink() or path.is_junction():
                raise ValueError('linked personal data requires explicit separate backup')
        for name in names:
            path = Path(directory)/name
            relative = path.relative_to(root).as_posix()
            if name == 'sumika-instance.json':
                if json.loads(path.read_text(encoding='utf8')) != {}:
                    raise ValueError('DSH ownership is not released; stop and reconcile the profile first')
            if name in ('sumika-bridge.lock', 'sumika-instance.lock'):
                continue
            files[relative] = {'size': path.stat().st_size, 'sha256': digest(path)}
    return files


def backup(source, destination):
    source = Path(source).absolute()
    destination = Path(destination).absolute()
    if source.is_symlink() or source.is_junction() or not source.is_dir():
        raise ValueError('source must be a physical data directory')
    source = source.resolve()
    if destination.exists() or destination.resolve().is_relative_to(source):
        raise ValueError('choose a new destination outside the source data')
    lease = DataLease(source).acquire()
    profile_leases = []
    try:
        # Independent CLI workbench processes do not hold the bridge lock.
        # Honor their existing byte-range lock without changing ownership records.
        for directory, dirs, names in os.walk(source, followlinks=False):
            prune_generated_dependencies(source, directory, dirs)
            for name in dirs:
                path = Path(directory)/name
                if path.is_symlink() or path.is_junction():
                    raise ValueError('linked personal data requires explicit separate backup')
            if 'sumika-instance.lock' in names or 'sumika-instance.json' in names:
                profile_leases.append(DataLease(directory, filename='sumika-instance.lock').acquire())
        before = inventory(source)
        destination.mkdir(parents=True, exist_ok=False)
        payload = destination/'data'
        payload.mkdir()
        for relative in before:
            target = payload/relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source/relative, target)
        copied = inventory(payload)
        after = inventory(source)
        if before != copied or before != after:
            raise ValueError('source changed or snapshot failed verification; incomplete destination retained')
        manifest = {'schema_version': 1, 'kind': 'sumika-private-offline-snapshot',
                    'status': 'verified', 'source': str(source), 'files': copied,
                    'excluded_generated_paths': ['dsh-profiles/*/profiles/node_modules'],
                    'boundary': 'Private data may contain credentials. External paths not copied; restore/rebinding not verified.'}
        with (destination/'snapshot.json').open('x', encoding='utf8') as output:
            json.dump(manifest, output, ensure_ascii=False, indent=2)
        return {'status': 'verified', 'files': len(copied), 'snapshot': str(destination)}
    finally:
        for profile_lease in reversed(profile_leases):
            profile_lease.release()
        lease.release()


def verify_snapshot(snapshot):
    """Return a verified manifest without creating files or acquiring locks."""
    snapshot = Path(snapshot).absolute()
    if snapshot.is_symlink() or snapshot.is_junction() or not snapshot.is_dir():
        raise ValueError('snapshot must be a physical directory')
    manifest_path = snapshot/'snapshot.json'
    if manifest_path.is_symlink() or manifest_path.is_junction():
        raise ValueError('linked snapshot manifest refused')
    manifest = json.loads(manifest_path.read_text(encoding='utf8'))
    if (not isinstance(manifest, dict) or type(manifest.get('schema_version')) is not int or manifest.get('schema_version') != 1
            or manifest.get('kind') != 'sumika-private-offline-snapshot'
            or manifest.get('status') != 'verified' or not isinstance(manifest.get('files'), dict)):
        raise ValueError('invalid snapshot manifest')
    payload = snapshot/'data'
    before = inventory(payload)
    if before != manifest['files']:
        raise ValueError('snapshot integrity mismatch')
    return manifest


def restore(snapshot, destination):
    """Verify and restore bytes into a new directory, without activating it."""
    snapshot = Path(snapshot).absolute()
    destination = Path(destination).absolute()
    manifest = verify_snapshot(snapshot)
    payload = snapshot/'data'
    before = manifest['files']
    if destination.exists() or destination.resolve().is_relative_to(snapshot.resolve()):
        raise ValueError('restore requires a new directory outside snapshot')
    destination.mkdir(parents=True, exist_ok=False)
    for relative in before:
        target = destination/relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(payload/relative, target)
    if inventory(destination) != before or inventory(payload) != before:
        raise ValueError('restore verification failed; incomplete destination retained')
    return {'status': 'bytes_restored', 'files': len(before), 'destination': str(destination),
            'boundary': 'Not activated. Absolute path bindings and external dependencies require reconciliation before use.'}


def rebind_role_paths(destination, original_root):
    """Resume a durable role-only rebind plan, never rewrite conversation content."""
    from extensions.models.settings import load, save
    from extensions.roles.conversations import Conversations
    from extensions.roles.relocation import require_settled
    destination, original_root = Path(destination).resolve(), Path(original_root).resolve()
    if destination == original_root:
        raise ValueError('rebind requires a separate restored copy')
    lease = DataLease(destination).acquire()
    try:
        settings = destination/'role-model-settings.json'
        journal = destination/'role-restore-state.json'
        require_settled(settings)

        def write_state(state):
            temporary = journal.with_suffix('.tmp')
            with temporary.open('w', encoding='utf8') as out:
                json.dump(state, out, ensure_ascii=False, indent=2)
                out.flush()
                os.fsync(out.fileno())
            os.replace(temporary, journal)

        def relocated(value):
            path = Path(value)
            if path.is_absolute() and path.resolve().is_relative_to(original_root):
                return str(destination/path.resolve().relative_to(original_root))
            return value

        inherited = False
        if journal.exists():
            state = json.loads(journal.read_text(encoding='utf8'))
            # A completed recovery can itself be backed up and relocated. Its
            # journal describes the previous destination, not this new copy.
            inherited = (isinstance(state, dict) and state.get('schema_version') == 1
                         and state.get('status') == 'complete'
                         and state.get('destination') == str(original_root))
            if inherited:
                history = destination/'role-restore-history'
                history.mkdir(exist_ok=True)
                raw = journal.read_bytes()
                archived = history/(hashlib.sha256(raw).hexdigest()+'.json')
                if archived.exists():
                    if archived.read_bytes() != raw:
                        raise ValueError('restore history integrity mismatch')
                else:
                    with archived.open('xb') as out:
                        out.write(raw)
                        out.flush()
                        os.fsync(out.fileno())
        if journal.exists() and not inherited:
            if (not isinstance(state, dict) or state.get('schema_version') != 1 or state.get('destination') != str(destination)
                    or state.get('source') != str(original_root)
                    or state.get('status') not in ('pending', 'complete')):
                raise ValueError('restore journal identity mismatch')
            current = load(settings)
            if current not in (state['original_config'], state['target_config']):
                raise ValueError('settings changed during restore; manual reconciliation required')
        else:
            config = load(settings)
            target = json.loads(json.dumps(config))
            fields = []
            for field in ('role_dir', 'database'):
                value = relocated(config['role'][field])
                if value != config['role'][field]:
                    target['role'][field] = value
                    fields.append('role.'+field)
            store = Conversations(destination/'role-conversations.sqlite3')
            with store.connect() as db:
                bindings = db.execute('SELECT owner,project,location,scope FROM role_scope_bindings WHERE retired=0').fetchall()
            role = config['role']
            old = role['role_dir']
            if relocated(old) != old and not any(row[0] == role['user_id'] and row[1] == role['project_id']
                                                and row[2] == str(Path(old).resolve()) for row in bindings):
                # Record deterministic legacy adoption before it is performed.
                scope = json.dumps([role['user_id'], str(Path(old).resolve()), role['project_id']], ensure_ascii=False)
                bindings.append((role['user_id'], role['project_id'], old, scope))
            moves = [dict(owner=o, project=p, source=old, target=relocated(old), scope=scope)
                     for o,p,old,scope in bindings if relocated(old) != old]
            for move in moves:
                if not Path(move['target']).is_dir():
                    raise ValueError('restored role resource missing')
            state = dict(schema_version=1, status='pending', source=str(original_root),
                         destination=str(destination), original_config=config,
                         target_config=target, moves=moves, fields=fields)
            write_state(state)
        if state['status'] != 'complete':
            store = Conversations(destination/'role-conversations.sqlite3')
            for move in state['moves']:
                with store.connect() as db:
                    old = db.execute('SELECT scope FROM role_scope_bindings WHERE owner=? AND project=? AND location=?',
                                     (move['owner'], move['project'], str(Path(move['source']).resolve()))).fetchone()
                if old is None:
                    scope = store.scope_for(move['owner'], move['source'], move['project'])
                    if scope != move['scope']:
                        raise ValueError('legacy identity differs from recovery plan')
                store.relocate_scope(move['owner'], move['project'], move['source'], move['target'],
                                     expected_scope=move['scope'])
            save(state['target_config'], settings)
            state['status'] = 'complete'
            write_state(state)
        return {'status': 'role_paths_rebound', 'changes': state['fields'],
                'boundary': 'Role-only recovery complete; external resources and DSH/capability paths still require review. No activation or replay.'}
    finally:
        lease.release()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--restore', action='store_true', help='Source is a verified snapshot; restore to a new directory without activation')
    parser.add_argument('--rebind-role-paths', action='store_true', help='After restore, rebind internal role paths and stable conversation scopes only')
    parser.add_argument('--resume-role-rebind', action='store_true', help='Resume role rebinding of an existing restored destination; source is its snapshot')
    parser.add_argument('--inspect', action='store_true', help='Read-only snapshot and role dependency preflight; no destination or activation')
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--destination', type=Path)
    args = parser.parse_args()
    if args.inspect:
        if args.restore or args.rebind_role_paths or args.resume_role_rebind or args.destination is not None:
            parser.error('--inspect cannot be combined with restore, rebind or destination')
        if __package__:
            from .restore_preflight import inspect_snapshot
        else:
            from restore_preflight import inspect_snapshot
        try:
            result = inspect_snapshot(args.source)
        except (OSError, ValueError):
            print(json.dumps({'status': 'unknown', 'integrity': 'unverified', 'issues': ['snapshot_verification_failed']}))
            raise SystemExit(2)
        print(json.dumps(result))
        return
    if args.destination is None:
        parser.error('--destination is required unless --inspect is used')
    if args.resume_role_rebind:
        if args.restore or args.rebind_role_paths:
            parser.error('--resume-role-rebind cannot be combined with restore flags')
        manifest = json.loads((args.source/'snapshot.json').read_text(encoding='utf8'))
        if not (args.destination/'role-restore-state.json').is_file():
            parser.error('no existing role restore journal')
        print(json.dumps(rebind_role_paths(args.destination, manifest['source'])))
        return
    if args.rebind_role_paths and not args.restore:
        parser.error('--rebind-role-paths requires --restore')
    action = restore if args.restore else backup
    result = action(args.source, args.destination)
    if args.rebind_role_paths:
        manifest = json.loads((args.source/'snapshot.json').read_text(encoding='utf8'))
        result['rebind'] = rebind_role_paths(args.destination, manifest['source'])
    print(json.dumps(result))


if __name__ == '__main__':
    main()
