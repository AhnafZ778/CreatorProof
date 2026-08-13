"use client";

/**
 * Counterparty co-attestation.
 *
 * Everything else on this page is signed by CreatorProof, so it can only show
 * when evidence existed. This panel is where a different organization binds
 * itself to the result with its own wallet key. The browser signs; CreatorProof
 * never sees the counterparty's private key, and only the 32-byte digest of the
 * signed decision reaches the chain.
 */

import { useCallback, useEffect, useState } from "react";

import { explorerLinksFromReceipt } from "@/app/lib/verifyStatement";

type Record_ = Record<string, unknown>;

type EthereumProvider = {
  request: (args: { method: string; params?: unknown[] }) => Promise<unknown>;
};

const DECISIONS = [
  ["ACCEPTED_FOR_PUBLICATION", "Accepted for publication"],
  ["ACKNOWLEDGED", "Acknowledged"],
  ["LICENSE_REQUIRED", "Licence required first"],
  ["REJECTED_FOR_PUBLICATION", "Rejected for publication"],
  ["DISPUTED", "Disputed"],
] as const;

const ROLES = ["BRAND", "AGENCY", "MARKETPLACE", "CREATOR", "REVIEWER"] as const;

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

function wallet(): EthereumProvider | null {
  const injected = (globalThis as { ethereum?: EthereumProvider }).ethereum;
  return injected && typeof injected.request === "function" ? injected : null;
}

function errorMessage(body: unknown, fallback: string): string {
  const detail = asRecord(body)?.detail;
  if (typeof detail === "string") return detail;
  const record = asRecord(detail);
  return text(record?.message ?? record?.code, fallback);
}

function checkLabel(name: string): string {
  switch (name) {
    case "body_hash_matches_body":
      return "Stored decision still hashes to the committed digest";
    case "signature_verified_at_submission":
      return "Signature recovered to the named member address";
    case "member_permitted_at_submission":
      return "Signer was an active member when it signed";
    case "binds_platform_attestation":
      return "Commitment names this scan's platform attestation";
    case "on_chain_commitment_matches_body_hash":
      return "On-chain value equals the decision digest";
    case "on_chain_ref_uid_matches_platform_attestation":
      return "On-chain reference points at the platform attestation";
    default:
      return name;
  }
}

export default function CoAttestationPanel({ scan }: { scan: Record_ }) {
  const scanId = typeof scan.id === "string" ? scan.id : null;
  const [status, setStatus] = useState<Record_ | null>(null);
  const [items, setItems] = useState<Record_[]>([]);
  const [role, setRole] = useState<string>("BRAND");
  const [orgId, setOrgId] = useState<string>("");
  const [decision, setDecision] = useState<string>(DECISIONS[0][0]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!scanId) return;
    const [statusResponse, listResponse] = await Promise.all([
      fetch("/api/network/status", { cache: "no-store" }),
      fetch(`/api/network/co-attestations?scan_id=${encodeURIComponent(scanId)}`, {
        cache: "no-store",
      }),
    ]);
    const statusBody = await statusResponse.json().catch(() => null);
    const listBody = await listResponse.json().catch(() => null);
    setStatus(statusResponse.ok ? asRecord(statusBody) : null);
    const listed = asRecord(listBody)?.items;
    setItems(Array.isArray(listed) ? (listed.filter(asRecord) as Record_[]) : []);
  }, [scanId]);

  useEffect(() => {
    setError(null);
    setNotice(null);
    void refresh();
  }, [refresh]);

  async function signAsCounterparty() {
    const provider = wallet();
    if (!scanId) return;
    if (!provider) {
      setError(
        "No EVM wallet was found in this browser. A counterparty signs with its own key, so this step cannot be delegated to the server.",
      );
      return;
    }
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const accounts = (await provider.request({ method: "eth_requestAccounts" })) as string[];
      const signer = accounts?.[0];
      if (!signer) throw new Error("The wallet did not return an account.");

      const challengeResponse = await fetch("/api/network/co-attestations/challenge", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          scan_id: scanId,
          signer_address: signer,
          party_org_id: orgId,
          party_role: role,
          decision,
        }),
      });
      const challenge = await challengeResponse.json();
      if (!challengeResponse.ok) {
        throw new Error(errorMessage(challenge, "The signing request was refused."));
      }

      const signature = (await provider.request({
        method: "eth_signTypedData_v4",
        params: [signer, JSON.stringify(challenge.typed_data)],
      })) as string;

      const submitResponse = await fetch("/api/network/co-attestations", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ scan_id: scanId, body: challenge.body, signature }),
      });
      const submitted = await submitResponse.json();
      if (!submitResponse.ok) {
        throw new Error(errorMessage(submitted, "The signature was not accepted."));
      }
      setNotice(
        "Signature accepted. The public commitment is queued; its transaction appears below once confirmed.",
      );
      await refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "The co-attestation could not be signed.");
    } finally {
      setBusy(false);
    }
  }

  const accepting = status?.accepting_signatures === true;
  const anchoring = status?.anchoring_ready === true;
  const reasons = Array.isArray(status?.reasons) ? (status.reasons as unknown[]) : [];
  const registry = asRecord(status?.member_registry);

  return (
    <section className="proofPanel" id="co-attestations" aria-label="Counterparty co-attestations">
      <header>
        <div>
          <small>MULTI-PARTY ATTESTATION</small>
          <h3>
            {items.length > 0
              ? `${items.length} counterparty commitment${items.length === 1 ? "" : "s"}`
              : "No counterparty has committed yet"}
          </h3>
        </div>
        <span className={`anchorState ${accepting ? "anchored" : "pending"}`}>
          {accepting ? "OPEN FOR SIGNATURES" : "UNAVAILABLE"}
        </span>
      </header>

      <p className="proofScope">
        A counterparty signs its decision with its own EVM key, so this is the one record on the
        page that CreatorProof could not have produced alone. Only the digest of the signed decision
        goes on chain, referenced to this scan&apos;s platform attestation.
      </p>

      {!accepting && (
        <p className="proofError" role="status">
          This deployment is not accepting counterparty signatures
          {reasons.length > 0 ? `: ${reasons.join(", ")}` : "."}
        </p>
      )}

      {accepting && !anchoring && (
        <p className="proofError" role="status">
          Signatures are still verified and stored, but the public commitment cannot be written yet.
          Nothing here should be presented as anchored.
        </p>
      )}

      {accepting && (
        <div className="proofActions">
          <label>
            Role
            <select value={role} onChange={(event) => setRole(event.target.value)} disabled={busy}>
              {ROLES.map((value) => (
                <option key={value} value={value}>
                  {value}
                </option>
              ))}
            </select>
          </label>
          <label>
            Organization
            <input
              value={orgId}
              onChange={(event) => setOrgId(event.target.value)}
              placeholder="brand-acme"
              disabled={busy}
            />
          </label>
          <label>
            Decision
            <select
              value={decision}
              onChange={(event) => setDecision(event.target.value)}
              disabled={busy}
            >
              {DECISIONS.map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          <button type="button" onClick={signAsCounterparty} disabled={busy || !scanId}>
            {busy ? "Waiting for the wallet…" : "Sign with a counterparty wallet"}
          </button>
        </div>
      )}

      {registry && (
        <p className="offlineHint">
          Membership authority:{" "}
          {registry.configured === true
            ? `on-chain registry ${shorten(registry.registry_address)} (${String(
                registry.active_member_count ?? "—",
              )} active members)`
            : "no registry contract configured; the local directory decides"}
        </p>
      )}

      {error && (
        <p className="proofError" role="alert">
          {error}
        </p>
      )}
      {notice && (
        <p className="proofScope" role="status">
          {notice}
        </p>
      )}

      {items.map((item) => {
        const chain = asRecord(item.public_chain);
        const checks = asRecord(item.checks) ?? {};
        return (
          <details key={String(item.id)} className="chainRecheck" open>
            <summary>
              {text(item.decision)} — {shorten(item.signer_address, 8, 6)} (
              {text(item.state, "UNKNOWN")})
            </summary>
            <dl className="proofGrid">
              <div>
                <dt>Signer</dt>
                <dd>
                  <code>{shorten(item.signer_address, 12, 10)}</code>
                </dd>
              </div>
              <div>
                <dt>Role</dt>
                <dd>
                  <code>{text(item.party_role)}</code>
                </dd>
              </div>
              <div>
                <dt>Committed digest</dt>
                <dd>
                  <code>{shorten(item.body_hash_sha256, 12, 10)}</code>
                </dd>
              </div>
              <div>
                <dt>Attestation UID</dt>
                <dd>
                  <code>{shorten(chain?.attestation_uid, 12, 10)}</code>
                </dd>
              </div>
              <div>
                <dt>References</dt>
                <dd>
                  <code>{shorten(item.platform_attestation_uid, 12, 10)}</code>
                </dd>
              </div>
              <div>
                <dt>Chain state</dt>
                <dd>
                  <code>{text(chain?.job_state, "PENDING")}</code>
                </dd>
              </div>
              <div>
                <dt>Transaction</dt>
                <dd>
                  <code>{shorten(chain?.transaction_hash, 12, 10)}</code>
                </dd>
              </div>
            </dl>
            {explorerLinksFromReceipt(chain).length > 0 && (
              <p className="proofActions">
                {explorerLinksFromReceipt(chain).map((link) => (
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
              </p>
            )}
            <ul>
              {Object.entries(checks).map(([name, value]) => (
                <li key={name} className={value === true ? "pass" : value === false ? "fail" : ""}>
                  <span className="checkBadge">
                    {value === true ? "PASS" : value === false ? "FAIL" : "PENDING"}
                  </span>
                  <div>
                    <strong>{checkLabel(name)}</strong>
                  </div>
                </li>
              ))}
            </ul>
          </details>
        );
      })}

      <details className="technicalDisclosure proofTechnicalDisclosure">
        <summary>What a counterparty commitment does and does not prove</summary>
        <p>
          It proves that this member signed this decision, about this evidence packet, at this time.
          It does not prove the decision is correct, that the member held authority to make it, or
          that any rights claim is true. The decision text, the member&apos;s name and any note stay
          off chain; the chain holds a 32-byte digest.
        </p>
      </details>
    </section>
  );
}
