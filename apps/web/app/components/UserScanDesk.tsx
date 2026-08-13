"use client";

import { FormEvent, useCallback, useEffect, useRef, useState } from "react";

import { buildScenario, type DemoScenario } from "@/app/lib/demoScenarios";

import CoAttestationPanel from "./CoAttestationPanel";
import DemoScenarioPicker from "./DemoScenarioPicker";
import EvidenceMicroscope, {
  LocalImagePreview,
  topEvidenceWorkId,
  topStyleEvidenceWorkId,
} from "./EvidenceMicroscope";
import PortalFileField from "./PortalFileField";
import ProofPanel from "./ProofPanel";
import ScanVerdict from "./ScanVerdict";
import StageTimelinePanel, { type StageTimeline } from "./StageTimeline";

type ApiResult = Record<string, unknown>;
type ScanProgress = {
  stage: string;
  label: string;
  percent: number;
};

const SCAN_POLL_BUDGET_MS = 180_000;

function scrollToResult(id: string) {
  document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });
}

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

export default function UserScanDesk() {
  const [scanResult, setScanResult] = useState<ApiResult | null>(null);
  const [candidatePreview, setCandidatePreview] = useState<LocalImagePreview | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [scanProgress, setScanProgress] = useState<ScanProgress | null>(null);
  const [scanElapsedSeconds, setScanElapsedSeconds] = useState(0);
  const [pendingScanId, setPendingScanId] = useState<string | null>(null);
  const [scanWaitPaused, setScanWaitPaused] = useState(false);
  const [timeline, setTimeline] = useState<StageTimeline | null>(null);
  const [cancelling, setCancelling] = useState(false);
  const [demoScenarioId, setDemoScenarioId] = useState<string | null>(null);
  const previewUrls = useRef(new Set<string>());

  useEffect(() => {
    const urls = previewUrls.current;
    return () => urls.forEach((url) => URL.revokeObjectURL(url));
  }, []);

  function preview(file: File): LocalImagePreview {
    const url = URL.createObjectURL(file);
    previewUrls.current.add(url);
    return { url, name: file.name };
  }

  const refreshTimeline = useCallback(async (scanId: string) => {
    try {
      const response = await fetch(`/api/scans/${encodeURIComponent(scanId)}/stages`, {
        cache: "no-store",
      });
      if (!response.ok) return;
      setTimeline((await response.json()) as StageTimeline);
    } catch {
      // Stage ledger is diagnostic only.
    }
  }, []);

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
        // Proof status is secondary.
      }
    }
  }

  const pollScan = useCallback(
    async (scanId: string) => {
      const startedAt = Date.now();
      let consecutiveErrors = 0;
      setBusy(true);
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
          void refreshTimeline(scanId);
          if (body.state === "COMPLETED" || body.state === "FAILED" || body.state === "CANCELLED") {
            setBusy(false);
            setPendingScanId(null);
            setScanWaitPaused(false);
            setScanProgress(null);
            if (body.state === "COMPLETED" && body.anchor_status === "PENDING") {
              void refreshPendingProof(scanId);
            }
            if (body.state === "FAILED") {
              setError(
                `The scan stopped at the server (${String(body.error_code ?? "unknown error")}).`,
              );
            }
            if (body.state === "CANCELLED") {
              setError("This scan was cancelled. No evidence packet was produced.");
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
      setBusy(false);
      setScanWaitPaused(true);
    },
    [refreshTimeline],
  );

  async function startScan(form: FormData, candidateFile: File | null) {
    setBusy(true);
    setError(null);
    setTimeline(null);
    setScanWaitPaused(false);
    setScanElapsedSeconds(0);
    setScanProgress({ stage: "UPLOADING", label: "Uploading the image", percent: 0 });
    if (candidateFile) setCandidatePreview(preview(candidateFile));
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
        setBusy(false);
        return;
      }
      if (typeof body.id !== "string") {
        setError("The scan started without a usable scan ID. Check the API logs.");
        setBusy(false);
        return;
      }
      setScanResult(body);
      setPendingScanId(body.id);
      setScanProgress(
        progressFrom(body) ?? { stage: "QUEUED", label: "Waiting to start", percent: 1 },
      );
      await pollScan(body.id);
    } catch (caught) {
      const message =
        caught instanceof Error && caught.name === "TimeoutError"
          ? "The API did not accept the scan within 35 seconds. Check that the local backend is active."
          : "The scan request was interrupted. Check the API connection and try again.";
      setError(message);
      setBusy(false);
    }
  }

  async function submitScan(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    const uploadedFile = form.get("file");
    await startScan(form, uploadedFile instanceof File ? uploadedFile : null);
  }

  async function runDemoScenario(scenario: DemoScenario) {
    setDemoScenarioId(scenario.id);
    // Held from the first click rather than from the scan itself: generating the
    // images and registering the references takes seconds, and the manual form
    // must not accept a second run underneath a scenario that is still setting up.
    setBusy(true);
    setError(null);
    setScanResult(null);
    setTimeline(null);
    try {
      const bundle = await buildScenario(scenario);
      // A catalog per run, so repeated demos never inflate the coverage counts
      // that the result page reports as eligible references.
      const catalogId = `demo-${scenario.id}-${crypto.randomUUID().slice(0, 8)}`;

      for (const reference of bundle.references) {
        const registration = new FormData();
        registration.append("file", reference.file);
        registration.append("title", reference.title);
        registration.append("claimant", reference.claimant);
        registration.append("catalog_id", catalogId);
        registration.append("claim_state", "ASSERTED");
        const response = await fetch("/api/works", { method: "POST", body: registration });
        if (!response.ok) {
          throw new Error(`The demo reference could not be registered (${response.status}).`);
        }
      }

      const form = new FormData();
      form.append("file", bundle.candidate);
      form.append("catalog_id", catalogId);
      form.append("intended_use", scenario.intendedUse);
      await startScan(form, bundle.candidate);
    } catch (caught) {
      setError(
        caught instanceof Error
          ? `The demo scenario could not start. ${caught.message}`
          : "The demo scenario could not start.",
      );
      setBusy(false);
    } finally {
      setDemoScenarioId(null);
    }
  }

  async function cancelScan() {
    if (!pendingScanId) return;
    setCancelling(true);
    try {
      await fetch(`/api/scans/${encodeURIComponent(pendingScanId)}/cancel`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ reason: "Cancelled from the User portal" }),
      });
    } catch {
      setError("The cancellation request could not be delivered.");
    } finally {
      setCancelling(false);
    }
  }

  const evidenceWorkId = topEvidenceWorkId(scanResult);
  const evidenceReferencePreview = evidenceWorkId
    ? {
        url: `/api/works/${encodeURIComponent(evidenceWorkId)}/media`,
        name: `Registered reference · ${evidenceWorkId.slice(0, 8)}`,
      }
    : null;
  const styleWorkId = topStyleEvidenceWorkId(scanResult);
  const styleReferencePreview = styleWorkId
    ? {
        url: `/api/works/${encodeURIComponent(styleWorkId)}/media`,
        name: `Style exemplar · ${styleWorkId.slice(0, 8)}`,
      }
    : null;

  const scanCompleted = scanResult?.state === "COMPLETED";
  const scanIsRunning = scanResult?.state === "QUEUED" || scanResult?.state === "PROCESSING";

  return (
    <div className="userScanDesk">
      <section id="scan-work" className="workflowArea" style={{ paddingTop: 0 }}>
        <form className="card scanCard" onSubmit={submitScan}>
          <div className="cardHeading">
            <span>02</span>
            <div>
              <small>PRE-PUBLICATION SCAN</small>
              <h3>Challenge the catalog</h3>
            </div>
          </div>
          <p className="cardSummary">
            Scan for AI-origin intelligence, stored-work reuse, and creator-profile signals.
          </p>
          <div className="formColumns portalForm">
            <div className="full">
              <PortalFileField
                required
                name="file"
                label="Candidate image"
                hint="PNG, JPG, or WEBP — the asset you plan to publish"
              />
            </div>
            <label className="portalField">
              <span className="portalFieldLabel">Catalog</span>
              <input required name="catalog_id" defaultValue="demo-catalog" />
            </label>
            <label className="portalField">
              <span className="portalFieldLabel">Intended use</span>
              <input required name="intended_use" defaultValue="marketing/social" />
            </label>
          </div>
          <div className="contract">
            <b>What CreatorProof checks</b>
            <span>
              AI-origin signals, verified visual reuse, creator-profile resemblance, and the recorded
              rights path.
            </span>
          </div>
          <button className="scanAction" disabled={busy}>
            {busy ? "Running CreatorProof analysis…" : "Run CreatorProof analysis"}
          </button>
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

        {/* Stays up while a scenario prepares so the chosen card can show its
            progress, and gives way to the stage timeline once the scan starts. */}
        {!scanResult && !scanIsRunning && (demoScenarioId !== null || !busy) && (
          <DemoScenarioPicker
            onRun={(scenario) => void runDemoScenario(scenario)}
            runningId={demoScenarioId}
            disabled={busy || demoScenarioId !== null}
          />
        )}

        {(scanIsRunning || (timeline && !scanCompleted)) && (
          <StageTimelinePanel
            timeline={timeline}
            elapsedSeconds={scanElapsedSeconds}
            onCancel={pendingScanId ? () => void cancelScan() : undefined}
            cancelling={cancelling}
          />
        )}
      </section>

      {error && (
        <div className="error" role="alert">
          {error}
        </div>
      )}

      {/* Verdict, then the evidence behind it, then the receipt that seals it.
          The workspace sits directly under the verdict rather than at the end,
          because "why did it say that" is the next question every reader has
          and burying it turns the summary into something to be taken on faith. */}
      {scanCompleted && scanResult && (
        <div id="scan-results" className="userScanResults">
          <ScanVerdict
            scan={scanResult}
            onOpenEvidence={() => scrollToResult("evidence")}
            onOpenProof={() => scrollToResult("proof")}
          />

          <section className="evidenceSection" id="evidence" aria-label="Evidence workspace">
            <header className="evidenceSectionHead">
              <div>
                <small>THE EVIDENCE</small>
                <h3>Why the scan reached that result</h3>
              </div>
              <p>
                Matched regions, the AI-origin ledger, and the creator profile behind each lane —
                with every raw score kept one click away rather than on the surface.
              </p>
            </header>
            <EvidenceMicroscope
              scan={scanResult}
              candidate={candidatePreview}
              copyReference={evidenceReferencePreview}
              styleReference={styleReferencePreview}
            />
          </section>

          <ProofPanel scan={scanResult} />
          <CoAttestationPanel scan={scanResult} />
        </div>
      )}
    </div>
  );
}
