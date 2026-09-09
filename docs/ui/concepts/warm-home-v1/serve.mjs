import { createServer } from 'node:http';
import { createReadStream } from 'node:fs';
import { stat } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { dirname, resolve, sep, extname } from 'node:path';

const directory = dirname(fileURLToPath(import.meta.url));
const root = resolve(directory, '../../../..');
const mounts = [
  ['/vendor/three/', resolve(root, 'frontend/node_modules/three')],
  ['/vendor/vrm/', resolve(root, 'frontend/node_modules/@pixiv/three-vrm/lib')],
];
const types = { '.html': 'text/html; charset=utf-8', '.css': 'text/css; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.png': 'image/png', '.json': 'application/json; charset=utf-8', '.vrm': 'model/gltf-binary' };

export async function startPreview(port = 0) {
  const server = createServer(async (request, response) => {
    if (!['GET', 'HEAD'].includes(request.method)) {
      response.writeHead(405).end();
      return;
    }
    try {
      const path = decodeURIComponent(new URL(request.url, 'http://localhost').pathname);
      let target;
      if (path === '/assets/AvatarSample_A.vrm') {
        target = resolve(root, 'assets/avatars/AvatarSample_A.vrm');
      } else {
        const mount = mounts.find(([prefix]) => path.startsWith(prefix));
        const base = mount?.[1] || directory;
        const relative = mount ? path.slice(mount[0].length) : path.slice(1) || 'index.html';
        target = resolve(base, relative);
        if (!target.startsWith(base + sep) || relative.includes('..') || relative.includes('\\')) {
          response.writeHead(403).end();
          return;
        }
      }
      if (!(await stat(target)).isFile()) throw new Error('not a file');
      response.writeHead(200, { 'Content-Type': types[extname(target)] || 'application/octet-stream', 'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff' });
      if (request.method === 'HEAD') response.end();
      else createReadStream(target).pipe(response);
    } catch {
      response.writeHead(404).end('Not found');
    }
  });
  await new Promise((done, reject) => { server.once('error', reject); server.listen(port, '127.0.0.1', done); });
  return { server, url: `http://127.0.0.1:${server.address().port}` };
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const requestedPort = Number(process.argv[2] || 8876);
  let preview;
  try { preview = await startPreview(requestedPort); }
  catch (error) { if (error.code !== 'EADDRINUSE') throw error; preview = await startPreview(0); }
  console.log(`Sumika design preview: ${preview.url}`);
  process.on('SIGINT', () => preview.server.close(() => process.exit(0)));
  process.on('SIGTERM', () => preview.server.close(() => process.exit(0)));
}
