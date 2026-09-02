type Environment = Record<string, string | undefined>;

const DEVELOPMENT_API_URL = "http://localhost:8000";
const DEVELOPMENT_API_KEY = "change-me-before-sharing";
const INSECURE_API_KEYS = new Set(["", DEVELOPMENT_API_KEY, "changeme", "secret"]);

export type BackendConfig = {
  apiUrl: string;
  apiKey: string;
  directUploadEnabled: boolean;
  coldStartBudgetMs: number;
};

export type WebAuthConfig =
  | { mode: "public" }
  | { mode: "basic"; username: string; password: string };

export class ServerConfigurationError extends Error {
  readonly code = "SERVER_CONFIGURATION_INVALID";

  constructor(message: string) {
    super(message);
    this.name = "ServerConfigurationError";
  }
}

function isProduction(env: Environment): boolean {
  return env.NODE_ENV === "production";
}

function parseBoolean(value: string | undefined, fallback = false): boolean {
  if (value === undefined || value.trim() === "") return fallback;
  if (["1", "true", "yes", "on"].includes(value.trim().toLowerCase())) return true;
  if (["0", "false", "no", "off"].includes(value.trim().toLowerCase())) return false;
  throw new ServerConfigurationError(`Invalid boolean environment value: ${value}`);
}

function parseBudget(value: string | undefined, env: Environment = process.env): number {
  if (!value?.trim()) {
    // Hobby Fluid functions are killed at 60s. Finish the Render wake-up
    // loop before the platform does, otherwise the client sees a generic 504.
    return env.VERCEL === "1" ? 55_000 : 75_000;
  }
  const parsed = Number(value);
  if (!Number.isInteger(parsed) || parsed < 10_000 || parsed > 150_000) {
    throw new ServerConfigurationError(
      "CREATORPROOF_BACKEND_COLD_START_BUDGET_MS must be an integer from 10000 to 150000.",
    );
  }
  return parsed;
}

export function readBackendConfig(env: Environment = process.env): BackendConfig {
  const production = isProduction(env);
  const rawUrl = env.CREATORPROOF_API_URL?.trim() || (production ? "" : DEVELOPMENT_API_URL);
  const apiKey =
    env.CREATORPROOF_API_KEY?.trim() ||
    env.CREATORPROOF_DEV_API_KEY?.trim() ||
    (production ? "" : DEVELOPMENT_API_KEY);

  if (!rawUrl) {
    throw new ServerConfigurationError("CREATORPROOF_API_URL is required in production.");
  }
  let parsed: URL;
  try {
    parsed = new URL(rawUrl);
  } catch {
    throw new ServerConfigurationError("CREATORPROOF_API_URL must be an absolute URL.");
  }
  if (!['http:', 'https:'].includes(parsed.protocol) || parsed.username || parsed.password) {
    throw new ServerConfigurationError(
      "CREATORPROOF_API_URL must use HTTP(S) and must not contain credentials.",
    );
  }
  if (parsed.search || parsed.hash) {
    throw new ServerConfigurationError(
      "CREATORPROOF_API_URL must not contain a query string or fragment.",
    );
  }
  if (production && parsed.protocol !== "https:") {
    throw new ServerConfigurationError("CREATORPROOF_API_URL must use HTTPS in production.");
  }
  if (!apiKey) {
    throw new ServerConfigurationError(
      "CREATORPROOF_API_KEY (or the legacy CREATORPROOF_DEV_API_KEY) is required.",
    );
  }
  if (production && (apiKey.length < 24 || INSECURE_API_KEYS.has(apiKey.toLowerCase()))) {
    throw new ServerConfigurationError(
      "The backend API key is missing, known-default, or too short for production.",
    );
  }

  parsed.pathname = parsed.pathname.replace(/\/$/, "");
  return {
    apiUrl: parsed.toString().replace(/\/$/, ""),
    apiKey,
    directUploadEnabled: parseBoolean(env.CREATORPROOF_DIRECT_UPLOAD_ENABLED, false),
    coldStartBudgetMs: parseBudget(env.CREATORPROOF_BACKEND_COLD_START_BUDGET_MS, env),
  };
}

export function readWebAuthConfig(env: Environment = process.env): WebAuthConfig {
  const rawMode = env.CREATORPROOF_WEB_AUTH_MODE?.trim().toLowerCase();
  const mode = rawMode || (isProduction(env) ? "basic" : "public");
  if (mode === "public") return { mode };
  if (mode !== "basic") {
    throw new ServerConfigurationError("CREATORPROOF_WEB_AUTH_MODE must be basic or public.");
  }

  const username = env.CREATORPROOF_WEB_BASIC_AUTH_USER?.trim() ?? "";
  const password = env.CREATORPROOF_WEB_BASIC_AUTH_PASSWORD ?? "";
  if (!username || password.length < 16) {
    throw new ServerConfigurationError(
      "Basic web auth requires CREATORPROOF_WEB_BASIC_AUTH_USER and a password of at least 16 characters.",
    );
  }
  return { mode, username, password };
}

/** Validate secrets once at process/function startup instead of failing mid-demo. */
export function validateServerEnvironment(env: Environment = process.env): void {
  readBackendConfig(env);
  readWebAuthConfig(env);
}
