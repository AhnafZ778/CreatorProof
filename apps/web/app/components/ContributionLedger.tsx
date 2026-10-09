"use client";

import { useCallback, useEffect, useState, type FormEvent } from "react";
import { CheckCheck, Download, GitCommitHorizontal, Plus } from "lucide-react";
import { api, csv, dateLabel, downloadJson, readable, record, rows, str, type Json } from "@/app/lib/phase1";
import { Feedback, Hash, Loading, PanelHeading, RefreshButton, Status } from "./Phase1UI";

const ACTIONS = ["ORIGINAL_CAPTURE", "ORIGINAL_SKETCH", "MANUAL_EDIT", "AI_GENERATION", "AI_EDIT", "AI_UPSCALE", "AI_BACKGROUND_REMOVAL", "HUMAN_SELECTION", "HUMAN_COMPOSITION", "COLOR_CORRECTION", "CROPPING", "EXPORT", "PUBLICATION", "LICENSED_SOURCE_IMPORT"];
const CLASSIFICATIONS: [string, string][] = [["UNKNOWN", "Not specified"], ["HUMAN_CREATED", "Human-created"], ["AI_ASSISTED_SUBSTANTIAL", "AI-assisted; substantial human contribution"], ["AI_GENERATED_HUMAN_SELECTION", "AI-generated; human selection"], ["AI_GENERATED_MINOR_MODIFICATION", "AI-generated; minor human changes"]];

export default function ContributionLedger({ workId }: { workId: string }) {
  const [ledger, setLedger] = useState<Json | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [formKey, setFormKey] = useState(0);
  const load = useCallback(async (signal?: AbortSignal) => { setLoading(true); setError(null); try { setLedger(await api(`works/${workId}/contributions`, { signal })); } catch (e) { if (!signal?.aborted) setError(e instanceof Error ? e.message : "Could not read the history."); } finally { if (!signal?.aborted) setLoading(false); } }, [workId]);
  useEffect(() => { const c = new AbortController(); void load(c.signal); return () => c.abort(); }, [load]);
  async function append(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setError(null); setMessage(null);
    const form = new FormData(event.currentTarget);
    const payload: Json = Object.fromEntries(["action_type", "description", "classification", "actor_type", "actor_id", "software_or_model", "model_provider", "model_version", "human_decision", "prompt_reference", "input_hash", "output_hash", "output_asset_id", "source_reference", "evidence_artifact_reference", "c2pa_reference"].map((key) => [key, str(form.get(key)).trim() || null]));
    payload.input_asset_ids = csv(str(form.get("input_asset_ids")));
    payload.timestamp = form.get("timestamp") ? new Date(String(form.get("timestamp"))).toISOString() : null;
    try { await api(`works/${workId}/contributions`, { method: "POST", body: JSON.stringify(payload) }); await load(); setFormKey((old) => old + 1); setMessage("Creation event saved. Its record and place in the history are preserved."); }
    catch (e) { setError(e instanceof Error ? e.message : "Could not record this event."); }
    finally { setBusy(false); }
  }
  const events = rows(ledger?.events);
  const verification = record(ledger?.verification);
  return <div className="cpWorkspaceContent"><PanelHeading eyebrow="Your creative process" title="Creation history" description="Document what you made, what tools you used, and which decisions were yours. Each entry becomes part of an append-only record."><RefreshButton busy={loading || busy} onClick={() => void load()} /></PanelHeading><Feedback error={error} message={message} />
    {loading ? <Loading /> : ledger && <>
      <div className="cpRecordBar"><GitCommitHorizontal size={20} /><div><strong>{events.length} recorded {events.length === 1 ? "event" : "events"}</strong><span>{events.length ? "Ordered creation history" : "Start by recording a real step in your process"}</span></div><Status value={verification.valid === true ? "VALID" : "INVALID"} /></div>
      <div className="cpActions"><button type="button" className="cpTextButton" onClick={async () => { setBusy(true); setError(null); try { const result = await api(`works/${workId}/contributions/verify`); setLedger((old) => ({ ...old, verification: result })); setMessage(result.valid === true ? "The recorded hash chain is consistent. This verifies record integrity, not authorship." : "The history could not be verified. Review the records before relying on them."); } catch (e) { setError(e instanceof Error ? e.message : "Verification failed."); } finally { setBusy(false); } }} disabled={busy}><CheckCheck size={16} />Verify history</button><button type="button" className="cpTextButton" onClick={() => downloadJson(ledger, `creation-history-${workId}.json`)}><Download size={16} />Export history</button></div>
      <ol className="cpTimeline">{events.map((item) => <li key={str(item.event_id)}><div className="cpTimelineDot"><GitCommitHorizontal size={16} /></div><article><div className="cpSplit"><h3>{readable(item.action_type)}</h3><span className="cpCaption">#{String(item.sequence)} · {dateLabel(item.timestamp || item.created_at)}</span></div><p>{str(item.description)}</p><div className="cpTags"><span>{readable(item.actor_type)} actor</span><span>{CLASSIFICATIONS.find(([key]) => key === item.classification)?.[1] || "Unknown contribution"}</span>{Boolean(item.software_or_model || item.model) && <span>{str(item.software_or_model || item.model)}</span>}</div>{Boolean(item.human_decision) && <p className="cpDecision"><b>Human decision</b>{str(item.human_decision)}</p>}<details className="cpDetails"><summary>Event receipt & references</summary><div className="cpDetailBody"><Hash value={item.event_hash} label="Event hash" /><Hash value={item.previous_event_hash} label="Previous event hash" /><div className="cpFacts">{["input_hash", "output_hash", "prompt_reference", "source_reference", "evidence_artifact_reference", "c2pa_reference", "created_by", "software_or_model", "model_provider", "model_version"].filter((key) => item[key]).map((key) => <div key={key}><span>{readable(key)}</span><strong>{str(item[key])}</strong></div>)}</div></div></details></article></li>)}</ol>
      {!events.length && <div className="cpEmpty"><GitCommitHorizontal size={27} /><h3>Your process starts here.</h3><p>Add a sketch, capture, edit, selection, or publication. Nothing is inferred from a missing history.</p></div>}
      <Hash value={verification.head_hash} label="History head hash" />
    </>}
    <form className="cpSubpanel" key={formKey} onSubmit={append}><h3><Plus size={17} />Record a creation event</h3><div className="cpFormGrid">
      <label className="portalField"><span className="portalFieldLabel">What happened?</span><select aria-label="What happened?" name="action_type" defaultValue="ORIGINAL_SKETCH">{ACTIONS.map((action) => <option key={action} value={action}>{readable(action)}</option>)}</select></label>
      <label className="portalField"><span className="portalFieldLabel">Who performed this step?</span><select aria-label="Who performed this step?" name="actor_type" defaultValue="HUMAN">{["HUMAN", "AI", "SYSTEM", "UNKNOWN"].map((v) => <option value={v} key={v}>{readable(v)}</option>)}</select></label>
      <label className="portalField cpFull"><span className="portalFieldLabel">Describe this step</span><textarea required name="description" rows={3} maxLength={4000} placeholder="I drew the original sketch and selected the composition…" /></label>
      <label className="portalField"><span className="portalFieldLabel">Contribution description</span><select aria-label="Contribution description" name="classification" defaultValue="UNKNOWN">{CLASSIFICATIONS.map(([v, label]) => <option value={v} key={v}>{label}</option>)}</select></label>
      <label className="portalField"><span className="portalFieldLabel">Software or model</span><input name="software_or_model" maxLength={240} placeholder="Procreate, Photoshop, model/version…" /></label>
      <label className="portalField"><span className="portalFieldLabel">When did it happen?</span><input type="datetime-local" name="timestamp" /><small className="portalFieldHint">Leave blank to use the current time.</small></label>
      <label className="portalField"><span className="portalFieldLabel">Your decision or contribution</span><textarea name="human_decision" rows={2} maxLength={1000} placeholder="What did you choose, correct, or compose?" /></label>
    </div><details className="cpDetails"><summary>Supporting assets, hashes & references</summary><div className="cpDetailBody cpFormGrid">
      {[["actor_id", "Actor identifier", "Optional contributor reference"], ["input_asset_ids", "Input asset version IDs", "Comma-separated registered asset IDs"], ["output_asset_id", "Output asset version ID", "An asset version belonging to this artwork"], ["model_provider", "Model provider", "Provider name, if applicable"], ["model_version", "Model version", "Exact version, if recorded"], ["prompt_reference", "Private prompt reference", "A record identifier or sha256:hash; no raw prompt"], ["source_reference", "Source record reference", "Optional record identifier"], ["evidence_artifact_reference", "Evidence reference", "Supporting record or artifact"], ["c2pa_reference", "Content Credentials reference", "Manifest reference, if recorded"]].map(([key, label, hint]) => <label className="portalField" key={key}><span className="portalFieldLabel">{label}</span><input name={key} maxLength={key === "actor_id" ? 160 : key === "prompt_reference" ? 256 : 512} placeholder={hint} /></label>)}
      {[["input_hash", "Before / input SHA-256"], ["output_hash", "After / output SHA-256"]].map(([key, label]) => <label className="portalField" key={key}><span className="portalFieldLabel">{label}</span><input name={key} maxLength={64} pattern="[a-fA-F0-9]{64}" placeholder="64 hexadecimal characters" /></label>)}
    </div></details><div className="cpFormFooter"><p>To correct a record, append another event describing the correction. Recorded contribution does not determine copyrightability.</p><button className="portalPrimary" type="submit" disabled={busy || loading || !ledger}><Plus size={16} />{busy ? "Recording…" : "Add event to history"}</button></div></form>
  </div>;
}
