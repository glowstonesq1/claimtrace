// Evidence page end-to-end + accessibility. Serve apps/site statically, then:
//   python -m http.server 8766 -d apps/site &   BASE=http://127.0.0.1:8766 node apps/site/evidence/e2e.mjs [shotsDir]
// playwright and axe-core resolve from apps/web/node_modules (CI's web job installs them there), else NODE_PATH.
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";

const fromWeb = createRequire(new URL("../../web/package.json", import.meta.url));
const local = createRequire(import.meta.url);
const need = (id) => { try { return fromWeb(id); } catch { return local(id); } };
const resolve = (id) => { try { return fromWeb.resolve(id); } catch { return local.resolve(id); } };
const { chromium } = need("playwright");
const axeSource = readFileSync(resolve("axe-core/axe.min.js"), "utf8");

const BASE = (process.env.BASE ?? "http://127.0.0.1:8766").replace(/\/$/, "");
const URL_ = `${BASE}/evidence/`;
const shots = process.argv[2];
const failures = [];
const check = (cond, msg) => { if (!cond) failures.push(msg); console.log(`${cond ? "ok  " : "FAIL"} ${msg}`); };

async function axe(page, name) {
  await page.addScriptTag({ content: axeSource });
  const res = await page.evaluate(async () => await window.axe.run(document, { resultTypes: ["violations"], preload: false }));
  const serious = res.violations.filter((v) => ["serious", "critical"].includes(v.impact));
  check(serious.length === 0, `axe: no serious/critical violations on ${name}` +
    (serious.length ? ` — ${serious.map((v) => `${v.id} (${v.nodes.length}: ${v.nodes[0].target})`).join(", ")}` : ""));
}

async function noHorizontalScroll(page, name) {
  const { sw, iw } = await page.evaluate(() => ({ sw: document.documentElement.scrollWidth, iw: window.innerWidth }));
  check(sw <= iw, `no horizontal page scroll on ${name} (${sw} <= ${iw})`);
}

function watch(page, errors) {
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("console", (m) => { if (m.type() === "error" && !/Failed to load resource/.test(m.text())) errors.push(m.text()); });
  page.on("response", (r) => { if (r.status() >= 400 && !r.url().endsWith("/favicon.ico")) errors.push(`${r.status()} ${r.url()} (from ${r.request().headers().referer ?? "?"}, page ${page.url()})`); });
  page.on("request", (r) => { if (!r.url().startsWith(BASE) && !r.url().startsWith("data:")) errors.push(`external request ${r.url()}`); });
}

const browser = await chromium.launch();
// bypassCSP only lets the test inject axe; the page's own CSP (no inline script) is unchanged.
const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 }, deviceScaleFactor: 2, bypassCSP: true });
const page = await ctx.newPage();
const errors = [];
watch(page, errors);

await page.goto(URL_);
await page.keyboard.press("Tab");
check(await page.getByText("Skip to content").isVisible(), "skip link appears on first Tab");
check(await page.getByRole("heading", { name: "Check our numbers", level: 1 }).isVisible(), "hero heading visible");
const lead = page.locator(".ev-answer--lead");
check(await lead.getByRole("heading", { name: "How good is it at amendments?" }).isVisible(), "amendment answer is shown first");
check((await lead.locator(".ev-answer__figure").textContent()).trim() === "0.60", "amendment verdict accuracy reads 0.60");
check(/Wrong 4 in 10/.test(await lead.textContent()), "the page says wrong 4 in 10");
for (const q of ["How often does it make things up?", "How often does it wrongly say everything is fine?", "Where is it no better than a simple baseline?"]) {
  check(await page.getByRole("heading", { name: q }).isVisible(), `answer: ${q}`);
}
if (shots) {
  await page.evaluate(() => document.activeElement && document.activeElement.blur());
  await page.screenshot({ path: `${shots}/evidence-top.png` });
}

// Chart: holdout first, then switch to the amendments set.
check(await page.locator('.ev-set[data-set="holdout"]').isVisible(), "holdout chart shown by default");
check(!(await page.locator('.ev-set[data-set="core"]').isVisible()), "other sets hidden behind the switch");
await page.locator("[data-switch]").getByText("Amendments", { exact: true }).click();
check(await page.locator('.ev-set[data-set="amendments-v2"]').isVisible(), "switch shows the amendments chart");
check(await page.locator('.ev-set[data-set="amendments-v2"] .ev-panel').count() >= 4, "amendments chart has its metric panels");
await page.locator('[data-switch] input[value="holdout"]').check();
if (shots) {
  const box = await page.locator("#metrics").boundingBox();
  await page.screenshot({ path: `${shots}/evidence-metrics.png`, fullPage: true,
    clip: { x: box.x, y: box.y, width: box.width, height: Math.min(box.height, 1300) } });
}

// Case browser: failed amendment cases for Rules v0.2, then open one.
await page.locator("[data-count]").filter({ hasText: /\d+ cases?/ }).waitFor();
const form = page.locator("[data-filters]");
await form.getByLabel("Set").selectOption("amendments-v2");
await form.getByLabel("Suite").selectOption("amendment");
await form.getByLabel("Result").selectOption("fail");
const count = await page.locator("[data-count]").textContent();
check(/^32 cases/.test(count), `filtered to failed amendment cases (${count.trim()})`);
check(await page.locator(".cb__item").count() === 20, "first page renders 20 rows, not all of them");
check(await page.locator(".cb__item .verdict--pass").count() === 0, "every listed case failed");
const first = page.locator(".cb__item a").first();
const firstId = (await first.locator(".cb__id").textContent()).trim();
await first.click();
await page.waitForURL(new RegExp(`#case=${firstId}$`));
const detail = page.locator("[data-detail]");
await detail.locator("h3").filter({ hasText: firstId }).waitFor({ timeout: 5000 }).catch(() => undefined);
check(await detail.getByRole("heading", { name: firstId }).isVisible(), `opened case ${firstId}`);
check(await detail.getByText("Failed with Rules v0.2.").isVisible(), "detail says it failed with Rules v0.2");
check(await detail.locator(".cb__verdict li").count() > 0, "detail says why it failed");
check(await detail.locator("mark").count() > 0, "the gold clause is highlighted in the document");
check(await detail.getByRole("columnheader", { name: "Right answer" }).first().isVisible(), "detail shows the right answer");
await page.getByRole("button", { name: "Next" }).click();
check(/Page 2 of 2/.test(await page.locator("[data-page]").textContent()), "pagination reaches page 2");
await axe(page, "evidence page with a case open (1280)");
if (shots) await detail.screenshot({ path: `${shots}/evidence-case.png` });

// Deep link, in a fresh page.
const deep = await ctx.newPage();
watch(deep, errors);
await deep.goto(`${URL_}#case=v2-sub-01`);
const deepOk = await deep.locator("[data-detail] h3").filter({ hasText: "v2-sub-01" }).waitFor({ timeout: 5000 }).then(() => true, () => false);
check(deepOk, "deep link #case=v2-sub-01 opens that case");
await deep.goto(`${URL_}#case=amd-003`);
await deep.locator("[data-detail] h3").filter({ hasText: "amd-003" }).waitFor({ timeout: 5000 }).catch(() => undefined);
check(await deep.locator("[data-detail] h3").textContent() === "amd-003", "changing the hash opens another case");
await deep.goto(`${URL_}#case=h-zz-999`);
await deep.locator("[data-detail]").getByText("Holdout cases are sealed").waitFor({ timeout: 5000 }).catch(() => undefined);
check(await deep.locator("[data-detail]").getByText("Holdout cases are sealed").isVisible(), "an unknown (e.g. holdout-style) id shows only the sealing note");

// Phone width.
const phone = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, bypassCSP: true, isMobile: true, hasTouch: true });
const m = await phone.newPage();
watch(m, errors);
await m.goto(`${URL_}#case=v2-sub-01`);
await m.locator("[data-detail] h3").waitFor();
await noHorizontalScroll(m, "390px with a case open");
await axe(m, "evidence page (390)");
await m.evaluate(() => window.scrollTo(0, 0));
if (shots) await m.screenshot({ path: `${shots}/evidence-phone.png` });

// Without JavaScript: the static summary and tables are there.
const nojs = await browser.newContext({ javaScriptEnabled: false, viewport: { width: 1280, height: 900 } });
const n = await nojs.newPage();
await n.goto(URL_);
check(await n.locator(".ev-answer--lead .ev-answer__figure").textContent() === "0.60", "no JS: the headline answers are in the HTML");
check(await n.locator(".ev-table table").count() >= 4, "no JS: the metric tables are in the HTML");
check(await n.locator(".ev-set").evaluateAll((els) => els.every((e) => e.offsetParent !== null)), "no JS: every set's chart is shown");
check(await n.getByText("The case browser needs JavaScript").isVisible(), "no JS: the case browser says it needs JavaScript");

// Reduced motion: nothing animates.
const calm = await browser.newContext({ reducedMotion: "reduce", viewport: { width: 1280, height: 900 } });
const c = await calm.newPage();
await c.goto(`${URL_}#case=amd-001`);
await c.locator("[data-detail] h3").waitFor();
check(await c.evaluate(() => document.getAnimations().every((a) => Number(a.effect?.getTiming().duration ?? 0) <= 1)),
  "reduced motion: no animation or transition longer than 1 ms");

check(errors.length === 0, `no page errors or external requests${errors.length ? ` — ${errors.join("; ")}` : ""}`);
await browser.close();
if (failures.length) { console.error(`\n${failures.length} failure(s)`); process.exit(1); }
console.log("\nall evidence checks passed");
