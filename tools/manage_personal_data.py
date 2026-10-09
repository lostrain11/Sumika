"""Explicit offline personal-data migration and confirmed uninstall cleanup."""
import argparse
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sumika_next.paths import user_data_directory
from sumika_next.runtime_ownership import process_identity
from ui.data_lease import DataLease
from tools.backup_personal_data import backup, restore, rebind_role_paths, inventory


def location_file():
    return Path(os.environ['LOCALAPPDATA']) / 'Sumika-location.json'


def location_digest():
    path = location_file()
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def physical(path):
    path = Path(path).absolute()
    for part in (path, *path.parents):
        if part.is_symlink() or part.is_junction():
            raise ValueError('数据路径包含链接，需先处理后再操作')
    return path


def validate_target(source, destination):
    if not isinstance(destination, (str, Path)) or not str(destination).strip() or not Path(destination).is_absolute():
        raise ValueError('请输入新的绝对路径')
    source, destination = physical(source), physical(destination)
    if not source.is_dir() or destination.exists() or not destination.parent.is_dir():
        raise ValueError('目标必须是现有父目录下尚不存在的新目录')
    if destination.is_relative_to(source) or source.is_relative_to(destination):
        raise ValueError('新旧个人目录不能互相包含')
    if destination.is_relative_to(ROOT) or ROOT.is_relative_to(destination):
        raise ValueError('个人数据不能放在程序目录内')
    return source, destination


def migrate(source, destination, expected_location, snapshot=None):
    source, destination = validate_target(source, destination)
    control = location_file().parent / 'Sumika-location-state'
    lease = DataLease(control).acquire()
    try:
        if location_digest() != expected_location:
            raise ValueError('数据位置已改变；未覆盖其他迁移结果')
        snapshot_path = destination.parent / ('.Sumika-backup-' + uuid.uuid4().hex)
        if snapshot is None:
            backup(source, snapshot_path)
            original = source
        else:
            # Existing snapshot verification and restore reject forged or linked payloads.
            snapshot_path = physical(snapshot)
            from tools.backup_personal_data import verify_snapshot
            manifest = verify_snapshot(snapshot_path)
            original = Path(manifest['source'])
        restore(snapshot_path, destination)
        rebind_role_paths(destination, original)
        # Recheck the old writer after copying; refuse activating an out-of-date copy.
        with ExitStack() as stack:
            held = DataLease(source).acquire(); stack.callback(held.release)
            target_lease = DataLease(destination).acquire(); stack.callback(target_lease.release)
            if snapshot is None:
                manifest = json.loads((snapshot_path / 'snapshot.json').read_text(encoding='utf-8'))
                if inventory(source) != manifest['files']:
                    raise ValueError('复制期间原数据已变化；副本保留但未启用')
            if location_digest() != expected_location:
                raise ValueError('数据位置已改变；副本未启用')
            temp = location_file().with_name('Sumika-location-' + uuid.uuid4().hex + '.tmp')
            temp.write_text(json.dumps({'schema_version': 1, 'directory': str(destination)}, ensure_ascii=False), encoding='utf-8')
            os.replace(temp, location_file())
        return {'status': 'complete', 'directory': str(destination), 'snapshot': str(snapshot_path), 'source_retained': True}
    finally:
        lease.release()


# Only Sumika-owned entries are eligible. External weights and unknown files stay.
CLEAN_NAMES = {'role-model-settings.json', 'role-conversations.sqlite3', 'role-chat.db',
               'env.ps1', 'roles', 'schedules', 'backups', 'dsh-profiles', 'capabilities.sqlite3',
               'browser-authorizations.json', 'role-restore-state.json', 'usage.sqlite3',
               'memory.sqlite3', 'capabilities.db', 'logs', 'speech-input', 'speech-output'}


def cleanup(directory, confirmed=False):
    if not confirmed:
        raise ValueError('必须明确确认删除个人数据')
    root = physical(directory)
    if root != physical(user_data_directory()) or root == root.parent or root == location_file().parent:
        raise ValueError('只能清理当前已登记的 Sumika 个人目录')
    if not (root / 'role-model-settings.json').is_file():
        raise ValueError('缺少 Sumika 配置标识；未删除任何文件')
    from extensions.models.settings import load
    load(root / 'role-model-settings.json')
    with ExitStack() as stack:
        lease = DataLease(root).acquire(); stack.callback(lease.release)
        profiles = root / 'dsh-profiles'
        if profiles.exists():
            physical(profiles)
            for profile in profiles.iterdir():
                physical(profile)
                if profile.is_dir():
                    held = DataLease(profile, filename='sumika-instance.lock').acquire(); stack.callback(held.release)
                    record = profile / 'sumika-instance.json'
                    if record.exists() and json.loads(record.read_text(encoding='utf-8')):
                        raise ValueError('工作台归属未释放，个人数据已保留')
        selected = [p for p in root.iterdir() if p.name in CLEAN_NAMES or
                    any(p.name == name + suffix for name in CLEAN_NAMES for suffix in ('-wal', '-shm'))]
        # Plan everything first; never follow a directory junction into external models.
        files, directories = [], []
        for entry in selected:
            physical(entry)
            if entry.is_dir():
                for folder, dirs, names in os.walk(entry):
                    if Path(folder).name == 'profiles' and Path(folder).parent.parent == profiles:
                        dirs[:] = [name for name in dirs if name != 'node_modules']
                    for name in dirs + names:
                        physical(Path(folder) / name)
                    files.extend(Path(folder) / name for name in names if name != 'sumika-instance.lock')
                    directories.append(Path(folder))
            else:
                files.append(entry)
        for path in sorted(files, key=lambda p: p.name == 'role-model-settings.json'):
            path.unlink()
        # Locks remain open until completion; empty-directory pruning is deliberately omitted.
        remaining = [p.name for p in root.iterdir() if p.name not in CLEAN_NAMES and p.name != 'sumika-bridge.lock']
        return {'status': 'cleaned_known_personal_files', 'files': len(files), 'preserved_unknown': remaining}


def prepare(source, destination, port, snapshot=None):
    source, destination = validate_target(source, destination)
    if snapshot:
        from tools.backup_personal_data import verify_snapshot
        verify_snapshot(physical(snapshot))
    jobs = location_file().parent / 'Sumika-location-state'
    jobs.mkdir(parents=True, exist_ok=True)
    job = jobs / (uuid.uuid4().hex + '.json')
    data = dict(source=str(source), destination=str(destination), expected_location=location_digest(),
                parent_pid=os.getpid(), parent_creation=process_identity(os.getpid()), port=port,
                root=str(ROOT), snapshot=snapshot, state='waiting_for_exit')
    job.write_text(json.dumps(data), encoding='utf-8')
    subprocess.Popen([sys.executable, '-B', str(Path(__file__).resolve()), 'run', '--job', str(job)],
                     creationflags=subprocess.CREATE_NO_WINDOW, close_fds=True)
    return {'status': 'prepared', 'job': str(job), 'directory': str(destination)}


def run_job(job):
    data = json.loads(job.read_text(encoding='utf-8'))
    # An interrupted/unknown job is never automatically replayed.
    if data.get('state') != 'waiting_for_exit':
        raise ValueError('Migration job already attempted')
    try:
        deadline = time.monotonic() + 120
        while process_identity(data['parent_pid']) == data['parent_creation']:
            if time.monotonic() >= deadline:
                raise ValueError('原客户端尚未退出，迁移未执行')
            time.sleep(.25)
        data['state'] = 'copying'; job.write_text(json.dumps(data), encoding='utf-8')
        result = migrate(data['source'], data['destination'], data['expected_location'], data.get('snapshot'))
        data.update(state='complete', result=result)
        job.write_text(json.dumps(data), encoding='utf-8')
        env = dict(os.environ); env.pop('SUMIKA_DATA_DIR', None)
        subprocess.Popen(['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
                          str(Path(data['root']) / 'tools/start_sumika.ps1'), '-Port', str(data['port']), '-NoBrowser'],
                         env=env, creationflags=subprocess.CREATE_NO_WINDOW)
    except Exception as error:
        data.update(state='failed_no_automatic_retry', error=str(error))
        job.write_text(json.dumps(data), encoding='utf-8')
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['resolve', 'cleanup', 'run'])
    parser.add_argument('--directory', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--confirmed', action='store_true')
    parser.add_argument('--job', type=Path)
    args = parser.parse_args()
    if args.action == 'resolve':
        value = str(user_data_directory())
        if args.output: args.output.write_text(value, encoding='utf-8-sig')
        else: print(value)
    elif args.action == 'cleanup':
        print(json.dumps(cleanup(args.directory, args.confirmed)))
    else:
        run_job(args.job)


if __name__ == '__main__':
    main()
