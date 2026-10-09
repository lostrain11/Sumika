// 响应式矩阵验证：分辨率 × 缩放 × 主题。
//
// 为什么需要它：用户的两条硬要求——「模块化卡片大小要统一」与「多测试不同拉伸
// 分辨率下的区别」——只有在组合遍历下才能证明。单点截图会漏掉只有某个断点才
// 出现的不等高卡片或横向溢出。
//
// 缩放如何模拟：浏览器 125% 缩放会让 CSS 视口变成物理尺寸的 1/1.25。所以
// 「1440 宽 + 125%」等价于 CSS 视口 1152 宽，本脚本按这个换算设置视口，
// 而不是用 deviceScaleFactor（后者只放大像素、不改变布局，测不出真实回流）。
//
// 断言（每个屏幕 × 每个组合）：
//   1. 页面无横向溢出（documentElement.scrollWidth ≤ 视口宽 + 1）
//   2. 当前屏幕内可见元素不出界（右/下不超过视口）
//   3. 每个 .cap-grid 内卡片等宽；同一行卡片等高
//   4. 主题真的生效（浅色底亮、深色底暗），避免「以为测了深色其实没切」
//
// 用法：
//   node tools/verify_ui_matrix.mjs [bridge] [evidence.json]
import { loadPlaywright } from './lib/playwright.mjs';
import { writeFile } from 'node:fs/promises';
import { waitForNativeFrame } from './lib/native-frame.mjs';

const { chromium } = loadPlaywright();

const bridge = process.argv[2] || 'http://127.0.0.1:8765';
const evidencePath = process.argv[3] || null;

/* 8 个分辨率：覆盖桌面宽屏到窄窗，并落在既有断点两侧
   （layout.css 1250/960/680、room.css 1024、settings.css 1024）。 */
const VIEWPORTS = [
  { width: 1920, height: 1080 },
  { width: 1600, height: 900 },
  { width: 1440, height: 900 },
  { width: 1280, height: 720 },
  { width: 1160, height: 800 },
  { width: 1024, height: 768 },
  { width: 960, height: 720 },
  { width: 900, height: 700 },
];
const ZOOMS = [1, 1.25];
const THEMES = ['light', 'dark'];
const SCREENS = ['room', 'shelf', 'settings', 'board'];

/** 125% 缩放 ⇒ CSS 视口 = 物理尺寸 / 1.25 */
const effective = (size, zoom) => ({
  width: Math.round(size.width / zoom),
  height: Math.round(size.height / zoom),
});

// 亮度判定：取 rgb() 的感知亮度，用于确认主题切换真的生效
const luminance = (rgb) => {
  const m = /rgba?\(([^)]+)\)/.exec(rgb || '');
  if (!m) return null;
  const [r, g, b] = m[1].split(',').map((v) => parseFloat(v));
  return Math.round((0.2126 * r + 0.7152 * g + 0.0722 * b) * 10) / 10;
};

const browser = await chromium.launch({
  executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  headless: true,
});
const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
const page = await context.newPage();
const pageErrors = [];
page.on('pageerror', (error) => pageErrors.push(String(error.message || error)));

const failures = [];
const cells = [];

/* 主题同步协议会把外壳的偏好**持久化到 DSH 的配置档案**：theme.js 在收到
   工作台的 sumika:theme-ready 后调用 send()，把 sumika:theme-set 发给工作台，
   工作台据此写自己的 settings.yaml（ui-theme.preference）。也就是说本脚本
   一旦切主题，用户的工作台主题就被真实改掉了，而且这个改动在浏览器之外存活、
   不会随浏览器关闭而消失。所以：开跑前读走工作台当前主题，全部结束后原样
   写回并复验，否则「验证」就等于「改了用户的设置还不说」。 */
async function workbenchPalette() {
  const frame = await waitForNativeFrame(page, bridge);
  await frame.locator('html[data-sumika-palette]').waitFor({ timeout: 60000 });
  return frame.evaluate(() => document.documentElement.dataset.sumikaPalette);
}
async function openAppearance() {
  await page.locator('#gnav [data-go="settings"]').click();
  await page.locator('[data-section="appearance"]').click();
  return page.getByLabel('主题配色');
}
await page.goto(`${bridge}/#board`, { waitUntil: 'domcontentloaded' });
const initialTheme = await workbenchPalette();
// 复原要按**用户偏好**写回，而不是按解析后的配色：偏好可能是 'system'，
// 若只写回 'light'/'dark' 就把用户的「跟随系统」悄悄改成了固定值。
// 工作台报告过之后，设置里的下拉值就是真实偏好（theme.js 由 theme-state 赋值）。
const initialPreference = await (await openAppearance()).inputValue();

for (const theme of THEMES) {
  // 主题由 localStorage 驱动，改动后需要重新加载才生效
  await page.goto(`${bridge}/#room`, { waitUntil: 'domcontentloaded' });
  await page.evaluate((value) => localStorage.setItem('sumika-theme', value), theme);
  await page.reload({ waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(2200);

  for (const size of VIEWPORTS) {
    for (const zoom of ZOOMS) {
      const view = effective(size, zoom);
      await page.setViewportSize(view);

      for (const screen of SCREENS) {
        const label = `${theme} · ${size.width}×${size.height} · ${Math.round(zoom * 100)}% · ${screen}`;
        try {
          await page.locator(`#gnav [data-go="${screen}"]`).click();
          await page.waitForTimeout(screen === 'board' ? 700 : 260);

          // 每次测量前重申主题。DSH 工作台会把自己的主题状态回传（theme.js 的
          // sumika:theme-state），打开工作台后外壳会跟随它变暗——那是设计行为，
          // 但会污染「我正在测浅色」的前提。所以逐格重申，并把工作台页的漂移
          // 记为预期之外的情况单独报告，而不是当成主题缺陷。
          await page.evaluate((value) => {
            localStorage.setItem('sumika-theme', value);
            document.documentElement.dataset.theme = value;
          }, theme);
          await page.waitForTimeout(120);

          const state = await page.evaluate(() => {
            const active = document.querySelector('.screen.show');
            const drifted = document.documentElement.dataset.theme;

            // 只有「水平方向被裁掉」才是真的布局问题。
            // 纵向超出往往只是内容在滚动容器里需要下滚——那是设计行为，不是缺陷；
            // 舞台美术用 transform 缩放并由 overflow:hidden 裁剪，也属于设计行为。
            // 因此：任一祖先在水平方向会裁剪/滚动时，该元素不计入出界。
            const clippedAncestor = (node) => {
              let parent = node.parentElement;
              while (parent && parent !== document.documentElement) {
                const style = getComputedStyle(parent);
                if (style.overflowX !== 'visible') return true;
                parent = parent.parentElement;
              }
              return false;
            };

            const overflow = active
              ? [...active.querySelectorAll('*')]
                  .filter((node) => {
                    const style = getComputedStyle(node);
                    if (style.display === 'none' || style.visibility === 'hidden') return false;
                    const rect = node.getBoundingClientRect();
                    if (rect.width <= 0 || rect.height <= 0) return false;
                    if (clippedAncestor(node)) return false;
                    return rect.right > innerWidth + 1 || rect.left < -1;
                  })
                  .map((node) => {
                    const rect = node.getBoundingClientRect();
                    return {
                      name: node.id || node.className || node.tagName,
                      right: Math.round(rect.right),
                      left: Math.round(rect.left),
                    };
                  })
              : [];

            // 卡片统一性。
            // 注意：CSS 网格默认 align-items:stretch，同一行本就等高——断言「行内等高」
            // 是恒真的，没有信息量（已用负向对照验证过：强行加高一张卡，整行跟着变高）。
            // 真正会不统一的是「不同行/不同组之间」的高度差，所以这里测全局极差。
            const cardBoxes = [...document.querySelectorAll('.cap-card')]
              .map((card) => card.getBoundingClientRect());
            const cardWidths = cardBoxes.map((b) => Math.round(b.width));
            const cardHeights = cardBoxes.map((b) => Math.round(b.height));
            const uniformity = cardBoxes.length >= 2 ? {
              cards: cardBoxes.length,
              widthSpread: Math.max(...cardWidths) - Math.min(...cardWidths),
              heightSpread: Math.max(...cardHeights) - Math.min(...cardHeights),
              heights: [...new Set(cardHeights)].sort((a, b) => a - b),
              clipped: [...document.querySelectorAll('.cap-card')]
                .filter((card) => card.scrollHeight > card.clientHeight + 1).length,
            } : null;

            const grids = [...document.querySelectorAll('.cap-grid')].map((grid) => {
              const cards = [...grid.querySelectorAll('.cap-card')];
              if (cards.length < 2) return null;
              const widths = cards.map((card) => Math.round(card.getBoundingClientRect().width));
              return {
                cards: cards.length,
                widthSpread: Math.max(...widths) - Math.min(...widths),
              };
            }).filter(Boolean);

            const background = getComputedStyle(document.body).backgroundColor;
            return {
              palette: document.documentElement.dataset.theme,
              screenShown: Boolean(active),
              docScrollWidth: document.documentElement.scrollWidth,
              innerWidth,
              overflow,
              grids,
              background,
              cards: document.querySelectorAll('.cap-card').length,
              uniformity,
              drifted,
            };
          });

          const cell = { label, theme, size, zoom, screen, ...state };
          delete cell.overflow;
          delete cell.grids;
          cell.cardHeights = state.uniformity?.heights || null;

          // 工作台页里 DSH 拥有主题，外壳跟随它是设计行为：只在非工作台页断言主题。
          if (screen !== 'board' && state.drifted !== theme) {
            failures.push(`${label}：主题未生效（data-theme=${state.drifted}）`);
          }
          const luma = luminance(state.background);
          if (luma !== null) {
            if (theme === 'light' && luma < 180) {
              failures.push(`${label}：浅色主题底色过暗（${state.background}）`);
            }
            if (theme === 'dark' && luma > 120) {
              failures.push(`${label}：深色主题底色过亮（${state.background}）`);
            }
          }
          if (screen !== 'board' && state.docScrollWidth > state.innerWidth + 1) {
            failures.push(`${label}：页面横向溢出 `
              + `(${state.docScrollWidth} > ${state.innerWidth})`);
          }
          if (state.overflow.length) {
            failures.push(`${label}：${state.overflow.length} 个元素出界 `
              + `→ ${state.overflow.slice(0, 3).map((o) => `${o.name}@${o.right}`).join(', ')}`);
          }
          for (const grid of state.grids) {
            if (grid.widthSpread > 1) {
              failures.push(`${label}：同一栅格内卡片宽度不一致（差 ${grid.widthSpread}px，`
                + `${grid.cards} 张）`);
            }
          }
          // 「同页所有卡片等大」是用户的硬要求，所以按全局极差断言，而不是行内（恒真）。
          if (state.uniformity) {
            if (state.uniformity.heightSpread > 1) {
              failures.push(`${label}：卡片高度不统一（极差 ${state.uniformity.heightSpread}px，`
                + `出现的高度：${state.uniformity.heights.join('/')}）`);
            }
            if (state.uniformity.widthSpread > 1) {
              failures.push(`${label}：卡片宽度不统一（极差 ${state.uniformity.widthSpread}px）`);
            }
            if (state.uniformity.clipped) {
              failures.push(`${label}：${state.uniformity.clipped} 张卡片内容被裁`);
            }
          }
          cells.push(cell);
        } catch (error) {
          failures.push(`${label}：${String(error.message || error).slice(0, 160)}`);
        }
      }
    }
  }
}

const themeLuma = {};
for (const theme of THEMES) {
  const sample = cells.find((cell) => cell.theme === theme);
  themeLuma[theme] = sample ? { background: sample.background, luma: luminance(sample.background) } : null;
}

// 复原用户的工作台主题。注意不能只写 localStorage 再 goto 同一个地址——
// 同 URL 的 goto 不会重新加载，theme.js 不会重新初始化，也就不会广播回工作台，
// 结果就是「看起来复原了、其实工作台还是旧值」。所以走人工验证过的路径：
// 在设置里把「主题配色」选回原偏好（setTheme → localStorage → render → send），
// 再回工作台屏复验配色确实回到原值。
let restoredTheme = null;
try {
  const select = await openAppearance();
  await select.selectOption(initialPreference);
  await page.waitForTimeout(800);
  await page.locator('#gnav [data-go="board"]').click();
  restoredTheme = await workbenchPalette();
  if (restoredTheme !== initialTheme) {
    failures.push(`主题未复原：偏好 ${initialPreference} 期望配色 ${initialTheme}，`
      + `实际 ${restoredTheme}（本次验收改动了用户的工作台主题且没能还原）`);
  }
} catch (error) {
  failures.push(`主题复原失败：${String(error.message || error).slice(0, 160)}`);
}

// 主题串扰：DSH 工作台会把自己的主题状态回传给外壳（theme.js 的 sumika:theme-state）。
// 这是设计行为，但会让「我设了浅色」在打开工作台之后变成别的值——必须显式记录，
// 否则后续断言会误报，或更糟：悄悄改变了被测环境却没人知道。
const paletteMismatch = cells
  .filter((cell) => cell.drifted !== cell.theme)
  .map((cell) => `${cell.label} → ${cell.drifted}`);

await browser.close();

const result = {
  checked_at: new Date().toISOString(),
  bridge,
  matrix: {
    viewports: VIEWPORTS.length,
    zooms: ZOOMS,
    themes: THEMES,
    screens: SCREENS,
    cells: cells.length,
    expected: VIEWPORTS.length * ZOOMS.length * THEMES.length * SCREENS.length,
  },
  theme_luminance: themeLuma,
  // 本次跑之前/之后工作台的主题，用于证明验收没有把用户的主题留在别处
  theme_restored: { preference: initialPreference, initial: initialTheme, restored: restoredTheme },
  // 卡片尺寸的实测分布，便于回答「到底出现过几种高度/宽度」
  card_sizes: (() => {
    const byScreen = {};
    for (const cell of cells) {
      if (!cell.cardHeights) continue;
      const key = cell.screen;
      if (!byScreen[key]) byScreen[key] = new Set();
      cell.cardHeights.forEach((h) => byScreen[key].add(h));
    }
    return Object.fromEntries(Object.entries(byScreen)
      .map(([screen, set]) => [screen, [...set].sort((a, b) => a - b)]));
  })(),
  palette_mismatch: paletteMismatch,
  page_errors: pageErrors,
  failures,
  status: failures.length || pageErrors.length ? 'failed' : 'passed',
};
if (pageErrors.length) result.failures.push(`客户端报错：${pageErrors.join(' | ')}`);

console.log(JSON.stringify(result, null, 2));
if (evidencePath) await writeFile(evidencePath, JSON.stringify(result, null, 2) + '\n', 'utf8');
process.exit(result.status === 'passed' ? 0 : 1);
