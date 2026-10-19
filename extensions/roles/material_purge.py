"""Explicit offline erasure of selected role-message material and derived memory.

Reuses the existing two domain databases. A single SQLite attached transaction
is required; WAL/memory journals are rejected rather than claiming crash atomicity.
The CLI caller owns the personal-data lease for the whole operation.
"""
import hashlib
import json
from pathlib import Path

from extensions.memory.embedded_memory import EmbeddedMemory
from extensions.memory.repository import message_evidence, suppression_key
from extensions.models.settings import load
from extensions.roles.conversations import Conversations
from extensions.roles.relocation import require_settled
from extensions.roles.roles import load_role


def physical_file(path):
    path = Path(path)
    if not path.is_absolute():
        raise ValueError('absolute file path required')
    for part in (path, *path.parents):
        if part.is_symlink() or part.is_junction():
            raise ValueError('linked data path refused')
    path = path.resolve(strict=True)
    if not path.is_file():
        raise ValueError('existing file required')
    return path


def purge_material(settings_path, message_ids, *, confirmed=False, expected_plan=None):
    """Preview by default; execute only an exact reviewed plan while offline.

    Deletion is scoped to the configured active role/user/project and explicit
    journal message IDs. Old snapshots/exports and external task recipients are
    retained; this is application-data erasure, not forensic disk sanitization.
    """
    from ui.data_lease import DataLease
    settings_path = physical_file(settings_path)
    if type(confirmed) is not bool:
        raise ValueError('explicit boolean confirmation required')
    if (not isinstance(message_ids, list) or not 1 <= len(message_ids) <= 100
            or any(not isinstance(m, str) or not m.endswith(':user') or not m[:-5]
                   or len(m) > 133 for m in message_ids)
            or len(set(message_ids)) != len(message_ids)):
        raise ValueError('1-100 distinct persisted user message IDs required')
    if confirmed and (not isinstance(expected_plan, str) or len(expected_plan) != 64):
        raise ValueError('reviewed expected_plan digest required')
    lease = DataLease(settings_path.parent).acquire()
    memory = None
    try:
        require_settled(settings_path)
        recovery = settings_path.parent / 'role-restore-state.json'
        if recovery.exists():
            state = json.loads(recovery.read_text(encoding='utf8'))
            if (not isinstance(state, dict) or state.get('schema_version') != 1
                    or state.get('status') != 'complete'
                    or state.get('destination') != str(settings_path.parent)):
                raise ValueError('personal data recovery incomplete')
        settings_bytes = settings_path.read_bytes()
        config = load(settings_path)
        role_path = physical_file(Path(config['role']['role_dir']) / 'role.json')
        role_bytes = role_path.read_bytes()
        role = load_role(role_path.parent)
        if role['verified']['status'] == 'failed':
            raise ValueError('role verification failed')
        database = physical_file(config['role']['database'])
        journal_path = physical_file(settings_path.parent / 'role-conversations.sqlite3')
        if database.samefile(journal_path):
            raise ValueError('distinct memory and material databases required')
        conversations = Conversations(journal_path)
        chat_scope = conversations.scope_for(config['role']['user_id'], str(role_path.parent),
                                               config['role']['project_id'])
        # No semantic model initialization is needed for maintenance.
        memory = EmbeddedMemory(database)
        fields = dict(user_id=config['role']['user_id'], role_id=role['id'],
                      project_id=config['role']['project_id'])
        memory.db.execute('ATTACH DATABASE ? AS materials', (str(journal_path),))
        for schema in ('main', 'materials'):
            mode = memory.db.execute(f'PRAGMA {schema}.journal_mode').fetchone()[0]
            if mode not in ('delete', 'truncate', 'persist'):
                raise ValueError('offline atomic erasure requires rollback journals; no data erased')
            memory.db.execute(f'PRAGMA {schema}.synchronous=FULL')
            memory.db.execute(f'PRAGMA {schema}.secure_delete=ON')
        with memory.db:
            memory.db.execute('BEGIN IMMEDIATE')
            turn_ids = [m[:-5] for m in message_ids]
            preview = Conversations._purge_rows(memory.db, chat_scope, turn_ids, schema='materials')
            refs = [ref for message in message_ids for ref in message_evidence(message)]
            keys = {suppression_key(ref) for ref in refs}
            affected = lambda refs: any(suppression_key(ref) in keys for ref in refs)
            derived_preview = dict(memory_records=0, proposals=0)
            for raw, in memory.db.execute('SELECT evidence_refs FROM memories WHERE scope=?',
                                          (memory.scope_key(**fields),)):
                derived_preview['memory_records'] += affected(json.loads(raw))
            for raw, in memory.db.execute('SELECT data FROM memory_proposals WHERE scope=?',
                                          (memory.scope_key(**fields),)):
                derived_preview['proposals'] += affected(json.loads(raw).get('evidence_refs', []))
            config_digest = hashlib.sha256(settings_bytes + b'\0' + role_bytes).hexdigest()
            plan = dict(configuration=config_digest, messages=sorted(message_ids),
                        memory_revision=memory.scope_revision(**fields), materials=preview)
            digest = hashlib.sha256(json.dumps(plan, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
            result = dict(status='preview', plan_digest=digest, message_ids=sorted(message_ids),
                          materials=preview, derived=derived_preview,
                          backups_deleted=False, external_copies_deleted=False,
                          disk_sanitized=False, daily_settings_changed=False)
            if not confirmed:
                return result
            if digest != expected_plan:
                raise ValueError('purge plan changed; preview again before confirmation')
            if settings_path.read_bytes() != settings_bytes or role_path.read_bytes() != role_bytes:
                raise ValueError('configuration changed; no data erased')
            # Validation permits 32 refs per call. Every chunk shares this transaction.
            counts = dict(memory_records=0, proposals=0)
            for start in range(0, len(refs), 32):
                removed = memory._purge_evidence_in_transaction(refs[start:start+32], **fields)
                for key in counts:
                    counts[key] += removed[key]
            Conversations._purge_rows(memory.db, chat_scope, turn_ids, schema='materials', erase=True)
            result.update(status='erased_current_databases', derived=counts)
        # Reclaim current database pages after atomic deletion. A failure here
        # must not disguise a committed deletion as a retryable pre-commit failure.
        result['compaction'] = {}
        for schema in ('main', 'materials'):
            try:
                memory.db.execute(f'VACUUM {schema}')
                result['compaction'][schema] = 'complete'
            except Exception:
                result['compaction'][schema] = 'pending_no_automatic_retry'
        return result
    finally:
        if memory is not None:
            memory.close()
        lease.release()
