"use client";

import { useCallback, useEffect, useState, type FormEvent } from "react";
import { Download, History, LockKeyhole, Save, ShieldCheck } from "lucide-react";
import { api, csv, dateLabel, downloadJson, labels, PERMISSIONS, PERMISSION_OPTIONS, record, str, toLocalDate, type Json, type Permission } from "@/app/lib/phase1";
import { Feedback, Hash, Loading, PanelHeading, RefreshButton, Status } from "./Phase1UI";

export default function RightsPassport({ workId }: { workId: string }) {
  const [passport, setPassport] = useState<Json | null>(null);
  const [historical, setHistorical] = useState<Json | null>(null);
  const [version, setVersion] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const load = useCallback(async (signal?: AbortSignal) => {
    setLoading(true); setError(null);
    try { const data = await api(`works/${workId}/rights-policy`, { signal }); setPassport(data); setVersion(Math.max(1, Number(record(data.policy).policy_version || 1))); }
    catch (e) { if (!signal?.aborted) setError(e instanceof Error ? e.message : "Could not load this passport."); }
    finally { if (!signal?.aborted) setLoading(false); }
  }, [workId]);
  useEffect(() => { const c = new AbortController(); void load(c.signal); return () => c.abort(); }, [load]);
  const policy = record(passport?.policy);
  const currentVersion = Number(policy.policy_version || 1);
  async function viewHistory() {
    setBusy(true); setError(null);
    try { setHistorical(await api(`works/${workId}/rights-policy/${version}`)); }
    catch (e) { setError(e instanceof Error ? e.message : "Could not load this version."); }
    finally { setBusy(false); }
  }
  async function save(payload: Json) {
    setBusy(true); setError(null); setMessage(null);
    try { const result = await api(`works/${workId}/rights-policy`, { method: "POST", body: JSON.stringify(payload) }); setPassport(result); setHistorical(null); setVersion(Number(record(result.policy).policy_version)); setMessage(`Version ${record(result.policy).policy_version} saved. Your earlier preferences remain in the history.`); }
    catch (e) { setError(e instanceof Error ? e.message : "Could not save preferences."); }
    finally { setBusy(false); }
  }
  return <div className="cpWorkspaceContent">
    <PanelHeading eyebrow="Your permissions" title="Artwork permissions" description="Choose how others may discover, train AI on, or transform this artwork. These choices form its Rights Passport.">
      <RefreshButton busy={loading || busy} onClick={() => void load()} />
    </PanelHeading>
    <Feedback error={error} message={message} />
    {loading ? <Loading /> : passport && <>
      <div className="cpRecordBar"><ShieldCheck size={19} /><div><strong>Version {currentVersion}</strong><span>{dateLabel(policy.created_at)} · Creator-recorded preferences</span></div><Status value={policy.state} /></div>
      <RightsEditor key={`${workId}-${currentVersion}`} policy={policy} busy={busy} save={save} />
      <details className="cpDetails artistPolicyAdvanced"><summary>Previous versions & passport export</summary><div className="cpDetailBody">
      <div className="cpHistoryBar"><History size={16} /><span>View a previous version</span><input aria-label="Policy version" type="number" min={1} max={currentVersion} value={version} onChange={(e) => setVersion(Number(e.target.value))} /><button type="button" className="portalSecondary" onClick={() => void viewHistory()} disabled={busy || version < 1 || version > currentVersion}>View version</button><button type="button" className="cpTextButton" onClick={() => downloadJson(historical || passport, `rights-passport-${workId}.json`)}><Download size={15} />Export passport</button></div>
      {historical && <div className="cpSubpanel"><div className="cpSplit"><h3>Saved version {record(historical.policy).policy_version as number}</h3><button className="cpTextButton" type="button" onClick={() => setHistorical(null)}>Close history</button></div><p className="cpDescription">Read-only snapshot. Saving below creates a version from your current preferences.</p><div className="cpMiniGrid">{PERMISSIONS.map((p) => <div key={p.key}><span>{p.label}</span><Status value={record(record(historical.policy).permissions)[p.key]} /></div>)}</div><Hash value={record(historical.policy).digest_sha256} label="Saved policy hash" /></div>}
      <Hash value={policy.digest_sha256} label="Current policy hash" />
      </div></details>
      <details className="cpDetails"><summary>Claims and licenses behind this passport</summary><div className="cpDetailBody"><p>These preferences are your declaration. Supporting evidence and contracts are recorded separately.</p><div className="cpFacts"><div><span>Assertion</span><strong>{str(policy.creator_assertion_status, "Unknown")}</strong></div><div><span>Corroboration</span><strong>{str(policy.corroboration_status, "Not independently verified").replaceAll("_", " ").toLowerCase()}</strong></div><div><span>Recorded licenses</span><strong>{Array.isArray(record(passport.evidence).contract_or_license) ? (record(passport.evidence).contract_or_license as unknown[]).length : 0}</strong></div></div></div></details>
    </>}
  </div>;
}

function RightsEditor({ policy, busy, save }: { policy: Json; busy: boolean; save: (payload: Json) => Promise<void> }) {
  const [permissions, setPermissions] = useState<Record<string, Permission>>(() => Object.fromEntries(PERMISSIONS.map((p) => [p.key, str(record(policy.permissions)[p.key], "UNKNOWN")])) as Record<string, Permission>);
  const [confirmRevocation, setConfirmRevocation] = useState(false);
  const [consentStatus, setConsentStatus] = useState(str(policy.consent_status, "UNKNOWN"));
  const dimensions = record(policy.dimensions);
  const groups = ["Discovery", "Training", "Creation", "Identity"];
  function preset(kind: "license" | "search" | "unknown") { setPermissions(Object.fromEntries(PERMISSIONS.map((p) => [p.key, kind === "unknown" ? "UNKNOWN" : kind === "search" && p.group === "Discovery" ? "ALLOW" : "LICENSE_REQUIRED"])) as Record<string, Permission>); }
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const form = new FormData(event.currentTarget);
    const fields: Json = { ...dimensions };
    for (const key of ["attribution_text", "license_contact", "minimum_license_fee", "license_fee_currency", "policy_notes", "asset_path"]) fields[key] = str(form.get(key)) || null;
    for (const key of ["geographic_scope", "permitted_platforms", "prohibited_platforms", "permitted_models", "prohibited_models", "channels", "audiences", "transformations"]) fields[key] = csv(str(form.get(key)));
    for (const key of ["attribution_required", "license_required"]) fields[key] = form.get(key) === "" ? null : form.get(key) === "true";
    fields.tdm_reservation = form.get("tdm_reservation") === "" ? null : Number(form.get("tdm_reservation"));
    const revocation = String(form.get("revocation_status") || "UNKNOWN");
    const payload: Json = { permissions, dimensions: fields, creator_id: policy.creator_id || null, creator_assertion_status: "SELF_DECLARED", creator_assertion: record(record(policy.creator_assertions).assertion), consent: record(record(policy.consent_metadata).assertion), consent_status: form.get("consent_status"), consent_source: form.get("consent_source") || null, revocation_status: revocation, revocation_timestamp: revocation === "REVOKED" ? (policy.revocation_timestamp || new Date().toISOString()) : null };
    for (const key of ["effective_from", "effective_until", "consent_timestamp"]) payload[key] = form.get(key) ? new Date(String(form.get(key))).toISOString() : null;
    await save(payload);
  }
  return <form className="cpRightsForm" onSubmit={submit}>
    <div className="cpPresetBar"><span>Quick starting choices</span><button type="button" onClick={() => preset("license")}><LockKeyhole size={14} />License first</button><button type="button" onClick={() => preset("search")}>Allow discovery; license other uses</button><button type="button" onClick={() => preset("unknown")}>Leave unspecified</button></div>
    <p className="artistPresetNote">A starting choice fills the preferences below. Adjust any setting, then save to apply it.</p>
    <div className="cpPermissionGroups">{groups.map((group) => {
      const fields = PERMISSIONS.filter((permission) => permission.group === group);
      const choices = [...new Set(fields.map((permission) => permissions[permission.key]))];
      const overview = choices.length === 1 ? PERMISSION_OPTIONS.find(([value]) => value === choices[0])?.[1] || "Not specified" : "Mixed preferences";
      return <details key={group} className="cpPermissionGroup" open={group === "Training"}>
        <summary><span>{group}</span><small>{fields.length} {fields.length === 1 ? "setting" : "settings"} · {overview}</small></summary>
        <div>{fields.map((permission) => <label key={permission.key} className="cpPermissionRow"><span><b>{permission.label}</b><small>{permission.description}</small></span><select aria-label={permission.label} value={permissions[permission.key]} onChange={(event) => setPermissions((old) => ({ ...old, [permission.key]: event.target.value as Permission }))}>{PERMISSION_OPTIONS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>)}</div>
      </details>;
    })}</div>
    <details className="cpDetails"><summary>Attribution & licensing details</summary><div className="cpDetailBody cpFormGrid">
      {[['attribution_required', 'Require attribution'], ['license_required', 'Require a license']].map(([key, label]) => <label className="portalField" key={key}><span className="portalFieldLabel">{label}</span><select aria-label={label} name={key} defaultValue={dimensions[key] === true ? "true" : dimensions[key] === false ? "false" : ""}><option value="">Not specified</option><option value="true">Yes</option><option value="false">No</option></select></label>)}
      <label className="portalField"><span className="portalFieldLabel">Attribution text</span><input name="attribution_text" maxLength={1000} defaultValue={str(dimensions.attribution_text)} placeholder="Artwork by…" /></label>
      <label className="portalField"><span className="portalFieldLabel">Licensing contact</span><input name="license_contact" maxLength={512} defaultValue={str(dimensions.license_contact)} placeholder="mailto:you@example.com or https://…" /></label>
      <label className="portalField"><span className="portalFieldLabel">Minimum license fee</span><input name="minimum_license_fee" inputMode="decimal" pattern="[0-9]{1,12}(\.[0-9]{1,4})?" defaultValue={str(dimensions.minimum_license_fee)} placeholder="Optional amount" /></label>
      <label className="portalField"><span className="portalFieldLabel">Currency</span><input name="license_fee_currency" pattern="[A-Z]{3}" maxLength={3} defaultValue={str(dimensions.license_fee_currency)} placeholder="USD, EUR, BDT…" /></label>
    </div></details>
    <details className="cpDetails"><summary>Advanced scope, consent & dates</summary><div className="cpDetailBody cpFormGrid">
      {[["geographic_scope", "Permitted countries", "BD, US, DE — blank means unspecified"], ["permitted_platforms", "Permitted platforms", "Comma-separated names"], ["prohibited_platforms", "Prohibited platforms", "Comma-separated names"], ["permitted_models", "Permitted models", "Model identifiers"], ["prohibited_models", "Prohibited models", "Model identifiers"], ["channels", "Channels", "web, print"], ["audiences", "Audiences", "internal, public"], ["transformations", "Transformations", "crop, resize"]].map(([key, label, hint]) => <label className="portalField" key={key}><span className="portalFieldLabel">{label}</span><input name={key} defaultValue={labels(dimensions[key]).join(", ")} placeholder={hint} /></label>)}
      <label className="portalField"><span className="portalFieldLabel">Consent status</span><select aria-label="Consent status" name="consent_status" value={consentStatus} onChange={(e) => setConsentStatus(e.target.value)}><option value="UNKNOWN">Not recorded</option><option value="GRANTED">Granted</option><option value="NOT_GRANTED">Not granted</option><option value="WITHDRAWN">Withdrawn</option></select></label>
      <label className="portalField"><span className="portalFieldLabel">Consent source</span><input required={consentStatus === "GRANTED"} name="consent_source" maxLength={512} defaultValue={str(policy.consent_source)} placeholder="Required with granted consent; use a record or agreement reference" /></label>
      <label className="portalField"><span className="portalFieldLabel">Policy revocation status</span><select aria-label="Policy revocation status" name="revocation_status" defaultValue={str(policy.revocation_status, "UNKNOWN")}><option value="UNKNOWN">Not specified</option><option value="NOT_REVOKED">Not revoked</option><option value="REVOKED">Revoked</option></select><small className="portalFieldHint">A new policy can explicitly record restored preferences; earlier versions remain preserved.</small></label>
      {[["consent_timestamp", "Consent recorded at"], ["effective_from", "Effective from"], ["effective_until", "Effective until"]].map(([key, label]) => <label className="portalField" key={key}><span className="portalFieldLabel">{label}</span><input required={key === "consent_timestamp" && consentStatus === "GRANTED"} type="datetime-local" name={key} defaultValue={toLocalDate(policy[key])} /></label>)}
      <label className="portalField"><span className="portalFieldLabel">Broad text/data mining reservation</span><select aria-label="Broad text/data mining reservation" name="tdm_reservation" defaultValue={dimensions.tdm_reservation == null ? "" : String(dimensions.tdm_reservation)}><option value="">Not specified</option><option value="1">Reserve rights</option><option value="0">Do not reserve broad TDM rights</option></select></label>
      <label className="portalField"><span className="portalFieldLabel">Artwork path on your website</span><input name="asset_path" defaultValue={str(dimensions.asset_path)} placeholder="/artworks/my-artwork.png" /><small className="portalFieldHint">Used for preference exports; no URL is fetched.</small></label>
      <label className="portalField cpFull"><span className="portalFieldLabel">Policy notes</span><textarea name="policy_notes" maxLength={4000} rows={3} defaultValue={str(dimensions.policy_notes)} placeholder="Additional conditions or review instructions" /></label>
    </div></details>
    <div className="cpFormFooter"><p>Preferences record your intent. They do not grant a contract or guarantee that other systems will comply.</p><button type="submit" className="portalPrimary" disabled={busy}><Save size={16} />{busy ? "Saving…" : "Save new policy version"}</button></div>
    {policy.state !== "REVOKED" && <details className="cpDetails"><summary>Withdraw this policy</summary><div className="cpDetailBody cpRevocation">{confirmRevocation ? <><p>Withdraw this policy? This records a new revoked version and preserves the history. Existing contracts need separate review.</p><div className="cpActions"><button type="button" className="portalSecondary" disabled={busy} onClick={() => { const now = new Date().toISOString(); void save({ permissions: record(policy.permissions), dimensions, creator_id: policy.creator_id || null, creator_assertion_status: policy.creator_assertion_status || "UNKNOWN", creator_assertion: record(record(policy.creator_assertions).assertion), consent: record(record(policy.consent_metadata).assertion), consent_status: "WITHDRAWN", consent_source: policy.consent_source || null, consent_timestamp: policy.consent_timestamp || null, revocation_status: "REVOKED", revocation_timestamp: now, effective_from: now }); }}>Confirm withdrawal</button><button className="cpTextButton" type="button" onClick={() => setConfirmRevocation(false)}>Keep current policy</button></div></> : <button className="cpTextButton" type="button" onClick={() => setConfirmRevocation(true)}>Withdraw this policy</button>}</div></details>}
  </form>;
}
