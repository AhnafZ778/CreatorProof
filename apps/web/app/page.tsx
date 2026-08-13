"use client";

import { FormEvent, useEffect, useRef, useState } from "react";

import EvidenceMicroscope, {
  LocalImagePreview,
  topEvidenceWorkId,
  topStyleEvidenceWorkId,
} from "./components/EvidenceMicroscope";

type ApiResult = Record<string, unknown>;
type ApiHealth = "checking" | "online" | "offline";
type ScanProgress = {
  stage: string;
  label: string;
  percent: number;
};

const CONSOLE_VERSION = "0.9.2";
const BUILD_SIGNATURE = "SEMANTIC-SAFETY-SCOPE-2026.08.10";
const SCAN_POLL_BUDGET_MS = 180_000;

function progressFrom(result: ApiResult): ScanProgress | null {
  const packet = result.evidence_packet;
  if (!packet || typeof packet !== "object") return null;
  const progress = (packet as ApiResult).progress;
  if (!progress || typeof progress !== "object") return null;
  const row = progress as ApiResult;
  if (typeof row.label !== "string" || typeof row.percent !== "number") return null;
  return {
    stage: typeof row.stage === "string" ? row.stage : "PROCESSING",
    label: row.label,
    percent: Math.max(0, Math.min(99, Math.round(row.percent))),
  };
}

function ResultPanel({ title, result }: { title: string; result: ApiResult | null }) {
  if (!result) return null;
  return (
    <details className="result developerRecord">
      <summary><span>{title}</span><small>Developer API record</small></summary>
      <div className="resultGrid">
        <div><span>Match status</span><strong>{String(result.match_status ?? "n/a")}</strong></div>
        <div><span>Policy</span><strong>{String(result.policy_action ?? "n/a")}</strong></div>
        <div><span>Rights path</span><strong>{String(result.rights_path ?? "n/a")}</strong></div>
        <div><span>State</span><strong>{String(result.state ?? "registered")}</strong></div>
      </div>
      <details><summary>Raw evidence JSON</summary><pre>{JSON.stringify(result, null, 2)}</pre></details>
    </details>
  );
}

export default function Home() {
  const [workResult, setWorkResult] = useState<ApiResult | null>(null);
  const [scanResult, setScanResult] = useState<ApiResult | null>(null);
  const [workPreviews, setWorkPreviews] = useState<Record<string, LocalImagePreview>>({});
  const [candidatePreview, setCandidatePreview] = useState<LocalImagePreview | null>(null);
  const [apiHealth, setApiHealth] = useState<ApiHealth>("checking");
  const [apiVersion, setApiVersion] = useState<string | null>(null);
  const [aiAvailable, setAiAvailable] = useState<boolean | null>(null);
  const [aiProvider, setAiProvider] = useState<string | null>(null);
  const [aiReason, setAiReason] = useState<string | null>(null);
  const [styleProvider, setStyleProvider] = useState<string | null>(null);
  const [styleLearned, setStyleLearned] = useState<boolean | null>(null);
  const [styleReason, setStyleReason] = useState<string | null>(null);
  const [syntheticAvailable, setSyntheticAvailable] = useState<boolean | null>(null);
  const [syntheticProvider, setSyntheticProvider] = useState<string | null>(null);
  const [syntheticReason, setSyntheticReason] = useState<string | null>(null);
  const [visibleMarkerAvailable, setVisibleMarkerAvailable] = useState<boolean | null>(null);
  const [visibleMarkerReason, setVisibleMarkerReason] = useState<string | null>(null);
  const [provenanceProvider, setProvenanceProvider] = useState<string | null>(null);
  const [proofProvider, setProofProvider] = useState<string | null>(null);
  const [proofScope, setProofScope] = useState<string | null>(null);
  const [originPolicyMode, setOriginPolicyMode] = useState<string | null>(null);
  const [copyRetrievalRequirement, setCopyRetrievalRequirement] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [scanProgress, setScanProgress] = useState<ScanProgress | null>(null);
  const [scanElapsedSeconds, setScanElapsedSeconds] = useState(0);
  const [pendingScanId, setPendingScanId] = useState<string | null>(null);
  const [scanWaitPaused, setScanWaitPaused] = useState(false);
  const previewUrls = useRef(new Set<string>());

  useEffect(() => {
    const urls = previewUrls.current;
    return () => urls.forEach((url) => URL.revokeObjectURL(url));
  }, []);

  useEffect(() => {
    let mounted = true;
    fetch("/api/health", { cache: "no-store" })
      .then(async (response) => {
        const body = (await response.json()) as {
          version?: unknown;
          ai_available?: unknown;
          ai_provider?: unknown;
          ai_reason?: unknown;
          style_provider?: unknown;
          style_learned?: unknown;
          style_reason?: unknown;
          synthetic_available?: unknown;
          synthetic_provider?: unknown;
          synthetic_reason?: unknown;
          visible_marker_available?: unknown;
          visible_marker_reason?: unknown;
          provenance_provider?: unknown;
          proof_provider?: unknown;
          proof_scope?: unknown;
          origin_policy_mode?: unknown;
          copy_retrieval_requirement?: unknown;
        };
        if (!mounted) return;
        if (!response.ok) {
          setApiHealth("offline");
          return;
        }
        setApiHealth("online");
        setApiVersion(typeof body.version === "string" ? body.version : null);
        setAiAvailable(typeof body.ai_available === "boolean" ? body.ai_available : null);
        setAiProvider(typeof body.ai_provider === "string" ? body.ai_provider : null);
        setAiReason(typeof body.ai_reason === "string" ? body.ai_reason : null);
        setStyleProvider(typeof body.style_provider === "string" ? body.style_provider : null);
        setStyleLearned(typeof body.style_learned === "boolean" ? body.style_learned : null);
        setStyleReason(typeof body.style_reason === "string" ? body.style_reason : null);
        setSyntheticAvailable(typeof body.synthetic_available === "boolean" ? body.synthetic_available : null);
        setSyntheticProvider(typeof body.synthetic_provider === "string" ? body.synthetic_provider : null);
        setSyntheticReason(typeof body.synthetic_reason === "string" ? body.synthetic_reason : null);
        setVisibleMarkerAvailable(typeof body.visible_marker_available === "boolean" ? body.visible_marker_available : null);
        setVisibleMarkerReason(typeof body.visible_marker_reason === "string" ? body.visible_marker_reason : null);
        setProvenanceProvider(typeof body.provenance_provider === "string" ? body.provenance_provider : null);
        setProofProvider(typeof body.proof_provider === "string" ? body.proof_provider : null);
        setProofScope(typeof body.proof_scope === "string" ? body.proof_scope : null);
        setOriginPolicyMode(typeof body.origin_policy_mode === "string" ? body.origin_policy_mode : null);
        setCopyRetrievalRequirement(typeof body.copy_retrieval_requirement === "string" ? body.copy_retrieval_requirement : null);
      })
      .catch(() => {
        if (mounted) setApiHealth("offline");
      });
    return () => {
      mounted = false;
    };
  }, []);

  function preview(file: File): LocalImagePreview {
    const url = URL.createObjectURL(file);
    previewUrls.current.add(url);
    return { url, name: file.name };
  }

  async function submitWork(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy("work");
    setError(null);
    const form = new FormData(event.currentTarget);
    const uploadedFile = form.get("file");
    form.set("allowed_uses", JSON.stringify([String(form.get("allowed_use") || "marketing/social")]));
    form.delete("allowed_use");
    const response = await fetch("/api/works", { method: "POST", body: form });
    const body = await response.json();
    if (!response.ok) setError(JSON.stringify(body));
    else {
      setWorkResult(body);
      if (uploadedFile instanceof File && typeof body.id === "string") {
        setWorkPreviews((current) => ({ ...current, [body.id]: preview(uploadedFile) }));
      }
    }
    setBusy(null);
  }

  async function submitScan(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy("scan");
    setError(null);
    setScanWaitPaused(false);
    setScanElapsedSeconds(0);
    setScanProgress({ stage: "UPLOADING", label: "Uploading the image", percent: 0 });
    const form = new FormData(event.currentTarget);
    const uploadedFile = form.get("file");
    if (uploadedFile instanceof File) setCandidatePreview(preview(uploadedFile));
    try {
      const response = await fetch("/api/scans", {
        method: "POST",
        headers: { "Idempotency-Key": crypto.randomUUID() },
        body: form,
        signal: AbortSignal.timeout(35_000),
      });
      const body = (await response.json()) as ApiResult;
      if (!response.ok) {
        setError(`The scan could not start. ${JSON.stringify(body)}`);
        setBusy(null);
        return;
      }
      if (typeof body.id !== "string") {
        setError("The scan started without a usable scan ID. Check the API logs.");
        setBusy(null);
        return;
      }
      setScanResult(body);
      setPendingScanId(body.id);
      setScanProgress(
        progressFrom(body) ?? { stage: "QUEUED", label: "Waiting to start", percent: 1 },
      );
      await pollScan(body.id);
    } catch (caught) {
      const message = caught instanceof Error && caught.name === "TimeoutError"
        ? "The API did not accept the scan within 35 seconds. Check that the local background backend is active."
        : "The scan request was interrupted. Check the API connection and try again.";
      setError(message);
      setBusy(null);
    }
  }

  async function pollScan(scanId: string) {
    const startedAt = Date.now();
    let consecutiveErrors = 0;
    setBusy("scan");
    setScanWaitPaused(false);
    while (Date.now() - startedAt < SCAN_POLL_BUDGET_MS) {
      const elapsed = Date.now() - startedAt;
      setScanElapsedSeconds(Math.round(elapsed / 1000));
      const delay = elapsed < 20_000 ? 750 : elapsed < 60_000 ? 1_250 : 2_000;
      await new Promise((resolve) => setTimeout(resolve, delay));
      try {
        const poll = await fetch(`/api/scans/${encodeURIComponent(scanId)}`, {
          cache: "no-store",
          signal: AbortSignal.timeout(10_000),
        });
        const body = (await poll.json()) as ApiResult;
        if (!poll.ok) throw new Error(`SCAN_POLL_${poll.status}`);
        consecutiveErrors = 0;
        setScanResult(body);
        const progress = progressFrom(body);
        if (progress) setScanProgress(progress);
        if (body.state === "COMPLETED" || body.state === "FAILED") {
          setBusy(null);
          setPendingScanId(null);
          setScanWaitPaused(false);
          setScanProgress(null);
          if (body.state === "COMPLETED" && body.anchor_status === "PENDING") {
            void refreshPendingProof(scanId);
          }
          if (body.state === "FAILED") {
            setError(`The scan stopped at the server (${String(body.error_code ?? "unknown error")}).`);
          }
          return;
        }
      } catch {
        consecutiveErrors += 1;
        if (consecutiveErrors >= 3) {
          setError("Live progress was interrupted. The server may still be working; use Check again.");
          break;
        }
      }
    }
    setBusy(null);
    setScanWaitPaused(true);
  }

  async function refreshPendingProof(scanId: string) {
    const deadline = Date.now() + 110_000;
    while (Date.now() < deadline) {
      await new Promise((resolve) => setTimeout(resolve, 2_000));
      try {
        const response = await fetch(`/api/scans/${encodeURIComponent(scanId)}`, {
          cache: "no-store",
          signal: AbortSignal.timeout(8_000),
        });
        if (!response.ok) continue;
        const body = (await response.json()) as ApiResult;
        setScanResult(body);
        if (body.anchor_status !== "PENDING") return;
      } catch {
        // Proof status is secondary to the already completed evidence result.
      }
    }
  }

  const evidenceWorkId = topEvidenceWorkId(scanResult);
  const evidenceReferencePreview = evidenceWorkId
    ? workPreviews[evidenceWorkId] ?? {
        url: `/api/works/${encodeURIComponent(evidenceWorkId)}/media`,
        name: `Registered reference · ${evidenceWorkId.slice(0, 8)}`,
      }
    : null;
  const styleWorkId = topStyleEvidenceWorkId(scanResult);
  const styleReferencePreview = styleWorkId
    ? workPreviews[styleWorkId] ?? {
        url: `/api/works/${encodeURIComponent(styleWorkId)}/media`,
        name: `Style exemplar · ${styleWorkId.slice(0, 8)}`,
      }
    : null;
  const versionMismatch = apiHealth === "online" && apiVersion !== CONSOLE_VERSION;
  const scanCompleted = scanResult?.state === "COMPLETED";
  const scanIsRunning = scanResult?.state === "QUEUED" || scanResult?.state === "PROCESSING";

  return (
    <>
      <nav className={`releaseBar ${versionMismatch ? "mismatch" : ""}`} aria-label="CreatorProof status">
        <div className="releaseIdentity">
          <span className="wordmark">CreatorProof</span>
          <span className="versionTag">v{CONSOLE_VERSION}</span>
          <span className="editionText">Visual rights intelligence</span>
        </div>
        <div className="releaseNav" aria-label="Page navigation">
          <a href="#workspace">Workbench</a>
          <a href={scanCompleted ? "#analysis" : "#scan-work"} className={scanCompleted ? "ready" : "pending"}>Analysis</a>
          <a href="#system">System</a>
        </div>
        <div className={`stackHealth ${apiHealth} ${versionMismatch ? "mismatch" : ""}`}>
          <i />
          <span>{apiHealth === "checking" ? "API CHECKING" : apiHealth === "offline" ? "API OFFLINE" : `API ${apiVersion ?? "unknown"}`}</span>
          <small>{BUILD_SIGNATURE}</small>
        </div>
      </nav>

      <main>
        {versionMismatch && (
          <div className="versionWarning" role="alert">
            <b>Version mismatch.</b>
            <span>This console is v{CONSOLE_VERSION}; the API reports v{apiVersion ?? "unknown"}. Restart both services from this v0.9.2 folder before evaluating results.</span>
          </div>
        )}

        <header className="productHeader">
          <div className="productKicker">CHECK BEFORE PUBLISHING / CLEAR VISUAL EVIDENCE</div>
          <div className="productIntroGrid">
            <h1>See what matches.<br /><span>Understand why.</span></h1>
            <div className="productStatement">
              <p>
                CreatorProof answers three separate questions: was AI likely used, does the image reuse a
                stored work, and does different content resemble a registered creator profile. Each result explains
                its score and tells you what to do next.
              </p>
              <p className="boundaryNote">It produces review evidence and customer-policy decisions—not legal infringement rulings.</p>
            </div>
          </div>
        </header>

        <nav className="journeyStrip" aria-label="CreatorProof workflow">
          <a href="#register-work" className={workResult ? "complete" : "active"}>
            <span>01</span><div><small>BUILD THE CATALOG</small><b>Register work</b><em>{workResult ? "Reference added" : "Upload protected originals"}</em></div><i>→</i>
          </a>
          <a href="#scan-work" className={scanCompleted ? "complete" : workResult ? "active" : "queued"}>
            <span>02</span><div><small>CHALLENGE IT</small><b>Run a scan</b><em>{scanCompleted ? "Scan completed" : scanIsRunning ? "Checks are running" : "Upload the candidate"}</em></div><i>→</i>
          </a>
          <a href={scanCompleted ? "#analysis" : "#scan-work"} className={scanCompleted ? "active" : "queued"}>
            <span>03</span><div><small>UNDERSTAND THE RESULT</small><b>Explore analysis</b><em>{scanCompleted ? "Four simple views available" : scanIsRunning ? "Available when checks finish" : "Available after scanning"}</em></div><i>↓</i>
          </a>
        </nav>

        <details id="system" className="systemDisclosure">
          <summary>System readiness <small>Open model and proof status</small></summary>
          <section className="runtimeLedger runtimeLedgerExpanded" aria-label="Active models">
            <div><span>Stored-work search</span><b>{aiAvailable ? "Ready" : copyRetrievalRequirement === "LEARNED_REQUIRED" ? "Required model missing" : "Baseline mode"}</b><small>{copyRetrievalRequirement ?? "requirement checking"} · {aiProvider ?? aiReason ?? "checking"}</small></div>
            <div><span>Matched-area check</span><b>Ready</b><small>Strict local alignment</small></div>
            <div><span>Creator profile</span><b>{styleLearned ? "Ready" : "Basic mode"}</b><small>{styleProvider ?? styleReason ?? "checking"}</small></div>
            <div><span>AI model checks</span><b>{originPolicyMode === "DISABLED" ? "Disabled by policy" : originPolicyMode === "INFORMATIONAL" ? "Informational" : syntheticAvailable ? "Required / ready" : "Required / unavailable"}</b><small>{originPolicyMode ?? "policy checking"} · {syntheticProvider ?? syntheticReason ?? "checking"}</small></div>
            <div><span>Visible AI labels</span><b>{visibleMarkerAvailable ? "Ready" : "Needs setup"}</b><small>{visibleMarkerAvailable ? "Local text check active" : visibleMarkerReason ?? "checking"}</small></div>
            <div><span>Proof receipt</span><b>{proofScope === "PUBLIC_EVM_ATTESTATION" ? "Public chain" : "Local receipt"}</b><small>{provenanceProvider ?? "source info unavailable"} · {proofProvider ?? "checking"}</small></div>
          </section>
        </details>

        <section id="workspace" className="workflowArea">
          <div className="sectionHeading">
            <div><span>WORKBENCH</span><h2>Build the catalog, then challenge it.</h2></div>
            <p>For style experiments, register at least three representative works under the exact same creator profile name.</p>
          </div>

          <div className="grid">
            <form id="register-work" className="card registerCard" onSubmit={submitWork}>
              <div className="cardHeading"><span>01</span><div><small>REFERENCE CATALOG</small><h3>Register protected work</h3></div></div>
              <p className="cardSummary">Create the trusted source record used by copy retrieval and creator-profile analysis.</p>
              <div className="formColumns">
                <label className="full">Reference image<input required type="file" name="file" accept="image/*" /></label>
                <label>Title<input required name="title" defaultValue="Demo reference" /></label>
                <label>Catalog<input required name="catalog_id" defaultValue="demo-catalog" /></label>
                <label className="full">Creator profile<input required name="claimant" defaultValue="Demo Creator" /><small>Reuse this exact name across the creator&apos;s representative works.</small></label>
                <label>Rights path<select name="rights_path" defaultValue="EXISTING_LICENSE"><option>EXISTING_LICENSE</option><option>LICENSE_AVAILABLE</option><option>NO_LICENSE_INFO</option><option>DISPUTED</option></select></label>
                <label>Allowed use<input name="allowed_use" defaultValue="marketing/social" /></label>
                <label className="full">Claim verification<select name="claim_state" defaultValue="ASSERTED"><option value="ASSERTED">ASSERTED — not independently checked</option><option value="CORROBORATED">CORROBORATED — demo/admin verified</option><option value="DISPUTED">DISPUTED — contested</option><option value="SUPERSEDED">SUPERSEDED — replaced</option><option value="REVOKED">REVOKED — withdrawn</option></select><small>Only a corroborated claim can authorize a recorded use. In production this state belongs to a controlled review workflow.</small></label>
              </div>
              <button className="registerAction" disabled={busy !== null}>{busy === "work" ? "Registering…" : "Register reference"}</button>
            </form>

            <form id="scan-work" className="card scanCard" onSubmit={submitScan}>
              <div className="cardHeading"><span>02</span><div><small>PRE-PUBLICATION SCAN</small><h3>Challenge the catalog</h3></div></div>
              <p className="cardSummary">Search every registered work, verify the strongest candidate, then open the evidence workspace.</p>
              <div className="formColumns">
                <label className="full">Candidate image<input required type="file" name="file" accept="image/*" /></label>
                <label>Catalog<input required name="catalog_id" defaultValue="demo-catalog" /></label>
                <label>Intended use<input required name="intended_use" defaultValue="marketing/social" /></label>
              </div>
              <div className="contract"><b>How the result works</b><span>A strong stored-work match can trigger rights review. AI-use and creator resemblance stay separate.</span></div>
              <button className="scanAction" disabled={busy !== null}>{busy === "scan" ? "Running evidence checks…" : "Run evidence verification"}</button>
              {pendingScanId && (scanIsRunning || scanWaitPaused) && (
                <div className="scanProgressPanel" role="status" aria-live="polite">
                  <div className="scanProgressHeading">
                    <span>{scanWaitPaused ? "Scan still running" : "Scan in progress"}</span>
                    <b>{scanProgress?.percent ?? 1}%</b>
                  </div>
                  <div className="scanProgressTrack" aria-hidden="true">
                    <i style={{ width: `${scanProgress?.percent ?? 1}%` }} />
                  </div>
                  <strong>{scanProgress?.label ?? "Waiting for the next update"}</strong>
                  <p>
                    {scanWaitPaused
                      ? "Live updates paused after three minutes. Your scan was not cancelled."
                      : `Working in the background · ${scanElapsedSeconds}s elapsed`}
                  </p>
                  <small>Scan ID: {pendingScanId}</small>
                  {scanWaitPaused && (
                    <button type="button" onClick={() => void pollScan(pendingScanId)}>
                      Check again
                    </button>
                  )}
                </div>
              )}
            </form>
          </div>
        </section>

        {error && <div className="error">{error}</div>}
        {scanResult?.state === "COMPLETED" && (
          <EvidenceMicroscope
            scan={scanResult}
            candidate={candidatePreview}
            copyReference={evidenceReferencePreview}
            styleReference={styleReferencePreview}
          />
        )}

        <ResultPanel title="Registered work" result={workResult} />
        <ResultPanel title="Latest scan" result={scanResult} />

        <footer>
          <div><b>CreatorProof v{CONSOLE_VERSION}</b><span>{BUILD_SIGNATURE}</span></div>
          <p>CreatorProof keeps AI-use, stored-work matching, and creator resemblance separate. Every result is source-scoped review evidence, not a legal ruling. Local receipts are clearly separated from optional public-chain proof.</p>
        </footer>
      </main>
    </>
  );
}
