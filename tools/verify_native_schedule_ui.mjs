// Native upstream task manager with the packaged Sumika skin; synthetic tasks only.
import { loadPlaywright } from './lib/playwright.mjs';
import { writeFile } from 'node:fs/promises';
import path from 'node:path';

let input = '';
for await (const chunk of process.stdin) input += chunk;
const { url, output } = JSON.parse(input);
const { chromium } = loadPlaywright();
const browser = await chromium.launch({
  channel: 'msedge', headless: true,
});
const report = { passed: false, pageErrors: [], checks: {} };
const page = await browser.newPage({ viewport: { width: 1400, height: 980 } });
page.on('pageerror', error => report.pageErrors.push(error.message));
try {
  await page.goto(url, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(7000);
  if (await page.getByText('预览版说明', { exact: true }).isVisible().catch(() => false)) {
    await page.getByRole('button', { name: '继续', exact: true }).click();
  }
  for (const label of ['稍后配置', 'Later', 'Skip']) {
    const button = page.getByRole('button', { name: label, exact: true });
    if (await button.isVisible().catch(() => false)) { await button.click(); break; }
  }
  const onboarding = page.getByRole('dialog', { name: '开始使用', exact: true });
  if (await onboarding.isVisible().catch(() => false)) {
    await onboarding.getByRole('button', { name: '关闭', exact: true }).click();
  }
  const entry = page.getByRole('button', { name: '自动化任务', exact: true });
  await entry.click();
  await page.getByRole('heading', { name: '自动化任务', exact: true }).waitFor();
  await page.getByText('Synthetic daily', { exact: true }).waitFor();
  await page.getByText('Synthetic weekly', { exact: true }).waitFor();
  report.checks.existing_native_entry_and_tasks_visible = true;
  report.checks.sumika_skin_loaded = await page.evaluate(() => document.documentElement.dataset.sumikaSkin === '1');
  await page.screenshot({ path: path.join(output, 'native-schedule-manager.png'), fullPage: true });
  if (report.pageErrors.length) throw Error('native task manager page errors');
  if (!report.checks.sumika_skin_loaded) throw Error('packaged skin absent');
  report.passed = true;
} finally {
  if (!report.passed) {
    await writeFile(path.join(output, 'native-schedule-ui-failed.txt'), await page.locator('body').innerText());
    await page.screenshot({ path: path.join(output, 'native-schedule-ui-failed.png'), fullPage: true });
  }
  await writeFile(path.join(output, 'browser-report.json'), JSON.stringify(report, null, 2));
  await browser.close();
}
