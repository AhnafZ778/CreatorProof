// Read-only checks against the configured, pre-assessed local collection.
import assert from "node:assert/strict";
import fs from "node:fs/promises";
import path from "node:path";

const { chromium } = await import(process.env.PLAYWRIGHT_MODULE_PATH || "playwright");
const base = process.env.STORED_CASES_WEB_URL || "http://localhost:3000";
assert(["localhost", "127.0.0.1"].includes(new URL(base).hostname));
const output = process.env.STORED_CASES_OUTPUT_DIR || "/tmp/creatorproof-ratings-browser";
await fs.mkdir(output, { recursive: true });
const browser = await chromium.launch({ executablePath: process.env.PLAYWRIGHT_CHROMIUM_PATH || undefined, args: ["--no-sandbox"] });
const context = await browser.newContext({ viewport: { width: 1440, height: 1100 } });
const page = await context.newPage();
const errors = [], mutations = [], checks = [], measurements = [];
page.on("pageerror", error => errors.push(error.message));
page.on("request", request => { if (!["GET", "HEAD"].includes(request.method()) && request.url().includes("/api/")) mutations.push(request.url()); });
const checked = text => { checks.push(text); console.log(`PASS ${text}`); };
try {
  const response = await context.request.get(`${base}/api/admin/stored-cases?limit=200`);
  assert(response.ok());
  const cases = await response.json();
  assert.equal(cases.length, 3);
  for (const row of cases) {
    const result = await context.request.get(`${base}/api/phase1/scans/${row.scan_id}/evidence-matrix`);
    assert(result.ok());
    const matrix = await result.json();
    const ratings = Object.fromEntries(Object.entries(matrix.assessment.lanes).map(([lane, value]) => [lane, value.rating]));
    assert(matrix.assessment_source.refreshed);
    assert(ratings.COPY.conclusive);
    assert.equal(ratings.INTEGRITY.grade, "Hash verified");
    assert.equal(typeof ratings.ORIGIN.value, "number");
    assert.equal(ratings.PROVENANCE.display, row.stored_case.comparison_kind === "AI_EDIT" ? "Valid" : "0");
    assert(matrix.assessment_signals.every(signal => signal.scan_id === matrix.assessment_source.scan_id));
    measurements.push({ comparison_kind: row.stored_case.comparison_kind, ratings });
  }
  checked("All three stored comparisons expose measured, hash-bound assessments and original records");
  await page.goto(`${base}/admin`);
  await page.locator(".storedCaseCard").first().waitFor({ timeout: 30000 });
  await page.getByRole("button", { name: "AI edits", exact: true }).click();
  await page.locator(".storedCaseCard").click();
  await page.getByRole("heading", { name: "Why this needs review", exact: true }).waitFor();
  await page.getByRole("tab", { name: "Detailed evidence", exact: true }).click();
  await page.locator(".cpLaneRating").first().waitFor({ timeout: 30000 });
  await page.getByRole("heading", { name: "Registered artwork reuse confirmed", exact: true }).waitFor();
  assert.equal(await page.locator(".cpLaneRating").count(), 8);
  assert.equal(await page.locator(".cpLaneGrid .cpStatus").count(), 0);
  const ai = measurements.find(row => row.comparison_kind === "AI_EDIT");
  const values = await page.locator(".cpRatingValue").allTextContents();
  assert.deepEqual(values, Object.values(ai.ratings).map(rating => rating.display + (rating.scale === 100 ? "/100" : "")));
  const headings = await page.locator(".cpLaneGrid h3").evaluateAll(nodes => nodes.slice(0, 4).map(node => node.getBoundingClientRect().top));
  assert(Math.max(...headings) - Math.min(...headings) <= 2, "Card headings must align");
  await page.locator(".cpLaneGrid").screenshot({ path: path.join(output, "ratings-desktop.png") });
  checked("Eight aligned rating cards display exactly the saved measurements with a clear reuse verdict");
  await page.locator(".cpLaneGrid > button").nth(1).click();
  await page.locator(".cpSignalDetail > .cpDetails > summary").click();
  assert((await page.locator(".cpSignalDetail").innerText()).includes("Origin assessment"));
  const details = await page.locator(".cpSignalDetail").innerText();
  assert(details.toLowerCase().includes("sightengine") || details.toLowerCase().includes("community"));
  checked("AI measurements retain detailed model results and provider receipts");
  for (const width of [390, 640, 1024, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), `Overflow at ${width}`);
  }
  await page.setViewportSize({ width: 390, height: 844 });
  await page.evaluate(() => window.scrollTo({ top: document.querySelector(".cpLaneGrid").getBoundingClientRect().top + scrollY - 110, behavior: "instant" }));
  await page.screenshot({ path: path.join(output, "ratings-mobile.png") });
  checked("Rating cards and receipts fit mobile, tablet and desktop widths");
  await page.reload();
  await page.locator(".storedCaseCard").first().waitFor();
  assert.equal(await page.locator(".storedCaseCard").count(), 3);
  assert.deepEqual(errors, []);
  assert.deepEqual(mutations, []);
  checked("Saved cases survive reload and presentation issues no API mutations or browser errors");
  await fs.writeFile(path.join(output, "verification.json"), JSON.stringify({ checks, measurements, browser_errors: errors, mutations }, null, 2));
} finally { await browser.close(); }
