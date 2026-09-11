// 把与 pdfjs-dist 同版本的 worker 同步到 public/，供 PdfReader 以静态路径加载。
// 直接引用 node_modules 里的 .mjs 会让 webpack/Terser 处理 ESM worker 而报错，
// 因此改为静态资源 + prebuild 同步，保证 worker 版本与 react-pdf 依赖一致。

import { copyFileSync, mkdirSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const here = dirname(fileURLToPath(import.meta.url));

// pdfjs-dist 是 react-pdf 的依赖，用 resolve 找到真实路径
const src = require.resolve('pdfjs-dist/build/pdf.worker.min.mjs');
const destDir = resolve(here, '..', 'public');
const dest = resolve(destDir, 'pdf.worker.min.mjs');

mkdirSync(destDir, { recursive: true });
copyFileSync(src, dest);
console.log(`[sync-pdf-worker] ${src} -> ${dest}`);
