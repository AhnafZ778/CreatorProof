import assert from "node:assert/strict";
import { test } from "node:test";

import { MAX_JSON_REQUEST_BYTES } from "./deployment.ts";
import { readJsonObject, RequestInputError } from "./requestBody.ts";

test("bounded JSON accepts an object and rejects invalid JSON", async () => {
  const parsed = await readJsonObject(
    new Request("http://localhost/api", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ upload_token: "signed" }),
    }),
  );
  assert.equal(parsed.upload_token, "signed");

  await assert.rejects(
    readJsonObject(new Request("http://localhost/api", { method: "POST", body: "{" })),
    (error: unknown) => error instanceof RequestInputError && error.code === "INVALID_JSON",
  );
});

test("bounded JSON rejects actual bytes even without a Content-Length header", async () => {
  const request = new Request("http://localhost/api", {
    method: "POST",
    body: JSON.stringify({ value: "x".repeat(MAX_JSON_REQUEST_BYTES) }),
  });
  await assert.rejects(
    readJsonObject(request),
    (error: unknown) => error instanceof RequestInputError && error.status === 413,
  );
});
