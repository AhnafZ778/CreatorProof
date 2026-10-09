"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { Fingerprint, ShieldCheck } from "lucide-react";
import { dateLabel, downloadJson, errorMessage, PERMISSIONS, record, str, type Json } from "@/app/lib/phase1";
import { validPublicToken } from "@/app/lib/phase1Contract";
import { Feedback, Hash, Loading, Status } from "./Phase1UI";

export default function PublicVerification({ token }: { token: string }) {
  const [data, setData] = useState<Json | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    async function load() { setLoading(true); setError(null); setData(null); try { if (!validPublicToken(token)) throw new Error("This verification link is not valid."); const response = await fetch(`/api/public-verification/${token}`, { cache: "no-store", referrerPolicy: "no-referrer", signal: controller.signal }); const body: unknown = await response.json(); if (!response.ok) throw new Error(response.status === 410 ? "This verification link has been revoked." : response.status === 404 ? "This verification link was not found or has expired." : errorMessage(body)); if (!controller.signal.aborted) setData(record(body)); } catch (e) { if (!controller.signal.aborted) setError(e instanceof Error ? e.message : "Could not read verification."); } finally { if (!controller.signal.aborted) setLoading(false); } }
    void load(); return () => controller.abort();
  }, [token, retry]);
  const rights = record(data?.rights_policy_summary);
  return <div className="portalPage isUser cpPublicPage"><header className="cpPublicNav"><Link className="portalBrand" href="/"><span className="portalBrandMark"><ShieldCheck size={17} /></span>CreatorProof</Link><span>Public verification</span></header><main className="portalMain"><section className="portalHero"><div className="portalHeroKicker">A scoped, shareable record</div><h1>Check the record.</h1><p>Read the information selected by the person who created this link. Private contacts, uploaded images, and internal model outputs are excluded.</p></section><section className="portalPanel cpPublicRecord">
    {loading ? <Loading label="Reading the verification record…" /> : error ? <><Feedback error={error} /><button className="portalSecondary" type="button" onClick={() => setRetry((old) => old + 1)}>Try again</button></> : data && <><div className="cpRecordBar"><Fingerprint size={23} /><div><strong>Public record available</strong><span>Checked {dateLabel(data.verification_timestamp)}</span></div><span className="cpStatus" data-tone="neutral">Scoped disclosure</span></div><div className="cpFacts"><div><span>CreatorProof asset</span><strong>{str(data.public_asset_id)}</strong></div><div><span>Record type</span><strong>{data.resource_type === "work" ? "Registered artwork" : "Image scan"}</strong></div>{data.registration_status != null && <div><span>Registration / scan status</span><Status value={data.registration_status} /></div>}{data.provenance_status != null && <div><span>Provenance status</span><Status value={data.provenance_status} /></div>}</div>
      {Object.keys(rights).length > 0 && <section className="cpSubpanel"><div className="cpSplit"><h3>Disclosed rights preferences</h3><Status value={rights.state} /></div><p className="cpDescription">Policy version {String(rights.policy_version)} · {rights.temporal_binding === "AS_OF_SCAN" ? "Recorded at the time of this scan" : "Current artwork policy"}</p><div className="cpMiniGrid">{PERMISSIONS.map((permission) => <div key={permission.key}><span>{permission.label}</span><Status value={record(rights.preferences)[permission.key]} /></div>)}</div><Hash value={rights.policy_digest_sha256} label="Disclosed policy hash" /></section>}
      {data.rights_policy_summary === null && <p className="cpDescription">No matched artwork rights summary was available for disclosure.</p>}
      <Hash value={data.packet_hash_sha256} label="Verification packet hash" />
      <p className="cpCaption">This record reports registration, stated preferences, provenance status, and byte commitments where disclosed. It does not independently establish ownership, human authorship, or a legal conclusion.</p><button className="portalSecondary" type="button" onClick={() => downloadJson(data, "creatorproof-public-verification.json")}>Download public record</button>
    </>}
    </section></main></div>;
}
