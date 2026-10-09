"use client";

import { useCallback, useEffect, useState, type FormEvent } from "react";
import { BookOpenCheck, FileSearch, Sparkles, UserRoundCheck } from "lucide-react";
import { api, ApiError, dateLabel, labels, record, rows, str, type Json } from "@/app/lib/phase1";
import { Feedback, Hash, PanelHeading, Status } from "./Phase1UI";

export default function InvestigationPanel({ scanId, scanState }: { scanId?: string; scanState?: string }) {
  const [manualScanId, setManualScanId] = useState("");
  const [runId, setRunId] = useState("");
  const [data, setData] = useState<Json | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [decision, setDecision] = useState("");
  const [edit, setEdit] = useState("");
  const target = scanId || manualScanId.trim();
  const run = record(data?.run); const output = record(data?.output);
  const lastReview = record(rows(data?.reviews).at(-1)?.review);
  const review = Object.keys(lastReview).length ? lastReview : record(data?.review);
  const effectiveSummary = str(review.edited_summary, str(output.summary));
  const loadRun = useCallback(async (id: string, signal?: AbortSignal) => {
    const result = await api(`investigations/${encodeURIComponent(id)}`, { signal });
    if (signal?.aborted) return;
    setData(result); setRunId(id); setEdit(str(record(result.output).summary)); setDecision("");
  }, []);
  useEffect(() => {
    if (!scanId) return;
    const c = new AbortController();
    try { const id = localStorage.getItem(`creatorproof.investigation.${scanId}`); if (id) void loadRun(id, c.signal).catch((e) => { if (!c.signal.aborted) setError(e instanceof Error ? e.message : "Could not restore the saved investigation."); }); } catch { /* No browser history is required to generate a new run. */ }
    return () => c.abort();
  }, [scanId, loadRun]);
  function remember(id: string) { if (id && target) { try { localStorage.setItem(`creatorproof.investigation.${target}`, id); } catch { /* Preserve the loaded result in memory. */ } } }
  async function generate() {
    setBusy(true); setError(null); setMessage(null);
    try { const result = await api(`investigations/scans/${encodeURIComponent(target)}`, { method: "POST", body: "{}" }); setData(result); setRunId(str(record(result.run).id)); setEdit(str(record(result.output).summary)); setDecision(""); remember(str(record(result.run).id)); setMessage("Investigation generated from recorded evidence. Review the facts before recording your decision."); }
    catch (e) { if (e instanceof ApiError) { const failedId = str(record(e.body.detail).run_id); if (failedId) { remember(failedId); try { await loadRun(failedId); } catch { setRunId(failedId); } } } setError(e instanceof Error ? e.message : "Could not generate an investigation."); }
    finally { setBusy(false); }
  }
  async function read(event: FormEvent<HTMLFormElement>) { event.preventDefault(); setBusy(true); setError(null); try { await loadRun(runId); } catch (e) { setError(e instanceof Error ? e.message : "Could not read that investigation."); } finally { setBusy(false); } }
  async function reviewOutput(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError(null); setMessage(null);
    try { const result = await api(`investigations/${str(run.id)}/decision`, { method: "POST", body: JSON.stringify({ decision, ...(decision === "EDITED" ? { edited_summary: edit.trim() } : {}) }) }); setData(result); setMessage("Your review was recorded. The original generated content and its hash remain unchanged. No notice was sent."); }
    catch (e) { setError(e instanceof Error ? e.message : "Could not record the review."); }
    finally { setBusy(false); }
  }
  return <section id="admin-investigation" className="portalPanel cpInvestigation"><PanelHeading eyebrow="Human-supervised assistance" title="Investigation workspace" description="Ask the assistant to summarize a completed scan's recorded evidence, identify missing facts, and suggest review steps. You make the final decision." />
    <div className="cpAssistantIntro"><div className="cpFeatureIcon"><FileSearch size={27} /></div><div><h3>Evidence first. Your judgment next.</h3><p>Generation never changes publication policy or sends a notice. It uses the configured provider only when you request it.</p></div></div>
    <div className="cpShareActions">{scanId ? <div className="cpScanSelection"><span>Selected scan</span><code>{scanId}</code><Status value={scanState} /></div> : <label className="portalField"><span className="portalFieldLabel">Completed scan ID</span><input value={manualScanId} onChange={(e) => { setManualScanId(e.target.value); setData(null); }} maxLength={96} placeholder="Choose a scan above, or enter its ID" /></label>}<button type="button" className="portalPrimary" disabled={busy || !target || Boolean(scanState && scanState !== "COMPLETED")} onClick={() => void generate()}><Sparkles size={16} />{busy ? "Working…" : data ? "Generate a new investigation" : "Generate investigation"}</button></div>
    <Feedback error={error} message={message} />
    <details className="cpDetails"><summary>Open a previously recorded investigation</summary><form className="cpDetailBody cpShareActions" onSubmit={read}><label className="portalField"><span className="portalFieldLabel">Investigation run ID</span><input required value={runId} onChange={(e) => setRunId(e.target.value.trim())} maxLength={96} /></label><button type="submit" className="portalSecondary" disabled={busy || !runId}>Open saved run</button></form></details>
    {data && <>
      <div className="cpRecordBar"><BookOpenCheck size={20} /><div><strong>Investigation for {str(run.scan_id)}</strong><span>{str(run.provider)} · {str(run.model)} · {dateLabel(run.completed_at || run.created_at)}</span></div><Status value={run.status} /></div>
      {run.status === "FAILED" && <div className="cpSubpanel"><h3>Assistant output unavailable</h3><p className="cpDescription">This attempt was recorded, but no accepted output was generated. Continue reviewing the Evidence Matrix and deterministic notice template. Retry generation when the provider is available.</p></div>}
      {Object.keys(output).length > 0 && <>
        <section className="cpAssistantSummary"><small>{output.human_decision === "EDITED" ? "Human-edited case summary" : output.human_decision === "ACCEPTED" ? "Generated case summary · accepted by reviewer" : output.human_decision === "REJECTED" ? "Generated case summary · rejected by reviewer" : "Generated case summary · awaiting factual review"}</small><p>{effectiveSummary}</p></section>
        <div className="cpFormGrid"><Checklist title="Missing facts" items={labels(output.missing_facts)} empty="No missing facts were reported. Check the evidence yourself." /><Checklist title="Suggested next steps" items={labels(output.next_steps)} empty="No next steps were reported." /></div>
        {!!labels(output.unsupported_claims).length && <Checklist title="Unsupported claims to exclude" items={labels(output.unsupported_claims)} empty="" />}
        {!!rows(output.evidence_references).length && <section className="cpSubpanel"><h3>Evidence cited by the assistant</h3><ul className="cpReferenceList">{rows(output.evidence_references).map((ref, i) => <li key={i}><code>{str(ref.id)}</code><p>{str(ref.reason)}</p></li>)}</ul></section>}
        {!!rows(output.duplicate_groups).length && <section className="cpSubpanel"><h3>Suggested duplicate groups</h3><ul className="cpReferenceList">{rows(output.duplicate_groups).map((group, index) => <li key={str(group.group_id, String(index))}><code>{labels(group.asset_ids).join(" · ")}</code><p>{str(group.reason)}</p></li>)}</ul></section>}
        {output.human_decision ? <div className="cpReviewed"><UserRoundCheck size={21} /><div><strong>Review recorded</strong><p>{str(output.human_decision_by)} · {dateLabel(output.human_decision_at)}</p></div><Status value={output.human_decision} /></div> : <form className="cpSubpanel" onSubmit={reviewOutput}><h3><UserRoundCheck size={19} />Record your review</h3><p className="cpDescription">Review the cited evidence and missing facts. This decision is recorded once; edits are saved separately from the original model output.</p><label className="portalField"><span className="portalFieldLabel">Your decision</span><select aria-label="Your decision" required value={decision} onChange={(e) => setDecision(e.target.value)}><option value="">Select after review</option><option value="ACCEPTED">Accept this summary</option><option value="EDITED">Edit and accept the corrected summary</option><option value="REJECTED">Reject this output</option></select></label>{decision === "EDITED" && <label className="portalField"><span className="portalFieldLabel">Corrected summary</span><textarea aria-label="Corrected summary" required value={edit} onChange={(e) => setEdit(e.target.value)} maxLength={12000} rows={5} /></label>}<button className="portalPrimary" type="submit" disabled={busy || !decision || (decision === "EDITED" && (!edit.trim() || edit.trim() === str(output.summary).trim()))}>Record review decision</button></form>}
      </>}
      <details className="cpDetails"><summary>Generation receipt</summary><div className="cpDetailBody"><div className="cpFacts"><div><span>Prompt-template version</span><strong>{str(run.prompt_template_version)}</strong></div><div><span>Run identifier</span><strong>{str(run.id)}</strong></div></div><Hash value={run.evidence_packet_hash} label="Source evidence packet hash" /><Hash value={run.input_hash} label="Generation context hash" /><Hash value={output.output_hash} label="Original output hash" /></div></details>
    </>}
  </section>;
}
function Checklist({ title, items, empty }: { title: string; items: string[]; empty: string }) { return <section className="cpSubpanel"><h3>{title}</h3>{items.length ? <ul className="cpReasonList">{items.map((item, i) => <li key={i}>{item}</li>)}</ul> : <p className="cpDescription">{empty}</p>}</section>; }
