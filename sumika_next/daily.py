"""Daily native Web entry. DSH owns prompts, permissions and task execution."""
from pathlib import Path
import json
import uuid
import subprocess

from .authorization import Authority
from .contracts import ToolRequest, WorkBinding, Workspace
from .dsh import Dsh
from .execution import Execution
from .runtime_ownership import ProfileLease
from .paths import data_override


def default_home(root: Path):
    release = json.loads((root / 'runtime/dsh/release.json').read_text(encoding='utf-8'))
    version = release['version']
    if not isinstance(version, str) or not version or version in ('.', '..') or any(c not in '0123456789abcdefghijklmnopqrstuvwxyz.-' for c in version):
        raise ValueError('invalid release version for profile directory')
    personal = data_override()
    return personal / 'dsh-profiles' / version if personal is not None else root / '.sumika-next/daily' / version


def create_workspace_session(adapter, workspace: Path, database: Path):
    workspace = Workspace(workspace.resolve()).path
    session_id = 'sumika-' + uuid.uuid4().hex
    authority = Authority(adapter.instance)
    execution = Execution(adapter, authority, database)
    try:
        # Explicit CLI --workspace requests registration plus one native session.
        binding = WorkBinding(adapter.instance.instance_id, session_id, 1, session_id, 'workspace')
        authority.bind(binding)
        request = ToolRequest(binding, 'workspace.create', str(workspace), json.dumps({'path': str(workspace)}).encode())
        registered = execution.dispatch(request, authority.approve(request))
        binding = WorkBinding(adapter.instance.instance_id, session_id, 1, session_id, 'create')
        authority.bind(binding)
        request = ToolRequest(binding, 'session.create', str(workspace),
                              json.dumps({'sessionId': session_id,
                                          'workspaceId': registered['workspace']['workspaceId']}).encode())
        return execution.dispatch(request, authority.approve(request))['sessionId']
    finally:
        execution.close()


def run(root: Path, home: Path, workspace: Path | None, browser: bool = True,
        extensions_config: Path | None = None, port: int = 0):
    if workspace is not None:
        Workspace(workspace.resolve())  # Reject missing workspace before launch.
    lease = ProfileLease(home).acquire()
    adapter = None
    host=None
    try:
        adapter = Dsh(root, home)
        adapter.start(port=port)
        lease.bind(adapter.process)
        if extensions_config is not None:
            from .extension_host import ExtensionHost
            host=ExtensionHost(adapter,extensions_config)
        if workspace is not None:
            session_id = create_workspace_session(adapter, workspace, home / 'sumika-launch.sqlite3')
            print('Workspace session:', session_id, flush=True)
        print('DSH Web:', adapter.url, flush=True)
        print('Profile:', home.resolve(), flush=True)
        print('Select the model in native Web. Ctrl+C stops this instance; history stays in the profile.', flush=True)
        if browser:
            adapter.open_browser()
        else:
            print('Browser disabled; the clean URL requires an existing authenticated browser cookie.', flush=True)
        if host is None:
            adapter.process.wait()
        else:
            while adapter.process.poll() is None:
                host.tick()
                try:adapter.process.wait(timeout=.2)
                except subprocess.TimeoutExpired:pass
        if adapter.process.returncode:
            raise RuntimeError(f'DSH exited with code {adapter.process.returncode}')
    except KeyboardInterrupt:
        print('Stopping managed DSH; resume from native session history next time.', flush=True)
    finally:
        try:
            if host:host.close()
        finally:
            if adapter is None:
                lease.release()
            else:
                # Keep the original handle: close() may clear adapter.process.
                process = adapter.process
                adapter.close()
                if process is not None and process.poll() is None:
                    raise RuntimeError('process exit not confirmed; profile remains fenced')
                lease.release()
