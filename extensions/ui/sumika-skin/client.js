// Public DSH theme extension. No patched bundles or global descendant overrides.
window.__ModuleLoader__.load({
  id: 'sumika-skin',
  factory: () => ({
    inject: ['theme'],
    apply(ctx) {
      if (document.documentElement.dataset.sumikaSkin !== '1') return;
      // Keep sidebar geometry in the browser extension, including both native
      // collapse states. This updates on reload without restarting the agent.
      const sidebarStyle = document.createElement('style');
      sidebarStyle.dataset.sumikaSidebar = '1';
      sidebarStyle.textContent = `
html[data-sumika-skin='1'] [data-slot='sidebar'] > div {
  position: relative; padding-top: 16px; box-sizing: border-box;
}
html[data-sumika-skin='1'] [class*='_logoRow'] {
  height: 0; min-height: 0; padding: 0; margin: 0; overflow: visible;
}
html[data-sumika-skin='1'] [class*='_logoRow'] [class*='_brand'] { display: none; }
html[data-sumika-skin='1'] [class*='_logoRow'] [class*='_toggle'] {
  position: absolute; top: 16px; right: 12px; z-index: 5;
  display: inline-flex; align-items: center; justify-content: center;
  width: 32px; height: 38px; min-height: 38px; padding: 0;
  border: none; border-radius: 8px;
  color: var(--sumika-muted); background: transparent;
}
html[data-sumika-skin='1'] [class*='_logoRow'] [class*='_toggle']:hover {
  background: var(--dsw-alias-bg-layer-2); color: var(--dsw-alias-label-primary);
}
html[data-sumika-skin='1'] [class*='_logoRow'] [class*='_toggle']:focus-visible {
  outline: 2px solid var(--sumika-rose); outline-offset: 2px;
}
html[data-sumika-skin='1'] [role='tooltip'] {
  background: var(--dsw-alias-bg-layer-1); color: var(--dsw-alias-label-primary);
  border: 1px solid var(--dsw-alias-border-l2); border-radius: 6px;
}
html[data-sumika-skin='1'] [class*='_logoRow'] [class*='_toggle'] [class*='_panelIcon'],
html[data-sumika-skin='1'] [class*='_collapsed'] [class*='_toggle']:hover [class*='_panelIcon'] {
  display: block; width: 16px; height: 16px;
}
html[data-sumika-skin='1'] [class*='_logoRow'] [class*='_toggle'] [class*='_railMark'],
html[data-sumika-skin='1'] [class*='_collapsed'] [class*='_toggle']:hover [class*='_railMark'] { display: none; }
html[data-sumika-skin='1'] button[class*='_newSession'] {
  min-height: 38px; height: 38px;
}
html[data-sumika-skin='1'] button[class*='_newSession'] {
  width: calc(100% - 64px); margin: 0 52px 14px 12px;
  border-radius: 8px; font-size: 12.5px;
}
html[data-sumika-skin='1'] [class*='_sidebarCol'] button svg { width: 16px; height: 16px; flex-shrink: 0; }
html[data-sumika-skin='1'] [class*='_collapsed'] [class*='_logoRow'] {
  height: 38px; min-height: 38px; margin-bottom: 10px;
}
html[data-sumika-skin='1'] [class*='_collapsed'] [class*='_logoRow'] [class*='_toggle'] {
  position: static; width: 36px; height: 38px; margin: 0 auto;
}
html[data-sumika-skin='1'] [class*='_collapsed'] button[class*='_newSession'] {
  width: 36px; margin: 0 auto 14px;
}
`;
      document.head.append(sidebarStyle);
      ctx.on('dispose', () => sidebarStyle.remove());
      const palette = {
        '--dsw-alias-bg-base': '#fffdf8',
        '--dsw-alias-bg-layer-1': '#faf8f0',
        '--dsw-alias-bg-layer-2': '#f5f3ea',
        '--dsw-alias-bg-overlay': '#fffdf8',
        '--dsw-specific-sidebar-fill': '#faf8f0',
        '--dsw-alias-border-l1': '#ddd9c8',
        '--dsw-alias-border-l2': '#c9c3ac',
        '--dsw-alias-brand-primary': '#b4496a',
        '--dsw-alias-label-primary': '#2f3a34',
        '--dsw-alias-label-secondary': '#6e7a72',
        '--dsw-alias-state-success-primary': '#567f6c',
        '--dsw-alias-state-warn-primary': '#9a7038',
        '--dsw-alias-state-error-primary': '#a6404d',
      };
      // Only shade the light palette. Dark/system-dark stays with the native
      // theme, so an unreviewed invented dark palette never overrides it.
      const tokens = Object.fromEntries(Object.entries(palette)
        .map(([key, value]) => [key, {light: value, dark: value}]));
      let dispose = null;
      let updating = false;
      const host='http://127.0.0.1:8765';
      let initial=true;
      const report=()=>{
        if(window.parent!==window)window.parent.postMessage({type:initial?'sumika:theme-ready':'sumika:theme-state',preference:ctx.theme.getTheme().preference},host);
      };
      const sync = () => {
        if (updating) return;
        updating = true;
        try {
          const light = ctx.theme.getTheme().active.colorScheme === 'light';
          document.documentElement.dataset.sumikaPalette = light ? 'light' : 'dark';
          if (light && !dispose) dispose = ctx.theme.overrideTokens('sumika-skin', tokens);
          if (!light && dispose) { const remove = dispose; dispose = null; remove(); }
        } finally { updating = false; }
        if(!initial)report();
      };
      // Let every native presenter finish the current snapshot before publishing
      // an override snapshot; nested emissions can repaint stale alias tokens.
      let queued = false;
      let stopped = false;
      ctx.on('theme/change', () => {
        if (queued || stopped) return;
        queued = true;
        queueMicrotask(() => {
          queued = false;
          if (!stopped) sync();
        });
      });
      ctx.effect(() => {
        sync();
        report();initial=false;
        const receive=event=>{
          if(event.source!==window.parent||event.origin!==host||event.data?.type!=='sumika:theme-set')return;
          const value=event.data.preference;
          if(!['light','dark','system'].includes(value))return;
          if(ctx.theme.getTheme().preference!==value)ctx.theme.setTheme(value);
          else report();
        };
        window.addEventListener('message',receive);
        return () => {
          stopped = true;
          window.removeEventListener('message',receive);
          updating = true;
          dispose?.();
          delete document.documentElement.dataset.sumikaPalette;
        };
      });
    },
  }),
});
