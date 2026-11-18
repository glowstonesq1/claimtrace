// Captures real ClaimTrace UI (dark scheme, deviceScaleFactor 2) for the promo film.
// Needs a running server with an empty data dir:
//   CLAIMTRACE_DB=/tmp/ct.db claimtrace serve --port 8791
//   BASE=http://127.0.0.1:8791 NODE_PATH=$(npm root -g) node scripts/capture.cjs public/shots
// Writes PNG crops plus layout.json (element boxes in CSS px) next to them.
const { chromium } = require("playwright");
const fs = require("node:fs");
const out = process.argv[2] || "public/shots";
const BASE = process.env.BASE || "http://127.0.0.1:8791";
const layout = {};

async function shot(page, locator, name, pad = 0) {
  await page.evaluate(() => document.activeElement && document.activeElement.blur());
  await locator.scrollIntoViewIfNeeded();
  await page.waitForTimeout(250);
  const box = await locator.boundingBox();
  const clip = { x: Math.max(0, box.x - pad), y: Math.max(0, box.y - pad), width: box.width + pad * 2, height: box.height + pad * 2 };
  await page.screenshot({ path: `${out}/${name}.png`, clip });
  layout[name] = { w: Math.round(clip.width), h: Math.round(clip.height) };
  console.log("shot", name, layout[name]);
}

(async () => {
  fs.mkdirSync(out, { recursive: true });
  const b = await chromium.launch();
  const page = await b.newPage({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 2, colorScheme: "dark" });
  await page.goto(BASE + "/");
  await page.waitForTimeout(800);
  if (await page.getByRole("button", { name: "Load sample documents" }).isVisible().catch(() => false)) {
    await page.getByRole("button", { name: "Load sample documents" }).click();
    await page.getByRole("link", { name: "Master Services Agreement", exact: true }).waitFor({ timeout: 60000 });
  }
  await page.waitForTimeout(1500);
  // Hide focus rings (the app focuses <main> after navigation; distracting in a film).
  const noFocus = async () => page.addStyleTag({ content: ":focus,:focus-visible{outline:none!important}" });
  await noFocus();

  // 1. Library table
  await shot(page, page.locator("table").first(), "library", 0);

  // 2. Register: the replaced delivery date and the current one
  await page.getByRole("link", { name: "Master Services Agreement", exact: true }).click();
  await page.getByRole("heading", { level: 1, name: "Master Services Agreement" }).waitFor();
  await page.waitForTimeout(800);
  await noFocus();
  // current card from amendment
  const cur = page.locator("main article, main .card").filter({ hasText: "no later than May 15, 2026" }).first();
  await shot(page, cur, "register-current", 2);
  await page.getByLabel("Show").selectOption("changed");
  await page.waitForTimeout(600);
  const old = page.locator("main article, main .card").filter({ hasText: "no later than March 31, 2026" }).filter({ hasText: "Replaced" }).first();
  await shot(page, old, "register-replaced", 2);
  await old.getByRole("button", { name: "Show in document" }).first().click();
  await page.waitForTimeout(800);
  await page.evaluate(() => document.querySelector("aside mark")?.scrollIntoView({ block: "center" }));
  await page.waitForTimeout(300);
  await shot(page, page.locator("aside").first(), "source-mark", 0);

  // 3. Ask: empty question card, then the answer
  await page.getByRole("link", { name: "Ask" }).click();
  await page.getByLabel("Your question").waitFor();
  await noFocus();
  await page.evaluate(() => window.scrollTo(0, 0));
  await shot(page, page.locator("form.card"), "ask-form-empty", 0);
  const inputBox = await page.getByLabel("Your question").boundingBox();
  const formBox = await page.locator("form.card").boundingBox();
  layout["ask-input-offset"] = { x: inputBox.x - formBox.x, y: inputBox.y - formBox.y, w: inputBox.width, h: inputBox.height };
  await page.getByLabel("Your question").fill("Did the vendor promise delivery by March 31?");
  await page.getByRole("button", { name: "Ask", exact: true }).click();
  await page.getByText("Conflicting source:").waitFor({ timeout: 30000 });
  await page.waitForTimeout(600);
  await noFocus();
  const ans = page.locator("section.card").filter({ hasText: "Answer" }).first();
  // answer head: from heading through Sources quotes
  const ansBox = await ans.boundingBox();
  const where = await page.getByText("Where this comes from").boundingBox();
  await page.screenshot({ path: `${out}/answer-top.png`, clip: { x: ansBox.x, y: ansBox.y, width: ansBox.width, height: where.y - ansBox.y - 4 } });
  layout["answer-top"] = { w: Math.round(ansBox.width), h: Math.round(where.y - ansBox.y - 4) };
  // positions of the three quotes inside answer-top, for highlight overlays
  const qs = await ans.locator("blockquote").evaluateAll((els) => els.map((e) => { const r = e.getBoundingClientRect(); return { x: r.x, y: r.y, w: r.width, h: r.height }; }));
  layout["answer-quotes"] = qs.map((q) => ({ x: q.x - ansBox.x, y: q.y - ansBox.y, w: q.w, h: q.h }));

  // 4. Verify: contract vs delivery record, then contract vs audit report
  async function verify(otherLabel, prefix, needles) {
    await page.getByRole("link", { name: "Check documents" }).click();
    await page.getByLabel("Compare with").waitFor();
    await page.getByLabel("Main document (usually the contract)").selectOption({ label: "Master Services Agreement (v1.0)" }).catch(() => {});
    await page.getByLabel("Compare with").selectOption({ label: otherLabel });
    await page.getByRole("button", { name: "Check", exact: true }).click();
    await page.getByRole("heading", { name: /^Findings:/ }).waitFor({ timeout: 30000 });
    await page.waitForTimeout(800);
    await noFocus();
    for (const [needle, name] of needles) {
      const art = page.locator("article.card").filter({ hasText: needle }).first();
      await shot(page, art, `${prefix}-${name}`, 0);
    }
  }
  await verify("Phase 1 Delivery and Acceptance Record (v1.0)", "vdel", [["7 days late", "late"]]);
  await verify("Vendor Security Audit Report — Corvane Software Ltd. (v1.0)", "vaud", [
    ["Ireland", "location"],
    ["99.1%", "availability"],
  ]);

  fs.writeFileSync(`${out}/layout.json`, JSON.stringify(layout, null, 2));
  await b.close();
})();
