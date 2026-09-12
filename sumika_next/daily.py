"""Daily native Web entry. DSH owns prompts, permissions and task execution."""
from pathlib import Path
import json
import uuid

from .authorization import Authority
from .contracts import ToolRequest, WorkBinding, Workspace
from .dsh import Dsh
from .execution import Execution


def default_home(root: Path):
    release = json.loads((root / 'runtime/dsh/release.json').read_text(encoding='utf-8'))
    version = release['version']
    if not isinstance(version, str) or not version or version in ('.', '..') or any(c not in '0123456789abcdefghijklmnopqrstuvwxyz.-' for c in version):
        raise ValueError('invalid release version for profile directory')
    return root / '.sumika-next/daily' / version


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


def run(root: Path, home: Path, workspace: Path | None, browser: bool = True):
    if workspace is not None:
        Workspace(workspace.resolve())  # Reject missing workspace before launch.
    adapter = Dsh(root, home)
    try:
        adapter.start()
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
        adapter.process.wait()
        if adapter.process.returncode:
            raise RuntimeError(f'DSH exited with code {adapter.process.returncode}')
    except KeyboardInterrupt:
        print('Stopping managed DSH; resume from native session history next time.', flush=True)
    finally:
        adapter.close()
