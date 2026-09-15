// Sumika skin for the DSH web UI.
//
// This is a host-plane plugin: it does not touch DSH sources, it only pushes
// structured index-injection rows (a <style> and a small classic script) into
// the page the harness already renders. It stays inert unless the profile
// enables it explicitly.
//
// Visual direction: D 方案「晴日部室」— 米白纸底、墨绿、玫红、水色、8–9px 圆角、细描边。

export const name = 'sumika-skin';

const SKIN_STYLE = `
html[data-sumika-skin='1'] {
  /* Values mirror direction-d-hiyori/index.html :root; keep them in step with
     the design file instead of re-deriving a palette here. */
  --sumika-paper: #fffdf8;
  --sumika-panel: #faf8f0;
  --sumika-ink: #2f3a34;
  --sumika-muted: #6e7a72;
  --sumika-green: #567f6c;
  --sumika-rose: #b4496a;
  --sumika-rose-deep: #9c3a56;
  --sumika-rose-soft: #f9e8ed;
  --sumika-water: #7aa8c7;
  --sumika-mizu-soft: #e9f1f7;
  --sumika-line: #ddd9c8;
  --sumika-hover: #f0ecdd;
}
/* Keep the overrides narrow and reversible: surfaces and accents only. */
html[data-sumika-skin='1'] body {
  background: var(--sumika-paper);
  color: var(--sumika-ink);
}
html[data-sumika-skin='1'] {
  --dsh-boot-bg: var(--sumika-paper);
  --dsh-boot-brand: var(--sumika-green);
  --dsh-state-ongoing: var(--sumika-rose);
  --dsh-scrollbar-thumb: #d8cfba;
  --dsh-scrollbar-thumb-hover: #c9bda2;
  /* DSH exposes 37 narrow custom properties and no general palette, so the skin
     maps the ones that exist: radii, strokes and code surfaces. */
  --dsl-web-radius: 9px;
  --dsl-diff-radius: 8px;
  --dsl-read-radius: 8px;
  --dsl-search-radius: 8px;
  --dsl-terminal-radius: 8px;
  --dsw-elevation-stroke-color: var(--sumika-line);
  --dsw-hovercard-bg: var(--sumika-panel);
  --dsl-code-block-background: #fbf8f1;
  --dsl-code-block-banner-background-color: #f1ebdd;
  --dsh-file-type-default-color: var(--sumika-muted);
}

/* Structural surfaces. DSH ships CSS-module hashes (pI_x6G_frame), so the
   selectors anchor on the stable semantic suffix of each token. */
html[data-sumika-skin='1'] [class$='_frame'],
html[data-sumika-skin='1'] [class*='_frame '],
html[data-sumika-skin='1'] [class$='_centerCol'],
html[data-sumika-skin='1'] [class*='_centerCol '] {
  background: var(--sumika-paper);
}
html[data-sumika-skin='1'] [class$='_sidebarCol'],
html[data-sumika-skin='1'] [class*='_sidebarCol '] {
  background: var(--sumika-panel);
  border-right: 1px solid var(--sumika-line);
}

/* Sidebar affordances: design's .new-task-d / .wb-item / .wb-proj-head. */
html[data-sumika-skin='1'] [class$='_newSession'],
html[data-sumika-skin='1'] [class*='_newSession '] {
  background: var(--sumika-rose);
  border: none;
  border-radius: 8px;
  color: #fff;
  font-weight: 600;
  box-shadow: 0 3px 10px rgba(180, 73, 106, .22);
}
html[data-sumika-skin='1'] [class$='_newSession']:hover,
html[data-sumika-skin='1'] [class*='_newSession ']:hover {
  background: var(--sumika-rose-deep);
}
html[data-sumika-skin='1'] [class$='_sessionRow'],
html[data-sumika-skin='1'] [class*='_sessionRow '] {
  border-radius: 8px;
}
html[data-sumika-skin='1'] [class*='_sessionRow']:hover {
  background: var(--sumika-hover);
}
html[data-sumika-skin='1'] [class*='_sessionRow'][class*='_selected'],
html[data-sumika-skin='1'] [class*='_selected'][class*='_sessionRow'] {
  background: var(--sumika-rose-soft);
  color: var(--sumika-rose-deep);
  font-weight: 600;
}
html[data-sumika-skin='1'] [class$='_sectionLabel'],
html[data-sumika-skin='1'] [class*='_sectionLabel '] {
  color: var(--sumika-muted);
}

/* Sidebar tree, design's .wb-search / .wb-proj-head / .wb-task:
   project row = name (+ path in the shell today is not rendered by DSH),
   task row = status dot + title + relative time, with 8px rows and a soft hover. */
html[data-sumika-skin='1'] [class*='_searchInput'] {
  border: 1px solid var(--sumika-line);
  border-radius: 9px;
  background: var(--sumika-paper);
  color: var(--sumika-ink);
  font-size: 11.5px;
  padding: 5px 9px;
}
html[data-sumika-skin='1'] [class*='_searchSlot'] {
  border-radius: 9px;
}
html[data-sumika-skin='1'] [class*='_groupSection'] [class*='_root_'] {
  font-size: 12px;
}
html[data-sumika-skin='1'] [class*='_sessionRow'] {
  padding: 6px 9px;
  font-size: 11.5px;
  gap: 7px;
}
html[data-sumika-skin='1'] [class*='_sessionRow'] [class*='_root_'] {
  font-size: 11.5px;
}
html[data-sumika-skin='1'] [class*='_groupSection'] {
  border-radius: 9px;
}

/* Project row (design .wb-proj-head) and the status dot (design .dot 8×3px).
   The dot colour stays DSH's own real state; rows without a state keep no dot
   rather than showing an invented one. */
html[data-sumika-skin='1'] [class*='_projectRow'] {
  border-radius: 9px;
  padding: 8px 9px;
  font-size: 12px;
  font-weight: 600;
}
html[data-sumika-skin='1'] [class*='_projectRow']:hover {
  background: var(--sumika-hover);
}
html[data-sumika-skin='1'] [class*='_projectRow'] [class*='_title'] {
  font-weight: 600;
}
html[data-sumika-skin='1'] [class*='_dot'] {
  width: 8px;
  height: 8px;
  border-radius: 3px;
  flex: none;
}

/* Timeline, design's .cm / .bub / .tool-d / .tool-d .df:
   message bubble = 1px hairline + 8px radius on the panel tone, the tool card
   carries the 3px green left rule and 10px radius, and the diff stat sits muted
   on the right. Only DSH's own semantic suffixes are touched. */
html[data-sumika-skin='1'] [class*='_bubble'] {
  border: 1px solid var(--sumika-line);
  border-radius: 8px;
  background: var(--sumika-panel);
  padding: 10px 13px;
  font-size: 12.5px;
  line-height: 1.75;
}
html[data-sumika-skin='1'] [class*='_userRow'] [class*='_bubble'] {
  background: var(--sumika-mizu-soft, #e9f1f7);
  border-color: #cfdfea;
}
html[data-sumika-skin='1'] [class*='_callRow'] {
  border: 1px solid var(--sumika-line);
  border-left: 3px solid var(--sumika-green);
  border-radius: 10px;
  background: var(--sumika-paper);
  padding: 9px 12px;
  font-size: 11.5px;
}
html[data-sumika-skin='1'] [class*='_callRow'] code {
  font-family: Consolas, monospace;
  font-size: 11px;
}
html[data-sumika-skin='1'] [class*='_diffBody'],
html[data-sumika-skin='1'] [class*='_codeBody'],
html[data-sumika-skin='1'] [class*='_terminalBody'] {
  border: 1px solid var(--sumika-line);
  border-radius: 10px;
  background: var(--sumika-paper);
}
html[data-sumika-skin='1'] [class*='_diffStat'] {
  margin-left: auto;
  color: var(--sumika-muted);
}
html[data-sumika-skin='1'] [class*='_turnStatus'],
html[data-sumika-skin='1'] [class*='_turnStatusClock'] {
  font-size: 9.5px;
  color: var(--sumika-muted);
}

/* Composer, design's .wb-composer (+ the dashed control-row separator the
   design uses in .chat-composer). Every native control stays where it is. */
html[data-sumika-skin='1'] [class*='_composerStack'],
html[data-sumika-skin='1'] [class*='_composerSeat'] {
  margin-left: 24px;
  margin-right: 24px;
  margin-bottom: 16px;
}
/* Real DOM (measured): composerStack > root > card > scroll > grow > input, plus
   placeholder / row / tools. Scoped to the composer so other _card elements
   (approval, io cards) keep their own styling. */
html[data-sumika-skin='1'] [class*='_composerStack'] [class*='_card'] {
  border: 1px solid var(--sumika-line);
  border-radius: 10px;
  background: var(--sumika-paper);
}
html[data-sumika-skin='1'] [class*='_placeholder'] {
  color: var(--sumika-muted);
}
html[data-sumika-skin='1'] [class*='_composerStack'] [class*='_tools'] {
  border-top: 1px dashed var(--sumika-line);
  padding-top: 9px;
}

/* Rail toggle: upstream swaps the brand mark for its own panel glyph on hover
   (.collapsed .toggle:hover .panelIcon{display:inline} plus a railMark hide), so
   the Sumika mark would disappear exactly while the pointer is on it. Keep the
   mark and suppress the swap; the button stays a plain icon button either way. */
html[data-sumika-skin='1'] [class*='_collapsed'] [class*='_toggle']:hover [class*='_panelIcon'] {
  display: none;
}
html[data-sumika-skin='1'] [class*='_collapsed'] [class*='_toggle']:hover [class*='_railMark'] {
  display: inline-flex;
}

/* The design's sidebar has no brand of its own - the wordmark lives in the
   shell's top bar - so the identity button is hidden while the collapse toggle
   beside it stays. In the collapsed rail the mark is shown again (railMark),
   because there the toggle *is* the only affordance. */
html[data-sumika-skin='1'] [class$='_brand'],
html[data-sumika-skin='1'] [class*='_brand '] {
  display: none;
}
/* With the identity gone that row only holds the collapse control, so it does
   not need its original 60px; the design starts the column with 新建任务. */
html[data-sumika-skin='1'] [class*='_logoRow'] {
  height: 40px;
  margin-bottom: 6px;
}
`;

const SKIN_SCRIPT = `(() => {
  const html = document.documentElement;
  if (html.dataset.sumikaSkin === '1') return;
  html.dataset.sumikaSkin = '1';
})();`;

export function apply(ctx, config = {}) {
  if (config.enabled !== true) return;
  ctx.on('webserver/index-inject', (table) => {
    table.push({ kind: 'style', text: SKIN_STYLE });
    table.push({ kind: 'script', placement: 'head', text: SKIN_SCRIPT });
  });
}
