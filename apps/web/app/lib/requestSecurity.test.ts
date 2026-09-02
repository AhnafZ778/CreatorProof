import assert from "node:assert/strict";
import { test } from "node:test";

import { guardMutation, isTrustedMutationOrigin } from "./requestSecurity.ts";

test("production mutations require the same forwarded origin", () => {
  const trusted = new Request("https://creatorproof.example/api/scans", {
    method: "POST",
    headers: {
      origin: "https://creatorproof.example",
    },
  });
  const foreign = new Request("https://creatorproof.example/api/scans", {
    method: "POST",
    headers: {
      origin: "https://attacker.example",
    },
  });
  assert.equal(isTrustedMutationOrigin(trusted, true), true);
  assert.equal(isTrustedMutationOrigin(foreign, true), false);
  assert.equal(isTrustedMutationOrigin(new Request("https://creatorproof.example/api/scans"), true), false);
});

test("the browser Host authority wins when Next reconstructs a different local URL", () => {
  const request = new Request("http://localhost:3000/api/uploads", {
    method: "POST",
    headers: {
      host: "127.0.0.1:3000",
      origin: "http://127.0.0.1:3000",
    },
  });
  assert.equal(isTrustedMutationOrigin(request, true), true);
});

test("TLS termination uses the forwarded protocol but never trusts a forwarded host", () => {
  const trusted = new Request("http://internal-web:3000/api/works", {
    method: "POST",
    headers: {
      host: "creatorproof.example",
      origin: "https://creatorproof.example",
      "x-forwarded-proto": "https",
    },
  });
  const spoofed = new Request("https://creatorproof.example/api/works", {
    method: "POST",
    headers: {
      host: "creatorproof.example",
      origin: "https://attacker.example",
      "x-forwarded-host": "attacker.example",
      "x-forwarded-proto": "https",
    },
  });
  assert.equal(isTrustedMutationOrigin(trusted, true), true);
  assert.equal(isTrustedMutationOrigin(spoofed, true), false);
});

test("malformed and non-HTTP origins remain denied", () => {
  for (const origin of ["null", "not a URL", "file://localhost"]) {
    const request = new Request("https://creatorproof.example/api/scans", {
      method: "POST",
      headers: { origin },
    });
    assert.equal(isTrustedMutationOrigin(request, true), false);
  }
});

test("the best-effort limiter returns 429 after the configured allowance", () => {
  const request = new Request("http://localhost:3000/api/scans", { method: "POST" });
  const bucket = `test-${crypto.randomUUID()}`;
  assert.equal(guardMutation(request, { bucket, limit: 1 }), null);
  const denied = guardMutation(request, { bucket, limit: 1 });
  assert.equal(denied?.status, 429);
  assert.equal(denied?.headers.get("retry-after"), "60");
});
