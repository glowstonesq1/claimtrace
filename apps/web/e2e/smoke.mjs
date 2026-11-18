// End-to-end smoke test: real server + real browser. Usage: BASE=http://127.0.0.1:8765 node e2e/smoke.mjs [shotsDir]
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";


const require = createRequire(import.meta.url);
const { chromium } = require("playwright"); // CJS resolution honours NODE_PATH (CI installs it locally)
const axeSource = readFileSync(require.resolve("axe-core/axe.min.js"), "utf8");
const BASE = process.env.BASE ?? "http://127.0.0.1:8765";
const shots = process.argv[2];
const failures = [];
const check = (cond, msg) => { if (!cond) failures.push(msg); console.log(`${cond ? "ok  " : "FAIL"} ${msg}`); };

async function axe(page, name) {
  await page.addScriptTag({ content: axeSource });
  const res = await page.evaluate(async () => await window.axe.run(document, { resultTypes: ["violations"] }));
  const serious = res.violations.filter((v) => ["serious", "critical"].includes(v.impact));
  check(serious.length === 0, `axe: no serious/critical violations on ${name}` +
    (serious.length ? ` — ${serious.map((v) => `${v.id} (${v.nodes.length})`).join(", ")}` : ""));
}

const browser = await chromium.launch();
// bypassCSP only lets the test inject axe; the app's CSP (which blocks inline scripts) is unchanged.
const page = await browser.newPage({ viewport: { width: 1280, height: 900 }, bypassCSP: true });
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));
page.on("requestfailed", (r) => { if (!r.url().startsWith(BASE)) errors.push(`external request ${r.url()}`); });
page.on("request", (r) => { if (!r.url().startsWith(BASE) && !r.url().startsWith("data:")) errors.push(`external request ${r.url()}`); });

await page.goto(BASE + "/");
check(await page.getByText("not legal advice").isVisible(), "disclaimer banner visible");
await page.keyboard.press("Tab");
check(await page.getByText("Skip to content").isVisible(), "skip link appears on first Tab");
if (await page.getByRole("button", { name: "Load sample documents" }).isVisible().catch(() => false)) {
  await page.getByRole("button", { name: "Load sample documents" }).click();
  await page.getByRole("link", { name: "Master Services Agreement", exact: true }).waitFor();
}
await axe(page, "Documents");
if (shots) await page.screenshot({ path: `${shots}/1-library.png`, fullPage: true });

await page.getByRole("link", { name: "Master Services Agreement", exact: true }).click();
await page.getByRole("heading", { level: 1, name: "Master Services Agreement" }).waitFor();
check(await page.getByText("From amendment").first().isVisible(), "amendment-sourced commitments shown in register");
await page.getByLabel("Show").selectOption("changed");
check((await page.getByText("Replaced by amendment").count()) >= 3, "replaced commitments listed under 'Replaced or deleted'");
await page.getByRole("button", { name: "Show in document" }).first().click();
check(await page.locator("aside mark").isVisible(), "quote highlighted in document text");
await axe(page, "Document");
if (shots) await page.screenshot({ path: `${shots}/2-document.png`, fullPage: false });

// Relationship graph: one tab stop, arrow keys follow links, Enter shows the source text.
await page.getByRole("tab", { name: "Relationships" }).click();
const firstNode = page.locator(".graph [data-node]").first();
await firstNode.waitFor();
check((await page.locator('.graph [data-node][tabindex="0"]').count()) === 1, "graph has a single tab stop");
await firstNode.focus();
await page.keyboard.press("ArrowRight");
const focused = await page.evaluate(() => document.activeElement?.getAttribute("aria-label") ?? "");
check(/^§/.test(focused), "ArrowRight moves from a party to a connected commitment");
await page.keyboard.press("Enter");
check(await page.locator("aside mark").isVisible(), "Enter on a graph node highlights its source text");
check((await page.locator("table").count()) > 0, "relationship list fallback still shown");
await axe(page, "Document relationships");

await page.getByRole("link", { name: "Ask" }).click();
await page.getByLabel("Your question").fill("What is the liability cap?");
await page.getByRole("button", { name: "Ask", exact: true }).click();
await page.getByText("I could not find support for this in the uploaded documents.").waitFor();
check(true, "not-found answer uses exact wording");
await page.getByLabel("Your question").fill("Is customer data kept in the UK?");
await page.getByRole("button", { name: "Ask", exact: true }).click();
await page.getByText("Documents disagree", { exact: true }).waitFor();
check(await page.getByText("Conflicting source:").isVisible(), "conflicting quote shown with label");
await axe(page, "Ask");
if (shots) await page.screenshot({ path: `${shots}/3-ask.png`, fullPage: true });

await page.getByRole("link", { name: "Check documents" }).click();
await page.getByLabel("Compare with").selectOption({ label: "Vendor Security Audit Report — Corvane Software Ltd. (v1.0)" });
await page.getByRole("button", { name: "Check", exact: true }).click();
await page.getByRole("heading", { name: /^Findings:/ }).waitFor();
check((await page.locator("article .badge", { hasText: "Conflicts" }).count()) >= 2, "verification shows conflicts");
check(await page.getByText("You decide").first().isVisible(), "evidence sufficiency left to the reviewer");
page.once("dialog", (d) => d.accept("E2E Reviewer"));
await page.getByRole("button", { name: "Looks right" }).first().click();
await page.getByText("Saved.").first().waitFor();
check(true, "review decision saved");
await axe(page, "Check documents");
if (shots) await page.screenshot({ path: `${shots}/4-verify.png`, fullPage: false });

check(errors.length === 0, `no page errors or external requests${errors.length ? `: ${errors.join("; ")}` : ""}`);
await browser.close();
if (failures.length) { console.error(`${failures.length} check(s) failed`); process.exit(1); }
console.log("E2E passed");
