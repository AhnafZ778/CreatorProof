"use client";

import { useEffect, useState } from "react";
import { Download, ExternalLink, Link2, LockKeyhole, ShieldCheck, X } from "lucide-react";
import { api, dateLabel, downloadJson, downloadText, errorMessage, labels, record, rows, str, type Json } from "@/app/lib/phase1";
import { Feedback, PanelHeading } from "./Phase1UI";

export default function ShareVerification({ resource, resourceId, exports = false }: { resource: "works" | "scans"; resourceId: string; exports?: boolean }) {
  const [expiry, setExpiry] = useState("86400");
  const [scopes, setScopes] = useState<string[]>(resource === "works" ? ["registration", "provenance", "rights"] : ["registration", "provenance", "rights", "evidence"]);
  const [links, setLinks] = useState<Json[]>([]);
  const [latestLink, setLatestLink] = useState<{ id: string; url: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const storageKey = `creatorproof.verification-links.v1.${resource}.${resourceId}`;
  useEffect(() => { try { setLinks(rows(JSON.parse(localStorage.getItem(storageKey) || "[]")).slice(0, 100)); } catch { setLinks([]); } }, [storageKey]);
  function remember(next: Json[]) { setLinks(next); try { localStorage.setItem(storageKey, JSON.stringify(next.map(({ token_id, expires_at, scopes, revoked }) => ({ token_id, expires_at, scopes, revoked })))); } catch { /* The active link remains usable when browser storage is unavailable. */ } }
  async function issue() {
    setBusy("issue"); setError(null); setMessage(null);
    try { const result = await api(`${resource}/${resourceId}/verification-token`, { method: "POST", body: JSON.stringify({ scopes, expires_in_seconds: Number(expiry) }) }); const id = str(result.token_id); setLatestLink({ id, url: `${window.location.origin}/verify/${encodeURIComponent(str(result.token))}` }); remember([{ token_id: id, expires_at: result.expires_at, scopes: result.scopes, revoked: false }, ...links].slice(0, 100)); setMessage("Your verification link is ready. Copy it before leaving this artwork."); }
    catch (e) { setError(e instanceof Error ? e.message : "Could not create a verification link."); }
    finally { setBusy(null); }
  }
  async function revoke(id: string) {
    setBusy(id); setError(null); setMessage(null);
    try { await api(`verification-tokens/${id}`, { method: "DELETE" }); remember(links.map((link) => link.token_id === id ? { ...link, revoked: true } : link)); if (latestLink?.id === id) setLatestLink(null); setMessage("Link revoked. It can no longer be used to read the record."); }
    catch (e) { setError(e instanceof Error ? e.message : "Could not revoke this link."); }
    finally { setBusy(null); }
  }
  async function exportFile(format: string, filename: string) {
    setBusy(format); setError(null);
    try {
      if (["ai.txt", "rights-statement"].includes(format)) { const response = await fetch(`/api/phase1/works/${resourceId}/${format}`, { cache: "no-store", signal: AbortSignal.timeout(90000) }); if (!response.ok) throw new Error(errorMessage(await response.json())); downloadText(await response.text(), filename); }
      else downloadJson(await api(`works/${resourceId}/${format}`), filename);
      setMessage(`${filename} downloaded.`);
    } catch (e) { setError(e instanceof Error ? e.message : "Could not export this record."); }
    finally { setBusy(null); }
  }
  return <div className="cpWorkspaceContent"><PanelHeading eyebrow="Share selected evidence" title={exports ? "Share & export" : "Public verification link"} description="Create an expiring link to a safe summary. Private contact details, uploaded images, and internal model outputs stay private." /><Feedback error={error} message={message} />
    <div className="cpShareCard"><div className="cpFeatureIcon"><ShieldCheck size={27} /></div><div><h3>A shareable record, with boundaries.</h3><p>Choose which parts to disclose. Anyone with the link can read that summary until it expires or you revoke it.</p></div></div>
    <div className="cpScopeChecks">{["registration", "provenance", "rights", ...(resource === "scans" ? ["evidence"] : [])].map((scope) => <label key={scope}><input type="checkbox" checked={scopes.includes(scope)} onChange={(e) => setScopes((old) => e.target.checked ? [...old, scope] : old.filter((v) => v !== scope))} />{({ registration: "Registration status", provenance: "Provenance status", rights: "Rights preferences", evidence: "Evidence packet hash" } as Record<string, string>)[scope]}</label>)}</div>
    <div className="cpShareActions"><label className="portalField"><span className="portalFieldLabel">Link expires after</span><select aria-label="Link expires after" value={expiry} onChange={(e) => setExpiry(e.target.value)}><option value="3600">1 hour</option><option value="86400">1 day</option><option value="604800">7 days</option><option value="2592000">30 days</option></select></label><button className="portalPrimary" type="button" disabled={busy !== null || !scopes.length} onClick={() => void issue()}><Link2 size={16} />{busy === "issue" ? "Creating link…" : "Create verification link"}</button></div>
    {latestLink && <div className="cpLinkResult"><input aria-label="Public verification link" readOnly value={latestLink.url} onFocus={(e) => e.target.select()} /><button type="button" className="portalSecondary" onClick={async () => { try { await navigator.clipboard.writeText(latestLink.url); setMessage("Verification link copied."); } catch { setError("Select the link and copy it manually."); } }}>Copy link</button><a className="cpIconButton" href={latestLink.url} target="_blank" rel="noopener noreferrer" aria-label="Open public verification"><ExternalLink size={17} /></a></div>}
    {!!links.length && <details className="cpDetails" open><summary>Links created in this browser</summary><div className="cpDetailBody cpLinkList">{links.map((link) => { const expired = new Date(str(link.expires_at)).getTime() <= Date.now(); return <div key={str(link.token_id)}><div><b>{link.revoked ? "Revoked" : expired ? "Expired" : "Active verification link"}</b><span>{labels(link.scopes).join(" · ")} · expires {dateLabel(link.expires_at)}</span></div>{!link.revoked && !expired && <button type="button" className="cpTextButton" onClick={() => void revoke(str(link.token_id))} disabled={busy !== null}><X size={14} />Revoke</button>}</div>; })}</div></details>}
    {exports && <section className="cpSubpanel"><h3><Download size={18} />Preference exports</h3><p className="cpDescription">Download the recorded policy for your own website or compliant systems. Publishing a preference does not prevent misuse.</p><div className="cpExportGrid">{[["rights-policy", "Rights Passport", "Full versioned policy and supporting record", `rights-passport-${resourceId}.json`], ["ai-preferences", "AI preferences", "Machine-readable permission values and mappings", `ai-preferences-${resourceId}.json`], ["ai.txt", "ai.txt fragment", "Install on your website's content origin", `ai-${resourceId}.txt`], ["tdm-policy", "TDM policy", "Reservation projection with mapping limits", `tdm-policy-${resourceId}.json`], ["rights-statement", "Rights statement", "A readable statement of recorded preferences", `rights-statement-${resourceId}.txt`]].map(([format, title, detail, filename]) => <button key={format} type="button" disabled={busy !== null} onClick={() => void exportFile(format, filename)}><Download size={18} /><b>{busy === format ? "Preparing…" : title}</b><span>{detail}</span></button>)}</div><p className="cpCaption"><LockKeyhole size={13} />Full authenticated exports may include your licensing contact. The public link always uses a minimized summary. Signed C2PA authoring is not available.</p></section>}
  </div>;
}
