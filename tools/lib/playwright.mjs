import { createRequire } from 'node:module';
import { readdirSync } from 'node:fs';
import { join } from 'node:path';

export function loadPlaywright() {
  try { return createRequire(import.meta.url)('playwright'); } catch {}
  const root = join(process.env.LOCALAPPDATA, 'OpenAI/Codex/runtimes/cua_node');
  for (const entry of readdirSync(root, { withFileTypes: true })) {
    if (!entry.isDirectory()) continue;
    try {
      return createRequire(join(root, entry.name, 'bin/node_modules/noop.js'))('playwright');
    } catch {}
  }
  throw new Error('Playwright is unavailable in local dependencies and Codex runtimes');
}
