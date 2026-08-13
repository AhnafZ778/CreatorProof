"use client";

/**
 * Proof receipt and independent verification.
 *
 * The panel keeps two things apart that are easy to blur in a demo: a public
 * chain attestation, which anyone can look up in a block explorer, and a local
 * append-only transparency receipt, which is real cryptographic evidence but is
 * not a blockchain. Verification runs in the browser against the downloaded
 * package, so the check does not depend on the server agreeing with itself.
 */

import { useCallback, useEffect, useState } from "react";

import {
  explorerLinksFromReceipt,
  isPublicBlockchainProof,
  verifyPackage,
  type VerificationOutcome,
} from "@/app/lib/verifyStatement";

type Record_ = Record<string, unknown>;

function asRecord(value: unknown): Record_ | null {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record_) : null;
}

function text(value: unknown, fallback = "—"): string {
  return typeof value === "string" && value.length > 0 ? value : fallback;
}

function shorten(value: unknown, head = 10, tail = 8): string {
  const raw = typeof value === "string" ? value : "";
  if (!raw) return "—";
  return raw.length <= head + tail + 1 ? raw : `${raw.slice(0, head)}…${raw.slice(-tail)}`;
}

const EXPECTED_ISSUER_KEY_FINGERPRINT =
  process.env.NEXT_PUBLIC_CREATORPROOF_ISSUER_KEY_FINGERPRINT_SHA256?.trim() || undefined;
const EXPECTED_DEPLOYMENT_FINGERPRINT =
  process.env.NEXT_PUBLIC_CREATORPROOF_DEPLOYMENT_FINGERPRINT_SHA256?.trim() || undefined;
const EXPECTED_ISSUER = process.env.NEXT_PUBLIC_CREATORPROOF_ISSUER?.trim() || undefined;

export default function ProofPanel({ scan }: { scan: Record_ }) {
  const scanId = typeof scan.id === "string" ? scan.id : null;
  const packet = asRecord(scan.evidence_packet);
  const proof = asRecord(packet?.proof);
  const receipt = asRecord(proof?.receipt);
  const isChain = isPublicBlockchainProof(proof);
  const anchorStatus = text(proof?.anchor_status, "UNKNOWN").toUpperCase();
  const chainAnchored = isChain && ["ANCHORED", "CONFIRMED", "FINALIZED"].includes(anchorStatus);

  const [pkg, setPkg] = useState<unknown>(null);
  const [outcome, setOutcome] = useState<VerificationOutcome | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [chainCheck, setChainCheck] = useState<Record_ | null>(null);

  useEffect(() => {
    setPkg(null);
    setOutcome(null);
    setError(null);
    setChainCheck(null);
  }, [scanId]);

  const loadPackage = useCallback(async (): Promise<unknown> => {
    if (pkg) return pkg;
    if (!scanId) throw new Error("This scan has no identifier.");
    const response = await fetch(`/api/scans/${encodeURIComponent(scanId)}/verification-package`, {
      cache: "no-store",
    });
    const body = await response.json();
    if (!response.ok) {
      throw new Error(
        typeof body?.detail === "string" ? body.detail : "The package could not be downloaded.",
      );
    }
    setPkg(body);
    return body;
  }, [pkg, scanId]);

  async function runVerification() {
    setBusy(true);
    setError(null);
    try {
      const loaded = await loadPackage();
      const strong = Boolean(EXPECTED_ISSUER_KEY_FINGERPRINT);
      setOutcome(
        await verifyPackage(loaded, {
          mode: strong ? "strong" : "self-contained",
          expectedIssuerKeyFingerprintSha256: EXPECTED_ISSUER_KEY_FINGERPRINT,
          expectedDeploymentFingerprintSha256: EXPECTED_DEPLOYMENT_FINGERPRINT,
          expectedIssuer: EXPECTED_ISSUER,
          requireTransparency: strong,
          requireChainBinding: strong && isChain,
        }),
      );
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Verification could not run.");
    } finally {
      setBusy(false);
    }
  }

  async function download() {
    setBusy(true);
    setError(null);
    try {
      const loaded = await loadPackage();
      const blob = new Blob([JSON.stringify(loaded, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `creatorproof-verification-${scanId ?? "package"}.json`;
      anchor.click();
      URL.revokeObjectURL(url);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "The download failed.");
    } finally {
      setBusy(false);
    }
  }

  async function recheckOnChain() {
    const uid = typeof receipt?.attestation_uid === "string" ? receipt.attestation_uid : null;
    if (!uid) return;
    const packetHash =
      typeof proof?.packet_hash_sha256 === "string"
        ? proof.packet_hash_sha256
        : typeof receipt?.packet_hash_sha256 === "string"
          ? receipt.packet_hash_sha256
          : null;
    setBusy(true);
    setError(null);
    try {
      const query = packetHash
        ? `?expected_packet_hash_sha256=${encodeURIComponent(packetHash)}`
        : "";
      const response = await fetch(
        `/api/proof/attestations/${encodeURIComponent(uid)}${query}`,
        { cache: "no-store" },
      );
      const body = await response.json();
      if (!response.ok) {
        const detail = asRecord(body)?.detail;
        throw new Error(
          typeof detail === "string"
            ? detail
            : text(asRecord(detail)?.message, "The live chain check failed."),
        );
      }
      const record: Record_ = asRecord(body) ?? { response: body };
      setChainCheck(record);
      const checks = asRecord(record.checks);
      const verified =
        (record.valid === true || record.attestation_valid === true) &&
        (record.binding_matches === true || checks?.commitment_matches_expected === true) &&
        (record.anchor_conditions_met === true || record.confirmed === true);
      if (!verified) {
        setError(
          record.binding_matches === false || checks?.commitment_matches_expected === false
            ? "The live attestation does not commit this evidence packet."
            : "The attestation was found, but its packet binding or configured chain-acceptance policy is not verified.",
        );
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "The live chain check failed.");
    } finally {
      setBusy(false);
    }
  }

  const committedHash = shorten(proof?.packet_hash_sha256 ?? receipt?.packet_hash_sha256, 12, 10);
  const rows: Array<[string, string]> = isChain
    ? [
        ["Network", `${text(receipt?.network_label)} (chain ${String(receipt?.chain_id ?? "—")})`],
        ["Transaction", shorten(receipt?.transaction_hash)],
        ["Block", String(receipt?.block_number ?? "—")],
        ["Attestation UID", shorten(receipt?.attestation_uid)],
        ["Schema UID", shorten(receipt?.schema_uid)],
        ["Attester", shorten(receipt?.attester_address)],
        ["Committed packet hash", committedHash],
        ["Confirmations", String(receipt?.confirmations ?? "—")],
      ]
    : [
        ["Log", text(receipt?.log_id)],
        ["Leaf index", String(receipt?.leaf_index ?? "—")],
        ["Tree size", String(receipt?.tree_size ?? "—")],
        ["Merkle root", shorten(receipt?.root_sha256, 12, 10)],
        ["Committed packet hash", committedHash],
        ["Inclusion verified", receipt?.inclusion_verified === true ? "yes" : "no"],
      ];

  const explorerLinks = explorerLinksFromReceipt(receipt);
  const chainChecks = asRecord(chainCheck?.checks);
  const chainCheckValid =
    (chainCheck?.valid === true || chainCheck?.attestation_valid === true) &&
    (chainCheck?.binding_matches === true || chainChecks?.commitment_matches_expected === true) &&
    (chainCheck?.anchor_conditions_met === true || chainCheck?.confirmed === true);

  return (
    <section className="proofPanel" id="proof" aria-label="Proof receipt and verification">
      <header>
        <div>
          <small>{isChain ? "PUBLIC BLOCKCHAIN ATTESTATION" : "TAMPER-EVIDENT EVIDENCE RECEIPT"}</small>
          <h3>
            {isChain
              ? chainAnchored
                ? "Anchored on a public chain"
                : "Public-chain anchoring is not complete"
              : "Secured in the verification log"}
          </h3>
        </div>
        <span className={`anchorState ${anchorStatus.toLowerCase()}`}>
          {anchorStatus}
        </span>
      </header>

      <p className="proofScope">
        {isChain
          ? chainAnchored
            ? "This public attestation anchors the exact CreatorProof evidence-packet hash at a recorded point in time."
            : "This receipt targets a public-chain attestation, but the transaction is not yet confirmed and must not be presented as anchored."
          : "This receipt secures the exact CreatorProof evidence packet in an append-only verification log."}
      </p>

      <dl className="proofGrid">
        {rows.map(([label, value]) => (
          <div key={label}>
            <dt>{label}</dt>
            <dd>
              <code>{value}</code>
            </dd>
          </div>
        ))}
      </dl>

      <div className="proofActions">
        <button type="button" onClick={runVerification} disabled={busy || !scanId}>
          {busy ? "Working…" : "Verify in this browser"}
        </button>
        <button type="button" className="secondary" onClick={download} disabled={busy || !scanId}>
          Download verification package
        </button>
        {isChain && typeof receipt?.attestation_uid === "string" && (
          <button type="button" className="secondary" onClick={recheckOnChain} disabled={busy}>
            Re-check the attestation on chain
          </button>
        )}
        {explorerLinks.map((link) => (
          <a
            key={`${link.kind}:${link.url}`}
            className="proofExplorer"
            href={link.url}
            target="_blank"
            rel="noreferrer noopener"
          >
            {link.label}
          </a>
        ))}
      </div>

      <details className="technicalDisclosure proofTechnicalDisclosure">
        <summary>Show proof record details</summary>
        <p>
          {isChain
            ? chainAnchored
              ? "The public attestation binds the packet hash to the listed network, transaction, schema, and attester. It does not prove that the underlying claim is true."
              : "The chain provider and target scope are recorded, but no accepted public-chain packet binding is being claimed."
            : "The local receipt binds the packet hash to a Merkle inclusion record that can be independently checked in this browser."}
        </p>
      </details>

      {error && (
        <p className="proofError" role="alert">
          {error}
        </p>
      )}

      {outcome && (
        <div className={`verificationResult ${outcome.valid ? "valid" : "invalid"}`} role="status">
          <b>
            {outcome.valid && outcome.trusted
              ? "Issuer identity and evidence bindings verified"
              : outcome.cryptographicallyValid
                ? "Package is consistent; issuer identity is not independently pinned"
                : "Verification failed"}
          </b>
          <ul>
            {outcome.checks.map((check) => (
              <li key={check.name} className={check.result.toLowerCase()}>
                <span className="checkBadge">{check.result}</span>
                <div>
                  <strong>{check.label}</strong>
                  <em>{check.detail}</em>
                </div>
              </li>
            ))}
          </ul>
          <p className="verificationScope">{outcome.scope}</p>
        </div>
      )}

      {chainCheck && (
        <details className="chainRecheck" open>
          <summary>
            {chainCheckValid
              ? "Live chain check: attestation and packet binding verified"
              : "Live chain check needs attention"}
          </summary>
          <pre>{JSON.stringify(chainCheck, null, 2)}</pre>
        </details>
      )}

      <p className="offlineHint">
        The downloaded package verifies offline with{" "}
        <code>python scripts/verify_evidence_statement.py package.json</code>, using only the Python
        standard library.
      </p>
    </section>
  );
}
