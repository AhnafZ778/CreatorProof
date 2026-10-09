"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";

type Record_ = Record<string, unknown>;

type ReviewCase = {
  id: string;
  state: string;
  priority: string;
  disposition: string;
  opened_reason: string;
  resolved_at?: string | null;
};

type Disposition =
  | "APPROVED_FOR_PUBLICATION"
  | "REJECTED_FOR_PUBLICATION"
  | "NEEDS_LICENSE"
  | "ESCALATED";

const ACTIONS: Array<{
  value: Disposition;
  label: string;
  detail: string;
}> = [
  {
    value: "APPROVED_FOR_PUBLICATION",
    label: "Approve for publication",
    detail: "You reviewed the evidence and accept the asset for the intended use.",
  },
  {
    value: "NEEDS_LICENSE",
    label: "Request a licence",
    detail: "Keep the asset on hold until the required rights are documented.",
  },
  {
    value: "REJECTED_FOR_PUBLICATION",
    label: "Reject before publishing",
    detail: "Record that this asset must not be used for the declared purpose.",
  },
  {
    value: "ESCALATED",
    label: "Escalate to rights owner",
    detail: "Record that rights-owner or legal review is needed.",
  },
];

function asRecord(value: unknown): Record_ | null {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record_) : null;
}

function text(value: unknown, fallback = "") {
  return typeof value === "string" && value.trim() ? value : fallback;
}

function policyAction(scan: Record_) {
  const packet = asRecord(scan.evidence_packet);
  const decision = asRecord(packet?.decision);
  return text(scan.policy_action ?? decision?.policy_action, "REVIEW").toUpperCase();
}

function readable(value: string) {
  return value.replaceAll("_", " ").toLowerCase();
}

function errorMessage(body: unknown, fallback: string) {
  const record = asRecord(body);
  const detail = record?.detail;
  if (typeof detail === "string" && detail.trim()) return detail;
  const detailRecord = asRecord(detail);
  return text(detailRecord?.message, fallback);
}

export default function ProtectionActionPanel({ scan, reviewRequired = false, onDecisionRecorded }: { scan: Record_; reviewRequired?: boolean; onDecisionRecorded?: (reviewCase: Record_) => void }) {
  const action = policyAction(scan);
  const packet = asRecord(scan.evidence_packet);
  const protection = asRecord(packet?.protection);
  const recommendedAction = text(
    protection?.recommended_action,
    "Preserve the evidence packet and follow the recorded policy path.",
  );
  const requiresReview = reviewRequired || action === "REVIEW" || action === "BLOCK";
  const [reviewCase, setReviewCase] = useState<ReviewCase | null>(null);
  const [loading, setLoading] = useState(requiresReview);
  const [selected, setSelected] = useState<Disposition | "">("");
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setReviewCase(null);
    if (!requiresReview) {
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    const scanId = text(scan.id);
    if (!scanId) {
      setLoading(false);
      setError("This result has no scan identifier, so its action case cannot be loaded.");
      return;
    }
    const loadCase = async () => {
      let lastError = "The review case could not be loaded.";
      for (let attempt = 0; attempt < 6 && !cancelled; attempt += 1) {
        try {
          const response = await fetch(`/api/review-cases?scan_id=${encodeURIComponent(scanId)}&limit=1`, {
            cache: "no-store",
          });
          const body = (await response.json()) as unknown;
          if (!response.ok) throw new Error(errorMessage(body, lastError));
          const first = asRecord(Array.isArray(body) ? body[0] : null);
          if (first) {
            setReviewCase({
              id: text(first.id),
              state: text(first.state, "OPEN"),
              priority: text(first.priority, "NORMAL"),
              disposition: text(first.disposition, "NOT_DECIDED"),
              opened_reason: text(first.opened_reason, "POLICY_REVIEW"),
              resolved_at: typeof first.resolved_at === "string" ? first.resolved_at : null,
            });
            setLoading(false);
            return;
          }
          lastError = "The review case is still being created.";
        } catch (caught) {
          lastError = caught instanceof Error ? caught.message : lastError;
        }
        if (attempt < 5) await new Promise((resolve) => setTimeout(resolve, 750));
      }
      if (!cancelled) {
        setError(lastError);
        setLoading(false);
      }
    };
    void loadCase();
    return () => {
      cancelled = true;
    };
  }, [requiresReview, scan.id]);

  const chosenAction = useMemo(
    () => ACTIONS.find((candidate) => candidate.value === selected) ?? null,
    [selected],
  );

  async function recordAction(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!reviewCase || !selected || saving) return;
    setSaving(true);
    setError(null);
    try {
      const response = await fetch(`/api/review-cases/${encodeURIComponent(reviewCase.id)}/actions`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          event_type: "DECIDED",
          disposition: selected,
          note: note.trim() || null,
        }),
      });
      const body = (await response.json()) as unknown;
      if (!response.ok) throw new Error(errorMessage(body, "The action could not be recorded."));
      const result = asRecord(body);
      setReviewCase((current) =>
        current
          ? {
              ...current,
              state: text(result?.state, "RESOLVED"),
              disposition: text(result?.disposition, selected),
              resolved_at: typeof result?.resolved_at === "string" ? result.resolved_at : new Date().toISOString(),
            }
          : current,
      );
      setSelected("");
      setNote("");
      if (result) onDecisionRecorded?.(result);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "The action could not be recorded.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className={`protectionAction action-${action.toLowerCase()}`} aria-label="Protection action">
      <header className="protectionActionHead">
        <div>
          <small>THE ACTION</small>
          <h3>{requiresReview ? "Record your decision" : "Recorded policy outcome"}</h3>
        </div>
        <span className={`protectionActionBadge ${reviewCase?.state === "RESOLVED" ? "isResolved" : ""}`}>
          {!requiresReview
            ? action === "PASS_BY_POLICY"
              ? "policy cleared"
              : "policy recorded"
            : reviewCase
              ? readable(reviewCase.state)
              : "loading case"}
        </span>
      </header>

      <div className="protectionActionBody">
        <div className="protectionActionGuidance">
          <b>{requiresReview ? "A person owns the final action." : "No review case is required."}</b>
          <p>{recommendedAction}</p>
          <small>
            {requiresReview
              ? "This records an internal, attributable disposition. It does not send a takedown or make a legal finding."
              : "Keep the evidence packet with the asset and apply your normal publication controls."}
          </small>
        </div>

        {!requiresReview ? (
          <div className="protectionActionClear" role="status">
            <span aria-hidden="true">✓</span>
            <div>
              <b>Continue through your publication workflow</b>
              <p>The recorded policy cleared this scan for the declared use.</p>
            </div>
          </div>
        ) : loading ? (
          <div className="protectionActionStatus" role="status">Loading the review case…</div>
        ) : reviewCase?.state === "RESOLVED" || reviewCase?.state === "CLOSED" ? (
          <div className="protectionActionResolved" role="status">
            <span aria-hidden="true">✓</span>
            <div>
              <b>{readable(reviewCase.disposition)}</b>
              <p>This action is recorded in the immutable review event history.</p>
            </div>
          </div>
        ) : reviewCase ? (
          <form className="protectionActionForm" onSubmit={recordAction}>
            <div className="protectionActionOptions" role="group" aria-label="Choose an action">
              {ACTIONS.map((candidate) => (
                <button
                  key={candidate.value}
                  type="button"
                  className={selected === candidate.value ? "isSelected" : ""}
                  onClick={() => setSelected(candidate.value)}
                  aria-pressed={selected === candidate.value}
                >
                  <b>{candidate.label}</b>
                  <span>{candidate.detail}</span>
                </button>
              ))}
            </div>
            {chosenAction && <p className="protectionActionSelected">Selected: {chosenAction.label}</p>}
            <label>
              Note <span>(optional)</span>
              <textarea
                value={note}
                onChange={(event) => setNote(event.target.value)}
                maxLength={4000}
                placeholder="Add the reason an auditor should see with this decision."
                rows={3}
              />
            </label>
            <button className="protectionActionSubmit" type="submit" disabled={!selected || saving}>
              {saving ? "Recording action…" : "Record action"}
            </button>
          </form>
        ) : (
          <div className="protectionActionStatus isWarning" role="alert">
            No review case is available yet. The scan result remains reviewable, but an attributable action cannot be recorded until the case is created.
          </div>
        )}

        {error && <p className="protectionActionError" role="alert">{error}</p>}
      </div>
    </section>
  );
}
