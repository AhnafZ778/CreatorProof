"use client";

import { ArrowUpRight, Check, Layers, Search, ShieldCheck } from "lucide-react";
import { useState } from "react";
import { mediaProxyPath, type AdminRecord } from "../lib/adminInbox";
import { dateLabel, record, str } from "../lib/phase1";

export default function StoredCaseGallery({ cases, loading, onSelect }: { cases: AdminRecord[]; loading: boolean; onSelect: (scanId: string) => void }) {
  const [filter, setFilter] = useState("all");
  const [search, setSearch] = useState("");
  const visible = cases.filter(row => (filter === "all" || (filter === "ai" ? row.stored_case?.comparison_kind === "AI_EDIT" : row.stored_case?.comparison_kind !== "AI_EDIT")) && `${row.matched_work?.title} ${row.matched_work?.claimant} ${row.stored_case?.case_title}`.toLowerCase().includes(search.toLowerCase()));
  return <section className="portalPanel adminPanel storedCaseLibrary" aria-labelledby="stored-cases-title">
    <div className="storedLibraryHeading"><div><span className="storedEyebrow"><ShieldCheck size={14} />Evidence collection</span><h2 id="stored-cases-title">Every image. The full story.</h2><p>Open a saved comparison to inspect the registered work, observed use, recorded evidence and prepared notice.</p></div><span className="storedReady"><Check size={14} />{cases.length} stored comparisons</span></div>
    <div className="storedLibraryToolbar"><div className="storedFilters" aria-label="Comparison filters">{[{ key: "all", text: "All comparisons" }, { key: "copies", text: "Artwork copies" }, { key: "ai", text: "AI edits" }].map(option => <button key={option.key} type="button" aria-pressed={filter === option.key} onClick={() => setFilter(option.key)}>{option.text}</button>)}</div><label className="storedSearch"><Search size={16} /><input aria-label="Find a stored case" placeholder="Find an artwork…" value={search} onChange={event => setSearch(event.target.value)} /></label></div>
    {loading && !cases.length ? <p role="status" className="cpLoading">Loading stored comparisons…</p> : visible.length ? <div className="storedCaseGrid">{visible.map(row => {
      const saved = record(row.stored_case);
      const ai = saved.comparison_kind === "AI_EDIT";
      return <button type="button" className="storedCaseCard" key={row.scan_id} onClick={() => onSelect(row.scan_id)} aria-label={`Open ${str(saved.case_title, row.matched_work?.title)}`}>
        <div className="storedCardImages"><figure><img src={mediaProxyPath(row.reference_media_url)} alt={`${row.matched_work?.title || "Artwork"}, registered reference`} loading="eager" /><figcaption>Registered artwork</figcaption></figure><figure><img src={mediaProxyPath(row.candidate_media_url)} alt={`${row.matched_work?.title || "Artwork"}, observed version`} loading="eager" /><figcaption>Observed version</figcaption></figure><span className="storedImageBridge"><Layers size={15} /></span></div>
        <div className="storedCardBody"><span className={`storedKind ${ai ? "isAI" : ""}`}>{ai ? "Documented AI edit" : saved.comparison_kind === "CROP" ? "Cropped & republished" : "Registered artwork match"}</span><h3>{str(saved.case_title, str(row.matched_work?.title))}</h3><p>{str(saved.caption, "A saved comparison with a recorded registered-work match.")}</p><div className="storedCardFooter"><span>{row.jurisdiction === "EU" ? "EU · DSA" : row.jurisdiction === "US" ? "US · DMCA" : str(row.jurisdiction)}<small>{dateLabel(saved.saved_at)}</small></span><span className="storedOpen">Open case<ArrowUpRight size={16} /></span></div></div>
      </button>;
    })}</div> : <div className="storedEmpty"><Layers size={28} /><h3>{cases.length ? "No comparisons match your search" : "Your saved comparisons belong here"}</h3><p>{cases.length ? "Choose another filter or artwork." : "Open a registered-artwork match in the review inbox and save its comparison."}</p></div>}
  </section>;
}
