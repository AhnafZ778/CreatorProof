// Run only against phase1-fixture-api.py and a separate Next development server.
// PLAYWRIGHT_MODULE_PATH points to an installed Playwright module (not a runtime dependency).
import assert from "node:assert/strict";
import fs from "node:fs/promises";
import path from "node:path";
const { chromium } = await import(process.env.PLAYWRIGHT_MODULE_PATH || "playwright");
const base = process.env.FRONTEND_FIXTURE_WEB_URL || "http://localhost:3011";
assert(["localhost", "127.0.0.1"].includes(new URL(base).hostname), "Use an isolated local fixture server.");
const fixture = process.env.FRONTEND_FIXTURE_DIR;
assert(fixture, "FRONTEND_FIXTURE_DIR is required");
const screenshots = path.join(fixture, "screenshots");
await fs.mkdir(screenshots, { recursive: true });
const browser = await chromium.launch({ executablePath: process.env.PLAYWRIGHT_CHROMIUM_PATH || undefined, args: ["--no-sandbox"] });
const context = await browser.newContext({ httpCredentials: { username: "fixture", password: "frontend-fixture-password" }, viewport: { width: 1440, height: 1000 } });
const page = await context.newPage();
const browserErrors = [];
page.on("pageerror", e => browserErrors.push(e.message));
const checks = [];
function checked(name) { checks.push(name); console.log(`PASS ${name}`); }
async function visible(text) { await page.getByText(text, { exact: false }).first().waitFor({ state: "visible", timeout: 30000 }); }
async function responseJSON(url, options) { const response = await context.request.fetch(`${base}${url}`, options); assert(response.ok(), `${url}: ${response.status()} ${await response.text()}`); return response.json(); }
async function screenshot(name, locator) { await (locator || page).screenshot({ path: path.join(screenshots, `${name}.png`), ...(locator ? { style: ".portalNav { visibility: hidden !important; }" } : { fullPage: true }) }); }
try {
  const anon = await browser.newContext();
  for (const route of ["/artist", "/user", "/admin", "/api/works", "/api/phase1/works/private/rights-policy"]) assert.equal((await anon.request.get(`${base}${route}`)).status(), 401);
  assert.equal((await anon.request.get(`${base}/api/public-verification/${"A".repeat(64)}`)).status(), 404);
  assert.equal((await anon.request.get(`${base}/api/public-verification/invalid`)).status(), 401);
  checked("Private portals and API require authentication; only exact public token routes are exempt");
  assert.equal((await context.request.post(`${base}/api/phase1/works/fake/rights-policy`, { headers: { Origin: "https://foreign.example" }, data: {} })).status(), 403);
  assert.equal((await context.request.get(`${base}/api/phase1/admin/credentials`)).status(), 404);
  checked("CSRF and finite gateway boundaries");

  await page.goto(`${base}/artist`);
  const catalog = `frontend-fixture-${Date.now()}`;
  await page.getByLabel("Catalog", { exact: true }).fill(catalog);
  await page.getByLabel("Title", { exact: true }).fill("Blue study · frontend validation");
  await page.getByLabel("Artist / claimant name", { exact: true }).fill("Fixture artist");
  await page.locator('input[type="file"]').setInputFiles(path.join(fixture, "artwork.png"));
  await page.getByRole("button", { name: "Register reference", exact: true }).click();
  await visible("Work registered.");
  const works = await responseJSON("/api/works");
  const work = works.find(w => w.catalog_id === catalog);
  assert(work?.id);
  await visible("AI Rights Passport");
  checked("Artist registration opens a real server-backed artwork workspace");
  await page.getByRole("button", { name: "Allow discovery; license other uses", exact: true }).click();
  await page.getByLabel("Licensing contact", { exact: true }).fill("mailto:fixture@example.com");
  await page.getByLabel("Require attribution", { exact: true }).selectOption("true");
  await page.getByLabel("Attribution text", { exact: true }).fill("Artwork by Fixture artist");
  await page.getByRole("button", { name: "Save new policy version", exact: true }).click();
  await visible("Version 2 saved.");
  const passport = await responseJSON(`/api/phase1/works/${work.id}/rights-policy`);
  assert.equal(passport.policy.policy_version, 2);
  assert.equal(passport.policy.permissions.search_indexing_permission, "ALLOW");
  assert.equal(passport.policy.permissions.AI_training_permission, "LICENSE_REQUIRED");
  await page.getByLabel("Policy version", { exact: true }).fill("1");
  await page.getByRole("button", { name: "View version", exact: true }).click();
  await visible("Saved version 1");
  await page.getByRole("button", { name: "Close history", exact: true }).click();
  await screenshot("artist-passport", page.locator("#artwork-workspace"));
  checked("All permission controls save a new policy version and history remains readable");

  await page.getByRole("tab", { name: "Creation history", exact: true }).click();
  await page.getByLabel("Describe this step", { exact: true }).fill("Drew the blue geometry and orange circle by hand.");
  await page.getByLabel("Contribution description", { exact: true }).selectOption("HUMAN_CREATED");
  await page.getByLabel("Your decision or contribution", { exact: true }).fill("Selected the composition and contrast.");
  await page.getByRole("button", { name: "Add event to history", exact: true }).click();
  await visible("Creation event saved.");
  await page.getByRole("button", { name: "Verify history", exact: true }).click();
  await visible("recorded hash chain is consistent");
  const ledger = await responseJSON(`/api/phase1/works/${work.id}/contributions`);
  assert.equal(ledger.events.length, 1); assert.equal(ledger.verification.valid, true);
  await screenshot("artist-history", page.locator("#artwork-workspace"));
  checked("Creation events persist with a verified append-only chain");

  await page.getByRole("tab", { name: "Provenance", exact: true }).click();
  await page.getByRole("button", { name: /Inspect .*again|Inspect stored/ }).click();
  await page.locator("#work-panel-provenance .cpProvenanceHero").waitFor();
  const provenance = await responseJSON(`/api/phase1/works/${work.id}/provenance`);
  assert.equal(provenance.status, "PROVIDER_UNAVAILABLE");
  await screenshot("artist-provenance", page.locator("#artwork-workspace"));
  checked("Missing provenance providers are shown as unavailable rather than human-authored");

  await page.getByRole("tab", { name: "Share & export", exact: true }).click();
  for (const name of ["Rights Passport", "AI preferences", "ai.txt fragment", "TDM policy", "Rights statement"]) {
    const downloadEvent = page.waitForEvent("download");
    await page.locator(".cpExportGrid").getByRole("button", { name: new RegExp(name.replaceAll(".", "\\.")) }).click();
    const download = await downloadEvent; assert.equal(await download.failure(), null);
  }
  await page.getByRole("button", { name: "Create verification link", exact: true }).click();
  await visible("verification link is ready");
  const url = await page.getByLabel("Public verification link", { exact: true }).inputValue();
  const token = new URL(url).pathname.split("/").at(-1);
  const publicPage = await anon.newPage(); await publicPage.goto(url);
  await publicPage.getByText("Public record available", { exact: true }).waitFor({ state: "visible" });
  const publicRead = await anon.request.get(`${base}/api/public-verification/${token}`);
  assert.equal(publicRead.status(), 200); assert(!JSON.stringify(await publicRead.json()).includes("fixture@example.com"));
  assert.equal(publicRead.headers()["referrer-policy"], "no-referrer");
  assert(publicRead.headers()["cache-control"].includes("no-store"));
  await screenshot("artist-share", page.locator("#artwork-workspace"));
  await publicPage.screenshot({ path: path.join(screenshots, "public-record.png"), fullPage: true });
  await page.reload(); await page.getByRole("tab", { name: "Share & export", exact: true }).click();
  await page.getByRole("button", { name: "Revoke", exact: true }).click(); await visible("Link revoked.");
  assert.equal((await anon.request.get(`${base}/api/public-verification/${token}`)).status(), 410);
  await publicPage.reload(); await publicPage.getByText(/expired|revoked/i).first().waitFor({ state: "visible" });
  await anon.close();
  checked("Five real exports, scoped anonymous verification, private-contact exclusion, and revocation after reload");
  await page.getByRole("tab", { name: "Rights Passport", exact: true }).click(); await visible("Version 2");
  await page.getByRole("button", { name: "Withdraw this policy", exact: true }).click();
  await page.getByRole("button", { name: "Confirm withdrawal", exact: true }).click(); await visible("Version 3 saved.");
  assert.equal((await responseJSON(`/api/phase1/works/${work.id}/rights-policy`)).policy.state, "REVOKED");
  await page.getByText("Scope, consent & effective dates", { exact: true }).click();
  await page.getByLabel("Policy revocation status", { exact: true }).selectOption("NOT_REVOKED");
  await page.getByLabel("Consent status", { exact: true }).selectOption("GRANTED");
  await page.getByLabel("Consent source", { exact: true }).fill("Fixture artist's recorded authorization");
  await page.locator('input[name="consent_timestamp"]').fill(new Date(Date.now() - 86400000).toISOString().slice(0, 16));
  await page.getByRole("button", { name: "Save new policy version", exact: true }).click(); await visible("Version 4 saved.");
  checked("Withdrawal and explicit reissue preserve earlier policy versions");

  await page.goto(`${base}/user`);
  await page.locator('form.scanCard input[name="catalog_id"]').fill(catalog);
  await page.locator('input[type="file"]').setInputFiles(path.join(fixture, "artwork.png"));
  await page.getByLabel("Your country", { exact: true }).selectOption("US");
  await page.getByLabel("Publication country", { exact: true }).fill("DE");
  await page.getByLabel("Publication channel", { exact: true }).fill("web");
  await page.getByLabel("Audience", { exact: true }).fill("public");
  await page.getByLabel("Artist permission to check", { exact: true }).selectOption("search_indexing_permission");
  const scanResponse = page.waitForResponse(r => r.url() === `${base}/api/scans` && r.request().method() === "POST");
  await page.getByRole("button", { name: "Run CreatorProof analysis", exact: true }).click();
  const submitted = await scanResponse; assert(submitted.ok(), await submitted.text()); const scanId = (await submitted.json()).id;
  await page.locator(".cpMatrix").waitFor({ timeout: 45000 });
  await page.locator(".cpLaneGrid > button").first().waitFor({ timeout: 30000 });
  const scan = await responseJSON(`/api/scans/${scanId}`);
  assert.equal(scan.state, "COMPLETED"); assert.equal(scan.match_status, "MATCH_FOUND");
  const serialized = JSON.stringify(scan.evidence_packet);
  assert(serialized.includes('"territory":"DE"')); assert(serialized.includes('"channel":"web"'));
  assert.equal(await page.locator(".cpLaneGrid > button").count(), 8);
  await screenshot("user-evidence", page.locator(".cpMatrix"));
  checked("Real exact-copy scan retains declared use separately from notice country and shows eight evidence lanes");
  assert.equal((await context.request.get(`${base}/api/scans/${scanId}/media`)).status(), 404);
  await page.getByRole("button", { name: "Inspect image again", exact: true }).click();
  await visible("candidate image is no longer retained");
  const persistedProvenance = await responseJSON(`/api/phase1/scans/${scanId}/provenance`);
  assert.equal(persistedProvenance.status, "PROVIDER_UNAVAILABLE");
  await page.getByRole("button", { name: "Create verification link", exact: true }).click();
  await visible("verification link is ready");
  const scanUrl = await page.getByLabel("Public verification link", { exact: true }).inputValue();
  const publicScan = await (await context.request.get(`${base}/api/public-verification/${new URL(scanUrl).pathname.split("/").at(-1)}`)).json();
  assert.equal(publicScan.rights_policy_summary.temporal_binding, "AS_OF_SCAN");
  assert(publicScan.packet_hash_sha256);
  checked("Expired candidate media remains unavailable while stored provenance and scan-time public evidence remain readable");

  await page.goto(`${base}/admin`);
  await page.locator(".adminDetectionList > button").first().click();
  await page.locator(".cpMatrix").waitFor();
  await page.locator(".cpLaneGrid > button").first().waitFor({ timeout: 30000 });
  assert.equal(await page.locator(".cpLaneGrid > button").count(), 8);
  await page.getByText("Append a matrix correction", { exact: true }).click();
  await page.getByLabel("Reason for correction", { exact: true }).fill("Operator requested the current projection of the recorded packet.");
  await page.getByRole("button", { name: "Append correction", exact: true }).click();
  await visible("A new matrix version was appended.");
  const corrected = await responseJSON(`/api/phase1/scans/${scanId}/evidence-matrix`);
  assert.equal(corrected.version, 2); assert.equal(corrected.policy_result, scan.policy_action);
  await visible("Candidate media is unavailable or no longer retained.");
  checked("Admin corrections append a matrix version and media retention has an understandable comparison fallback");
  await page.locator("#admin-investigation").getByRole("button", { name: "Generate investigation", exact: true }).click();
  await visible("Browser test fixture:");
  await page.getByLabel("Your decision", { exact: true }).selectOption("EDITED");
  await page.getByLabel("Corrected summary", { exact: true }).fill("Human review: visual reuse is recorded; authority and publication context need verification.");
  await page.getByRole("button", { name: "Record review decision", exact: true }).click();
  await visible("Your review was recorded.");
  await screenshot("admin-investigation", page.locator("#admin-investigation"));
  const runId = await page.getByLabel("Investigation run ID", { exact: true }).inputValue();
  const investigation = await responseJSON(`/api/phase1/investigations/${runId}`);
  assert.equal(investigation.output.human_decision, "EDITED");
  assert(investigation.output.summary.startsWith("Browser test fixture:"));
  assert.equal(investigation.reviews.length, 1);
  await page.reload(); await page.locator(".adminDetectionList > button").first().click();
  await visible("Review recorded"); await visible("Human review: visual reuse is recorded");
  checked("User matches reach Admin; assistant output has immutable receipts and the human edit survives reload");
  await fs.writeFile(path.join(fixture, "fail-assistant"), "fixture\n");
  await page.locator("#admin-investigation").getByRole("button", { name: "Generate a new investigation", exact: true }).click();
  await visible("Assistant output unavailable");
  assert.equal((await responseJSON(`/api/phase1/investigations/${await page.getByLabel("Investigation run ID", { exact: true }).inputValue()}`)).run.status, "FAILED");
  await fs.unlink(path.join(fixture, "fail-assistant"));
  checked("Assistant failure is persisted and review remains available");

  for (const width of [1440, 768, 375]) {
    await page.setViewportSize({ width, height: 900 });
    for (const route of ["artist", "user", "admin", "pipeline"]) {
      await page.goto(`${base}/${route}`);
      await page.waitForTimeout(600);
      assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), `${route} overflows at ${width}px`);
      if (route === "artist" && width < 760) assert(await page.locator(".cpLibraryIdentity > div:last-child").first().evaluate(el => el.clientWidth) >= 140, "Artwork titles need room to remain readable on phones");
      await screenshot(`${route}-${width}`);
    }
  }
  await page.getByRole("button", { name: /Resemblance without validated reuse/ }).click();
  await page.getByRole("button", { name: "Play walkthrough", exact: true }).click();
  await visible("Step 7 of 7");
  await page.getByRole("button", { name: "Reset walkthrough", exact: true }).click(); await visible("Click any node");
  checked("Responsive layouts at 1440 / 768 / 375 px, pipeline scenarios and playback");
  assert.deepEqual(browserErrors, []);
  checked("No browser runtime errors");
  await fs.writeFile(path.join(fixture, "results.json"), JSON.stringify({ checks, count: checks.length, browserErrors }, null, 2));
} catch (e) {
  await screenshot("failure");
  console.error((await page.locator("body").innerText()).slice(-12000));
  throw e;
} finally { await browser.close(); }
