// Host half of the Sumika brand plugin.
//
// The components live in the browser half; the host plane exists for two
// reasons: the loader needs a package entry to find this package's `dsh.client`
// declaration, and the browser half must not guess runtime facts. The only fact
// the components need is the harness release, so the host reads it from config
// and publishes it as a frozen global instead of letting the UI invent a value.

export const name = 'sumika-brand';

/** Escape a value for embedding in a classic script. */
function scriptLiteral(value) {
  return JSON.stringify(value).replace(/</g, '\\u003c');
}

export function apply(ctx, config = {}) {
  const shell = {
    harness: typeof config.harness === 'string' && config.harness ? config.harness : 'dsh',
    release: typeof config.release === 'string' ? config.release : null,
    shellUrl: typeof config.shellUrl === 'string' && config.shellUrl ? config.shellUrl : null,
  };
  const text = `(() => {
  window.__sumikaShell = Object.freeze(${scriptLiteral(shell)});
})();`;
  ctx.on('webserver/index-inject', (table) => {
    table.push({ kind: 'script', placement: 'head', text });
  });
}
