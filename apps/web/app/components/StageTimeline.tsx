"use client";

/**
 * Truthful stage timeline.
 *
 * The bar reflects the durable stage ledger on the server, not an animation. A
 * stage that has not started says so, a stage that failed says why, and a stage
 * that was skipped is never drawn as if it had succeeded.
 */

export type StageAttempt = {
  stage: string;
  state: string;
  worker_class?: string;
  attempt?: number;
  max_attempts?: number;
  progress_percent?: number;
  progress_label?: string | null;
  error_code?: string | null;
  retry_class?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
};

export type StageTimeline = {
  scan_id?: string;
  state?: string;
  lifecycle_state?: string;
  correlation_id?: string | null;
  stages?: StageAttempt[];
};

const STAGE_LABELS: Record<string, string> = {
  INTAKE: "Accept and store the candidate",
  EVIDENCE: "Run the evidence lanes",
  STATEMENT: "Sign the evidence statement",
  PROOF: "Record the proof receipt",
  NOTIFY: "Notify subscribers",
};

const STATE_LABELS: Record<string, string> = {
  PENDING: "Not started",
  RUNNING: "Running",
  SUCCEEDED: "Done",
  FAILED: "Failed",
  SKIPPED: "Skipped",
  CANCELLED: "Cancelled",
  ABANDONED: "Lease expired, will be retried",
};

function stateClass(state: string): string {
  const normalized = state.toUpperCase();
  if (normalized === "SUCCEEDED") return "done";
  if (normalized === "RUNNING") return "running";
  if (normalized === "FAILED" || normalized === "ABANDONED") return "failed";
  if (normalized === "SKIPPED" || normalized === "CANCELLED") return "skipped";
  return "pending";
}

export default function StageTimelinePanel({
  timeline,
  elapsedSeconds,
  onCancel,
  cancelling,
}: {
  timeline: StageTimeline | null;
  elapsedSeconds: number;
  onCancel?: () => void;
  cancelling?: boolean;
}) {
  const stages = timeline?.stages ?? [];
  if (!timeline) return null;

  return (
    <section className="stageTimeline" aria-label="Scan stage timeline">
      <header>
        <div>
          <small>DURABLE STAGE LEDGER</small>
          <h4>{timeline.lifecycle_state ?? timeline.state ?? "QUEUED"}</h4>
        </div>
        <div className="stageTimelineMeta">
          <span>{elapsedSeconds}s elapsed</span>
          {timeline.correlation_id && <code>{timeline.correlation_id}</code>}
        </div>
      </header>

      {stages.length === 0 ? (
        <p className="stageEmpty">
          No stage has been recorded yet. The scan is accepted and waiting for a worker.
        </p>
      ) : (
        <ol>
          {stages.map((stage) => {
            const status = stage.state?.toUpperCase() ?? "PENDING";
            const attempts =
              (stage.attempt ?? 0) > 1
                ? ` · attempt ${stage.attempt} of ${stage.max_attempts ?? "?"}`
                : "";
            return (
              <li key={stage.stage} className={stateClass(status)}>
                <span className="stageMarker" aria-hidden="true" />
                <div className="stageBody">
                  <b>{STAGE_LABELS[stage.stage] ?? stage.stage}</b>
                  <span className="stageState">
                    {STATE_LABELS[status] ?? status}
                    {attempts}
                  </span>
                  {stage.progress_label && <em>{stage.progress_label}</em>}
                  {stage.error_code && (
                    <strong className="stageError">
                      {stage.error_code}
                      {stage.retry_class ? ` (${stage.retry_class.toLowerCase()})` : ""}
                    </strong>
                  )}
                </div>
                <div className="stageProgress" aria-hidden="true">
                  <i style={{ width: `${Math.max(0, Math.min(100, stage.progress_percent ?? 0))}%` }} />
                </div>
              </li>
            );
          })}
        </ol>
      )}

      {onCancel && (
        <button type="button" className="stageCancel" onClick={onCancel} disabled={cancelling}>
          {cancelling ? "Requesting cancellation…" : "Cancel this scan"}
        </button>
      )}
    </section>
  );
}
