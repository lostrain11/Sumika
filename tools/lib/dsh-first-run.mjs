// Shared DSH first-run fixture for isolated Playwright profiles.
//
// A fresh browser context gets DSH's own first-configuration modal, whose
// overlay blocks pointer events and makes later clicks time out. The fixture
// dismisses it through the modal's OWN product button (稍后配置/Later/Skip):
// native UI is never hidden or patched away to satisfy an assertion, and the
// DSH native plugin entries stay visible for the caller to assert on.
export async function dismissFirstRunDialog(frame, page, {timeout = 8000} = {}) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    for (const label of ['稍后配置', 'Later', 'Skip']) {
      const button = frame.getByRole('button', {name: label});
      if (await button.count().catch(() => 0)) {
        await button.first().click().catch(() => {});
        await page.waitForTimeout(800);
        return true;
      }
    }
    await page.waitForTimeout(300);
  }
  return false;
}
