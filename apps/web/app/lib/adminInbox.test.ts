import assert from "node:assert/strict";
import { test } from "node:test";
import { adminInbox, needsAdminReview, flagLabel, mediaProxyPath } from "./adminInbox.ts";

test("a detection, saved marketplace image and review case for one scan create one inbox record", () => {
  const items = adminInbox([{ scan_id: "one", classification: "COPIED", matched_work: { title: "Original" } }], [{ id: "case", scan_id: "one", state: "OPEN" }], [{ scan_id: "one", provider: "ebay", title: "Listing", classification: "COPIED" }]);
  assert.equal(items.length, 1);
  assert.equal(items[0].asset?.title, "Listing");
  assert.equal(items[0].reviewCase?.id, "case");
  assert.equal(items[0].detection?.matched_work.title, "Original");
});

test("resolving a case removes it from pending review while preserving its inbox history", () => {
  const [item] = adminInbox([{ scan_id: "one", classification: "COPIED" }], [{ scan_id: "one", state: "RESOLVED" }], []);
  assert.equal(needsAdminReview(item), false);
  assert.equal(flagLabel(item), "Registered artwork match");
});

test("an assessment gap is not presented as a copying finding; saved unclassified photos do not fill the queue", () => {
  const [item] = adminInbox([{ scan_id: "one", classification: "REVIEW", category: "ASSESSMENT_GAP" }], [], [{ scan_id: "other", classification: "UNCLASSIFIED" }]);
  assert.equal(flagLabel(item), "Assessment incomplete");
  assert.equal(adminInbox([], [], [{ scan_id: "other", classification: "UNCLASSIFIED" }]).length, 0);
});

test("media proxy paths stay on the finite authenticated API gateway", () => {
  assert.equal(mediaProxyPath("/v1/scans/id/media"), "/api/scans/id/media");
  assert.equal(mediaProxyPath("https://evil.example/media"), "");
});

test("saved comparison media accepts only the exact case id and image kind", () => {
  const id = `scn_${"a".repeat(32)}`;
  assert.equal(mediaProxyPath(`/v1/admin/stored-cases/${id}/media/candidate`), `/api/admin/stored-cases/${id}/media/candidate`);
  assert.equal(mediaProxyPath(`/v1/admin/stored-cases/${id}/media/reference`), `/api/admin/stored-cases/${id}/media/reference`);
  assert.equal(mediaProxyPath(`/v1/admin/stored-cases/${id}/media/../../secret`), "");
  assert.equal(mediaProxyPath("/v1/admin/stored-cases/not-a-scan/media/candidate"), "");
});
