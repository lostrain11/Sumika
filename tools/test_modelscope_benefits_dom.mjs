import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test, { after, afterEach, before } from 'node:test';
import { chromium } from '../frontend/node_modules/playwright-core/index.mjs';

const source = readFileSync(new URL('../backend/src/sumika_core/integrations/modelscope_benefits.py', import.meta.url), 'utf8');
const guard = source.match(/_PAGE_GUARD = r"""([\s\S]*?)"""/)[1];
const expressions = Object.fromEntries(['READ_EXPRESSION', 'SELECT_RECORDS_EXPRESSION'].map(name => {
  const body = source.match(new RegExp(`${name} = [^\\n]+r"""([\\s\\S]*?)"""`))[1];
  return [name, `JSON.stringify((() => {\n${guard}${body}`];
}));
const grantTitle = '注册并登录';
const bindingTitle = '绑定阿里云账号';
const recordsLabel = '发放记录';
const usageLabel = '消耗统计';
const grantText = '2026-09-08获得，有效期1天\n200';
const escape = value => String(value).replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;');
let browser;
let context;
before(async () => {
  browser = await chromium.launch({ headless: true });
  context = await browser.newContext({ serviceWorkers: 'block' });
  await context.route('**/*', route => route.abort());
});
afterEach(async () => { await Promise.all(context.pages().map(page => page.close())); });
after(async () => { await browser?.close(); });

async function fixture(options = {}) {
  const page = await context.newPage();
  const selected = options.selected ?? recordsLabel;
  const plain = options.plain ?? false;
  const hash = options.hash ?? 'changed-fixture';
  const controlTag = plain ? 'div' : 'button';
  const tabs = (options.tabs ?? [usageLabel, recordsLabel]).map(label => {
    const attributes = plain ? '' : `type="button" role="${options.role ?? 'tab'}" aria-selected="${label === selected}" aria-controls="${label === recordsLabel ? 'records-panel' : 'usage-panel'}"`;
    return `<${controlTag} class="acss-${hash}" data-fixture-tab ${attributes}><span>${escape(label)}</span></${controlTag}>`;
  }).join('');
  const rows = (options.rows ?? [{ title: grantTitle, detail: grantText }]).map(row =>
    `<div class="acss-${hash}-card" ${row.hidden ? 'hidden' : ''} data-fixture-card><div class="acss-${hash}-title"><span>${escape(row.title)}</span></div>` +
    `<div class="acss-${hash}-detail" data-fixture-detail>${row.detail.split('\n').map(line => `<div>${escape(line)}</div>`).join('')}</div></div>`).join('');
  const balances = (options.balances ?? ['242']).map(balance => `<button aria-label="Magic Cube">${escape(balance)}</button>`).join('');
  const controls = (options.controls ?? []).map(label => `<button>${escape(label)}</button>`).join('');
  const html = `<!doctype html><html><head><meta charset="utf-8"></head><body>${balances}${controls}` +
    `${options.login ? '<input type="password">' : ''}${options.challenge ? '<div class="captcha">private-captcha</div>' : ''}` +
    `<section data-fixture-workspace><div ${plain ? '' : 'role="tablist"'}>${tabs}</div>` +
    `<div id="records-panel" role="tabpanel" ${selected !== recordsLabel ? 'hidden' : ''}>${rows}</div>` +
    `<div id="usage-panel" role="tabpanel" ${selected === recordsLabel ? 'hidden' : ''}>private-consumption-details</div></section>` +
    `${options.extraHtml ?? ''}</body></html>`;
  const url = options.url ?? 'https://modelscope.cn/magicube/usage';
  if (url.startsWith('about:blank')) {
    await page.goto(url);
    await page.setContent(html);
  } else {
    await page.route('**/*', route => route.request().isNavigationRequest() && route.request().frame() === page.mainFrame()
      ? route.fulfill({ contentType: 'text/html', body: html }) : route.abort());
    await page.goto(url);
  }
  await page.evaluate(({ readyState, plain }) => {
    window.fixtureClicks = [];
    if (readyState) Object.defineProperty(document, 'readyState', { get: () => readyState });
    for (const tab of document.querySelectorAll('[data-fixture-tab]')) tab.addEventListener('click', () => {
      window.fixtureClicks.push(tab.textContent);
      const records = tab.textContent === '发放记录';
      for (const peer of document.querySelectorAll('[data-fixture-tab]')) if (!plain) peer.setAttribute('aria-selected', String(peer === tab));
      document.getElementById('records-panel').hidden = !records;
      document.getElementById('usage-panel').hidden = records;
    });
    for (const control of document.querySelectorAll('button:not([data-fixture-tab]), a')) control.addEventListener('click', () => window.fixtureClicks.push('forbidden-control'));
  }, { readyState: options.readyState, plain });
  return {
    page,
    run: async (name = 'READ_EXPRESSION') => JSON.parse(await page.evaluate(expressions[name])),
    clicks: () => page.evaluate(() => window.fixtureClicks),
  };
}

test('semantic tabs project exact known rows without depending on CSS hashes', async () => {
  for (const hash of ['new-layout', 'another-build', '']) {
    const view = await fixture({ hash, rows: [{ title: grantTitle, detail: grantText }, { title: bindingTitle, detail: grantText.replace('\n200', '\n50') }] });
    const result = await view.run();
    assert.equal(result.state, 'verified');
    assert.equal(result.available_balance, 242);
    assert.deepEqual(result.grants.map(grant => grant.kind), ['daily-login', 'aliyun-binding']);
    assert.equal(result.grants[0].expires_at, null);
    assert.equal(JSON.stringify(result).includes(grantTitle), false);
    assert.equal(JSON.stringify(result).includes('private'), false);
    assert.deepEqual(await view.clicks(), []);
  }
});

test('known two-sibling div layout selects only records and verifies visible rows', async () => {
  const view = await fixture({ plain: true, selected: usageLabel });
  assert.equal((await view.run()).state, 'select-records');
  assert.equal((await view.run('SELECT_RECORDS_EXPRESSION')).reason, 'records-selected');
  assert.equal((await view.run()).state, 'verified');
  await view.run('SELECT_RECORDS_EXPRESSION');
  assert.deepEqual(await view.clicks(), [recordsLabel]);
});

test('role button and native button retain exact-label records selection', async () => {
  for (const role of ['button', '']) {
    const view = await fixture({ role, selected: usageLabel });
    assert.equal((await view.run('SELECT_RECORDS_EXPRESSION')).state, 'pending');
    assert.equal((await view.run()).available_balance, 242);
    assert.deepEqual(await view.clicks(), [recordsLabel]);
  }
});

test('observed earning-records-usage layout clicks records only, never earning or claims', async () => {
  for (const extra of ['赚魔粒', '领取', '立即领取', '', '发放记录', '未知页签']) {
    const view = await fixture({ plain: true, selected: extra, tabs: [extra, recordsLabel, usageLabel] });
    const result = await view.run('SELECT_RECORDS_EXPRESSION');
    if (extra === '赚魔粒') {
      assert.equal(result.reason, 'records-selected');
      assert.equal((await view.run()).state, 'verified');
      assert.deepEqual(await view.clicks(), [recordsLabel]);
    } else {
      assert.equal(result.reason, 'missing-records-tabs');
      assert.deepEqual(await view.clicks(), []);
    }
  }
});

test('earning descriptions and completed badges are not grant records', async () => {
  const view = await fixture({ plain: true, selected: '赚魔粒', tabs: ['赚魔粒', recordsLabel, usageLabel] });
  await view.page.evaluate(() => {
    const description = document.createElement('div');
    description.textContent = '注册账号后每日登录即可获取';
    document.querySelector('[data-fixture-card] > div').append(description);
    const panel = document.getElementById('usage-panel');
    panel.innerHTML = '<div><div><div>注册并登录</div><div>注册账号后每日登录即可获取</div></div><div>今日已完成</div><div>200</div></div>' +
      '<a><div><div><div>绑定阿里云账号</div><div>绑定阿里云账号后每日登录即可获取</div></div><div>今日已完成</div><div>50</div></div></a>';
    panel.querySelector('a').addEventListener('click', () => window.fixtureClicks.push('forbidden-control'));
  });
  assert.equal((await view.run()).state, 'select-records');
  assert.equal((await view.run('SELECT_RECORDS_EXPRESSION')).reason, 'records-selected');
  assert.equal((await view.run()).state, 'verified');
  assert.deepEqual(await view.clicks(), [recordsLabel]);
});

test('wrong sources and fragments reject before any records click', async () => {
  for (const url of ['https://other.invalid/magicube/usage', 'https://modelscope.cn/docs', 'https://modelscope.cn/magicube/usage#other', 'http://modelscope.cn/magicube/usage']) {
    const view = await fixture({ url, selected: usageLabel });
    assert.equal((await view.run('SELECT_RECORDS_EXPRESSION')).reason, 'wrong-page');
    assert.deepEqual(await view.clicks(), []);
  }
});

test('query stays opaque; initial blank, loading and absent tabs remain pending', async () => {
  const queried = await fixture({ url: 'https://modelscope.cn/magicube/usage?opaque=fixture', readyState: 'interactive' });
  assert.equal((await queried.run()).state, 'verified');
  assert.equal(JSON.stringify(await queried.run()).includes('opaque'), false);
  const blank = await fixture({ url: 'about:blank' });
  assert.deepEqual(await blank.run(), { state: 'pending', reason: 'initial-blank' });
  const loading = await fixture({ readyState: 'loading' });
  assert.deepEqual(await loading.run(), { state: 'pending', reason: 'page-loading' });
  const absent = await fixture({ tabs: [] });
  assert.deepEqual(await absent.run(), { state: 'pending', reason: 'missing-records-tabs' });
});

test('login/challenge stops both expressions without touching those controls', async () => {
  for (const [options, state] of [[{ login: true }, 'login-required'], [{ challenge: true }, 'challenge'], [{ controls: ['登录'] }, 'login-required'], [{ controls: ['安全验证'] }, 'challenge']]) {
    const view = await fixture({ ...options, selected: usageLabel });
    for (const name of Object.keys(expressions)) assert.equal((await view.run(name)).state, state);
    assert.deepEqual(await view.clicks(), []);
  }
});

test('duplicate labels and conflicting selection evidence fail closed', async () => {
  for (const options of [{ tabs: [recordsLabel, recordsLabel] }, { extraHtml: '<button role="tab">发放记录</button>' }]) {
    const view = await fixture(options);
    assert.equal((await view.run('SELECT_RECORDS_EXPRESSION')).reason, 'ambiguous-records-tab');
    assert.deepEqual(await view.clicks(), []);
  }
  for (const attribute of ['peer', 'aria-pressed', 'aria-selected']) {
    const view = await fixture();
    await view.page.evaluate(attribute => {
      const tabs = document.querySelectorAll('[data-fixture-tab]');
      if (attribute === 'peer') tabs[0].setAttribute('aria-selected', 'true');
      else tabs[1].setAttribute(attribute, attribute === 'aria-pressed' ? 'false' : 'invalid');
    }, attribute);
    assert.equal((await view.run()).reason, 'ambiguous-records-tab');
    assert.deepEqual(await view.clicks(), []);
  }
});

test('non-record labels and unsupported plain layouts never trigger a click', async () => {
  for (const options of [{ tabs: ['领取', '发放记录并领取'] }, { plain: true, tabs: ['领取', recordsLabel] }, { plain: true, tabs: [usageLabel, recordsLabel, '领取'] }]) {
    const view = await fixture({ ...options, selected: usageLabel });
    assert.equal((await view.run('SELECT_RECORDS_EXPRESSION')).reason, 'missing-records-tabs');
    assert.deepEqual(await view.clicks(), []);
  }
});

test('hidden duplicates are excluded; disabled/form/link controls never receive a click', async () => {
  const hidden = await fixture({ extraHtml: '<div hidden><button role="tab">发放记录</button><button aria-label="Magic Cube">999</button></div>' });
  assert.equal((await hidden.run()).available_balance, 242);
  for (const mode of ['disabled', 'aria-disabled', 'form', 'link', 'inert', 'hidden']) {
    const view = await fixture({ selected: usageLabel });
    await view.page.evaluate(mode => {
      const target = document.querySelectorAll('[data-fixture-tab]')[1];
      if (mode === 'form' || mode === 'link') {
        const wrapper = document.createElement(mode === 'form' ? 'form' : 'a');
        target.replaceWith(wrapper);
        wrapper.append(target);
      } else target.setAttribute(mode, mode === 'aria-disabled' ? 'true' : '');
    }, mode);
    assert.notEqual((await view.run('SELECT_RECORDS_EXPRESSION')).reason, 'records-selected');
    assert.deepEqual(await view.clicks(), []);
  }
});

test('aria panel binding stays unique and never reads unrelated page rows', async () => {
  for (const mode of ['duplicate', 'missing', 'no-binding', 'hidden']) {
    const view = await fixture();
    await view.page.evaluate(mode => {
      const panel = document.getElementById('records-panel');
      const tab = document.querySelectorAll('[data-fixture-tab]')[1];
      if (mode === 'duplicate') panel.after(panel.cloneNode(true));
      if (mode === 'missing') tab.setAttribute('aria-controls', 'absent-panel');
      if (mode === 'no-binding') { tab.removeAttribute('aria-controls'); document.querySelector('[role="tablist"]').removeAttribute('role'); }
      if (mode === 'hidden') panel.hidden = true;
    }, mode);
    assert.notEqual((await view.run()).state, 'verified');
  }
});

test('selected false cannot reuse stale visible records; color is not a selection signal', async () => {
  const view = await fixture();
  await view.page.evaluate(() => {
    const tab = document.querySelectorAll('[data-fixture-tab]')[1];
    tab.setAttribute('aria-selected', 'false');
    tab.style.color = 'blue';
    tab.className = 'acss-10mpfo8 active selected';
  });
  assert.equal((await view.run()).state, 'select-records');
});

test('missing/hidden data and invalid balances never generate default evidence', async () => {
  for (const options of [{ balances: [] }, { rows: [] }, { rows: [{ title: grantTitle, detail: grantText, hidden: true }] }]) {
    const result = await (await fixture(options)).run();
    assert.notEqual(result.state, 'verified');
    assert.equal('available_balance' in result, false);
  }
  for (const balances of [['242', '242'], ['1,000'], ['-1'], ['Infinity'], ['0.001'], ['private']]) {
    assert.equal((await (await fixture({ balances })).run()).reason, 'invalid-balance');
  }
  assert.equal((await (await fixture({ balances: ['0'] })).run()).available_balance, 0);
});

test('invalid dates, amounts, validity, duplicates and unknown grants remain rejected', async () => {
  for (const detail of [grantText.replace('09-08', '02-30'), grantText.replace('\n200', '\n0'), grantText.replace('\n200', '\n-1'),
    grantText.replace('\n200', '\n0.8'), grantText.replace('1天', '0天'), grantText + '\nprivate']) {
    assert.equal((await (await fixture({ rows: [{ title: grantTitle, detail }] })).run()).state, 'needs-review');
  }
  const row = { title: grantTitle, detail: grantText };
  assert.equal((await (await fixture({ rows: [row, row] })).run()).reason, 'duplicate-grant');
  assert.deepEqual(await (await fixture({ rows: [{ title: 'private reward', detail: grantText }] })).run(),
    { state: 'needs-review', reason: 'no-grant-evidence' });
  assert.equal((await (await fixture({ rows: Array(101).fill(row) })).run()).reason, 'unbounded-grants');
});

test('broken pairing cannot combine adjacent rows or expose partial evidence', async () => {
  const view = await fixture({ rows: [{ title: grantTitle, detail: grantText }, { title: bindingTitle, detail: grantText }] });
  await view.page.evaluate(() => document.querySelector('[data-fixture-detail]').remove());
  assert.deepEqual(await view.run(), { state: 'needs-review', reason: 'invalid-grant-row' });
  const duplicate = await fixture();
  await duplicate.page.evaluate(() => {
    const detail = document.querySelector('[data-fixture-detail]');
    detail.after(detail.cloneNode(true));
  });
  assert.equal((await duplicate.run()).reason, 'invalid-grant-row');
});

test('CSS-hidden rows and multiple legacy groups cannot become visible grant evidence', async () => {
  const hidden = await fixture();
  await hidden.page.evaluate(() => { document.getElementById('records-panel').style.display = 'none'; });
  assert.deepEqual(await hidden.run(), { state: 'pending', reason: 'missing-grants' });
  const duplicate = await fixture({ plain: true, selected: usageLabel,
    extraHtml: '<div><div>消耗统计</div><div>发放记录</div></div>' });
  assert.deepEqual(await duplicate.run('SELECT_RECORDS_EXPRESSION'), { state: 'needs-review', reason: 'ambiguous-records-tab' });
  assert.deepEqual(await duplicate.clicks(), []);
});
