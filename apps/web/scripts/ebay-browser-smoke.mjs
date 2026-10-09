// Use ebay-fixture-api.py and a separate Next server; no real-provider requests.
import assert from "node:assert/strict";
import fs from "node:fs/promises";
import path from "node:path";
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE_PATH || "playwright");
const base = process.env.FRONTEND_FIXTURE_WEB_URL || "http://localhost:3011";
assert(["localhost", "127.0.0.1"].includes(new URL(base).hostname));
const root = process.env.FRONTEND_FIXTURE_DIR;
assert(root, "Set FRONTEND_FIXTURE_DIR to the isolated API fixture directory");
const browser = await chromium.launch({ executablePath: process.env.PLAYWRIGHT_CHROMIUM_PATH || undefined, args: ["--no-sandbox"] });
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
const page = await context.newPage();
const errors = [];
page.on("pageerror", error => errors.push(error.message));
const checks = [];
const checked = name => { checks.push(name); console.log(`PASS ${name}`); };
try {
  const works = await (await context.request.get(`${base}/api/works?catalog_id=default`)).json();
  if (!works.length) {
  const registration = await context.request.post(`${base}/api/works`, {
    headers: { Origin: base },
    multipart: { catalog_id: "default", title: "Fixture artist original", file: { name: "artwork.png", mimeType: "image/png", buffer: await fs.readFile(path.join(root, "artwork.png")) } },
  });
  assert.equal(registration.status(), 201, await registration.text());
  }
  await page.goto(`${base}/user`);
  const monitor = page.locator(".marketplaceMonitor");
  await monitor.getByLabel("Source", { exact: true }).selectOption("ebay");
  await monitor.getByLabel("Catalog", { exact: true }).fill("default");
  await monitor.getByText("Sandbox test listings", { exact: false }).waitFor();
  await monitor.getByRole("button", { name: "Search source", exact: true }).click();
  await monitor.getByText("Sandbox artwork listing", { exact: true }).waitFor();
  await monitor.getByText("Seller fixture-seller", { exact: true }).waitFor();
  await monitor.getByText("eBay · Sandbox", { exact: true }).last().waitFor();
  checked("User source selector and listing cards identify eBay sandbox and seller");
  const scanResponse = page.waitForResponse(response => response.url().endsWith("/api/marketplaces/scan"));
  await monitor.getByRole("button", { name: "Scan this image", exact: true }).click();
  const scanned = await scanResponse;
  assert.equal(scanned.status(), 202, await scanned.text());
  assert.equal((await scanned.json()).scan.match_status, "MATCH_FOUND");
  checked("User-selected eBay photo matches the registered artwork through the real scan API");
  await monitor.getByLabel("Search", { exact: true }).fill("invalid-key");
  await monitor.getByRole("button", { name: "Search source", exact: true }).click();
  await monitor.getByText("The provider rejected the API key or permissions.", { exact: true }).waitFor();
  checked("Structured provider errors are visible to the user");
  await monitor.getByLabel("Search", { exact: true }).fill("no-photos");
  await monitor.getByRole("button", { name: "Search source", exact: true }).click();
  await monitor.getByText("No listings with usable photos", { exact: false }).waitFor();
  checked("Empty sandbox inventory explains how to obtain test images");
  await page.goto(`${base}/admin`);
  await page.getByRole("tab", { name: "Monitoring", exact: true }).click();
  const adminMonitor = page.locator("#admin-monitor");
  await adminMonitor.getByLabel("Image source", { exact: true }).selectOption("ebay");
  await adminMonitor.getByText("Sandbox test listings", { exact: false }).waitFor();
  await page.clock.install();
  let calls = 0;
  page.on("request", request => { if (request.method() === "POST" && request.url().endsWith("/api/admin/marketplaces/monitor")) calls++; });
  await adminMonitor.getByRole("button", { name: "Start monitor", exact: false }).click();
  await page.clock.runFor(59_000);
  assert.equal(calls, 0);
  for (let i = 0; i < 3; i++) {
    const responsePromise = page.waitForResponse(response => response.url().endsWith("/api/admin/marketplaces/monitor") && response.request().method() === "POST");
    await page.clock.runFor(i === 0 ? 1001 : 60_100);
    const response = await responsePromise;
    assert.equal(response.status(), 200, await response.text());
    const body = await response.json();
    assert.equal(body.new_images.length, i === 0 ? 1 : 0);
    assert.equal(body.duplicate_count, i === 0 ? 0 : 1);
    assert.equal(body.history.length, 1);
    assert.equal(body.history[0].classification, "COPIED");
    assert.equal(body.history[0].country_code, null);
    await page.waitForTimeout(150);
  }
  assert.equal(calls, 3);
  checked("Admin waits 60s then continues checking; repeated listings retain one copied-image record");
  await adminMonitor.getByRole("button", { name: "Pause monitor", exact: false }).click();
  await page.clock.runFor(120_000);
  assert.equal(calls, 3);
  checked("Pausing the monitor stops subsequent requests");
  await fs.mkdir(path.join(root, "screenshots"), { recursive: true });
  await adminMonitor.screenshot({ path: path.join(root, "screenshots", "ebay-admin-desktop.png") });
  await page.setViewportSize({ width: 390, height: 844 });
  await adminMonitor.screenshot({ path: path.join(root, "screenshots", "ebay-admin-mobile.png") });
  assert(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1), "Mobile layout must not overflow");
  assert.deepEqual(errors, []);
  checked("Desktop/mobile layout has no overflow or browser exceptions");
  await fs.writeFile(path.join(root, "ebay-browser-results.json"), JSON.stringify({ passed: checks.length, checks }, null, 2));
} finally { await browser.close(); }
