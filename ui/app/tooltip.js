/* ============================================================================
   说明文本模块（全站唯一机制）
   ----------------------------------------------------------------------------
   约定（来自 docs/project/ui-redesign-plan.md）：
   - 稍复杂或需要解释的设置项，说明文本一律走「悬停提示」，
     **不得直接常驻写在选项下方**。
   - 全站只有这一种写法；不要再自建 title 属性、小字说明或其他悬浮层。

   两种用法：
   1) 声明式（推荐）：在 HTML 里写
        <span class="lbl">温度
          <span class="sumika-field-help" data-help="取值 0~1...">
            <button type="button" class="sumika-help-trigger" aria-label="说明">i</button>
            <span class="sumika-tooltip"></span>
          </span>
        </span>
      页面载入时由 hydrateHelp() 把 data-help 填进 .sumika-tooltip。

   2) 命令式：helpNode('文本', {flip:'left'}) 直接返回节点。
   ========================================================================== */

const TRIGGER = 'sumika-help-trigger';
const TOOLTIP = 'sumika-tooltip';

/** 构造一个标准提示块（触发器 + 气泡） */
function helpNode(text, opts = {}) {
  const wrap = document.createElement('span');
  wrap.className = 'sumika-field-help' + (opts.cls ? ' ' + opts.cls : '');

  const trigger = document.createElement('button');
  trigger.type = 'button';
  trigger.className = TRIGGER;
  trigger.setAttribute('aria-label', opts.label || '说明');
  trigger.setAttribute('aria-expanded', 'false');
  trigger.textContent = opts.glyph || 'i';

  const tip = document.createElement('span');
  tip.className = TOOLTIP + (opts.flip === 'left' ? ' flip-left' : '');
  tip.setAttribute('role', 'tooltip');
  tip.textContent = text;

  wrap.append(trigger, tip);
  return wrap;
}

/** 把 [data-help] 占位节点补全为可用的悬停提示 */
function hydrateHelp(root = document) {
  root.querySelectorAll('[data-help]').forEach((wrap) => {
    if (!wrap.classList.contains('sumika-field-help')) wrap.classList.add('sumika-field-help');
    let trigger = wrap.querySelector('.' + TRIGGER);
    if (!trigger) {
      trigger = document.createElement('button');
      trigger.type = 'button';
      trigger.className = TRIGGER;
      trigger.textContent = 'i';
      wrap.append(trigger);
    }
    trigger.setAttribute('aria-label', wrap.dataset.helpLabel || '说明');
    let tip = wrap.querySelector('.' + TOOLTIP);
    if (!tip) {
      tip = document.createElement('span');
      tip.className = TOOLTIP;
      wrap.append(tip);
    }
    if (wrap.dataset.helpFlip === 'left') tip.classList.add('flip-left');
    tip.setAttribute('role', 'tooltip');
    tip.textContent = wrap.dataset.help || '';
    // 键盘可达：聚焦触发器时展开，Esc 收起
    trigger.setAttribute('aria-expanded', 'false');
  });
}

/* ---- 展开/收起（供点击与 Esc 使用；悬停由 CSS 负责） ---- */
function openHelp(wrap) {
  wrap.classList.add('open');
  const t = wrap.querySelector('.' + TRIGGER);
  if (t) t.setAttribute('aria-expanded', 'true');
  placeTooltip(wrap);
}

function closeHelp(wrap) {
  wrap.classList.remove('open');
  const t = wrap.querySelector('.' + TRIGGER);
  if (t) t.setAttribute('aria-expanded', 'false');
}

/* ---- 自动避让：气泡贴近视口右边界时翻到左侧展开 ----
   纯 CSS 无法得知触发器在页面中的位置，故在展开时机测量一次。
   悬停(pointerenter)、聚焦、点击三条路径都会经过这里；
   同时作为兜底，CSS 已把默认方向设为「从左缘向右展开」，即使测量未跑到也不会溢出左侧。 */
function placeTooltip(wrap) {
  const tip = wrap.querySelector('.' + TOOLTIP);
  if (!tip) return;
  tip.classList.remove('flip-left');
  const rect = tip.getBoundingClientRect();
  const margin = 8;
  if (rect.right > window.innerWidth - margin) tip.classList.add('flip-left');
}

/* 用 pointerenter/mouseenter 而非 mouseover：直接绑定到元素本身，命中更可靠 */
document.addEventListener('pointerenter', (ev) => {
  const wrap = ev.target.closest && ev.target.closest('.sumika-field-help');
  if (wrap) placeTooltip(wrap);
}, true);
document.addEventListener('focusin', (ev) => {
  const wrap = ev.target.closest && ev.target.closest('.sumika-field-help');
  if (wrap) placeTooltip(wrap);
});
window.addEventListener('resize', () => {
  document.querySelectorAll('.sumika-field-help').forEach(placeTooltip);
});

/* 触屏/键盘兜底：点击触发器切换展开态（悬停与 focus-within 已由 CSS 覆盖） */
document.addEventListener('click', (ev) => {
  const trigger = ev.target.closest && ev.target.closest('.' + TRIGGER);
  if (trigger) {
    const wrap = trigger.closest('.sumika-field-help');
    if (wrap.classList.contains('open')) closeHelp(wrap); else openHelp(wrap);
    return;
  }
  // 点击别处收起所有手动展开的提示
  document.querySelectorAll('.sumika-field-help.open').forEach(closeHelp);
});

document.addEventListener('keydown', (ev) => {
  if (ev.key !== 'Escape') return;
  document.querySelectorAll('.sumika-field-help.open').forEach((n) => {
    closeHelp(n);
    const t = n.querySelector('.' + TRIGGER);
    if (t) t.focus();
  });
});

/** 动态注入内容（如 management.js 渲染的设置区）渲染完成后调用 */
function observeHelpRegions(...nodes) {
  const targets = nodes.filter(Boolean);
  if (!targets.length) return;
  const mo = new MutationObserver(() => hydrateHelp(document));
  targets.forEach((n) => mo.observe(n, { childList: true, subtree: true }));
  hydrateHelp(document);
  return mo;
}

export { helpNode, hydrateHelp, observeHelpRegions };
