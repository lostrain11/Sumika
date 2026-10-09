#!/usr/bin/env node
/* ============================================================================
   同步 Lucide 图标到 ui/vendor/icons/
   ----------------------------------------------------------------------------
   用法：
     node tools/sync_lucide_icons.mjs             # 按 tools/lucide-manifest.json 同步
     node tools/sync_lucide_icons.mjs --check     # 只校验本地文件是否与清单一致（不联网）

   设计要点：
   - 只从官方 npm 包按字节复制，不手工改 SVG，保证可复现、可审计。
   - 已是幂等的：清单不变则产物不变。
   - --check 模式用于 CI / 验收：本地缺文件或版本漂移时非零退出。
   ========================================================================== */

import fs from 'node:fs';
import path from 'node:path';
import zlib from 'node:zlib';
import { fileURLToPath } from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const MANIFEST = path.join(ROOT, 'tools', 'lucide-manifest.json');
const OUT_DIR = path.join(ROOT, 'ui', 'vendor', 'icons');
const CATALOGUE = path.join(ROOT, 'ui', 'vendor', 'lucide-names.txt');
const TMP = path.join(ROOT, '.sumika-next');

const checkOnly = process.argv.includes('--check');

/** 极简 tar 解析：返回 { 'package/icons/x.svg': Buffer } */
function readTar(buffer) {
  const out = {};
  let off = 0;
  while (off + 512 <= buffer.length) {
    const name = buffer.toString('utf8', off, off + 100).replace(/\0.*/, '');
    if (!name) { off += 512; continue; }
    const size = parseInt(buffer.toString('utf8', off + 124, off + 136).replace(/\0.*/, '').trim(), 8) || 0;
    const type = buffer.toString('utf8', off + 156, off + 157);
    if (type === '0') out[name] = buffer.subarray(off + 512, off + 512 + size);
    off += 512 + Math.ceil(size / 512) * 512;
  }
  return out;
}

async function main() {
  const manifest = JSON.parse(fs.readFileSync(MANIFEST, 'utf8'));

  if (checkOnly) {
    const missing = manifest.icons.filter(
      (n) => !fs.existsSync(path.join(OUT_DIR, n + '.svg')),
    );
    const hasLicense = fs.existsSync(path.join(OUT_DIR, 'LICENSE'));
    console.log(`lucide ${manifest.version} · 清单 ${manifest.icons.length} 个 · 缺失 ${missing.length} 个 · LICENSE ${hasLicense ? 'ok' : '缺失'}`);
    if (missing.length) console.log('缺失：' + missing.join(', '));
    process.exit(missing.length || !hasLicense ? 1 : 0);
  }

  const tgz = path.join(TMP, 'lucide-static.tgz');
  fs.mkdirSync(TMP, { recursive: true });
  if (!fs.existsSync(tgz)) {
    const url = manifest.source;
    console.log('下载 ' + url);
    const res = await fetch(url);
    if (!res.ok) throw new Error('下载失败：HTTP ' + res.status);
    fs.writeFileSync(tgz, Buffer.from(await res.arrayBuffer()));
  }

  const files = readTar(zlib.gunzipSync(fs.readFileSync(tgz)));
  fs.mkdirSync(OUT_DIR, { recursive: true });

  const written = [];
  const missing = [];
  for (const key of manifest.icons) {
    const src = files['package/icons/' + key + '.svg'];
    if (!src) { missing.push(key); continue; }
    const dest = path.join(OUT_DIR, key + '.svg');
    const next = Buffer.from(src);
    if (!fs.existsSync(dest) || !fs.readFileSync(dest).equals(next)) {
      fs.writeFileSync(dest, next);
      written.push(key);
    }
  }

  const license = files['package/LICENSE'];
  if (!license) throw new Error('官方包内未找到 LICENSE');
  fs.writeFileSync(path.join(OUT_DIR, 'LICENSE'), license);

  const all = Object.keys(files)
    .filter((n) => n.startsWith('package/icons/') && n.endsWith('.svg'))
    .map((n) => n.replace('package/icons/', '').replace('.svg', ''))
    .sort();
  fs.writeFileSync(CATALOGUE, all.join('\n'), 'utf8');

  console.log(`lucide ${manifest.version}（${manifest.license}）`);
  console.log(`  清单 ${manifest.icons.length} 个 · 本次写入 ${written.length} 个 · 未变化 ${manifest.icons.length - written.length - missing.length} 个`);
  if (missing.length) console.log('  官方包中不存在：' + missing.join(', '));
  console.log(`  可用图标目录 ${all.length} 项 → ui/vendor/lucide-names.txt`);
  console.log(`  LICENSE → ui/vendor/icons/LICENSE`);
  if (missing.length) process.exit(1);
}

main().catch((err) => { console.error(err); process.exit(1); });
