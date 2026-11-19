// Renders each frame in frame.html at deviceScaleFactor 2 into docs/img/readme-<name>.png.
// Usage: node docs/img/frames/render.mjs [base]   (base serves the repository root; default http://127.0.0.1:8791)
import { createRequire } from 'node:module';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const require = createRequire(import.meta.url);
const { chromium } = require('playwright');
const here = dirname(fileURLToPath(import.meta.url));
const BASE = process.argv[2] || 'http://127.0.0.1:8791';
const names = ['hero', 'map', 'try', 'evidence'];

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1200, height: 900 }, deviceScaleFactor: 2 });
for (const n of names) {
  await page.goto(`${BASE}/docs/img/frames/frame.html?f=${n}`, { waitUntil: 'networkidle' });
  await page.evaluate(() => document.fonts.ready);
  await page.waitForFunction(() => [...document.images].every((i) => i.dataset.ready === '1'));
  await page.locator('.frame').screenshot({ path: join(here, '..', `readme-${n}.png`), omitBackground: true });
  console.log('rendered', `readme-${n}.png`);
}
await browser.close();
