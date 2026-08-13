/**
 * Typed TypeScript client for the CreatorProof API.
 *
 * Dependency-free and runtime-agnostic: it needs only `fetch`, `FormData` and
 * WebCrypto, which Node 18+, Deno, Bun and browsers all provide. Keep the API
 * key on a server; a browser should call your own backend, which then calls
 * CreatorProof.
 */

export type PolicyAction = "PASS_BY_POLICY" | "REVIEW" | "BLOCK";
export type ScanState = "QUEUED" | "PROCESSING" | "COMPLETED" | "FAILED" | "CANCELLED";
export type CoverageStatus =
  | "COMPLETE"
  | "EMPTY_SCOPE"
  | "PARTIAL"
  | "DEGRADED"
  | "TRUNCATED"
  | "FAILED";

export type ProofReceipt = {
  anchor_status?: string;
  provider?: string;
  /** Identifies the proof mechanism; unlike commitment_scope, this can identify a chain. */
  proof_kind?: string;
  anchor_scope?: string;
  /** Describes the bytes committed and does not identify where they were committed. */
  commitment_scope?: string;
  packet_hash_sha256?: string;
  receipt?: Record<string, unknown> | null;
};

export type VerificationPackage = {
  schema?: string;
  statement?: Record<string, unknown>;
  payload_digest_sha256?: string;
  status?: string;
  signature?: Record<string, unknown>;
  trust_bundle?: Record<string, unknown>;
  transparency?: Record<string, unknown>;
  evidence_packet_without_proof?: Record<string, unknown>;
  evidence_packet_canonical_b64?: string;
  canonicalization_algorithm?: string;
  evidence_packet_canonicalization?: string;
  proof_binding?: Record<string, unknown>;
  proof_binding_signature?: Record<string, unknown>;
  deployment?: {
    issuer?: string;
    issuer_key_fingerprint_sha256?: string;
    deployment_fingerprint_sha256?: string;
  };
};

export type OfflineChainStatus = "UNVERIFIED_OFFLINE";

/** A package records an issuer declaration; only a live RPC re-check proves current EAS state. */
export function offlineChainStatus(_package: VerificationPackage): OfflineChainStatus {
  return "UNVERIFIED_OFFLINE";
}

export type AttestationVerification = {
  valid?: boolean;
  binding_matches?: boolean;
  finalized?: boolean;
  expected?: Record<string, unknown>;
  actual?: Record<string, unknown>;
  [key: string]: unknown;
};

export type ProofExplorerLink = {
  kind: "transaction" | "attestation" | "attester" | "explorer";
  url: string;
};

export type EvidenceScope = {
  coverage_status?: CoverageStatus;
  coverage_reason_codes?: string[];
  eligible_reference_count?: number;
  verified_candidate_count?: number;
  omitted_candidate_count?: number;
  failed_candidate_count?: number;
  snapshot_digest_sha256?: string;
};

export type EvidencePacket = {
  scope?: EvidenceScope;
  matches?: Array<Record<string, unknown>>;
  style_analysis?: Record<string, unknown>;
  synthetic_origin?: Record<string, unknown>;
  decision?: { match_status?: string; policy_action?: PolicyAction; joint_risk?: Record<string, unknown> };
  proof?: ProofReceipt;
  limitations?: string[];
};

export type Scan = {
  id: string;
  state: ScanState;
  match_status?: string;
  policy_action?: PolicyAction;
  rights_path?: string;
  intended_use?: string;
  error_code?: string | null;
  evidence_packet?: EvidencePacket;
};

export type Work = {
  id: string;
  catalog_id: string;
  title: string;
  sha256: string;
  rights_path: string;
};

export type StageAttempt = {
  stage: string;
  state: string;
  attempt: number;
  max_attempts: number;
  progress_percent: number;
  progress_label?: string | null;
  error_code?: string | null;
};

export type StageTimeline = {
  scan_id: string;
  lifecycle_state: string;
  correlation_id?: string | null;
  stages: StageAttempt[];
};

export type ReviewCase = {
  id: string;
  scan_id: string;
  state: string;
  priority?: string;
  assignee?: string | null;
};

export class CreatorProofError extends Error {
  constructor(
    readonly status: number,
    readonly detail: string,
    readonly body?: unknown,
  ) {
    super(`CreatorProof API error ${status}: ${detail}`);
    this.name = "CreatorProofError";
  }
}

export type ClientOptions = {
  baseUrl?: string;
  /** Echoed into logs, scans, statements and webhooks so one id traces a request. */
  correlationId?: string;
  timeoutMs?: number;
  fetchImpl?: typeof fetch;
};

export class CreatorProofClient {
  private readonly baseUrl: string;
  private readonly timeoutMs: number;
  private readonly fetchImpl: typeof fetch;

  constructor(
    private readonly apiKey: string,
    private readonly options: ClientOptions = {},
  ) {
    this.baseUrl = (options.baseUrl ?? "http://localhost:8000").replace(/\/$/, "");
    this.timeoutMs = options.timeoutMs ?? 30_000;
    this.fetchImpl = options.fetchImpl ?? globalThis.fetch;
  }

  private async request<T>(
    path: string,
    init: RequestInit = {},
    timeoutMs?: number,
  ): Promise<T> {
    const headers = new Headers(init.headers);
    headers.set("X-API-Key", this.apiKey);
    headers.set("Accept", "application/json");
    if (this.options.correlationId) headers.set("X-Correlation-Id", this.options.correlationId);

    let response: Response;
    try {
      response = await this.fetchImpl(`${this.baseUrl}${path}`, {
        ...init,
        headers,
        signal: AbortSignal.timeout(timeoutMs ?? this.timeoutMs),
      });
    } catch (caught) {
      const reason = caught instanceof Error ? caught.message : String(caught);
      throw new CreatorProofError(0, `The API is unreachable: ${reason}`);
    }

    const text = await response.text();
    const body: unknown = text ? JSON.parse(text) : null;
    if (!response.ok) {
      const detail =
        body && typeof body === "object" && "detail" in body
          ? String((body as { detail: unknown }).detail)
          : response.statusText;
      throw new CreatorProofError(response.status, detail, body);
    }
    return body as T;
  }

  private postJson<T>(path: string, payload: unknown): Promise<T> {
    return this.request<T>(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  }

  health(): Promise<Record<string, unknown>> {
    return this.request("/healthz");
  }

  /** Readiness names every degraded capability; check it before demonstrating. */
  readiness(): Promise<Record<string, unknown>> {
    return this.request("/readyz");
  }

  async registerWork(input: {
    file: Blob;
    filename: string;
    title: string;
    catalogId: string;
    rightsPath?: string;
    allowedUses?: string[];
    claimant?: string;
    claimState?: string;
  }): Promise<Work> {
    const form = new FormData();
    form.set("file", input.file, input.filename);
    form.set("title", input.title);
    form.set("catalog_id", input.catalogId);
    form.set("rights_path", input.rightsPath ?? "NO_LICENSE_INFO");
    form.set("allowed_uses", JSON.stringify(input.allowedUses ?? []));
    form.set("claim_state", input.claimState ?? "ASSERTED");
    if (input.claimant) form.set("claimant", input.claimant);
    return this.request<Work>("/v1/works", { method: "POST", body: form });
  }

  listWorks(catalogId?: string): Promise<Work[]> {
    return this.request(`/v1/works${catalogId ? `?catalog_id=${encodeURIComponent(catalogId)}` : ""}`);
  }

  deleteWork(workId: string): Promise<Record<string, unknown>> {
    return this.request(`/v1/works/${encodeURIComponent(workId)}`, { method: "DELETE" });
  }

  async createScan(input: {
    file: Blob;
    filename: string;
    catalogId: string;
    intendedUse: string;
    idempotencyKey?: string;
  }): Promise<Scan> {
    const form = new FormData();
    form.set("file", input.file, input.filename);
    form.set("catalog_id", input.catalogId);
    form.set("intended_use", input.intendedUse);
    return this.request<Scan>("/v1/scans", {
      method: "POST",
      headers: { "Idempotency-Key": input.idempotencyKey ?? crypto.randomUUID() },
      body: form,
    });
  }

  getScan(scanId: string): Promise<Scan> {
    return this.request(`/v1/scans/${encodeURIComponent(scanId)}`);
  }

  /** Poll until the scan reaches a terminal state or the budget runs out. */
  async waitForScan(
    scanId: string,
    options: { timeoutMs?: number; pollIntervalMs?: number } = {},
  ): Promise<Scan> {
    const deadline = Date.now() + (options.timeoutMs ?? 180_000);
    const interval = options.pollIntervalMs ?? 1_000;
    while (Date.now() < deadline) {
      const scan = await this.getScan(scanId);
      if (scan.state === "COMPLETED" || scan.state === "FAILED" || scan.state === "CANCELLED") {
        return scan;
      }
      await new Promise((resolve) => setTimeout(resolve, interval));
    }
    throw new CreatorProofError(0, `Scan ${scanId} did not finish within the timeout.`);
  }

  cancelScan(scanId: string, reason: string): Promise<Scan> {
    return this.postJson(`/v1/scans/${encodeURIComponent(scanId)}/cancel`, { reason });
  }

  scanStages(scanId: string): Promise<StageTimeline> {
    return this.request(`/v1/scans/${encodeURIComponent(scanId)}/stages`);
  }

  getStatement(scanId: string): Promise<Record<string, unknown>> {
    return this.request(`/v1/scans/${encodeURIComponent(scanId)}/statement`);
  }

  /** Server-side verification. Prefer the package for an independent check. */
  verifyStatement(scanId: string): Promise<Record<string, unknown>> {
    return this.request(`/v1/scans/${encodeURIComponent(scanId)}/statement/verify`);
  }

  verificationPackage(scanId: string): Promise<VerificationPackage> {
    return this.request(`/v1/scans/${encodeURIComponent(scanId)}/verification-package`);
  }

  /** Append a correction, dispute, supersession or revocation. History is kept. */
  appendStatementStatus(
    scanId: string,
    statementType: string,
    reason: string,
  ): Promise<Record<string, unknown>> {
    return this.postJson(`/v1/scans/${encodeURIComponent(scanId)}/statement/status`, {
      statement_type: statementType,
      reason,
    });
  }

  proofStatus(): Promise<Record<string, unknown>> {
    return this.request("/v1/proof/status");
  }

  verifyAttestation(
    uid: string,
    expectedPacketHashSha256?: string,
  ): Promise<AttestationVerification> {
    if (
      expectedPacketHashSha256 &&
      !/^(?:0x)?[0-9a-fA-F]{64}$/.test(expectedPacketHashSha256)
    ) {
      throw new TypeError("expectedPacketHashSha256 must be a 32-byte hexadecimal SHA-256 value");
    }
    const query = expectedPacketHashSha256
      ? `?expected_packet_hash_sha256=${encodeURIComponent(expectedPacketHashSha256)}`
      : "";
    return this.request(`/v1/proof/attestations/${encodeURIComponent(uid)}${query}`);
  }

  trustBundle(): Promise<Record<string, unknown>> {
    return this.request("/v1/proof/trust-bundle");
  }

  listReviewCases(state?: string): Promise<ReviewCase[]> {
    return this.request(`/v1/review-cases${state ? `?state=${encodeURIComponent(state)}` : ""}`);
  }

  getReviewCase(caseId: string): Promise<Record<string, unknown>> {
    return this.request(`/v1/review-cases/${encodeURIComponent(caseId)}`);
  }

  appendReviewAction(caseId: string, payload: Record<string, unknown>) {
    return this.postJson<Record<string, unknown>>(
      `/v1/review-cases/${encodeURIComponent(caseId)}/actions`,
      payload,
    );
  }

  /** Create a subscription. The signing secret is returned exactly once. */
  createWebhookEndpoint(url: string, eventTypes: string[]) {
    return this.postJson<Record<string, unknown>>("/v1/webhooks/endpoints", {
      url,
      event_types: eventTypes,
    });
  }

  listWebhookDeliveries(endpointId?: string): Promise<Array<Record<string, unknown>>> {
    const suffix = endpointId ? `?endpoint_id=${encodeURIComponent(endpointId)}` : "";
    return this.request(`/v1/webhooks/deliveries${suffix}`);
  }

  policyDryRun(payload: Record<string, unknown>) {
    return this.postJson<Record<string, unknown>>("/v1/policies/dry-run", payload);
  }

  rightsPosition(workId: string): Promise<Record<string, unknown>> {
    return this.request(`/v1/rights/position?work_id=${encodeURIComponent(workId)}`);
  }
}

/** True when the scan searched its whole declared catalog. Check before trusting a clean result. */
export function coverageIsComplete(scan: Scan): boolean {
  return scan.evidence_packet?.scope?.coverage_status === "COMPLETE";
}

const PUBLIC_CHAIN_SCOPES = new Set([
  "PUBLIC_EVM_ATTESTATION",
  "PUBLIC_EVM_ATTESTATION_PACKET_HASH_ONLY",
  "EAS_ATTESTATION",
  "EVM_ATTESTATION",
]);

function objectRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function isPublicChainScope(value: unknown): boolean {
  return typeof value === "string" && PUBLIC_CHAIN_SCOPES.has(value.trim().toUpperCase());
}

/**
 * True only when proof metadata identifies a public chain. `commitment_scope`
 * describes what was hashed and is intentionally ignored here.
 */
export function isPublicBlockchainProof(input: Scan | ProofReceipt): boolean {
  const scan = input as Scan;
  const proof = scan.evidence_packet?.proof ?? (input as ProofReceipt);
  const receipt = objectRecord(proof.receipt);
  return (
    isPublicChainScope(proof.proof_kind) ||
    isPublicChainScope(proof.anchor_scope) ||
    isPublicChainScope(receipt?.proof_kind) ||
    isPublicChainScope(receipt?.anchor_scope)
  );
}

function safeHttpUrl(value: unknown): string | null {
  if (typeof value !== "string") return null;
  try {
    const parsed = new URL(value);
    return parsed.protocol === "https:" || parsed.protocol === "http:" ? parsed.href : null;
  } catch {
    return null;
  }
}

/** Normalize legacy explorer strings and structured EAS explorer URL objects. */
export function proofExplorerLinks(proof: ProofReceipt): ProofExplorerLink[] {
  const receipt = objectRecord(proof.receipt);
  if (!receipt) return [];
  const values: Array<[ProofExplorerLink["kind"], unknown]> = [
    ["explorer", receipt.explorer_url],
  ];
  for (const containerValue of [receipt.explorer, receipt.explorer_urls]) {
    if (typeof containerValue === "string") {
      values.push(["explorer", containerValue]);
      continue;
    }
    const container = objectRecord(containerValue);
    if (!container) continue;
    values.push(
      ["transaction", container.transaction_url ?? container.transaction],
      ["attestation", container.attestation_url ?? container.attestation],
      ["attester", container.attester_url ?? container.address_url],
      ["explorer", container.url],
    );
  }
  const seen = new Set<string>();
  const links: ProofExplorerLink[] = [];
  for (const [kind, value] of values) {
    const url = safeHttpUrl(value);
    if (url && !seen.has(url)) {
      seen.add(url);
      links.push({ kind, url });
    }
  }
  return links;
}

/**
 * Verify an inbound webhook.
 *
 * The signature covers `timestamp.body`, so a captured delivery replayed outside
 * the tolerance window fails even though its signature is intact.
 */
export async function verifyWebhookSignature(input: {
  secret: string;
  signatureHeader: string;
  timestampHeader: string;
  body: string | Uint8Array;
  toleranceSeconds?: number;
}): Promise<boolean> {
  const sentAt = Number.parseInt(input.timestampHeader, 10);
  if (!Number.isFinite(sentAt)) return false;
  const tolerance = input.toleranceSeconds ?? 300;
  if (Math.abs(Math.floor(Date.now() / 1000) - sentAt) > tolerance) return false;

  const encoder = new TextEncoder();
  const bodyBytes = typeof input.body === "string" ? encoder.encode(input.body) : input.body;
  const prefix = encoder.encode(`${sentAt}.`);
  const message = new Uint8Array(prefix.length + bodyBytes.length);
  message.set(prefix, 0);
  message.set(bodyBytes, prefix.length);

  const key = await crypto.subtle.importKey(
    "raw",
    encoder.encode(input.secret) as unknown as ArrayBuffer,
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const signature = new Uint8Array(
    await crypto.subtle.sign("HMAC", key, message as unknown as ArrayBuffer),
  );
  const expected = [...signature].map((byte) => byte.toString(16).padStart(2, "0")).join("");
  const presented = input.signatureHeader.split("=").pop()?.trim() ?? "";
  if (presented.length !== expected.length) return false;
  let mismatch = 0;
  for (let index = 0; index < expected.length; index += 1) {
    mismatch |= expected.charCodeAt(index) ^ presented.charCodeAt(index);
  }
  return mismatch === 0;
}
