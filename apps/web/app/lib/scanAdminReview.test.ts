import assert from "node:assert/strict";
import test from "node:test";
import { adminReviewHref, savedAdminReview } from "./scanAdminReview.ts";

const saved = { id: "scn_123", state: "COMPLETED", intended_use: "social", match_status: "MATCH_FOUND", top_match_work_id: "wrk_123", admin_review: { saved: true, status: "needs_review", category: "CONTENT_FLAG", reasons: ["REGISTERED_WORK_MATCH"] } };

test("only an explicit server confirmation shows a saved Admin receipt", () => {
  assert(savedAdminReview(saved));
  for (const scan of [
    { ...saved, state: "QUEUED" },
    { ...saved, state: "FAILED" },
    { ...saved, admin_review: { ...saved.admin_review, saved: false } },
    { ...saved, admin_review: { ...saved.admin_review, status: "not_flagged" } },
    { ...saved, admin_review: { ...saved.admin_review, status: "unavailable" } },
    { ...saved, admin_review: undefined },
  ]) assert.equal(savedAdminReview(scan), null);
});

test("stored declaration, publication territory and marketplace source remain distinct", () => {
  const review = savedAdminReview({ ...saved, submission_context: { country_code: "BD", source_url: "https://example.com/listing/1", source_kind: "marketplace", use_context: { territory: "US", channel: "web" } } });
  assert.equal(review?.countryCode, "BD");
  assert.equal(review?.sourceUrl, "https://example.com/listing/1");
  assert.equal(review?.sourceKind, "marketplace");
  assert.deepEqual(review?.useContext, { territory: "US", channel: "web" });
  const unknown = savedAdminReview(saved);
  assert.equal(unknown?.countryCode, null);
  assert.equal(unknown?.sourceUrl, null);
});

test("assessment gaps do not imply a registered-work match or an unsafe public link", () => {
  const scan = { ...saved, match_status: "INCONCLUSIVE", admin_review: { ...saved.admin_review, category: "ASSESSMENT_GAP" } };
  for (const source_url of ["javascript:alert(1)", "https://user:password@example.com/listing", "invalid"]) {
    const review = savedAdminReview({ ...scan, submission_context: { source_url } });
    assert.equal(review?.matchedWorkId, null);
    assert.equal(review?.sourceUrl, null);
    assert.equal(review?.category, "ASSESSMENT_GAP");
  }
  assert.equal(adminReviewHref("scn_123"), "/admin?scan_id=scn_123#admin-review-inbox");
  assert.match(adminReviewHref("scn_1&next=/outside"), /scn_1%26next%3D%2Foutside/);
});
