"""Isolated real DSH lifecycle acceptance, without model calls or credentials."""
import json
import html
import re
from pathlib import Path
import sys
import tempfile
import urllib.error
import urllib.request
import urllib.parse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sumika_next.authorization import Authority
from sumika_next.contracts import WorkBinding, ToolRequest
from sumika_next.dsh import Dsh
from sumika_next.execution import Execution


def main():
    root = Path(__file__).resolve().parents[1]
    base = root / ".sumika-next"
    base.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="acceptance-", dir=base) as tmp:
        home = Path(tmp) / "home"
        workspace = Path(tmp) / "workspace"
        workspace.mkdir()
        adapter = Dsh(root, home)
        executor = None
        try:
            adapter.start()
            with adapter._opener.open(adapter.url, timeout=10) as response:
                document = response.read().decode('utf-8')
                assert 'text/html' in response.headers.get('Content-Type', '')
            assert '<html' in document.lower()
            scripts = re.findall(r'<script[^>]+src="([^"]+)"', document)
            assert scripts, 'Web UI has no script entry'
            for script in scripts:
                asset = urllib.parse.urljoin(adapter.url + '/', html.unescape(script))
                assert asset.startswith(adapter.url + '/'), 'unexpected external Web entry'
                with adapter._opener.open(asset, timeout=10) as response:
                    assert response.status == 200 and len(response.read()) > 100
            print('native Web document and script assets: passed')
            for path in ("/api/settings/describe", "/api/session/create"):
                request = urllib.request.Request(adapter.url + path, data=b'{"args":{}}', headers={"Content-Type":"application/json", "X-Approved":"true"})
                try:
                    urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=5)
                    raise AssertionError("unauthenticated request accepted")
                except urllib.error.HTTPError as error:
                    assert error.code in (401, 403), error.code
            authority = Authority(adapter.instance)
            cross_origin = urllib.request.Request(adapter.url + "/api/session/create",
                data=b'{}', headers={"Content-Type":"application/json", "Origin":"https://untrusted.invalid"})
            try:
                adapter._opener.open(cross_origin, timeout=5)
                raise AssertionError("cross-origin write accepted")
            except urllib.error.HTTPError as error:
                assert error.code == 403, error.code
            executor = Execution(adapter, authority, Path(tmp) / "steps.sqlite3")
            session = "sumika-p1-acceptance"
            binding = WorkBinding(adapter.instance.instance_id, "acceptance", 1, session, "create")
            authority.bind(binding)
            request = ToolRequest(binding, "session.create", str(workspace.resolve()), json.dumps({"sessionId":session, "cwd":str(workspace.resolve())}).encode())
            created = executor.dispatch(request, authority.approve(request))
            assert created["sessionId"] == session, created
            print("create response:", json.dumps(created))
            assert not adapter.inspect(binding).can_replay
            cancel = WorkBinding(adapter.instance.instance_id, "acceptance", 1, session, "cancel")
            authority.bind(cancel)
            request = ToolRequest(cancel, "session.cancel", session, json.dumps({"sessionId":session}).encode())
            result = executor.dispatch(request, authority.approve(request))
            assert result == {"accepted": True}, result
            print("cancel response:", json.dumps(result))
            print("managed identity, auth rejection, cross-origin rejection, create, history, idle cancel: passed; model calls: 0")
        finally:
            if executor:
                executor.close()
            adapter.close()


if __name__ == "__main__":
    main()
