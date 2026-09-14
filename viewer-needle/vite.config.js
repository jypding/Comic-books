import { defineConfig } from 'vite';
import { fileURLToPath } from 'node:url';
import { resolve, dirname } from 'node:path';
import fs from 'node:fs';

// ESM 下 __dirname 不存在，用 import.meta.url 构造（仅本文件配置期使用）。
// alias 路径必须用 path.resolve 绝对路径，与 tsconfig.json paths 一一对应。
const __dirname = fileURLToPath(new URL('.', import.meta.url));
const projectRoot = resolve(__dirname, '..');
const booksRoot = resolve(projectRoot, 'books');

// Dev: 把 HTTP /books/* 映射到磁盘 ${projectRoot}/books/*（漫画内容包禁止打进 bundle）
// Prod: dist 不包含 books；部署时由 Deploy-ComicToViewer.ps1 / CI 单独同步到发布根 /books/
function booksServeMiddleware() {
  return {
    name: 'books-serve',
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        const url = req.url || '';
        // 适配 base: /Comic-books/ 或直接访问 /books/
        const base = '/Comic-books/';
        const booksPrefix = 'books/';
        
        let rel = '';
        if (url.startsWith(base + booksPrefix)) {
          rel = url.substring((base + booksPrefix).length);
        } else if (url.startsWith('/' + booksPrefix)) {
          rel = url.substring(('/' + booksPrefix).length);
        } else {
          return next();
        }
        
        rel = decodeURIComponent(rel.split('?')[0].split('#')[0]);
        const diskPath = resolve(booksRoot, rel);
        // 禁止 .. 逃逸 booksRoot
        const booksRootNorm = booksRoot.replace(/\\/g, '/');
        const diskNorm = diskPath.replace(/\\/g, '/');
        if (!diskNorm.startsWith(booksRootNorm + '/') && diskNorm !== booksRootNorm) {
          return next();
        }
        try {
          if (fs.existsSync(diskPath) && fs.statSync(diskPath).isFile()) {
            const ext = rel.split('.').pop()?.toLowerCase() || '';
            const mime =
              ext === 'json' ? 'application/json; charset=utf-8'
              : ext === 'glb' ? 'model/gltf-binary'
              : ext === 'jpg' || ext === 'jpeg' ? 'image/jpeg'
              : ext === 'png' ? 'image/png'
              : ext === 'mp3' ? 'audio/mpeg'
              : ext === 'wav' ? 'audio/wav'
              : ext === 'webp' ? 'image/webp'
              : ext === 'md' ? 'text/markdown; charset=utf-8'
              : ext === 'css' ? 'text/css; charset=utf-8'
              : ext === 'js' ? 'application/javascript; charset=utf-8'
              : ext === 'html' ? 'text/html; charset=utf-8'
              : 'application/octet-stream';
            res.setHeader('Content-Type', mime);
            res.setHeader('Cache-Control', 'no-cache');
            const stream = fs.createReadStream(diskPath);
            stream.on('error', () => {
              try { res.destroy(); } catch { /* ignore */ }
              next();
            });
            stream.pipe(res);
            return;
          }
        } catch { /* fallthrough */ }
        next();
      });
    },
  };
}

export default defineConfig({
  base: "/Comic-books/",
  resolve: {
    alias: {
      "@core": resolve(__dirname, "../src/core"),
      "@modes": resolve(__dirname, "../src/modes"),
      "@ui": resolve(__dirname, "../src/ui"),
      "@comic-runtime": resolve(__dirname, "./src/comic-runtime"),
      "@ext": resolve(__dirname, "./src/extensions"),
      "@runtime": resolve(__dirname, "./src"),
    }
  },
  plugins: [booksServeMiddleware()],
  server: {
    port: 5173,
    fs: {
      allow: [
        __dirname,
        resolve(__dirname, "../src"),
        projectRoot,
      ]
    }
  },
  build: {
    outDir: "dist",
    target: "ES2020"
  }
})
