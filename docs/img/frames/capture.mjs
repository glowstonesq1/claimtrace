// Captures the real site UI at deviceScaleFactor 2 into docs/img/frames/raw/ (not committed).
// Usage: node docs/img/frames/capture.mjs [base]   (default base http://127.0.0.1:8790, serving apps/site)
import { createRequire } from 'node:module';
import { mkdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const require = createRequire(import.meta.url);
const { chromium } = require('playwright');
const here = dirname(fileURLToPath(import.meta.url));
const out = join(here, 'raw');
const BASE = process.argv[2] || 'http://127.0.0.1:8790';
mkdirSync(out, { recursive: true });

const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 }, deviceScaleFactor: 2, reducedMotion: 'reduce' });
const page = await ctx.newPage();
const settle = () => page.evaluate(() => document.fonts.ready).then(() => page.waitForTimeout(600));

// 1. home hero, with the nav, exactly the first screen
await page.setViewportSize({ width: 1280, height: 860 });
await page.goto(`${BASE}/`, { waitUntil: 'networkidle' });
await settle();
await page.screenshot({ path: join(out, 'hero.png') });

// 2. evidence map with clause 2.1 of the contract selected
await page.setViewportSize({ width: 1280, height: 800 });
await page.locator('[data-clip="msa-2.1"]').click();
await settle();
await page.locator('#how').screenshot({ path: join(out, 'map.png') });

// 3. /try with the samples loaded and checked against the delivery record
await page.setViewportSize({ width: 1280, height: 900 });
await page.goto(`${BASE}/try/`, { waitUntil: 'networkidle' });
await page.waitForSelector('body[data-engine="ready"]', { timeout: 180000 });
await page.getByRole('button', { name: 'Load sample documents' }).click();
await page.waitForSelector('.item', { timeout: 60000 });
await settle();
await page.locator('#register').evaluate((el) => window.scrollTo(0, el.getBoundingClientRect().top + window.scrollY - 24));
await settle();
await page.screenshot({ path: join(out, 'try-register.png') });
await page.selectOption('#base-doc', { label: 'Master Services Agreement (Contract)' });
await page.selectOption('#other-doc', { label: 'Phase 1 Delivery and Acceptance Record (Record)' });
await page.getByRole('button', { name: 'Check', exact: true }).click();
await page.waitForSelector('.finding');
await settle();
await page.locator('#check').evaluate((el) => window.scrollTo(0, el.getBoundingClientRect().top + window.scrollY - 24));
await settle();
await page.screenshot({ path: join(out, 'try-check.png') });

// 4. evidence ledger
await page.setViewportSize({ width: 1280, height: 800 });
await page.goto(`${BASE}/evidence/`, { waitUntil: 'networkidle' });
await settle();
await page.screenshot({ path: join(out, 'evidence-top.png'), clip: { x: 0, y: 0, width: 1280, height: 1100 }, fullPage: true });
await page.locator('#answers').screenshot({ path: join(out, 'evidence-answers.png') });
await page.locator('#metrics').evaluate((el) => window.scrollTo(0, el.getBoundingClientRect().top + window.scrollY));
await settle();
await page.screenshot({ path: join(out, 'evidence-metrics.png') });

await browser.close();
console.log('captured into', out);
