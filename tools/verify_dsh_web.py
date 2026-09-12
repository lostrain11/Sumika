"""Native browser acceptance with a local model; never reads cloud credentials."""
import json
from pathlib import Path
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests_next'))
from p2_fixture import ModelFixture
from sumika_next.daily import create_workspace_session
from sumika_next.dsh import Dsh
from playwright.sync_api import sync_playwright, expect


def main():
    base = ROOT / '.sumika-next' / ('p3-web-' + uuid.uuid4().hex)
    home, work = base/'home', base/'browser-project'
    home.mkdir(parents=True); work.mkdir()
    subprocess.run(['git', 'init', '-q', str(work)], check=True)
    report = {'complete': False, 'external_model_calls': 0}
    errors = []
    with ModelFixture() as model:
        (home/'.env').write_text('DEEPSEEK_API_KEY=p2-local-fixture-not-a-secret\n', encoding='utf-8')
        (home/'cordis.patch.yml').write_text(json.dumps([
            {'id': 'session-title-llm', 'disabled': True},
            {'id': 'llm-deepseek', 'config': {'baseURL': model.url}},
            {'id': 'session-telemetry-otel', 'disabled': True},
        ]), encoding='utf-8')
        adapter = Dsh(ROOT, home)
        try:
            adapter.start()
            session = create_workspace_session(adapter, work, base/'launch.sqlite3')
            with sync_playwright() as pw:
                browser = pw.chromium.launch(channel='msedge', headless=True)
                try:
                    page = browser.new_page(viewport={'width': 1440, 'height': 1000})
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    page.goto(adapter._browser_url, wait_until='networkidle')
                    expect(page.get_by_role('button', name='继续', exact=True)).to_be_visible(timeout=20000)
                    page.get_by_role('button', name='继续', exact=True).click()
                    expect(page.get_by_role('dialog', name='内测声明')).not_to_be_visible(timeout=15000)
                    print('WEB_INITIAL', page.locator('body').inner_text(), flush=True)
                    expect(page.get_by_role('button', name='选择工作区', exact=True)).to_contain_text('browser-project', timeout=15000)
                    print('WEB_PROJECT', page.locator('body').inner_text(), flush=True)
                    box = page.locator('[contenteditable=true]').last
                    expect(box).to_be_visible(timeout=15000)
                    box.fill('P3_BROWSER_NATIVE_INPUT')
                    page.get_by_role('button', name='发送消息', exact=True).click()
                    expect(page.get_by_text('P2_FIXTURE_DONE', exact=True).last).to_be_visible(timeout=60000)
                    page.screenshot(path=str(base/'native-web.png'))
                    assert any('P3_BROWSER_NATIVE_INPUT' in json.dumps(r) for r in model.requests)
                    assert not errors, errors
                    report.update(complete=True, workspace_registration=True, native_browser_prompt=True,
                                  native_browser_result=True, javascript_errors=errors, session_created=session)
                finally:
                    browser.close()
        finally:
            adapter.close()
            (base/'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
            print('WEB_ARTIFACT', base, report, flush=True)


if __name__ == '__main__':
    main()
