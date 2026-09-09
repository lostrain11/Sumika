import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { runInNewContext } from 'node:vm';

const source = readFileSync(new URL('./read_modelscope_magicube.ps1', import.meta.url), 'utf8');
const expression = source.match(/\$expression = @'\r?\n([\s\S]*?)\r?\n'@/)[1];
const dailyTitle = '\u6ce8\u518c\u5e76\u767b\u5f55';
const grantText = '2026-09-08\u83b7\u5f97\uff0c\u6709\u6548\u671f1\u5929\n200';

function observe({ origin = 'https://modelscope.cn', pathname = '/magicube/usage',
  selected = '\u53d1\u653e\u8bb0\u5f55', balances = ['242'], rows = [{ title: dailyTitle, detail: grantText }] } = {}) {
  const document = {
    querySelector: () => ({ textContent: selected }),
    querySelectorAll: (selector) => selector === 'button[aria-label]'
      ? balances.map(balance => ({ textContent: balance, getAttribute: () => 'Magic Cube' }))
      : rows.map(row => ({ querySelector: (childSelector) => ({
        innerText: childSelector === '.acss-k9j1zc' ? row.title : row.detail,
      }) })),
  };
  return JSON.parse(runInNewContext(expression, { document, location: { origin, pathname } }));
}

test('keeps measured balance distinct from grants and unknown exact expiry', () => {
  const result = observe();
  assert.equal(result.ok, true);
  assert.equal(result.available_balance, 242);
  assert.equal(result.grants[0].amount, 200);
  assert.equal(result.grants[0].expires_at, null);
  assert.equal(result.account_binding_verified, false);
  assert.equal(result.automatic_routing_authorized, false);
  assert.equal(result.login_or_claim_submitted, false);
  assert.equal(result.model_calls, 0);
});

test('rejects wrong origin, page and unselected records', () => {
  assert.equal(observe({ origin: 'https://example.com' }).ok, false);
  assert.equal(observe({ pathname: '/docs/magicube/intro' }).ok, false);
  assert.equal(observe({ selected: '\u6d88\u8017\u7edf\u8ba1' }).ok, false);
});

test('rejects missing, duplicate and malformed balances', () => {
  for (const balances of [[], ['242', '242'], [''], ['1,000'], ['-1'], ['unknown']]) {
    assert.equal(observe({ balances }).ok, false);
  }
  assert.equal(observe({ balances: ['0'] }).available_balance, 0);
});

test('rejects invalid dates, amounts, validity and duplicate rows', () => {
  for (const detail of [grantText.replace('09-08', '02-30'), grantText.replace('200', 'unknown'),
    grantText.replace('200', '-1'), grantText.replace('1\u5929', '0\u5929'), grantText + '\nprivate']) {
    assert.equal(observe({ rows: [{ title: dailyTitle, detail }] }).ok, false);
  }
  const row = { title: dailyTitle, detail: grantText };
  assert.equal(observe({ rows: [row, row] }).reason, 'duplicate-grant');
});

test('does not derive daily grants from unrelated rewards or an empty page', () => {
  assert.equal(observe({ rows: [] }).ok, false);
  assert.equal(observe({ rows: [{ title: 'unrelated-private-text', detail: grantText }] }).ok, false);
  assert.equal(observe({ rows: Array(101).fill({ title: dailyTitle, detail: grantText }) }).ok, false);
  assert.equal(JSON.stringify(observe()).includes(dailyTitle), false);
});
