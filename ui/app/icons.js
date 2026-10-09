/* ============================================================================
   图标模块（Lucide · ISC）
   ----------------------------------------------------------------------------
   唯一图标来源。规则：
   1. 图标来自 ui/vendor/icons/（字节级复制自 lucide-static 1.47.0），
      不在业务代码里手写 <svg> 路径。
   2. 新功能需要图标时，先追加到 tools/lucide-manifest.json 的 icons 清单，
      再运行 `node tools/sync_lucide_icons.mjs`，然后在下方 ICON_MAP 里登记语义名。
   3. 图标默认 1em 大小、跟随 currentColor，颜色由外层 CSS 决定。
   4. 按需加载：只请求当前 DOM 中出现的图标，不预拉全表。新增节点用
      `await hydrateIconsAsync(root)` 补拉并替换，或用 data-icon 占位再 hydrate。
   5. 失败不写缓存，可重试；并发上限 ICON_CONCURRENCY，避免打满本地桥接。
   ========================================================================== */

/* ---- 语义名 → Lucide 图标名 ----------------------------------------------
   只登记「本项目实际用到」的语义，避免把整个库搬进内存。
   命名规则：<域>-<用途>，域取 nav / act / state / cap / obj / chara / sys / ui。
   -------------------------------------------------------------------------- */
const ICON_MAP = {
  /* 全局导航 */
  'nav-room':       'house',
  'nav-board':      'layout-grid',
  'nav-shelf':      'puzzle',
  'nav-settings':   'settings',

  /* 通用动作 */
  'act-close':      'x',
  'act-check':      'check',
  'act-plus':       'plus',
  'act-minus':      'minus',
  'act-edit':       'pencil',
  'act-save':       'save',
  'act-copy':       'copy',
  'act-trash':      'trash-2',
  'act-download':   'download',
  'act-upload':     'upload',
  'act-refresh':    'refresh-cw',
  'act-search':     'search',
  'act-send':       'send',
  'act-more':       'ellipsis',
  'act-open':       'maximize-2',
  'act-back':       'arrow-left',
  'act-play':       'play',
  'act-pause':      'pause',

  /* 展开/折叠 */
  'act-chevron-down':  'chevron-down',
  'act-chevron-up':    'chevron-up',
  'act-chevron-right': 'chevron-right',

  /* 说明 / 状态 */
  'act-help':       'circle-help',
  'act-info':       'info',
  'state-ok':       'circle-check',
  'state-warn':     'triangle-alert',
  'state-error':    'circle-alert',
  'state-loading':  'loader',
  'state-pending':  'clock',
  'state-done':     'check',
  'state-none':     'minus',
  'state-blocked':  'ban',
  'state-live':     'circle-dot',

  /* 能力模块（开发工具 · DSH 原生） */
  'cap-terminal':   'square-terminal',
  'cap-edit':       'square-pen',
  'cap-subagent':   'bot',
  'cap-skills':     'sparkles',
  'cap-mcp':        'plug',
  'cap-code':       'code',
  'cap-command':    'command',
  'cap-workflow':   'workflow',
  'cap-tool':       'wrench',
  'cap-agent':      'brain-circuit',
  'cap-bug':        'bug',
  'cap-network':    'network',
  'cap-server':     'server',
  'cap-database':   'database',
  'cap-cloud':      'cloud',
  'cap-cpu':        'cpu',
  'cap-gauge':      'gauge',
  'cap-layers':     'layers',
  'cap-box':        'box',
  'cap-archive':    'archive',
  'cap-module':     'package',

  /* 能力模块（具体扩展，按注册表 id 一一对应） */
  'cap-ocr':        'scan-text',
  'cap-desktop':    'monitor',
  'cap-camera':     'camera',
  'cap-office':     'file-spreadsheet',
  'cap-speech':     'audio-lines',
  'cap-memory':     'brain',

  /* 对象 / 资源 */
  'obj-file':       'file-text',
  'obj-file-code':  'file-code',
  'obj-folder':     'folder',
  'obj-folder-open':'folder-open',
  'obj-image':      'image',
  'obj-link':       'link',
  'obj-list':       'list',
  'obj-clipboard':  'clipboard-list',
  'obj-calendar':   'calendar',
  'obj-clock':      'alarm-clock',
  'obj-library':    'library',
  'obj-star':       'star',
  'obj-pin':        'pin',

  /* 角色 / 陪伴 */
  'chara-user':     'user-round',
  'chara-self':     'circle-user-round',
  'chara-group':    'users',
  'chara-heart':    'heart',
  'chara-chat':     'message-circle',
  'chara-speech':   'message-square',
  'chara-voice':    'mic',
  'chara-audio':    'volume-2',
  'chara-sparkle':  'wand-sparkles',

  /* 系统 / 安全 */
  'sys-lock':       'lock',
  'sys-key':        'key-round',
  'sys-shield':     'shield-check',
  'sys-power':      'power',
  'sys-disk':       'hard-drive',
  'sys-toggle':     'toggle-left',
  'sys-eye':        'eye',
  'sys-eye-off':    'eye-off',
  'sys-globe':      'globe',
  'sys-app':        'app-window',
  'sys-activity':   'activity',

  /* 主题 / 外观 */
  'ui-theme-light': 'sun',
  'ui-theme-dark':  'moon',
  'ui-palette':     'palette',
  'ui-brush':       'brush',
  'ui-grid':        'layout-grid',
  'ui-graduate':    'graduation-cap',
};

/* ---- 路径与缓存 ---------------------------------------------------------- */
const ICON_BASE = '/vendor/icons/';
const svgCache = new Map();    // lucide 名 → 内部 SVG 串（不含外层 <svg>）
const inflight = new Map();    // lucide 名 → 进行中的 Promise，避免重复请求
const failed = new Set();      // 仅本次会话内记录失败，供重试判断；不写入 svgCache

/* ---- 并发闸门 --------------------------------------------------------------
   同一时刻最多 ICON_CONCURRENCY 个图标请求。首屏会解析出大量图标占位，
   一次性并发打满本地桥接的监听队列会导致随机 ERR_CONNECTION_REFUSED，
   表现为「个别图标静默不显示」。排队后峰值连接数可控。
   -------------------------------------------------------------------------- */
const ICON_CONCURRENCY = 6;
let active = 0;
const waiting = [];
function slot() {
  if (active < ICON_CONCURRENCY) { active += 1; return Promise.resolve(); }
  return new Promise((resolve) => waiting.push(resolve));
}
function release() {
  active -= 1;
  const next = waiting.shift();
  if (next) { active += 1; next(); }
}

/* ---- 加载 ------------------------------------------------------------------
   fetch 是异步的，而绑定逻辑是同步的；index.html 用「await initIcons()」保证
   首屏用到的图标在 hydrate 前就位。只加载 DOM 里真正出现的图标，不预拉全表。
   -------------------------------------------------------------------------- */
async function loadIcon(lucideName) {
  if (svgCache.has(lucideName)) return svgCache.get(lucideName);
  if (inflight.has(lucideName)) return inflight.get(lucideName);
  const job = (async () => {
    await slot();
    try {
      const res = await fetch(ICON_BASE + lucideName + '.svg');
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const text = await res.text();
      // 剥掉注释与最外层 <svg>，只留内部图元，便于继承宿主尺寸与颜色
      const inner = text
        .replace(/<!--[\s\S]*?-->/g, '')
        .replace(/^[\s\S]*?<svg[^>]*>/, '')
        .replace(/<\/svg>\s*$/, '')
        .trim();
      // 只缓存成功结果：失败不落缓存，后续 hydrateIcons 仍可重试。
      svgCache.set(lucideName, inner);
      failed.delete(lucideName);
      return inner;
    } catch (error) {
      failed.add(lucideName);
      console.warn(`[icons] 加载失败：${lucideName}（${error.message}）`);
      return '';
    } finally {
      release();
      inflight.delete(lucideName);
    }
  })();
  inflight.set(lucideName, job);
  return job;
}

/** 解析语义名 → Lucide 名；未登记或直写 lucide: 前缀时给出对应结果 */
function resolveName(name) {
  if (!name) return null;
  return name.startsWith('lucide:') ? name.slice(7) : (ICON_MAP[name] || null);
}

/**
 * 生成图标元素。
 * @param {string} name     ICON_MAP 中的语义名，或 'lucide:xxx' 直写 Lucide 名
 * @param {{size?:number, cls?:string, title?:string}} [opts]
 * @returns {SVGElement|null}
 */
function icon(name, opts = {}) {
  const lucide = resolveName(name);
  if (!lucide) { console.warn('[icons] 未登记的语义名：' + name); return null; }
  const inner = svgCache.get(lucide);
  if (inner === undefined || inner === '') return null;   // 未就绪或加载失败
  const ns = 'http://www.w3.org/2000/svg';
  const svg = document.createElementNS(ns, 'svg');
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('fill', 'none');
  svg.setAttribute('stroke', 'currentColor');
  svg.setAttribute('stroke-width', '2');
  svg.setAttribute('stroke-linecap', 'round');
  svg.setAttribute('stroke-linejoin', 'round');
  svg.setAttribute('aria-hidden', 'true');
  svg.setAttribute('focusable', 'false');
  svg.style.width = svg.style.height = (opts.size || 16) + 'px';
  if (opts.cls) svg.setAttribute('class', opts.cls);
  if (opts.title) { svg.setAttribute('role', 'img'); svg.setAttribute('aria-label', opts.title); }
  svg.innerHTML = inner;
  return svg;
}

/** 便捷：返回图标 SVG 的 outerHTML 字符串（用于模板串拼接） */
function iconHTML(name, opts = {}) {
  const el = icon(name, opts);
  return el ? el.outerHTML : '';
}

/** 收集 root 下所有 [data-icon] 用到的 Lucide 名（去重） */
function collectNames(root) {
  const names = new Set();
  root.querySelectorAll('[data-icon]').forEach((node) => {
    const lucide = resolveName(node.dataset.icon);
    if (lucide) names.add(lucide);
  });
  return [...names];
}

/** 把已存在的占位元素替换为图标：<i data-icon="cap-terminal"></i> */
function hydrateIcons(root = document) {
  let replaced = 0;
  root.querySelectorAll('[data-icon]').forEach((node) => {
    const el = icon(node.dataset.icon, {
      size: Number(node.dataset.iconSize) || 16,
      title: node.dataset.iconTitle || undefined,
    });
    if (el) {
      if (node.id) el.id = node.id;
      if (node.className) el.setAttribute('class', `${node.className} ${el.getAttribute('class') || ''}`.trim());
      node.replaceWith(el);
      replaced += 1;
    }
  });
  return replaced;
}

/**
 * 首屏初始化：只预取当前 DOM 中真正用到的图标。
 * 必须等它 resolve 后再 hydrateIcons()，否则占位会被跳过。
 * 后续动态插入的占位用 hydrateIcons 增量处理即可（loadIcon 会按需补拉）。
 */
let readyPromise = null;
function initIcons(root = document) {
  if (readyPromise) return readyPromise;
  const wanted = collectNames(root);
  readyPromise = Promise.all(wanted.map(loadIcon)).then(() => true);
  return readyPromise;
}

/**
 * 为 root 下尚未加载的占位补拉图标并替换。用于 bind.js 等运行期新建的节点。
 * 返回实际替换的数量。
 */
async function hydrateIconsAsync(root = document) {
  const wanted = collectNames(root);
  await Promise.all(wanted.map(loadIcon));
  return hydrateIcons(root);
}

export { ICON_MAP, icon, iconHTML, hydrateIcons, hydrateIconsAsync, initIcons, loadIcon, collectNames };
