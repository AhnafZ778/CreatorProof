/**
 * In-browser verification of a CreatorProof verification package.
 *
 * There are deliberately two verification modes:
 *
 * - `self-contained` proves that the package is internally consistent. The
 *   signing key shipped inside the package is not an independent trust root.
 * - `strong` also requires an issuer-key fingerprint supplied outside the
 *   package and, by default, complete transparency and public-chain bindings.
 *
 * This distinction prevents a forged statement, signature and attacker key
 * from authenticating one another merely because they arrived in one file.
 */

import { canonicalBytes, canonicalize, sha256Hex } from "./canonicalJson";
import { base64ToBytes, hexToBytes, verify as verifyEd25519 } from "./ed25519";

export type CheckResult = "PASS" | "FAIL" | "SKIPPED" | "ATTENTION";
export type VerificationMode = "self-contained" | "strong";

export type VerificationCheck = {
  name: string;
  label: string;
  result: CheckResult;
  detail: string;
};

export type VerificationOptions = {
  mode?: VerificationMode;
  /** SHA-256 of the raw 32-byte Ed25519 public key, pinned outside the package. */
  expectedIssuerKeyFingerprintSha256?: string;
  /** Optional deployment identity pinned alongside the issuer key. */
  expectedDeploymentFingerprintSha256?: string;
  expectedIssuer?: string;
  /** Defaults to true in strong mode and false in self-contained mode. */
  requireTransparency?: boolean;
  /** Defaults to true in strong mode and false in self-contained mode. */
  requireChainBinding?: boolean;
};

export type VerificationOutcome = {
  /** Compatibility summary: strong mode includes trust and required bindings. */
  valid: boolean;
  /** True when statement/package cryptography has no failed check. */
  cryptographicallyValid: boolean;
  /** True only when a key fingerprint supplied outside the package matched. */
  trusted: boolean;
  /** True when the externally pinned issuer also signed the proof-binding object. */
  packageBindingAuthenticated: boolean;
  /** Offline packages cannot independently query EAS; use the live re-check action. */
  liveChainStatus: "UNVERIFIED_OFFLINE";
  mode: VerificationMode;
  checks: VerificationCheck[];
  scope: string;
};

export type ExplorerLink = {
  kind: "transaction" | "attestation" | "attester" | "explorer";
  label: string;
  url: string;
};

type Record_ = Record<string, unknown>;

type Package = {
  statement?: unknown;
  payload_digest_sha256?: string;
  status?: string;
  signature?: {
    alg?: string;
    kid?: string;
    signature_b64?: string;
    cose_sign1_b64?: string;
  };
  trust_bundle?: { keys?: Array<{ kid?: string; public_key_hex?: string; active?: boolean }> };
  transparency?: {
    log_id?: string;
    leaf_index?: number;
    leaf_hash_sha256?: string;
    packet_hash_sha256?: string;
    tree_size?: number;
    root_sha256?: string;
    inclusion_proof?: Array<{ side: string; hash: string }>;
    latest_checkpoint?: {
      root_sha256?: string;
      tree_size?: number;
      signature_kid?: string;
      signature_b64?: string;
      created_at?: string | null;
    } | null;
    scope?: string;
  };
  statement_lineage?: Array<{
    statement?: unknown;
    payload_digest_sha256?: string;
    statement_type?: string;
    previous_statement_id?: string | null;
    signature?: {
      alg?: string;
      kid?: string;
      signature_b64?: string;
      cose_sign1_b64?: string;
    };
  }>;
  statement_lineage_binding?: Record_;
  statement_lineage_binding_signature?: {
    alg?: string;
    kid?: string;
    signature_b64?: string;
    payload_digest_sha256?: string;
  };
  evidence_packet_without_proof?: unknown;
  /** Exact bytes hashed by the API, preferred over cross-runtime reserialization. */
  evidence_packet_canonical_b64?: string;
  evidence_packet_canonical_json?: string;
  canonicalization_algorithm?: string;
  evidence_packet_canonicalization?: string;
  proof_binding?: Record_;
  proof_binding_signature?: {
    alg?: string;
    kid?: string;
    signature_b64?: string;
  };
  deployment?: {
    issuer?: string;
    issuer_key_fingerprint_sha256?: string;
    deployment_fingerprint_sha256?: string;
    manifest?: {
      schema?: string;
      chain_id?: number | null;
      contract_address?: string;
      schema_uid?: string;
      checkpoint_schema_uid?: string;
      schema_definition?: string;
      checkpoint_schema_definition?: string;
      recipient?: string;
      required_attester_address?: string;
      expected_contract_code_sha256?: string;
      finality_policy?: string;
    } | null;
  };
};

const PUBLIC_CHAIN_SCOPES = new Set([
  "PUBLIC_EVM_ATTESTATION",
  "PUBLIC_EVM_ATTESTATION_PACKET_HASH_ONLY",
  "PUBLIC_EVM_ATTESTATION_CHECKPOINT_HASH_ONLY",
  "EAS_ATTESTATION",
  "EVM_ATTESTATION",
]);

function asRecord(value: unknown): Record_ | null {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record_) : null;
}

function stringValue(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}

function normalizedScope(value: unknown): string | null {
  const scope = stringValue(value)?.trim().toUpperCase();
  return scope && PUBLIC_CHAIN_SCOPES.has(scope) ? scope : null;
}

/**
 * Detect a real public-chain proof from proof kind / receipt scope.
 * `commitment_scope` describes what was hashed; it never identifies a chain.
 */
export function isPublicBlockchainProof(proof: unknown): boolean {
  const outer = asRecord(proof);
  const receipt = asRecord(outer?.receipt);
  return Boolean(
    normalizedScope(outer?.proof_kind) ||
      normalizedScope(outer?.anchor_scope) ||
      normalizedScope(receipt?.proof_kind) ||
      normalizedScope(receipt?.anchor_scope),
  );
}

function safeHttpUrl(value: unknown): string | null {
  if (typeof value !== "string" || !value) return null;
  try {
    const parsed = new URL(value);
    return parsed.protocol === "https:" || parsed.protocol === "http:" ? parsed.href : null;
  } catch {
    return null;
  }
}

/** Normalize both legacy string explorer values and current URL objects. */
export function explorerLinksFromReceipt(receiptValue: unknown): ExplorerLink[] {
  const receipt = asRecord(receiptValue);
  if (!receipt) return [];
  const candidates: Array<[ExplorerLink["kind"], string, unknown]> = [
    ["explorer", "Open in block explorer", receipt.explorer_url],
  ];
  for (const containerValue of [receipt.explorer, receipt.explorer_urls]) {
    if (typeof containerValue === "string") {
      candidates.push(["explorer", "Open in block explorer", containerValue]);
      continue;
    }
    const container = asRecord(containerValue);
    if (!container) continue;
    candidates.push(
      ["transaction", "Open transaction", container.transaction_url ?? container.transaction],
      ["attestation", "Open attestation", container.attestation_url ?? container.attestation],
      ["attester", "Open attester", container.attester_url ?? container.address_url],
      ["explorer", "Open in block explorer", container.url],
    );
  }
  const seen = new Set<string>();
  const links: ExplorerLink[] = [];
  for (const [kind, label, candidate] of candidates) {
    const url = safeHttpUrl(candidate);
    if (url && !seen.has(url)) {
      seen.add(url);
      links.push({ kind, label, url });
    }
  }
  return links;
}

function encodeCborHead(major: number, length: number): Uint8Array {
  const prefix = major << 5;
  if (length < 24) return Uint8Array.from([prefix | length]);
  if (length < 0x100) return Uint8Array.from([prefix | 24, length]);
  if (length < 0x10000) return Uint8Array.from([prefix | 25, length >> 8, length & 0xff]);
  return Uint8Array.from([
    prefix | 26,
    (length >>> 24) & 0xff,
    (length >>> 16) & 0xff,
    (length >>> 8) & 0xff,
    length & 0xff,
  ]);
}

function concat(parts: Uint8Array[]): Uint8Array {
  const total = parts.reduce((sum, part) => sum + part.length, 0);
  const out = new Uint8Array(total);
  let offset = 0;
  for (const part of parts) {
    out.set(part, offset);
    offset += part.length;
  }
  return out;
}

function cborText(value: string): Uint8Array {
  const bytes = new TextEncoder().encode(value);
  return concat([encodeCborHead(3, bytes.length), bytes]);
}

function cborBytes(value: Uint8Array): Uint8Array {
  return concat([encodeCborHead(2, value.length), value]);
}

/** `{1: -8}` — the COSE protected header for EdDSA, matching the API. */
const PROTECTED_HEADER = Uint8Array.from([0xa1, 0x01, 0x27]);

function sigStructure(payload: Uint8Array): Uint8Array {
  return concat([
    encodeCborHead(4, 4),
    cborText("Signature1"),
    cborBytes(PROTECTED_HEADER),
    cborBytes(new Uint8Array(0)),
    cborBytes(payload),
  ]);
}

async function sha256Bytes(data: Uint8Array): Promise<Uint8Array> {
  const buffer = data.slice().buffer as ArrayBuffer;
  return new Uint8Array(await crypto.subtle.digest("SHA-256", buffer));
}

function toHex(bytes: Uint8Array): string {
  return [...bytes].map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

function validHex(value: unknown, bytes?: number): value is string {
  if (typeof value !== "string" || !/^(?:0x)?[0-9a-fA-F]+$/.test(value)) return false;
  const length = value.startsWith("0x") ? value.length - 2 : value.length;
  return length % 2 === 0 && (bytes === undefined || length === bytes * 2);
}

function bytesFromHex(value: string): Uint8Array {
  if (!validHex(value)) throw new Error("Invalid hexadecimal value");
  return hexToBytes(value);
}

function normalizeFingerprint(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const normalized = value.trim().toLowerCase().replace(/^sha256:/, "").replace(/^0x/, "");
  return /^[0-9a-f]{64}$/.test(normalized) ? normalized : null;
}

type VerificationKey = { kid?: string; public_key_hex?: string; active?: boolean };
type DetachedSignature = { alg?: string; kid?: string; signature_b64?: string };

async function keyFingerprint(key: VerificationKey | undefined): Promise<string | null> {
  if (!key?.public_key_hex || !validHex(key.public_key_hex, 32)) return null;
  return toHex(await sha256Bytes(bytesFromHex(key.public_key_hex)));
}

async function verifyDetachedPayload(
  payload: unknown,
  signature: DetachedSignature | undefined,
  key: VerificationKey | undefined,
): Promise<boolean> {
  if (!signature?.signature_b64 || !signature.kid || signature.kid !== key?.kid) return false;
  if (!key?.public_key_hex || !validHex(key.public_key_hex, 32)) return false;
  const algorithm = (signature.alg ?? "Ed25519").trim().toLowerCase();
  if (algorithm !== "ed25519" && algorithm !== "eddsa") return false;
  try {
    return await verifyEd25519(
      bytesFromHex(key.public_key_hex),
      sigStructure(canonicalBytes(payload)),
      base64ToBytes(signature.signature_b64),
    );
  } catch {
    return false;
  }
}

function sameCanonical(left: unknown, right: unknown): boolean {
  try {
    return canonicalize(left) === canonicalize(right);
  } catch {
    return false;
  }
}

async function leafHash(packetHashHex: string): Promise<Uint8Array> {
  return sha256Bytes(concat([Uint8Array.from([0x00]), bytesFromHex(packetHashHex)]));
}

async function nodeHash(left: Uint8Array, right: Uint8Array): Promise<Uint8Array> {
  return sha256Bytes(concat([Uint8Array.from([0x01]), left, right]));
}

function statementPacketHash(statement: unknown): string | null {
  return stringValue(asRecord(asRecord(statement)?.packet_commitment)?.packet_hash_sha256);
}

function proofBindingRecord(pkg: Package): Record_ | null {
  const binding = asRecord(pkg.proof_binding);
  const receipt = asRecord(binding?.receipt);
  return receipt ? { ...binding, ...receipt } : binding;
}

function chainBindingPacketHash(pkg: Package): string | null {
  return stringValue(proofBindingRecord(pkg)?.packet_hash_sha256) ?? statementPacketHash(pkg.statement);
}

function compareUnicodeCodePoints(left: string, right: string): number {
  const a = [...left];
  const b = [...right];
  for (let index = 0; index < Math.min(a.length, b.length); index += 1) {
    const difference = (a[index].codePointAt(0) ?? 0) - (b[index].codePointAt(0) ?? 0);
    if (difference) return difference;
  }
  return a.length - b.length;
}

function pythonAsciiString(value: string): string {
  let out = '"';
  for (const char of value) {
    const code = char.codePointAt(0) ?? 0;
    if (char === '"') out += '\\"';
    else if (char === "\\") out += "\\\\";
    else if (char === "\b") out += "\\b";
    else if (char === "\t") out += "\\t";
    else if (char === "\n") out += "\\n";
    else if (char === "\f") out += "\\f";
    else if (char === "\r") out += "\\r";
    else if (code < 0x20 || code >= 0x7f) {
      if (code <= 0xffff) out += `\\u${code.toString(16).padStart(4, "0")}`;
      else {
        const scalar = code - 0x10000;
        const high = 0xd800 + (scalar >> 10);
        const low = 0xdc00 + (scalar & 0x3ff);
        out += `\\u${high.toString(16)}\\u${low.toString(16)}`;
      }
    } else out += char;
  }
  return `${out}"`;
}

/**
 * Best-effort mirror of Python json.dumps(sort_keys=True, separators=(",", ":"),
 * ensure_ascii=True). JSON parsing erases Python's int-versus-float distinction,
 * so strong verification uses exact canonical bytes supplied by the API instead.
 */
function sortedJsonAscii(value: unknown): string {
  if (value === null) return "null";
  if (typeof value === "boolean") return value ? "true" : "false";
  if (typeof value === "string") return pythonAsciiString(value);
  if (typeof value === "number") {
    if (!Number.isFinite(value)) throw new Error("Non-finite numbers cannot be hashed");
    return Object.is(value, -0) ? "-0" : String(value);
  }
  if (Array.isArray(value)) return `[${value.map(sortedJsonAscii).join(",")}]`;
  if (typeof value === "object") {
    const record = value as Record_;
    const keys = Object.keys(record).sort(compareUnicodeCodePoints);
    return `{${keys
      .map((key) => `${pythonAsciiString(key)}:${sortedJsonAscii(record[key])}`)
      .join(",")}}`;
  }
  throw new Error(`Unsupported packet value: ${typeof value}`);
}

function exactPacketBytes(pkg: Package): { bytes: Uint8Array | null; exact: boolean; error?: string } {
  try {
    if (pkg.evidence_packet_canonical_b64) {
      const bytes = base64ToBytes(pkg.evidence_packet_canonical_b64);
      if (pkg.evidence_packet_without_proof !== undefined) {
        const decoded = JSON.parse(new TextDecoder().decode(bytes));
        if (canonicalize(decoded) !== canonicalize(pkg.evidence_packet_without_proof)) {
          return { bytes: null, exact: true, error: "Canonical packet bytes do not encode the supplied packet." };
        }
      }
      return { bytes, exact: true };
    }
    if (pkg.evidence_packet_canonical_json) {
      const decoded = JSON.parse(pkg.evidence_packet_canonical_json);
      if (
        pkg.evidence_packet_without_proof !== undefined &&
        canonicalize(decoded) !== canonicalize(pkg.evidence_packet_without_proof)
      ) {
        return { bytes: null, exact: true, error: "Canonical packet JSON does not encode the supplied packet." };
      }
      return { bytes: new TextEncoder().encode(pkg.evidence_packet_canonical_json), exact: true };
    }
    if (pkg.evidence_packet_without_proof !== undefined) {
      return {
        bytes: new TextEncoder().encode(sortedJsonAscii(pkg.evidence_packet_without_proof)),
        exact: false,
      };
    }
    return { bytes: null, exact: false };
  } catch (error) {
    return {
      bytes: null,
      exact: Boolean(pkg.evidence_packet_canonical_b64 || pkg.evidence_packet_canonical_json),
      error: error instanceof Error ? error.message : "Packet canonicalization failed.",
    };
  }
}

async function checkPacketCommitment(
  pkg: Package,
  options: { required: boolean },
): Promise<VerificationCheck> {
  const { required } = options;
  const packet = exactPacketBytes(pkg);
  const bindingHash = chainBindingPacketHash(pkg);
  if (packet.error) {
    return {
      name: "packet_commitment",
      label: "Evidence packet reproduces the committed hash",
      result: "FAIL",
      detail: packet.error,
    };
  }
  if (!packet.bytes || !bindingHash) {
    return {
      name: "packet_commitment",
      label: "Evidence packet reproduces the committed hash",
      result: required ? "FAIL" : "SKIPPED",
      detail: required
        ? "Strong verification requires the exact packet bytes and its committed hash."
        : "This package does not include the exact evidence packet and commitment needed for recomputation.",
    };
  }
  if (!validHex(bindingHash, 32)) {
    return {
      name: "packet_commitment",
      label: "Evidence packet reproduces the committed hash",
      result: "FAIL",
      detail: "The recorded packet commitment is not a 32-byte SHA-256 value.",
    };
  }
  const computed = await sha256Hex(packet.bytes);
  const statementHash = statementPacketHash(pkg.statement);
  const matches = computed === bindingHash.toLowerCase().replace(/^0x/, "");
  const statementMatches = !statementHash || normalizeFingerprint(statementHash) === computed;
  if (!matches || !statementMatches) {
    return {
      name: "packet_commitment",
      label: "Evidence packet reproduces the committed hash",
      result: "FAIL",
      detail: `Recomputed ${computed.slice(0, 16)}…; the proof binding records ${bindingHash.slice(0, 16)}…${statementMatches ? "" : " and the statement commitment differs"}.`,
    };
  }
  if (!packet.exact) {
    return {
      name: "packet_commitment",
      label: "Evidence packet reproduces the committed hash",
      result: required ? "FAIL" : "ATTENTION",
      detail:
        "The object reproduces the hash, but JSON parsing erases Python integer/float distinctions. Exact canonical packet bytes are required for strong verification.",
    };
  }
  return {
    name: "packet_commitment",
    label: "Evidence packet reproduces the committed hash",
    result: "PASS",
    detail: `Exact ${pkg.evidence_packet_canonicalization ?? pkg.canonicalization_algorithm ?? "declared"} bytes reproduce ${computed.slice(0, 16)}…`,
  };
}

async function checkTransparency(
  pkg: Package,
  required: boolean,
  keys: VerificationKey[],
  expectedPinnedFingerprint: string | null,
): Promise<VerificationCheck> {
  const transparency = pkg.transparency;
  const recordedLeaf = transparency?.leaf_hash_sha256;
  if (!recordedLeaf) {
    return {
      name: "transparency",
      label: "Statement is included in the transparency log",
      result: required ? "FAIL" : "SKIPPED",
      detail: required
        ? "Strong verification requires a transparency inclusion proof."
        : "This statement has not been written to the transparency log yet.",
    };
  }
  try {
    const committed = transparency?.packet_hash_sha256 ?? pkg.payload_digest_sha256 ?? "";
    if (!validHex(committed, 32) || !validHex(recordedLeaf, 32)) {
      throw new Error("The transparency commitment or leaf is not a 32-byte hash.");
    }
    let ok = toHex(await leafHash(committed)) === recordedLeaf.toLowerCase().replace(/^0x/, "");
    let detail = `Leaf ${transparency?.leaf_index ?? "?"} of ${transparency?.tree_size ?? "?"}.`;
    const checkpoint = transparency?.latest_checkpoint;
    const root = transparency?.root_sha256;
    const inclusion = transparency?.inclusion_proof;
    if (inclusion && root && validHex(root, 32) && checkpoint) {
      const checkpointTreeSize = checkpoint.tree_size;
      const proofTreeSize = transparency?.tree_size;
      const leafIndex = transparency?.leaf_index;
      if (
        typeof checkpointTreeSize !== "number" ||
        !Number.isSafeInteger(checkpointTreeSize) ||
        checkpointTreeSize < 1 ||
        proofTreeSize !== checkpointTreeSize ||
        typeof leafIndex !== "number" ||
        !Number.isSafeInteger(leafIndex) ||
        leafIndex < 0 ||
        leafIndex >= checkpointTreeSize ||
        !validHex(checkpoint.root_sha256, 32) ||
        normalizeFingerprint(checkpoint.root_sha256) !== normalizeFingerprint(root) ||
        !transparency.log_id
      ) {
        throw new Error("The inclusion proof is not bound to one well-formed signed checkpoint.");
      }
      let current = bytesFromHex(recordedLeaf);
      for (const step of inclusion) {
        if ((step.side !== "left" && step.side !== "right") || !validHex(step.hash, 32)) {
          throw new Error("The inclusion proof contains an invalid step.");
        }
        const sibling = bytesFromHex(step.hash);
        current = step.side === "left" ? await nodeHash(sibling, current) : await nodeHash(current, sibling);
      }
      const inclusionOk = toHex(current) === root.toLowerCase().replace(/^0x/, "");
      ok = ok && inclusionOk;
      detail += inclusionOk
        ? ` The inclusion proof reproduces root ${root.slice(0, 16)}….`
        : " The inclusion proof does not reproduce the published root.";
      const checkpointKey = keys.find((candidate) => candidate.kid === checkpoint.signature_kid);
      const checkpointBody = {
        log_id: transparency.log_id,
        tree_size: checkpointTreeSize,
        root_sha256: checkpoint.root_sha256,
      };
      const checkpointSignatureValid = await verifyDetachedPayload(
        checkpointBody,
        {
          alg: "Ed25519",
          kid: checkpoint.signature_kid,
          signature_b64: checkpoint.signature_b64,
        },
        checkpointKey,
      );
      const checkpointFingerprint = await keyFingerprint(checkpointKey);
      const checkpointPinned = Boolean(
        expectedPinnedFingerprint && checkpointFingerprint === expectedPinnedFingerprint,
      );
      if (!checkpointSignatureValid || (required && !checkpointPinned)) {
        throw new Error(
          checkpointSignatureValid
            ? "The checkpoint key is bundled but does not match the independently pinned issuer key."
            : "The checkpoint signature over {log_id, tree_size, root_sha256} is invalid.",
        );
      }
      detail += ` Checkpoint signature valid${checkpointPinned ? " and externally pinned" : " (self-consistency only)"}.`;
    } else if (required) {
      return {
        name: "transparency",
        label: "Statement is included in the transparency log",
        result: "FAIL",
        detail: `${detail} Strong verification requires an inclusion proof bound to a signed checkpoint.`,
      };
    } else {
      detail += " The leaf is consistent, but no complete signed-checkpoint proof was supplied.";
      return {
        name: "transparency",
        label: "Statement is included in the transparency log",
        result: ok ? "ATTENTION" : "FAIL",
        detail,
      };
    }
    return {
      name: "transparency",
      label: "Statement is included in the transparency log",
      result: ok ? "PASS" : "FAIL",
      detail,
    };
  } catch (error) {
    return {
      name: "transparency",
      label: "Statement is included in the transparency log",
      result: "FAIL",
      detail: error instanceof Error ? error.message : "The transparency proof is malformed.",
    };
  }
}

const STATUS_BY_STATEMENT_TYPE: Record<string, string> = {
  CORRECTION: "SUPERSEDED",
  DISPUTE: "DISPUTED",
  SUPERSESSION: "SUPERSEDED",
  REVOCATION: "REVOKED",
};

async function checkStatementLineage(
  pkg: Package,
  required: boolean,
  keys: VerificationKey[],
  expectedPinnedFingerprint: string | null,
): Promise<{ check: VerificationCheck; currentStatus: string | null }> {
  const lineage = pkg.statement_lineage;
  const binding = asRecord(pkg.statement_lineage_binding);
  const bindingSignature = pkg.statement_lineage_binding_signature;
  if (!lineage?.length || !binding || !bindingSignature) {
    return {
      currentStatus: null,
      check: {
        name: "statement_lineage",
        label: "Signed lineage establishes the statement's current status",
        result: required ? "FAIL" : "ATTENTION",
        detail: "No signed statement-lineage binding is available; the mutable outer status is not trusted.",
      },
    };
  }
  try {
    const statementRecord = asRecord(pkg.statement);
    const rootId = stringValue(statementRecord?.statement_id);
    const scanId = stringValue(statementRecord?.scan_id);
    if (!rootId || !scanId) throw new Error("The root statement has no stable statement_id or scan_id.");

    const ids: string[] = [];
    const digests: string[] = [];
    const byId = new Map<string, { digest: string; statement: Record_; type: string }>();
    let derivedStatus = "ACTIVE";
    for (const row of lineage) {
      const statement = asRecord(row.statement);
      const id = stringValue(statement?.statement_id);
      const type = stringValue(statement?.statement_type)?.toUpperCase();
      const digest = stringValue(row.payload_digest_sha256);
      if (!statement || !id || !type || !digest || !validHex(digest, 32) || byId.has(id)) {
        throw new Error("The lineage contains a malformed or duplicate statement.");
      }
      if (statement.scan_id !== scanId || row.statement_type !== statement.statement_type) {
        throw new Error(`Lineage metadata does not match signed statement ${id}.`);
      }
      if ((row.previous_statement_id ?? null) !== (statement.previous_statement_id ?? null)) {
        throw new Error(`Lineage predecessor metadata does not match signed statement ${id}.`);
      }
      const computedDigest = await sha256Hex(canonicalBytes(statement));
      if (computedDigest !== digest.toLowerCase().replace(/^0x/, "")) {
        throw new Error(`Lineage digest does not verify for statement ${id}.`);
      }
      const signatureKey = keys.find((candidate) => candidate.kid === row.signature?.kid);
      const signatureValid = await verifyDetachedPayload(statement, row.signature, signatureKey);
      const fingerprint = await keyFingerprint(signatureKey);
      if (!signatureValid || (required && fingerprint !== expectedPinnedFingerprint)) {
        throw new Error(
          signatureValid
            ? `Statement ${id} was signed by a bundled but unpinned key.`
            : `Statement ${id} has an invalid signature.`,
        );
      }
      const previousId = stringValue(statement.previous_statement_id);
      if (type === "RESULT") {
        if (previousId) throw new Error(`Result statement ${id} unexpectedly has a predecessor.`);
      } else {
        const previous = previousId ? byId.get(previousId) : undefined;
        if (!previous) throw new Error(`Statement ${id} does not reference an earlier signed statement.`);
        if (previousId !== ids[ids.length - 1]) {
          throw new Error(`Statement ${id} does not extend the current signed lineage tip.`);
        }
        if (statement.previous_payload_digest_sha256 !== previous.digest) {
          throw new Error(`Statement ${id} does not bind its predecessor digest.`);
        }
        const nextStatus = STATUS_BY_STATEMENT_TYPE[type];
        if (!nextStatus) throw new Error(`Statement ${id} has unsupported status type ${type}.`);
        derivedStatus = nextStatus;
      }
      ids.push(id);
      digests.push(digest);
      byId.set(id, { digest, statement, type });
    }

    const root = byId.get(rootId);
    if (!root || root.type !== "RESULT" || !sameCanonical(root.statement, pkg.statement)) {
      throw new Error("The packaged root statement is not the signed RESULT in its lineage.");
    }
    const expectedCheckpoint = pkg.transparency?.latest_checkpoint
      ? {
          log_id: pkg.transparency.log_id,
          tree_size: pkg.transparency.latest_checkpoint.tree_size,
          root_sha256: pkg.transparency.latest_checkpoint.root_sha256,
        }
      : null;
    const bindingConsistent =
      binding.schema === "creatorproof.statement_lineage_binding.v1" &&
      binding.scan_id === scanId &&
      binding.root_statement_id === rootId &&
      binding.current_status === derivedStatus &&
      sameCanonical(binding.statement_ids, ids) &&
      sameCanonical(binding.payload_digests_sha256, digests) &&
      sameCanonical(binding.checkpoint ?? null, expectedCheckpoint);
    if (!bindingConsistent) {
      throw new Error("The signed lineage binding does not match the verified lineage and checkpoint.");
    }
    const bindingKey = keys.find((candidate) => candidate.kid === bindingSignature.kid);
    const bindingValid = await verifyDetachedPayload(binding, bindingSignature, bindingKey);
    const bindingFingerprint = await keyFingerprint(bindingKey);
    if (!bindingValid || (required && bindingFingerprint !== expectedPinnedFingerprint)) {
      throw new Error(
        bindingValid
          ? "The lineage binding key is bundled but not independently pinned."
          : "The statement-lineage binding signature is invalid.",
      );
    }
    return {
      currentStatus: derivedStatus,
      check: {
        name: "statement_lineage",
        label: "Signed lineage establishes the statement's current status",
        result: "PASS",
        detail: `${lineage.length} signed statement(s) verify; derived current status is ${derivedStatus}.`,
      },
    };
  } catch (error) {
    return {
      currentStatus: null,
      check: {
        name: "statement_lineage",
        label: "Signed lineage establishes the statement's current status",
        result: "FAIL",
        detail: error instanceof Error ? error.message : "The statement lineage is malformed.",
      },
    };
  }
}

async function checkChainBinding(
  pkg: Package,
  required: boolean,
  key: { kid?: string; public_key_hex?: string } | undefined,
): Promise<{ check: VerificationCheck; signatureValid: boolean }> {
  const binding = proofBindingRecord(pkg);
  const publicScope =
    normalizedScope(binding?.proof_kind) || normalizedScope(binding?.anchor_scope);
  if (!binding || !publicScope) {
    return {
      signatureValid: false,
      check: {
        name: "package_chain_binding",
        label: "Issuer authenticated the packaged chain-binding record",
        result: required ? "FAIL" : "SKIPPED",
        detail: required
          ? "Strong verification requires a public EVM proof binding."
          : "No public-chain proof binding is present in this package.",
      },
    };
  }
  const packetHash = stringValue(binding.packet_hash_sha256);
  const statementHash = statementPacketHash(pkg.statement);
  const requiredFields = [
    stringValue(binding.transaction_hash),
    stringValue(binding.attestation_uid),
    stringValue(binding.contract_address),
    stringValue(binding.schema_uid),
    stringValue(binding.attester_address),
    binding.chain_id,
  ];
  const fieldsPresent = requiredFields.every((value) => value !== null && value !== undefined && value !== "");
  const hashMatches = Boolean(
    packetHash && statementHash && normalizeFingerprint(packetHash) === normalizeFingerprint(statementHash),
  );
  const confirmations = typeof binding.confirmations === "number" ? binding.confirmations : null;
  const requiredConfirmations =
    typeof binding.required_confirmations === "number" ? binding.required_confirmations : null;
  const confirmationPolicyMet = Boolean(
    confirmations !== null &&
      requiredConfirmations !== null &&
      requiredConfirmations >= 0 &&
      confirmations >= requiredConfirmations,
  );
  const finalityPolicy = stringValue(binding.finality_policy)?.trim().toLowerCase() ?? "confirmation_depth";
  const confirmationDepthReached =
    binding.confirmation_depth_reached === true ||
    (finalityPolicy === "confirmation_depth" && binding.finality_reached === true);
  const finalityPolicyMet =
    binding.anchor_conditions_met === true &&
    (finalityPolicy === "finalized"
      ? binding.finalized_block_verified === true && binding.finalized === true
      : finalityPolicy === "safe"
        ? binding.safe_block_verified === true
        : finalityPolicy === "confirmation_depth"
          ? confirmationDepthReached
          : false);
  const attestationValid = binding.attestation_valid === true;
  const canonicalReceipt = binding.canonical_receipt === true;
  const transactionSucceeded = binding.transaction_status === 1;
  const manifest = pkg.deployment?.manifest;
  const manifestBindingMatches = Boolean(
    manifest &&
      binding.chain_id === manifest.chain_id &&
      stringValue(binding.contract_address)?.toLowerCase() ===
        stringValue(manifest.contract_address)?.toLowerCase() &&
      stringValue(binding.schema_uid)?.toLowerCase() ===
        stringValue(manifest.schema_uid)?.toLowerCase() &&
      stringValue(binding.attester_address)?.toLowerCase() ===
        stringValue(manifest.required_attester_address)?.toLowerCase(),
  );
  const complete = Boolean(
    fieldsPresent &&
      hashMatches &&
      finalityPolicyMet &&
      confirmationPolicyMet &&
      attestationValid &&
      canonicalReceipt &&
      transactionSucceeded &&
      (!required || manifestBindingMatches),
  );
  const bindingSignature = pkg.proof_binding_signature ?? {};
  let bindingSignatureValid = false;
  try {
    const algorithm = (bindingSignature.alg ?? "Ed25519").trim().toLowerCase();
    if (algorithm !== "ed25519" && algorithm !== "eddsa") {
      throw new Error("Unsupported proof-binding signature algorithm");
    }
    if (!bindingSignature.signature_b64 || !bindingSignature.kid) {
      throw new Error("Proof-binding signature is missing");
    }
    if (bindingSignature.kid !== key?.kid || !key?.public_key_hex || !validHex(key.public_key_hex, 32)) {
      throw new Error("Proof-binding key does not match the statement key");
    }
    bindingSignatureValid = await verifyEd25519(
      bytesFromHex(key.public_key_hex),
      sigStructure(canonicalBytes(pkg.proof_binding)),
      base64ToBytes(bindingSignature.signature_b64),
    );
  } catch {
    bindingSignatureValid = false;
  }
  const detail = [
    `scope=${publicScope}`,
    `packet_match=${hashMatches}`,
    `finality_policy=${finalityPolicy}`,
    `finality_policy_met=${finalityPolicyMet}`,
    `confirmations=${confirmations ?? "?"}/${requiredConfirmations ?? "?"}`,
    `attestation_valid=${attestationValid}`,
    `canonical_receipt=${canonicalReceipt}`,
    `transaction_succeeded=${transactionSucceeded}`,
    `deployment_binding=${manifestBindingMatches}`,
    `binding_signature=${bindingSignatureValid}`,
  ].join(" · ");
  if (complete && bindingSignatureValid) {
    return {
      signatureValid: true,
      check: {
        name: "package_chain_binding",
        label: "Issuer authenticated the packaged chain-binding record",
        result: "PASS",
        detail: `${detail} · live chain state remains UNVERIFIED_OFFLINE`,
      },
    };
  }
  const signatureWasSupplied = Boolean(bindingSignature.signature_b64);
  return {
    signatureValid: bindingSignatureValid,
    check: {
      name: "package_chain_binding",
      label: "Issuer authenticated the packaged chain-binding record",
      // A bad issuer signature is package tampering and always fails. A validly
      // signed but pending/failed optional chain attempt does not invalidate the
      // independently signed evidence; it is surfaced as attention instead.
      result: !bindingSignatureValid && signatureWasSupplied
        ? "FAIL"
        : required
          ? "FAIL"
          : "ATTENTION",
      detail: `${detail}${fieldsPresent ? "" : " · required receipt fields are missing"} · this package does not independently prove live chain state`,
    },
  };
}

export async function verifyPackage(
  input: unknown,
  options: VerificationOptions = {},
): Promise<VerificationOutcome> {
  const pkg = (input && typeof input === "object" ? input : {}) as Package;
  const mode = options.mode ?? "self-contained";
  const requireTransparency = options.requireTransparency ?? mode === "strong";
  const requireChainBinding = options.requireChainBinding ?? mode === "strong";
  const checks: VerificationCheck[] = [];

  const statement = pkg.statement;
  const recordedDigest = pkg.payload_digest_sha256 ?? "";
  let canonical: Uint8Array | null = null;
  if (statement && typeof statement === "object" && recordedDigest) {
    canonical = canonicalBytes(statement);
    const computed = await sha256Hex(canonical);
    checks.push({
      name: "canonical_digest",
      label: "Canonical statement reproduces the recorded digest",
      result: computed === recordedDigest ? "PASS" : "FAIL",
      detail:
        computed === recordedDigest
          ? `SHA-256 of the RFC 8785 statement is ${computed.slice(0, 16)}…`
          : `Recomputed ${computed.slice(0, 16)}… but the package records ${recordedDigest.slice(0, 16)}…`,
    });
  } else {
    checks.push({
      name: "canonical_digest",
      label: "Canonical statement reproduces the recorded digest",
      result: "FAIL",
      detail: "The package is missing the statement body or its digest.",
    });
  }

  const signature = pkg.signature ?? {};
  const keys = pkg.trust_bundle?.keys ?? [];
  const key = keys.find((candidate) => candidate.kid === signature.kid);
  let keyFingerprint: string | null = null;
  let signatureValid = false;
  try {
    if (!signature.signature_b64) throw new Error("No signature was included in this statement package.");
    const algorithm = (signature.alg ?? "Ed25519").trim().toLowerCase();
    if (algorithm !== "ed25519" && algorithm !== "eddsa") {
      throw new Error(`Unsupported statement signature algorithm: ${signature.alg}`);
    }
    if (!key?.public_key_hex) {
      throw new Error(`Key ${signature.kid ?? "unknown"} is not in the bundled key set.`);
    }
    if (!validHex(key.public_key_hex, 32)) throw new Error("The bundled Ed25519 key is malformed.");
    if (!canonical) throw new Error("The statement could not be canonicalized.");
    const publicKey = bytesFromHex(key.public_key_hex);
    keyFingerprint = toHex(await sha256Bytes(publicKey));
    signatureValid = await verifyEd25519(
      publicKey,
      sigStructure(canonical),
      base64ToBytes(signature.signature_b64),
    );
    checks.push({
      name: "signature",
      label: "Signature matches the bundled Ed25519 key",
      result: signatureValid ? "PASS" : "FAIL",
      detail: signatureValid
        ? `Cryptographically valid for key ${signature.kid}${key.active === false ? " (retired; historical statements remain checkable)" : ""}. This alone does not establish who controls that key.`
        : "The signature does not verify against the bundled key.",
    });
  } catch (error) {
    checks.push({
      name: "signature",
      label: "Signature matches the bundled Ed25519 key",
      result: "FAIL",
      detail: error instanceof Error ? error.message : "The signature is malformed.",
    });
  }

  const declaredKeyFingerprint = normalizeFingerprint(
    pkg.deployment?.issuer_key_fingerprint_sha256,
  );
  const packageDeploymentFingerprint = normalizeFingerprint(
    pkg.deployment?.deployment_fingerprint_sha256,
  );
  const computedDeploymentFingerprint = pkg.deployment?.manifest
    ? await sha256Hex(canonicalBytes(pkg.deployment.manifest))
    : null;
  if (pkg.deployment?.issuer_key_fingerprint_sha256 && !declaredKeyFingerprint) {
    checks.push({
      name: "deployment_identity",
      label: "Package deployment identity is internally consistent",
      result: "FAIL",
      detail: "The package declares a malformed issuer-key fingerprint.",
    });
  } else if (declaredKeyFingerprint && keyFingerprint !== declaredKeyFingerprint) {
    checks.push({
      name: "deployment_identity",
      label: "Package deployment identity is internally consistent",
      result: "FAIL",
      detail: "The declared issuer-key fingerprint does not match the bundled public key.",
    });
  } else if (
    pkg.deployment?.deployment_fingerprint_sha256 &&
    (!packageDeploymentFingerprint || computedDeploymentFingerprint !== packageDeploymentFingerprint)
  ) {
    checks.push({
      name: "deployment_identity",
      label: "Package deployment identity is internally consistent",
      result: "FAIL",
      detail: "The declared deployment fingerprint does not match its chain deployment manifest.",
    });
  } else {
    checks.push({
      name: "deployment_identity",
      label: "Package deployment identity is internally consistent",
      result: keyFingerprint ? "PASS" : "SKIPPED",
      detail: declaredKeyFingerprint
        ? `The package fingerprint matches key ${signature.kid ?? "unknown"}${computedDeploymentFingerprint ? " and the deployment manifest reproduces its fingerprint" : ""}.`
        : "No deployment fingerprint was declared; the key fingerprint was computed locally.",
    });
  }

  const expectedKeyFingerprint = normalizeFingerprint(options.expectedIssuerKeyFingerprintSha256);
  const expectedDeploymentFingerprint = normalizeFingerprint(
    options.expectedDeploymentFingerprintSha256,
  );
  const expectedIssuer = options.expectedIssuer?.trim();
  const actualIssuer =
    pkg.deployment?.issuer ?? stringValue(asRecord(pkg.statement)?.issuer) ?? undefined;
  let trusted = false;
  if (options.expectedIssuerKeyFingerprintSha256 && !expectedKeyFingerprint) {
    checks.push({
      name: "issuer_trust",
      label: "Issuer matches an independently pinned identity",
      result: "FAIL",
      detail: "The configured issuer-key fingerprint is not a valid SHA-256 value.",
    });
  } else if (!expectedKeyFingerprint) {
    checks.push({
      name: "issuer_trust",
      label: "Issuer matches an independently pinned identity",
      result: mode === "strong" ? "FAIL" : "ATTENTION",
      detail:
        "The package supplied its own verification key. Configure an expected issuer-key fingerprint outside the package before treating the issuer as trusted.",
    });
  } else if (requireChainBinding && !options.expectedDeploymentFingerprintSha256) {
    checks.push({
      name: "issuer_trust",
      label: "Issuer matches an independently pinned identity",
      result: "FAIL",
      detail:
        "Strong chain verification requires a deployment fingerprint obtained outside the package.",
    });
  } else if (
    options.expectedDeploymentFingerprintSha256 &&
    !expectedDeploymentFingerprint
  ) {
    checks.push({
      name: "issuer_trust",
      label: "Issuer matches an independently pinned identity",
      result: "FAIL",
      detail: "The configured deployment fingerprint is not a valid SHA-256 value.",
    });
  } else {
    const keyMatches = signatureValid && keyFingerprint === expectedKeyFingerprint;
    const deploymentMatches = options.expectedDeploymentFingerprintSha256
      ? Boolean(
          expectedDeploymentFingerprint &&
            packageDeploymentFingerprint === expectedDeploymentFingerprint &&
            computedDeploymentFingerprint === expectedDeploymentFingerprint,
        )
      : true;
    const issuerMatches = expectedIssuer ? actualIssuer === expectedIssuer : true;
    trusted = keyMatches && deploymentMatches && issuerMatches;
    checks.push({
      name: "issuer_trust",
      label: "Issuer matches an independently pinned identity",
      result: trusted ? "PASS" : "FAIL",
      detail: trusted
        ? `Bundled key ${signature.kid ?? "unknown"} matches the externally configured fingerprint${expectedIssuer ? ` for ${expectedIssuer}` : ""}.`
        : `Pinned key match=${keyMatches} · deployment match=${deploymentMatches} · issuer match=${issuerMatches}.`,
    });
  }

  checks.push(await checkPacketCommitment(pkg, { required: requireChainBinding }));
  checks.push(
    await checkTransparency(pkg, requireTransparency, keys, expectedKeyFingerprint),
  );
  const lineage = await checkStatementLineage(
    pkg,
    mode === "strong",
    keys,
    expectedKeyFingerprint,
  );
  checks.push(lineage.check);
  const packageChainBinding = await checkChainBinding(pkg, requireChainBinding, key);
  checks.push(packageChainBinding.check);

  const status = lineage.currentStatus ?? "UNVERIFIED";
  checks.push({
    name: "statement_status",
    label: "Signed lineage establishes a current statement status",
    result: status === "ACTIVE" ? "PASS" : "ATTENTION",
    detail:
      status === "ACTIVE"
        ? "The fully verified signed lineage derives ACTIVE status."
        : status === "UNVERIFIED"
          ? "Current status could not be derived from a verified signed lineage."
          : `Signed-lineage status is ${status}: the historical signature may remain valid, but the result is not current for reliance.`,
  });

  const integrityChecks = checks.filter(
    (check) => check.name !== "issuer_trust" && check.name !== "statement_status",
  );
  const cryptographicallyValid = integrityChecks.every((check) => check.result !== "FAIL");
  // A non-ACTIVE statement remains historically authentic, but must never be
  // presented as currently valid for reliance after dispute/revocation.
  const current = status === "ACTIVE";
  const valid =
    mode === "strong"
      ? cryptographicallyValid && trusted && current
      : cryptographicallyValid && current;
  return {
    valid,
    cryptographicallyValid,
    trusted,
    packageBindingAuthenticated: packageChainBinding.signatureValid && trusted,
    liveChainStatus: "UNVERIFIED_OFFLINE",
    mode,
    checks,
    scope: trusted
      ? "The statement, required packaged bindings and externally pinned issuer identity verified. Live chain state is not proven offline; use the EAS re-check. This authenticates the record, not the truth of its claims."
      : cryptographicallyValid
        ? "The package is cryptographically self-consistent, but its bundled key is not an independent trust root. Pin the issuer-key fingerprint to authenticate who issued it."
        : "One or more integrity, transparency or chain-binding checks failed. Do not rely on this package.",
  };
}
