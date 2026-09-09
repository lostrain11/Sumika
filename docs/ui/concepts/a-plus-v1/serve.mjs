import { createServer } from 'node:http';
import { createReadStream } from 'node:fs';
import { stat } from 'node:fs/promises';
import { dirname, resolve, sep, extname } from 'node:path';
import { fileURLToPath } from 'node:url';

const directory = dirname(fileURLToPath(import.meta.url));
const root = resolve(directory,'../../../..');
const mounts = [
  ['/vendor/three/',resolve(root,'frontend/node_modules/three')],
  ['/vendor/vrm/',resolve(root,'frontend/node_modules/@pixiv/three-vrm/lib')],
];
const exact = {
  '/assets/AvatarSample_A.vrm':resolve(root,'assets/avatars/AvatarSample_A.vrm'),
  '/shared/room.js':resolve(directory,'../style-studies-v1/room.js'),
  '/shared/studies.js':resolve(directory,'../style-studies-v1/studies.js'),
};
const types = {'.html':'text/html; charset=utf-8','.css':'text/css; charset=utf-8','.js':'text/javascript; charset=utf-8','.json':'application/json; charset=utf-8','.png':'image/png','.vrm':'model/gltf-binary'};

export async function startPreview(port=0) {
  const server = createServer(async(request,response) => {
    if (!['GET','HEAD'].includes(request.method)) { response.writeHead(405).end(); return; }
    try {
      const path = decodeURIComponent(new URL(request.url,'http://localhost').pathname);
      let target = exact[path];
      if (!target) {
        const mount = mounts.find(([prefix]) => path.startsWith(prefix));
        const base = mount?.[1] || directory;
        const relative = mount ? path.slice(mount[0].length) : path.slice(1) || 'index.html';
        target = resolve(base,relative);
        if (!target.startsWith(base+sep) || relative.includes('..') || /[\\:]/.test(relative)) { response.writeHead(403).end(); return; }
      }
      const info = await stat(target);
      if (!info.isFile()) throw new Error('Not a file');
      response.writeHead(200,{'Content-Type':types[extname(target)] || 'application/octet-stream','Content-Length':info.size,'Cache-Control':'no-store','X-Content-Type-Options':'nosniff'});
      if (request.method === 'HEAD') response.end();
      else createReadStream(target).on('error',() => response.destroy()).pipe(response);
    } catch { response.writeHead(404).end('Not found'); }
  });
  await new Promise((done,reject) => { server.once('error',reject); server.listen(port,'127.0.0.1',done); });
  return {server,url:`http://127.0.0.1:${server.address().port}`};
}
if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  let preview;
  try { preview = await startPreview(Number(process.argv[2] || 8878)); }
  catch (error) { if (error.code !== 'EADDRINUSE') throw error; preview = await startPreview(); }
  console.log(`Sumika A+ preview: ${preview.url}`);
  process.on('SIGINT',() => preview.server.close(() => process.exit(0)));
  process.on('SIGTERM',() => preview.server.close(() => process.exit(0)));
}
