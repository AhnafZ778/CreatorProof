import assert from "node:assert/strict";
import test from "node:test";
import { completionFields, isPublicVerificationApiPath, phase1Route, useContextFromForm, validPublicToken } from "./phase1Contract.ts";

test("the feature gateway exposes only its finite read/write operations", () => {
  for (const route of ["works/wrk_123/rights-policy", "works/wrk_123/rights-policy/2", "works/wrk_123/ai.txt", "works/wrk_123/contributions/verify", "scans/scn_123/evidence-matrix", "investigations/inv_123"]) assert.equal(phase1Route(route.split("/"), "GET"), `/v1/${route}`);
  for (const route of ["works/wrk_123/rights-policy", "works/wrk_123/provenance/inspect", "scans/scn_123/evidence-matrix/corrections", "scans/scn_123/verification-token", "investigations/scans/scn_123", "investigations/inv_123/decision"]) assert.equal(phase1Route(route.split("/"), "POST"), `/v1/${route}`);
  assert.equal(phase1Route(["verification-tokens", "pvt_123"], "DELETE"), "/v1/verification-tokens/pvt_123");
});
test("unknown paths, traversal and mismatched verbs cannot use server credentials", () => {
  for (const path of ["admin/tenants", "works/wrk_1/../credentials", "works/%2e%2e/rights-policy", "works/wrk_1/provenance?url=https://evil.test", "https://evil.test", "works/wrk_1/provenance/inspect/extra"]) assert.equal(phase1Route(path.split("/"), "GET"), null);
  assert.equal(phase1Route(["works", "wrk_1", "rights-policy"], "DELETE"), null);
  assert.equal(phase1Route(["scans", "scn_1", "evidence-matrix"], "POST"), null);
  assert.equal(phase1Route(["works", "wrk_1", "rights-policy", "0"], "GET"), null);
});
test("direct-upload completion preserves the structured intended-use object", () => {
  const fields = { catalog_id: "default", country_code: "BD", source_url: "https://example.com/artwork/post", use_context: JSON.stringify({ territory: "US", channel: "web", rights_permission: "image_to_image_permission" }) };
  assert.deepEqual(completionFields(fields), { ...fields, use_context: { territory: "US", channel: "web", rights_permission: "image_to_image_permission" } });
  assert.deepEqual(completionFields({ catalog_id: "default" }), { catalog_id: "default" });
  assert.throws(() => completionFields({ use_context: "[\"US\"]" }));
});
test("blank scope fields stay absent and notice country cannot imply use territory", () => {
  const form = new FormData(); form.set("country_code", "BD"); form.set("use_channel", " web "); form.set("use_model", "");
  assert.deepEqual(useContextFromForm(form), { channel: "web" });
});
test("only exact unguessable-token verifier requests bypass web login", () => {
  const token = "a".repeat(64);
  assert(validPublicToken(token)); assert(isPublicVerificationApiPath(`/api/public-verification/${token}`));
  for (const value of ["a".repeat(63), "../admin", "a".repeat(64) + "/extra", "a".repeat(64) + "?secret=x"]) { assert(!validPublicToken(value)); assert(!isPublicVerificationApiPath(`/api/public-verification/${value}`)); }
  assert(!isPublicVerificationApiPath("/api/phase1/works/wrk_1/rights-policy"));
});
