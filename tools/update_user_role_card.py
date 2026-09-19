"""Update a personal card in place, preserving resource bindings and a verified backup."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from extensions.roles.roles import import_card, load_role, verify_role, _refresh_checksums


def update(card, role_dir, backup_root):
    role_dir = Path(role_dir).resolve(strict=True)
    backup_root = Path(backup_root).resolve()
    if role_dir == backup_root or role_dir in backup_root.parents:
        raise ValueError('backup must be outside the role directory')
    old = load_role(role_dir)
    if old['verified']['status'] != 'ok':
        raise ValueError('existing role integrity must be verified before updating')
    before = {p.relative_to(role_dir).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in role_dir.rglob('*') if p.is_file()}
    backup_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='card-update-', dir=backup_root) as temp:
        staged = import_card(card, Path(temp)/'roles', old['id'])
        imported = json.loads((staged/'role.json').read_text(encoding='utf8'))
        manifest = json.loads((role_dir/'role.json').read_text(encoding='utf8'))
        for key in ('persona','worldbook','source_format'):
            manifest[key] = imported[key]
        # Stable role ID, user display name and all resource bindings survive.
        target_card = Path(old['assets']['card'])
        backup = backup_root / ('role-card-' + uuid.uuid4().hex)
        shutil.copytree(role_dir, backup)
        copied = {p.relative_to(backup).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in backup.rglob('*') if p.is_file()}
        if before != copied:
            raise RuntimeError('backup checksum mismatch; role untouched')
        paths = [target_card, role_dir/'role.json', role_dir/'checksums.json']
        try:
            card_temp = target_card.with_name(target_card.name + '.update-' + uuid.uuid4().hex)
            card_temp.write_bytes((staged/'card/original-card.json').read_bytes())
            os.replace(card_temp, target_card)
            manifest_temp = role_dir/'role.json.update'
            manifest_temp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+'\n', encoding='utf8')
            os.replace(manifest_temp, role_dir/'role.json')
            _refresh_checksums(role_dir)
            if verify_role(role_dir)['status'] != 'ok':
                raise RuntimeError('updated role verification failed')
        except BaseException:
            for path in paths:
                shutil.copy2(backup/path.relative_to(role_dir), path)
            raise
    after = load_role(role_dir)
    if after['assets'] != old['assets'] or after['id'] != old['id']:
        raise RuntimeError('resource binding changed')
    return {'id': old['id'], 'backup': str(backup), 'verified': after['verified'],
            'card_sha256': hashlib.sha256(target_card.read_bytes()).hexdigest(),
            'source_sha256': hashlib.sha256(Path(card).read_bytes()).hexdigest(),
            'resource_bindings_preserved': True}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--card', type=Path, required=True)
    parser.add_argument('--role-dir', type=Path, required=True)
    parser.add_argument('--backup-root', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(update(args.card, args.role_dir, args.backup_root), ensure_ascii=False))
