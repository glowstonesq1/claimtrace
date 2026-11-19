// End-to-end test of the try page: the real engine in Chromium, served from apps/site.
//
//   make try-bundle && node apps/site/try/e2e.mjs
//
// Needs `playwright` (Chromium) and `axe-core` resolvable by require() (CI installs playwright@1.49.1 and
// axe-core@4.10.2 with --no-save and points NODE_PATH at them), and Python with reportlab and python-docx
// to generate the upload fixtures (PYTHON, default python3). Starts `python -m http.server` on apps/site
// unless BASE is set. SHOTS=1 writes try-*.png at deviceScaleFactor 2 into SHOTS_DIR (default
// docs/img/frames/raw/, which is gitignored: raw frames, never referenced as they are).
//
// Asserts: samples load and the register shows commitments, a replaced clause and verified quotes; an
// answer with a verified quote; a contradiction when the contract is checked against the delivery record;
// a generated PDF and DOCX are read; export works; NO request leaves the local origin during the whole
// flow (every request is routed and recorded; anything else is aborted and fails the test), and the CSP
// blocks a deliberate cross-origin fetch from both the page and the engine worker; axe finds no serious or
// critical issues; no horizontal scroll at 390 px; with JavaScript off the page says it needs it; a call
// past the watchdog limit, or a cancelled one, terminates the worker with a plain message and the next
// action restarts it.

import { execFileSync, spawn } from 'node:child_process';
import { mkdirSync, mkdtempSync, readFileSync, writeFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const require = createRequire(import.meta.url);
const { chromium } = require('playwright');
const axeSource = readFileSync(require.resolve('axe-core/axe.min.js'), 'utf8');

const here = dirname(fileURLToPath(import.meta.url));
const site = resolve(here, '..');
const repo = resolve(site, '..', '..');
const PY = process.env.PYTHON || 'python3';
const SHOTS = process.env.SHOTS === '1';
const SHOTS_DIR = resolve(process.env.SHOTS_DIR || join(repo, 'docs/img/frames/raw'));
if (SHOTS) mkdirSync(SHOTS_DIR, { recursive: true });
const PORT = Number(process.env.PORT || 8790);
let BASE = process.env.BASE;
const failures = [];
const report = {};

function check(ok, what) {
  console.log(`${ok ? 'ok  ' : 'FAIL'} ${what}`);
  if (!ok) failures.push(what);
}

async function serve() {
  if (BASE) return null;
  const proc = spawn(PY, ['-m', 'http.server', String(PORT), '--bind', '127.0.0.1', '--directory', site], { stdio: 'ignore' });
  BASE = `http://127.0.0.1:${PORT}`;
  for (let i = 0; i < 50; i++) {
    try {
      if ((await fetch(`${BASE}/try/`)).ok) return proc;
    } catch { /* not up yet */ }
    await new Promise((r) => setTimeout(r, 200));
  }
  throw new Error('http.server did not start');
}

function fixtures() {
  const dir = mkdtempSync(join(tmpdir(), 'ct-try-'));
  const code = `
import io, sys
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from docx import Document
out = sys.argv[1]
c = canvas.Canvas(out + "/supply.pdf", pagesize=A4)
y = 780
for line in ("Supply Agreement", 'This Supply Agreement is made between Arden Mills Ltd. (the "Supplier") and',
             'Brook Foods plc (the "Buyer").', "1. Delivery",
             "1.1 The Supplier shall deliver the goods no later than June 30, 2026."):
    c.drawString(72, y, line); y -= 18
c.save()
d = Document()
d.add_heading("Service Order", level=1)
d.add_paragraph('This Service Order is between Kestrel Labs Ltd. (the "Provider") and Mere Holdings Ltd. (the "Client").')
d.add_paragraph("1. The Provider shall deliver the monthly report within 5 Business Days of each month end.")
d.save(out + "/order.docx")
`;
  execFileSync(PY, ['-c', code, dir]);
  return dir;
}

const axeNoise = new Set(); // console errors raised while axe itself runs (it sets inline styles while measuring)
let consoleErrors = [];

async function shot(page, selector, file) {
  if (!SHOTS) return;
  await page.locator(selector).evaluate((el) => el.scrollIntoView({ block: 'start' }));
  await page.screenshot({ path: join(SHOTS_DIR, file) });
}

async function axe(page, name) {
  const before = consoleErrors.length;
  await page.evaluate(axeSource); // evaluated by the test harness, not by the page: the page's CSP still holds
  const res = await page.evaluate(async () => await window.axe.run(document, { resultTypes: ['violations'] }));
  const bad = res.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical');
  for (const v of bad) console.log(`     axe ${v.impact}: ${v.id} (${v.nodes.length}) ${v.nodes.slice(0, 2).map((n) => n.target.join(' ')).join(' | ')}`);
  await page.waitForTimeout(200);
  for (const t of consoleErrors.slice(before)) axeNoise.add(t);
  report[`axe_${name}`] = { serious_or_critical: bad.length, all: res.violations.length };
  check(bad.length === 0, `axe ${name}: 0 serious/critical (found ${bad.length})`);
}

function isLocal(url) {
  if (url.startsWith('blob:')) url = url.slice(5);
  if (url.startsWith('data:')) return true;
  try {
    const u = new URL(url);
    return (u.hostname === '127.0.0.1' || u.hostname === 'localhost') && u.origin === new URL(BASE).origin;
  } catch {
    return false;
  }
}

async function guard(context, seen, offenders) {
  await context.route('**/*', (route) => {
    const url = route.request().url();
    seen.push(url);
    if (!isLocal(url)) {
      offenders.push(url);
      return route.abort('blockedbyclient');
    }
    return route.continue();
  });
}

async function main() {
  const server = await serve();
  const dir = fixtures();
  const browser = await chromium.launch();
  try {
    // ---- JavaScript off -------------------------------------------------------------------------
    const nojs = await browser.newContext({ javaScriptEnabled: false });
    const np = await nojs.newPage();
    await np.goto(`${BASE}/try/`);
    check(await np.getByRole('heading', { name: 'This page needs JavaScript' }).isVisible(), 'JS off: says the page needs JavaScript');
    check(await np.getByText('Your files are read by code running in this tab. Nothing is uploaded.').isVisible(), 'JS off: privacy statement visible');
    check(!(await np.locator('#app').isVisible()), 'JS off: the tool itself is hidden');
    await nojs.close();

    // ---- desktop, cold cache --------------------------------------------------------------------
    const seen = [];
    const offenders = [];
    const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 }, deviceScaleFactor: 2, acceptDownloads: true });
    await guard(ctx, seen, offenders);
    let bytes = 0;
    ctx.on('requestfinished', async (req) => {
      try {
        const s = await req.sizes();
        bytes += s.responseBodySize + s.responseHeadersSize;
      } catch { /* ignore */ }
    });
    const page = await ctx.newPage();
    consoleErrors = [];
    page.on('console', (m) => { if (m.type() === 'error') consoleErrors.push(m.text()); });
    page.on('pageerror', (e) => consoleErrors.push(String(e)));

    const t0 = Date.now();
    await page.goto(`${BASE}/try/`);
    await page.waitForSelector('body[data-engine="ready"]', { timeout: 180000 });
    report.cold_load_ms = Date.now() - t0;
    report.engine_note = await page.locator('#engine-note').innerText();
    check(true, `engine ready (cold) in ${(report.cold_load_ms / 1000).toFixed(1)} s`);
    check(await page.getByText('Your files are read by code running in this tab. Nothing is uploaded.').isVisible(), 'privacy statement visible');
    check(seen.some((u) => u.endsWith('/pyodide.asm.wasm')), 'worker requests are routed through the egress guard');
    if (SHOTS) await page.screenshot({ path: join(SHOTS_DIR, 'try-start.png') });
    await axe(page, 'ready');

    // 1. samples -> register
    await page.getByRole('button', { name: 'Load sample documents' }).click();
    await page.waitForSelector('.item', { timeout: 60000 });
    const items = await page.locator('.item').count();
    check(items >= 20, `register shows commitments (${items})`);
    check(await page.locator('.party__head', { hasText: 'Vendor' }).count() > 0, 'register grouped by party');
    const replaced = page.locator('.item.is-replaced', { hasText: 'March 31, 2026' }).first();
    check(await replaced.isVisible(), 'clause 2.1 shown as replaced');
    check((await replaced.innerText()).includes('May 15, 2026'), 'replacement wording shown');
    check(await page.locator('.item .check-bad').count() === 0, 'every register quote matches its document');
    check(await page.evaluate(() => document.activeElement && document.activeElement.id) === 'register-title', 'focus moves to the register');
    report.register_summary = await page.locator('#register-summary').innerText();

    // show in document, then focus returns
    const show = replaced.getByRole('button', { name: 'Show in document' });
    await show.click();
    await page.waitForSelector('#viewer[open]');
    const mark = await page.locator('#viewer-mark').innerText();
    check(mark.includes('March 31, 2026'), 'show in document highlights the passage');
    if (SHOTS) await page.screenshot({ path: join(SHOTS_DIR, 'try-document.png') });
    await page.keyboard.press('Escape');
    check(await page.evaluate(() => !document.getElementById('viewer').open), 'Escape closes the document');
    check(await show.evaluate((el) => el === document.activeElement), 'focus returns to the button');
    await shot(page, '#register', 'try-register.png');

    // 3. ask
    await page.getByLabel('Your question').fill('Did the vendor promise delivery by March 31?');
    await page.getByRole('button', { name: 'Ask', exact: true }).click();
    await page.waitForSelector('.answer__card');
    const answer = await page.locator('.answer__card').innerText();
    check(answer.includes('Found in the documents'), 'answer status shown');
    const verifiedQuote = page.locator('.cite', { hasText: 'March 31, 2026' }).locator('.check-ok');
    check(await verifiedQuote.count() > 0, 'answer shows a verified quote');
    check((await page.locator('#answer-status').innerText()).startsWith('Answer:'), 'answer announced (aria-live)');
    await shot(page, '#ask', 'try-answer.png');

    // 4. check contract vs delivery record
    await page.selectOption('#base-doc', { label: 'Master Services Agreement (Contract)' });
    await page.selectOption('#other-doc', { label: 'Phase 1 Delivery and Acceptance Record (Record)' });
    await page.getByRole('button', { name: 'Check', exact: true }).click();
    await page.waitForSelector('.finding');
    const first = page.locator('.findings__list').first().locator('.finding').first();
    check(await first.evaluate((el) => el.classList.contains('is-contradicted') && el.classList.contains('is-high')),
      'contract vs delivery record: a high-severity contradiction comes first');
    check((await first.innerText()).includes('late'), 'the explanation is shown');
    await shot(page, '#check', 'try-check.png');
    await axe(page, 'results');

    // 2. own files: a generated PDF and DOCX
    await page.setInputFiles('#file-input', [join(dir, 'supply.pdf'), join(dir, 'order.docx')]);
    // A locator wait, not waitForFunction: older Playwright evaluates that as a string, which this page's CSP
    // (no 'unsafe-eval') correctly refuses.
    await page.locator('#add-status', { hasText: /^Read 2 documents/ }).waitFor({ timeout: 60000 });
    const docs = await page.locator('#doc-list').innerText();
    check(docs.includes('supply.pdf') && docs.includes('order.docx'), 'PDF and DOCX listed');
    check(await page.locator('.item', { hasText: 'June 30, 2026' }).count() > 0, 'PDF commitment in the register');
    check(await page.locator('.item', { hasText: 'monthly report' }).count() > 0, 'DOCX commitment in the register');
    await page.setInputFiles('#file-input', { name: 'notes.exe', mimeType: 'application/octet-stream', buffer: Buffer.from('MZ') });
    check((await page.locator('#add-status').innerText()).includes('only PDF, Word'), 'unsupported file refused with a plain message');

    // export (a Blob, no network)
    const [dl] = await Promise.all([page.waitForEvent('download'), page.getByRole('button', { name: 'Download JSON' }).click()]);
    const exported = JSON.parse(readFileSync(await dl.path(), 'utf8'));
    check(exported.reports && exported.reports.length >= 3, 'JSON export has a report per document');
    const [dl2] = await Promise.all([page.waitForEvent('download'), page.getByRole('button', { name: 'Download Markdown' }).click()]);
    check(readFileSync(await dl2.path(), 'utf8').includes('not legal advice'), 'Markdown export includes the disclaimer');

    // negative control: the CSP stops a cross-origin request from the page and from the engine worker
    const fromPage = await page.evaluate(() => fetch('https://example.com/claimtrace-egress-probe').then(() => 'sent', () => 'blocked'));
    check(fromPage === 'blocked', 'CSP blocks a cross-origin fetch from the page');
    const engineWorker = page.workers()[0];
    const fromWorker = engineWorker
      ? await engineWorker.evaluate(() => fetch('https://example.com/claimtrace-egress-probe').then(() => 'sent', () => 'blocked'))
      : 'no worker';
    check(fromWorker === 'blocked', `CSP blocks a cross-origin fetch from the engine worker (${fromWorker})`);

    report.requests = seen.length;
    report.transferred_mb_cold = +(bytes / 1e6).toFixed(2);
    check(offenders.length === 0, `no request left ${BASE} (${seen.length} requests, offenders: ${offenders.length ? offenders.join(', ') : 'none'})`);
    const cspErrors = consoleErrors.filter((t) => /Content Security Policy/i.test(t) && !t.includes('claimtrace-egress-probe') && !axeNoise.has(t));
    report.csp_messages_during_axe = [...axeNoise].filter((t) => /Content Security Policy/i.test(t)).length;
    check(cspErrors.length === 0, `no unexpected CSP violations${cspErrors.length ? ': ' + cspErrors.join(' | ') : ''}`);
    report.console_errors = consoleErrors.filter((t) => !axeNoise.has(t) && !t.includes('claimtrace-egress-probe'));

    await ctx.close();

    // ---- second visit (HTTP cache) ---------------------------------------------------------------
    // Request routing turns Chromium's HTTP cache off, so this context only observes requests. It has a
    // profile on disk: a throwaway (incognito) context keeps its cache in memory and drops the 9.6 MB wasm.
    const seenW = [];
    const cache = await chromium.launchPersistentContext(mkdtempSync(join(tmpdir(), 'ct-try-profile-')));
    cache.on('request', (r) => seenW.push(r.url()));
    const wp = await cache.newPage();
    await wp.goto(`${BASE}/try/`);
    await wp.waitForSelector('body[data-engine="ready"]', { timeout: 180000 });
    const t1 = Date.now();
    await wp.reload();
    await wp.waitForSelector('body[data-engine="ready"]', { timeout: 120000 });
    report.warm_load_ms = Date.now() - t1;
    report.engine_note_warm = await wp.locator('#engine-note').innerText();
    check(seenW.every(isLocal), `second visit: every request local (${seenW.length})`);
    await cache.close();

    // ---- phone width, keyboard only, reduced motion -------------------------------------------------
    const seenM = [];
    const offM = [];
    const mob = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, reducedMotion: 'reduce', isMobile: true, hasTouch: true });
    await guard(mob, seenM, offM);
    const mp = await mob.newPage();
    await mp.goto(`${BASE}/try/`);
    await mp.waitForSelector('body[data-engine="ready"]', { timeout: 180000 });
    if (SHOTS) await mp.screenshot({ path: join(SHOTS_DIR, 'try-mobile-start.png') });
    await mp.focus('#load-samples');
    await mp.keyboard.press('Enter');
    await mp.waitForSelector('.item', { timeout: 60000 });
    const sw = await mp.evaluate(() => document.documentElement.scrollWidth);
    check(sw <= 390, `390 px: no horizontal scroll (scrollWidth ${sw})`);
    await mp.getByLabel('Your question').fill('Is customer data kept in the UK?');
    await mp.keyboard.press('Enter');
    await mp.waitForSelector('.answer__card');
    const sw2 = await mp.evaluate(() => document.documentElement.scrollWidth);
    check(sw2 <= 390, `390 px with an answer: no horizontal scroll (scrollWidth ${sw2})`);
    if (SHOTS) {
      await mp.locator('.party').first().scrollIntoViewIfNeeded();
      await mp.screenshot({ path: join(SHOTS_DIR, 'try-mobile.png') });
    }
    await axe(mp, 'mobile');
    check(offM.length === 0, `390 px: no request left ${BASE} (${seenM.length} requests)`);
    await mob.close();

    // ---- watchdog and Cancel ----------------------------------------------------------------------
    // ?watchdog-ms shortens the page's 120 s limit for this test; it changes a timer, not the CSP. The slow
    // file is one long run-on sentence of numbered obligations: within the size caps, but several seconds
    // of work in Pyodide.
    const seenS = [];
    const offS = [];
    const slowCtx = await browser.newContext({ viewport: { width: 1280, height: 800 } });
    await guard(slowCtx, seenS, offS);
    const sp = await slowCtx.newPage();
    const slowErrors = [];
    sp.on('pageerror', (e) => slowErrors.push(String(e)));
    await sp.goto(`${BASE}/try/?watchdog-ms=3000`);
    await sp.waitForSelector('body[data-engine="ready"]', { timeout: 180000 });
    const slow = { name: 'slow.txt', mimeType: 'text/plain', buffer: Buffer.from('the Vendor shall deliver the item within 30 days; '.repeat(16000)) };
    await sp.getByRole('button', { name: 'Load sample documents' }).click();
    await sp.waitForSelector('.item', { timeout: 60000 });
    await sp.setInputFiles('#file-input', slow);
    await sp.getByRole('button', { name: 'Cancel' }).waitFor({ timeout: 10000 });
    check(true, 'watchdog: Cancel shown while busy');
    await sp.locator('#add-status', { hasText: 'This document took too long to read in the browser. Try a smaller file, or install ClaimTrace.' })
      .waitFor({ timeout: 60000 });
    check(true, 'watchdog: a long call is stopped with the plain message');
    check(await sp.locator('body[data-engine="stopped"]').count() === 1, 'watchdog: the worker was terminated');
    check(!(await sp.getByRole('button', { name: 'Cancel' }).isVisible()), 'watchdog: Cancel hidden again');
    check(await sp.locator('.item').count() === 0, 'watchdog: the stale register is cleared');
    check(!(await sp.locator('#load-samples').isDisabled()), 'watchdog: actions are enabled again');
    await sp.getByRole('button', { name: 'Load sample documents' }).click();
    await sp.waitForSelector('.item', { timeout: 180000 });
    check(await sp.locator('body[data-engine="ready"]').count() === 1, 'watchdog: the next action restarts the engine and works');

    await sp.setInputFiles('#file-input', slow);
    await sp.getByRole('button', { name: 'Cancel' }).click();
    await sp.locator('#add-status', { hasText: /^Stopped\./ }).waitFor({ timeout: 10000 });
    check(await sp.locator('body[data-engine="stopped"]').count() === 1, 'cancel: the worker was terminated');
    check(await sp.locator('.item').count() === 0, 'cancel: the register is cleared');
    await sp.getByRole('button', { name: 'Load sample documents' }).click();
    await sp.waitForSelector('.item', { timeout: 180000 });
    check(await sp.locator('.item').count() >= 20, 'cancel: the next action restarts the engine and works');
    check(slowErrors.length === 0, `watchdog and cancel: no page errors${slowErrors.length ? ': ' + slowErrors.join(' | ') : ''}`);
    check(offS.length === 0, `watchdog and cancel: no request left ${BASE} (${seenS.length} requests)`);
    await slowCtx.close();
  } finally {
    await browser.close();
    if (server) server.kill();
  }
  console.log(JSON.stringify(report, null, 2));
  if (failures.length) {
    console.error(`\n${failures.length} failure(s)`);
    process.exit(1);
  }
  console.log('\nall try-page checks passed');
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
