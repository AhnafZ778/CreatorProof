import assert from "node:assert/strict";
import { test } from "node:test";
import { marketplaceLabel, marketplaceDescription } from "./marketplaces.ts";

test("eBay test listings are explicitly labeled sandbox; an unknown environment is not called production", () => {
  assert.equal(marketplaceLabel("ebay", "sandbox"), "eBay · Sandbox");
  assert.equal(marketplaceLabel("ebay", "production"), "eBay · Production");
  assert.equal(marketplaceLabel("ebay"), "eBay");
  assert.equal(marketplaceLabel("pixabay", "production"), "Pixabay");
});

test("configuration presence is not described as verified live API access", () => {
  const source = { provider: "ebay" as const, configured: true, environment: "sandbox" as const, marketplace_id: "EBAY_US" };
  assert.match(marketplaceDescription(source), /Sandbox test listings/);
  assert.match(marketplaceDescription(source), /Production keys are needed/);
  assert.match(marketplaceDescription({ ...source, configured: false }), /not configured/);
  assert.match(marketplaceDescription({ ...source, environment: "production" }), /Production eBay listings/);
});
