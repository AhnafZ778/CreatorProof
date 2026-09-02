import assert from "node:assert/strict";
import { test } from "node:test";

import { backendAttemptTimeout } from "./backendTiming.ts";

test("retryable mutations keep the full deadline instead of using short read retries", () => {
  assert.equal(backendAttemptTimeout("POST", true, 20_000), 20_000);
  assert.equal(backendAttemptTimeout("GET", true, 20_000), 12_000);
  assert.equal(backendAttemptTimeout("HEAD", true, 5_000), 5_000);
});
