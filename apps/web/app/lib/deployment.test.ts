import assert from "node:assert/strict";
import { test } from "node:test";

import {
  MAX_IMAGE_UPLOAD_BYTES,
  validateImageMetadata,
} from "./deployment.ts";
import { readBackendConfig, readWebAuthConfig } from "./serverEnv.ts";

test("production refuses an implicit localhost backend", () => {
  assert.throws(
    () => readBackendConfig({ NODE_ENV: "production" }),
    /CREATORPROOF_API_URL is required/,
  );
});

test("production refuses plaintext URLs and known development credentials", () => {
  assert.throws(
    () =>
      readBackendConfig({
        NODE_ENV: "production",
        CREATORPROOF_API_URL: "http://api.example.com",
        CREATORPROOF_API_KEY: "a-securely-long-key-that-is-not-used",
      }),
    /must use HTTPS/,
  );
  assert.throws(
    () =>
      readBackendConfig({
        NODE_ENV: "production",
        CREATORPROOF_API_URL: "https://api.example.com",
        CREATORPROOF_DEV_API_KEY: "change-me-before-sharing",
      }),
    /known-default/,
  );
});

test("production accepts a private HTTPS backend and direct-upload flag", () => {
  const config = readBackendConfig({
    NODE_ENV: "production",
    CREATORPROOF_API_URL: "https://api.example.com/",
    CREATORPROOF_API_KEY: "a-securely-long-key-that-is-not-used",
    CREATORPROOF_DIRECT_UPLOAD_ENABLED: "true",
    CREATORPROOF_BACKEND_COLD_START_BUDGET_MS: "90000",
  });
  assert.equal(config.apiUrl, "https://api.example.com");
  assert.equal(config.directUploadEnabled, true);
  assert.equal(config.coldStartBudgetMs, 90_000);
});

test("Vercel defaults the backend wake budget inside the Hobby function ceiling", () => {
  const config = readBackendConfig({
    NODE_ENV: "production",
    VERCEL: "1",
    CREATORPROOF_API_URL: "https://api.example.com",
    CREATORPROOF_API_KEY: "a-securely-long-key-that-is-not-used",
  });
  assert.equal(config.coldStartBudgetMs, 55_000);
});

test("production web auth fails closed unless public mode is explicit", () => {
  assert.throws(() => readWebAuthConfig({ NODE_ENV: "production" }), /Basic web auth requires/);
  assert.deepEqual(
    readWebAuthConfig({ NODE_ENV: "production", CREATORPROOF_WEB_AUTH_MODE: "public" }),
    { mode: "public" },
  );
  assert.deepEqual(
    readWebAuthConfig({
      NODE_ENV: "production",
      CREATORPROOF_WEB_AUTH_MODE: "basic",
      CREATORPROOF_WEB_BASIC_AUTH_USER: "judges",
      CREATORPROOF_WEB_BASIC_AUTH_PASSWORD: "a-long-random-password",
    }),
    { mode: "basic", username: "judges", password: "a-long-random-password" },
  );
});

test("image metadata contract stays safely below Vercel's payload ceiling", () => {
  assert.equal(
    validateImageMetadata({ size: MAX_IMAGE_UPLOAD_BYTES, type: "image/png" }),
    null,
  );
  assert.match(
    validateImageMetadata({ size: MAX_IMAGE_UPLOAD_BYTES + 1, type: "image/png" }) ?? "",
    /4 MB/,
  );
  assert.match(validateImageMetadata({ size: 1, type: "image/gif" }) ?? "", /PNG/);
});
