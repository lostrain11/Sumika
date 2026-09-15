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
