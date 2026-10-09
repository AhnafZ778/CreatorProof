"use client";

import { useCallback, useEffect, useState, type FormEvent } from "react";
import { Blocks, Fingerprint, Focus, Globe2, Layers3, LockKeyhole, ScanEye, ShieldCheck, UserRound, type LucideIcon } from "lucide-react";
import { api, ApiError, dateLabel, labels, readable, record, rows, str, type Json } from "@/app/lib/phase1";
import { Feedback, Hash, Loading, PanelHeading, RefreshButton, Status } from "./Phase1UI";

const LANES: { key: string; title: string; description: string; Icon: LucideIcon }[] = [
  { key: "COPY", title: "Visual reuse", description: "Hashes, correspondence, and validated geometry.", Icon: Focus },
  { key: "ORIGIN", title: "AI origin", description: "Origin indicators, independent of copying.", Icon: ScanEye },
  { key: "PROVENANCE", title: "Provenance", description: "Manifest validity and signer trust.", Icon: Fingerprint },
  { key: "CREATOR_PROFILE", title: "Creator resemblance", description: "Advisory resemblance, not artist identity.", Icon: UserRound },
  { key: "RIGHTS", title: "Permissions", description: "Recorded assertions, licenses, and conditions.", Icon: LockKeyhole },
  { key: "POLICY", title: "Publication policy", description: "Your organization's deterministic decision.", Icon: ShieldCheck },
  { key: "SOURCE_COVERAGE", title: "Source coverage", description: "What was checked and what remains unknown.", Icon: Globe2 },
  { key: "INTEGRITY", title: "Record integrity", description: "Packet commitment, not ownership.", Icon: Layers3 },
];
const REASONS: Record<string, string> = {
  AI_ORIGIN_INFORMATIONAL_ONLY: "AI-origin indicators provide context for this policy.",
  MATCH_REQUIRES_PERSISTED_RIGHTS_EVALUATION: "A matched work needs a recorded permissions review.",
  MATCH_WITHOUT_AUTHORIZING_PERSISTED_LICENSE: "No recorded license authorizes this intended use.",
  EXACT_SHA256_MATCH: "The candidate and registered file have identical bytes.",
  RIGHTS_PREFERENCE_PERMISSION_DENIED: "The artist's recorded preferences do not allow the requested use.",
};
function AssessmentBadge({ assessment }: { assessment: Json }) {
  return <span className="cpStatus cpAssessmentBadge" data-tone={str(assessment.tone, "neutral")}><i aria-hidden="true" />{str(assessment.label, "Assessment unavailable")}</span>;
}
function LaneRating({ assessment }: { assessment: Json }) {
  const rating = record(assessment.rating);
  const value = typeof rating.value === "number" ? rating.value : null;
  const scale = typeof rating.scale === "number" ? rating.scale : null;
  const progress = value !== null && scale && scale > 0 ? Math.max(0, Math.min(100, value / scale * 100)) : null;
  return <div className="cpLaneRating" data-tone={str(rating.tone, "neutral")}><div className="cpRatingValue">{str(rating.display, "—")}{scale === 100 && <span>/100</span>}</div><span className="cpRatingLabel">{str(rating.label, "No completed measurement")}</span>{progress !== null && <div className="cpRatingTrack" role="meter" aria-label={str(rating.label)} aria-valuemin={0} aria-valuemax={scale!} aria-valuenow={value!}><i style={{ width: `${progress}%` }} /></div>}<span className="cpRatingGrade">{str(rating.grade, "Not measured")}</span></div>;
}
const METRIC_LABELS: Record<string, string> = {
  verified_feature_pairs: "Verified feature pairs", inlier_ratio: "Verified inlier ratio",
  evidence_index: "Evidence index", independent_support_count: "Independent supporting checks",
  evidence_tier: "Evidence tier", calibration_state: "Calibration", score_semantics: "Score meaning",
};
export default function EvidenceMatrixPanel({ scanId, canCorrect = false }: { scanId: string; canCorrect?: boolean }) {
  const [data, setData] = useState<Json | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [selected, setSelected] = useState("COPY");
  const [busy, setBusy] = useState(false);
  const load = useCallback(async (signal?: AbortSignal) => { setLoading(true); setError(null); try { setData(await api(`scans/${scanId}/evidence-matrix`, { signal })); } catch (e) { if (!signal?.aborted) setError(e instanceof ApiError && e.status === 409 ? "This scan does not have a finalized matrix yet. Older scans may need a new scan to produce one." : e instanceof Error ? e.message : "Could not read the evidence matrix."); } finally { if (!signal?.aborted) setLoading(false); } }, [scanId]);
  useEffect(() => { const c = new AbortController(); void load(c.signal); return () => c.abort(); }, [load]);
  async function correct(event: FormEvent<HTMLFormElement>) { event.preventDefault(); const form = event.currentTarget; setBusy(true); setError(null); setMessage(null); try { await api(`scans/${scanId}/evidence-matrix/corrections`, { method: "POST", body: JSON.stringify({ reason: new FormData(form).get("reason") }) }); await load(); form.reset(); setMessage("A new matrix version was appended. The scan decision and previous records remain preserved."); } catch (e) { setError(e instanceof Error ? e.message : "Could not append a correction."); } finally { setBusy(false); } }
  const signals = rows(data?.assessment_signals || data?.signals);
  const coverageRows = rows(data?.coverage_rows);
  const assessment = record(data?.assessment);
  const laneAssessments = record(assessment.lanes);
  const overall = record(assessment.overall);
  const selectedAssessment = record(laneAssessments[selected]);
  const source = record(data?.assessment_source);
  const headline = overall.verdict === "REUSE_CONFIRMED_AUTHORIZATION_UNVERIFIED"
    ? record(laneAssessments.COPY).verdict === "EXACT_COPY" ? "Exact copy confirmed" : "Registered artwork reuse confirmed"
    : str(overall.label);
  const selectedLane = LANES.find((lane) => lane.key === selected)!;
  return <section className="portalPanel cpMatrix" aria-label="Evidence matrix"><PanelHeading eyebrow="Eight independent questions" title="Evidence Matrix" description="See the support, gaps, and limits behind this scan. Each lane keeps its own meaning; the scores are never averaged into an infringement probability."><RefreshButton busy={loading || busy} onClick={() => void load()} /></PanelHeading><Feedback error={error} message={message} />
    {loading ? <Loading /> : data && <>
      {Boolean(overall.label) && <section className="cpAssessmentBanner" data-tone={str(overall.tone, "review")} aria-label="Misuse assessment"><small>Assessment verdict</small><h3>{headline}</h3><p>{str(overall.explanation)}</p><details className="cpAssessmentContext"><summary>Completed findings & follow-up</summary><div className="cpAssessmentFindings"><div><b>Supported findings</b><ul>{labels(overall.supported_findings).map((finding) => <li key={finding}>{finding}</li>)}</ul>{!labels(overall.supported_findings).length && <p>No completed finding is supported.</p>}</div><div><b>Needs verification</b><ul>{labels(overall.unresolved_findings).map((finding) => <li key={finding}>{finding}</li>)}</ul>{!labels(overall.unresolved_findings).length && <p>No unresolved detector check recorded.</p>}</div></div></details><p className="cpCaption">Assessed {dateLabel(source.completed_at)} · Results saved for immediate review.</p></section>}
      <details className="cpDetails"><summary>Saved policy & matrix trace</summary><div className="cpDetailBody"><div className="cpMatrixOverview"><div><Blocks size={22} /><span>Evidence state</span><Status value={data.final_status} /></div><div><span>Publication decision</span><Status value={data.policy_result} /></div><div><span>Human review</span><b>{data.abstention ? "Recommended; evidence is incomplete" : "Follow the recorded policy result"}</b></div></div>
      {Boolean(data.reason) && <ul className="cpReasonList cpMatrixReason">{str(data.reason).split(";").filter((reason) => reason.trim()).map((reason, index) => <li key={index}>{REASONS[reason.trim()] || readable(reason.trim())}</li>)}</ul>}</div></details>
      <p className="cpRatingSemantics">{str(assessment.rating_semantics)}</p><div className="cpLaneGrid">{LANES.map(({ key, title, description, Icon }) => { const laneSignals = signals.filter((s) => s.lane === key); const verdict = record(laneAssessments[key]); return <button key={key} type="button" className={selected === key ? "isSelected" : ""} aria-pressed={selected === key} aria-controls={`lane-detail-${scanId}`} onClick={() => setSelected(key)}><div><Icon size={19} /><span>{String(LANES.findIndex((l) => l.key === key) + 1).padStart(2, "0")}</span></div><h3>{title}</h3><p>{description}</p><LaneRating assessment={verdict} /><small>{laneSignals.length} recorded {laneSignals.length === 1 ? "signal" : "signals"} · View measurements</small></button>; })}</div>
      <section className="cpSignalDetail" id={`lane-detail-${scanId}`} aria-label={`${selectedLane.title} signals`}><div className="cpSplit"><h3><selectedLane.Icon size={19} />{selectedLane.title}</h3><span className="cpCaption">Assessment version {String(source.matrix_version || data.version)}</span></div><div className="cpLaneAssessment"><AssessmentBadge assessment={selectedAssessment} /><p>{str(selectedAssessment.explanation, "No lane assessment is available.")}</p>{Object.entries(record(selectedAssessment.metrics)).some(([, value]) => value != null) && <div className="cpFacts">{Object.entries(record(selectedAssessment.metrics)).filter(([key, value]) => value != null && key in METRIC_LABELS).map(([key, value]) => <div key={key}><span>{METRIC_LABELS[key]}</span><strong>{typeof value === "number" ? Number.isInteger(value) ? value : value.toFixed(4) : readable(value)}</strong></div>)}</div>}{!!labels(selectedAssessment.limitations).length && <ul className="cpReasonList">{labels(selectedAssessment.limitations).map((limit) => <li key={limit}>{limit}</li>)}</ul>}{!!labels(selectedAssessment.missing_facts).length && <p className="cpCaption">Missing facts: {labels(selectedAssessment.missing_facts).map(readable).join(" · ")}</p>}</div><details className="cpDetails"><summary>Individual signal results & receipts</summary><div className="cpDetailBody">{signals.filter((signal) => signal.lane === selected).map((signal) => <article key={str(signal.signal_id || signal.id)} className="cpSignal"><div className="cpSplit"><div><b>{readable(signal.signal_type)}</b><span className="cpCaption">{str(signal.provider, "Provider not recorded")} {str(signal.provider_version)}</span></div><Status value={signal.status} /></div><div className="cpFacts"><div><span>Score</span><strong>{typeof signal.score === "number" ? signal.score.toFixed(4) : "Not supplied"}</strong></div><div><span>Score meaning</span><strong>{readable(signal.score_semantics)}</strong></div><div><span>Evidence quality</span><strong>{readable(signal.evidence_quality)}</strong></div><div><span>Coverage</span><strong>{readable(signal.coverage_status)}</strong></div></div>{!!labels(signal.reason_codes).length && <ul className="cpReasonList">{labels(signal.reason_codes).map((reason) => <li key={reason}>{readable(reason)}</li>)}</ul>}<details className="cpDetails"><summary>Signal receipt & artifact references</summary><div className="cpDetailBody"><Hash value={signal.input_sha256} label="Signal input hash" /><div className="cpFacts"><div><span>Model or rule</span><strong>{str(signal.model_or_rule_identifier, "Not supplied")}</strong></div><div><span>Recorded at</span><strong>{dateLabel(signal.completed_at)}</strong></div><div><span>Fallback used</span><strong>{signal.fallback_used ? "Yes" : "No"}</strong></div></div>{Array.isArray(signal.artifact_refs) && <ul className="cpReasonList">{signal.artifact_refs.map((ref, index) => <li key={index}>{typeof ref === "string" ? ref : JSON.stringify(record(ref))}</li>)}</ul>}</div></details></article>)}{!signals.some((signal) => signal.lane === selected) && <p className="cpDescription">No signal was recorded for this lane.</p>}</div></details></section>
      {!!labels(overall.next_steps).length && <section className="cpAssessmentNext"><h3>Next action</h3><ol>{labels(overall.next_steps).map((step) => <li key={step}>{step}</li>)}</ol><p className="cpCaption">Based on the saved detector assessments and permissions at scan time. An AI-origin finding or stylistic resemblance alone does not establish misuse.</p></section>}
      <Hash value={source.packet_hash_sha256 || data.packet_hash_sha256} label="Model assessment packet hash" />{Boolean(source.refreshed) && <Hash value={data.packet_hash_sha256} label="Original case packet hash" />}
      <details className="cpDetails"><summary>Saved coverage & recommended next action</summary><div className="cpDetailBody"><p className="cpDescription">Recommended action: {readable(data.recommended_action)}. A coverage percentage is shown only when the backend recorded one; missing coverage remains unspecified.</p><div className="cpMiniGrid">{coverageRows.map((row) => <div key={str(row.id)}><span>{LANES.find((lane) => lane.key === row.lane)?.title || readable(row.lane)}</span><strong className="cpCaption">{typeof row.coverage_percent === "number" ? `${row.coverage_percent}% recorded` : "Coverage not quantified"}</strong></div>)}</div></div></details>
      {canCorrect && <details className="cpDetails"><summary>Append a matrix correction</summary><form className="cpDetailBody" onSubmit={correct}><p className="cpDescription">Reproject the existing packet with the current normalizer. This records a new version and does not change detector results or publication policy.</p><label className="portalField"><span className="portalFieldLabel">Reason for correction</span><textarea required name="reason" rows={2} maxLength={500} /></label><button className="portalSecondary" type="submit" disabled={busy || loading}>Append correction</button></form></details>}
    </>}
  </section>;
}
