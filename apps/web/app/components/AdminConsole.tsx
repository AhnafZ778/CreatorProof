"use client";

import { ArrowLeft, ArrowUpRight, FileText, History, Images, Inbox, Pause, Play, RefreshCw, ScanSearch } from "lucide-react";
import { useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent, type ReactNode } from "react";
import { adminInbox, flagLabel, mediaProxyPath, needsAdminReview, type AdminRecord as Json, type InboxItem } from "../lib/adminInbox";
import { marketplaceLabel, type MarketplaceName } from "../lib/marketplaces";
import { dateLabel, downloadJson, errorMessage, labels, readable, record, str } from "../lib/phase1";
import EvidenceMatrixPanel from "./EvidenceMatrixPanel";
import InvestigationPanel from "./InvestigationPanel";
import MarketplaceSourceSelect from "./MarketplaceSourceSelect";
import ProtectionActionPanel from "./ProtectionActionPanel";
import { Feedback, Status } from "./Phase1UI";
import "../styles/admin-workspace.css";

const SECTIONS = [
  { key: "review", label: "Review inbox", Icon: Inbox },
  { key: "monitor", label: "Monitoring", Icon: ScanSearch },
  { key: "history", label: "History", Icon: History },
] as const;
type Section = typeof SECTIONS[number]["key"];
const DETAILS = [{ key: "summary", label: "Review & decide" }, { key: "evidence", label: "Detailed evidence" }, { key: "notice", label: "Prepare notice" }] as const;
type Detail = typeof DETAILS[number]["key"];
const MONITOR_DELAY_MS = 60_000;
const PAGE_SIZE = 200;
const EMPTY_DRAFT = { jurisdiction: "GENERIC", claimant_name: "", claimant_email: "", protected_title: "", protected_url: "", infringing_url: "", evidence_summary: "", recipient_email: "" };

function safePublicUrl(value: unknown): string {
  if (typeof value !== "string") return "";
  try { const url = new URL(value); return ["http:", "https:"].includes(url.protocol) && !url.username && !url.password ? url.href : ""; } catch { return ""; }
}
function statusLabel(item: InboxItem) { return item.reviewCase ? readable(item.reviewCase.state) : "Needs review"; }
function sourceLabel(item: InboxItem) { return marketplaceLabel(item.source, item.asset?.metadata?.environment || item.detection?.source_metadata?.metadata?.environment); }

export default function AdminConsole() {
  const params = useSearchParams();
  const deepLink = params.get("scan_id");
  const [section, setSection] = useState<Section>("review");
  const [detail, setDetail] = useState<Detail>("summary");
  const [cases, setCases] = useState<Json[]>([]);
  const [detections, setDetections] = useState<Json[]>([]);
  const [history, setHistory] = useState<Json[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [moreAvailable, setMoreAvailable] = useState(false);
  const [historyMoreAvailable, setHistoryMoreAvailable] = useState(false);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [flagsLoading, setFlagsLoading] = useState(false);
  const detectionOffset = useRef(0);
  const historyOffset = useRef(0);
  const loadMoreBusy = useRef(false);
  const loadEpoch = useRef(0);
  const [queueFilter, setQueueFilter] = useState("pending");
  const [search, setSearch] = useState("");
  const [historyFilter, setHistoryFilter] = useState("all");
  const [selectedItem, setSelectedItem] = useState<InboxItem | null>(null);
  const [selectedScan, setSelectedScan] = useState<Json | null>(null);
  const [selectionBusy, setSelectionBusy] = useState(false);
  const [selectionError, setSelectionError] = useState<string | null>(null);
  const selectionEpoch = useRef(0);
  const handledLink = useRef<string | null>(null);
  const [draftForm, setDraftForm] = useState(EMPTY_DRAFT);
  const [draft, setDraft] = useState<Json | null>(null);
  const [draftBusy, setDraftBusy] = useState(false);
  const [draftError, setDraftError] = useState<string | null>(null);
  const [deliveryBusy, setDeliveryBusy] = useState(false);
  const [copied, setCopied] = useState(false);
  const [noticeReviewed, setNoticeReviewed] = useState(false);
  const [draftReadyForEmail, setDraftReadyForEmail] = useState(false);
  const [savedDrafts, setSavedDrafts] = useState<Json[]>([]);
  const [draftsLoading, setDraftsLoading] = useState(false);
  const loadedDraftScan = useRef<string | null>(null);

  const [provider, setProvider] = useState<MarketplaceName>("pixabay");
  const [sourceConfigured, setSourceConfigured] = useState<boolean | null>(null);
  const [query, setQuery] = useState("digital art");
  const [catalogId, setCatalogId] = useState("default");
  const [intendedUse, setIntendedUse] = useState("marketplace monitoring");
  const [monitoring, setMonitoring] = useState(false);
  const [monitorBusy, setMonitorBusy] = useState(false);
  const [lastChecked, setLastChecked] = useState<string | null>(null);
  const [newImages, setNewImages] = useState<Json[]>([]);
  const [duplicates, setDuplicates] = useState(0);
  const [monitorError, setMonitorError] = useState<string | null>(null);

  const loadAdminData = useCallback(async (quiet = false) => {
    const epoch = ++loadEpoch.current;
    if (!quiet) setLoading(true);
    const paths = ["/api/review-cases?limit=200", `/api/admin/marketplaces/monitor?limit=${PAGE_SIZE}&offset=0`, `/api/admin/user-detections?limit=${PAGE_SIZE}`];
    const results = await Promise.allSettled(paths.map(async (path) => {
      const response = await fetch(path, { cache: "no-store" });
      const body: unknown = await response.json();
      if (!response.ok) throw new Error(errorMessage(body, "Saved records could not be loaded."));
      if (!Array.isArray(body)) throw new Error("The server returned an unexpected record list.");
      return body as Json[];
    }));
    if (epoch !== loadEpoch.current) return;
    const [caseRows, assets, flags] = results;
    if (caseRows.status === "fulfilled") setCases(current => [...new Map([...current, ...caseRows.value].map(row => [row.id, row])).values()]);
    if (assets.status === "fulfilled") {
      setHistory(current => [...new Map([...current, ...assets.value].map(row => [row.id, row])).values()]);
      if (!quiet) { historyOffset.current = assets.value.length; setHistoryMoreAvailable(assets.value.length === PAGE_SIZE); }
    }
    if (flags.status === "fulfilled") {
      setDetections(current => [...new Map([...current, ...flags.value].map(row => [row.scan_id, row])).values()]); if (!quiet) detectionOffset.current = flags.value.length;
      if (!quiet) setMoreAvailable(flags.value.length === PAGE_SIZE);
    }
    setLoadError(results.some(result => result.status === "rejected") ? "Some saved records could not be refreshed. Your existing records remain visible; try Refresh." : null);
    setLoading(false);
  }, []);

  useEffect(() => {
    void loadAdminData();
    const interval = setInterval(() => { if (document.visibilityState === "visible") void loadAdminData(true); }, 30_000);
    const onFocus = () => void loadAdminData(true);
    window.addEventListener("focus", onFocus);
    return () => { clearInterval(interval); window.removeEventListener("focus", onFocus); loadEpoch.current++; selectionEpoch.current++; };
  }, [loadAdminData]);

  async function loadMore() {
    if (loadMoreBusy.current || !moreAvailable) return;
    loadMoreBusy.current = true; setFlagsLoading(true); setLoadError(null);
    const offset = detectionOffset.current;
    try {
      const response = await fetch(`/api/admin/user-detections?limit=${PAGE_SIZE}&offset=${offset}`, { cache: "no-store" });
      const body: unknown = await response.json();
      if (!response.ok || !Array.isArray(body)) throw new Error(errorMessage(body, "Older flags could not be loaded."));
      const rows = body as Json[];
      setDetections(current => [...new Map([...current, ...rows].map(row => [row.scan_id, row])).values()]);
      detectionOffset.current = offset + rows.length; setMoreAvailable(rows.length === PAGE_SIZE);
    } catch (e) { setLoadError(e instanceof Error ? e.message : "Older flags could not be loaded."); }
    finally { loadMoreBusy.current = false; setFlagsLoading(false); }
  }

  async function loadMoreHistory() {
    if (historyLoading || !historyMoreAvailable) return;
    setHistoryLoading(true); setLoadError(null);
    const offset = historyOffset.current;
    try {
      const response = await fetch(`/api/admin/marketplaces/monitor?limit=${PAGE_SIZE}&offset=${offset}`, { cache: "no-store" });
      const body: unknown = await response.json();
      if (!response.ok || !Array.isArray(body)) throw new Error(errorMessage(body, "Older source history could not be loaded."));
      const rows = body as Json[];
      setHistory(current => [...new Map([...current, ...rows].map(row => [row.id, row])).values()]);
      historyOffset.current = offset + rows.length; setHistoryMoreAvailable(rows.length === PAGE_SIZE);
    } catch (e) { setLoadError(e instanceof Error ? e.message : "Older source history could not be loaded."); }
    finally { setHistoryLoading(false); }
  }

  const inbox = useMemo(() => adminInbox(detections, cases, history), [detections, cases, history]);
  const pendingCount = inbox.filter(needsAdminReview).length;
  const visibleInbox = inbox.filter(item => (queueFilter !== "pending" || needsAdminReview(item)) && `${item.title} ${sourceLabel(item)} ${flagLabel(item)} ${item.scanId}`.toLowerCase().includes(search.toLowerCase()));
  const visibleHistory = history.filter(asset => historyFilter === "all" || asset.classification === historyFilter);

  const selectItem = useCallback(async (initial: InboxItem) => {
    const epoch = ++selectionEpoch.current;
    setSection("review"); setDetail("summary"); setSelectedItem(initial); setSelectedScan(null);
    setSelectionBusy(true); setSelectionError(null); setDraft(null); setSavedDrafts([]); loadedDraftScan.current = null; setDraftError(null); setDraftBusy(false); setDeliveryBusy(false); setDraftsLoading(false); setNoticeReviewed(false); setDraftReadyForEmail(false); setCopied(false);
    try {
      const response = await fetch(`/api/scans/${encodeURIComponent(initial.scanId)}`, { cache: "no-store" });
      const body: unknown = await response.json();
      if (!response.ok) throw new Error(errorMessage(body, "The selected scan could not be loaded."));
      if (epoch !== selectionEpoch.current) return;
      const scan = record(body) as Json;
      setSelectedScan(scan);
      let item = initial;
      if (!item.detection) {
        const flagResponse = await fetch(`/api/admin/user-detections?scan_id=${encodeURIComponent(initial.scanId)}&limit=1`, { cache: "no-store" });
        if (flagResponse.ok) {
          const flags: unknown = await flagResponse.json();
          if (Array.isArray(flags) && flags[0]) item = { ...item, detection: flags[0], reviewCase: flags[0].review_case || item.reviewCase };
        }
      }
      if (epoch !== selectionEpoch.current) return;
      if (!item.reviewCase && scan.admin_review?.status === "needs_review") {
        const caseResponse = await fetch(`/api/admin/user-detections/${encodeURIComponent(item.scanId)}/review-case`, { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
        const opened: unknown = await caseResponse.json();
        if (!caseResponse.ok) throw new Error(errorMessage(opened, "The review case could not be opened."));
        item = { ...item, reviewCase: { ...record(opened), scan_id: item.scanId } as Json };
        if (epoch !== selectionEpoch.current) return;
        setCases(current => [...current.filter(row => row.scan_id !== item.scanId), item.reviewCase!]);
      }
      setSelectedItem(item);
      const work = record(item.detection?.matched_work);
      const packet = record(scan.evidence_packet);
      const match = Array.isArray(packet.matches) ? record(packet.matches.find(row => record(row).work_id === scan.top_match_work_id) || packet.matches[0]) : {};
      setDraftForm(() => ({
        ...EMPTY_DRAFT, claimant_name: str(work.claimant),
        jurisdiction: String(item.detection?.jurisdiction || "GENERIC"),
        protected_title: str(work.title, str(match.title)),
        infringing_url: safePublicUrl(item.detection?.source_url || item.asset?.source_url),
        evidence_summary: str(item.detection?.review_summary, `CreatorProof recorded ${flagLabel(item).toLowerCase()} for scan ${item.scanId}. Review the visual comparison, rights and publication context before taking action.`),
      }));
    } catch (e) { if (epoch === selectionEpoch.current) setSelectionError(e instanceof Error ? e.message : "The selected record could not be opened."); }
    finally { if (epoch === selectionEpoch.current) setSelectionBusy(false); }
  }, []);

  useEffect(() => {
    if (loading || !deepLink || handledLink.current === deepLink) return;
    handledLink.current = deepLink;
    if (!/^scn_[a-f0-9]{32}$/.test(deepLink)) { setLoadError("The linked scan identifier is invalid."); return; }
    const item = inbox.find(row => row.scanId === deepLink);
    void selectItem(item || { key: deepLink, scanId: deepLink, source: "User scan", title: "Submitted image", classification: "REVIEW", createdAt: "" });
  }, [deepLink, loading, inbox, selectItem]);

  const runMonitor = useCallback(async () => {
    setMonitorBusy(true); setMonitorError(null);
    try {
      const response = await fetch("/api/admin/marketplaces/monitor", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ provider, query, catalog_id: catalogId, intended_use: intendedUse, per_page: 9, scan_new: true }) });
      const body: unknown = await response.json();
      if (!response.ok) throw new Error(errorMessage(body, "The marketplace check failed."));
      const result = record(body);
      setNewImages(Array.isArray(result.new_images) ? result.new_images : []);
      if (Array.isArray(result.history)) {
        const rows = result.history as Json[];
        setHistory(current => [...new Map([...current, ...rows].map(row => [row.id, row])).values()]);
      }
      setDuplicates(Number(result.duplicate_count || 0)); setLastChecked(str(result.checked_at));
      await loadAdminData(true);
    } catch (e) { setMonitorError(e instanceof Error ? e.message : "The marketplace check failed."); }
    finally { setMonitorBusy(false); }
  }, [provider, query, catalogId, intendedUse, loadAdminData]);

  useEffect(() => {
    if (!monitoring) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    const check = async () => { await runMonitor(); if (!cancelled) timer = setTimeout(() => void check(), MONITOR_DELAY_MS); };
    timer = setTimeout(() => void check(), MONITOR_DELAY_MS);
    return () => { cancelled = true; clearTimeout(timer); };
  }, [monitoring, runMonitor]);

  function selectAsset(asset: Json) {
    if (!asset.scan_id) { setMonitorError("This image has no completed scan yet. Its source record is kept in History."); setSection("monitor"); return; }
    void selectItem(inbox.find(item => item.scanId === asset.scan_id) || { key: asset.scan_id, scanId: asset.scan_id, asset, source: asset.provider, title: asset.title, classification: asset.classification, createdAt: asset.first_seen_at });
  }

  const detection = selectedItem?.detection;
  const asset = selectedItem?.asset;
  const packet = record(selectedScan?.evidence_packet);
  const matchedWork = record(detection?.matched_work);
  const referenceWork = Object.keys(matchedWork).length ? matchedWork : record(detection?.reference_work);
  const referenceId = str(referenceWork.id, str(selectedScan?.top_match_work_id));
  const sourceUrl = safePublicUrl(detection?.source_url || asset?.source_url || record(packet.source_observation).source_url);
  const caseRecord = selectedItem?.reviewCase;
  const selectedEpoch = selectionEpoch.current;
  const noticeEligible = Boolean(selectedScan?.state === "COMPLETED" && selectedScan.match_status === "MATCH_FOUND" && detection?.takedown_eligible !== false && !(caseRecord && ["RESOLVED", "CLOSED"].includes(String(caseRecord.state)) && String(caseRecord.disposition) === "APPROVED_FOR_PUBLICATION"));
  const publicNoticeReady = Boolean(safePublicUrl(draftForm.infringing_url) && safePublicUrl(draftForm.protected_url));
  const emailReady = Boolean(draftReadyForEmail && publicNoticeReady && draft && noticeReviewed && str(draft.recipient_email, draftForm.recipient_email).trim());

  useEffect(() => {
    if (detail !== "notice" || !selectedItem || loadedDraftScan.current === selectedItem.scanId) return;
    const controller = new AbortController();
    const id = selectedItem.scanId;
    setDraftsLoading(true);
    void fetch(`/api/admin/takedowns/drafts?scan_id=${encodeURIComponent(id)}&limit=20`, { cache: "no-store", signal: controller.signal })
      .then(async response => {
        const body: unknown = await response.json();
        if (!response.ok || !Array.isArray(body)) throw new Error(errorMessage(body, "Saved notices could not be loaded."));
        if (!controller.signal.aborted) { setSavedDrafts(body); loadedDraftScan.current = id; }
      }).catch(error => { if (!controller.signal.aborted) setDraftError(error instanceof Error ? error.message : "Saved notices could not be loaded."); })
      .finally(() => { if (!controller.signal.aborted) setDraftsLoading(false); });
    return () => controller.abort();
  }, [detail, selectedItem?.scanId]);

  async function createDraft(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!selectedItem || !noticeEligible || draftBusy) return;
    const epoch = selectionEpoch.current;
    setDraftBusy(true); setDraftError(null); setNoticeReviewed(false);
    try {
      const response = await fetch("/api/admin/takedowns/drafts", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ...draftForm, scan_id: selectedItem.scanId, infringing_url: draftForm.infringing_url || null, recipient_email: draftForm.recipient_email || null }) });
      const body: unknown = await response.json();
      if (!response.ok) throw new Error(errorMessage(body, "The notice could not be drafted."));
      if (epoch === selectionEpoch.current) { const saved = record(body); setDraft(saved); setDraftReadyForEmail(true); setSavedDrafts(current => [saved, ...current.filter(row => row.id !== saved.id)]); }
    } catch (e) { if (epoch === selectionEpoch.current) setDraftError(e instanceof Error ? e.message : "The notice could not be drafted."); }
    finally { if (epoch === selectionEpoch.current) setDraftBusy(false); }
  }

  async function openMailto() {
    if (!draft || !noticeReviewed || !emailReady || deliveryBusy) return;
    const epoch = selectionEpoch.current;
    setDeliveryBusy(true); setDraftError(null);
    try {
      const recipient = str(draft.recipient_email, draftForm.recipient_email);
      const response = await fetch(`/api/admin/takedowns/${encodeURIComponent(String(draft.id))}/send`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ delivery: "mailto", recipient_email: recipient || null }) });
      const body: unknown = await response.json();
      if (!response.ok) throw new Error(errorMessage(body, "The notice handoff could not be recorded."));
      if (epoch !== selectionEpoch.current) return;
      window.location.href = `mailto:${encodeURIComponent(recipient)}?subject=${encodeURIComponent(String(draft.subject || ""))}&body=${encodeURIComponent(String(draft.body || ""))}`;
    } catch (e) { if (epoch === selectionEpoch.current) setDraftError(e instanceof Error ? e.message : "The notice could not be opened."); }
    finally { if (epoch === selectionEpoch.current) setDeliveryBusy(false); }
  }

  function switchSection(next: Section) { setSection(next); }
  function backToInbox() { selectionEpoch.current++; setSelectedItem(null); setSelectedScan(null); setSelectionBusy(false); setDraftBusy(false); setSelectionError(null); }

  return <div className="adminConsole adminWorkspace">
    <section className="portalHero adminHero" aria-labelledby="admin-title">
      <div className="portalHeroKicker">Admin portal</div>
      <h1 id="admin-title">Review first. Act with evidence.</h1>
      <p>Flagged scans arrive in your inbox. Open an image, check the facts, then record a decision or prepare a notice.</p>
      <div className="adminHeaderMeta"><span><Inbox size={16} />{pendingCount} need review</span><span><Images size={16} />{history.length} source images saved</span>{monitoring && <span className="adminLiveIndicator">Monitoring active</span>}</div>
    </section>
    <div className="adminSectionNav" role="tablist" aria-label="Admin sections">
      {SECTIONS.map(({ key, label, Icon }) => <button key={key} id={`admin-tab-${key}`} type="button" role="tab" aria-controls={`admin-panel-${key}`} aria-selected={section === key} tabIndex={section === key ? 0 : -1} onClick={() => switchSection(key)} onKeyDown={event => { const index = SECTIONS.findIndex(tab => tab.key === key); const next = event.key === "ArrowRight" ? (index + 1) % SECTIONS.length : event.key === "ArrowLeft" ? (index + SECTIONS.length - 1) % SECTIONS.length : event.key === "Home" ? 0 : event.key === "End" ? SECTIONS.length - 1 : -1; if (next >= 0) { event.preventDefault(); switchSection(SECTIONS[next].key); document.getElementById(`admin-tab-${SECTIONS[next].key}`)?.focus(); } }}><Icon size={17} />{label}{key === "review" && pendingCount > 0 && <span>{pendingCount}</span>}</button>)}
    </div>
    <Feedback error={loadError} />

    <div id="admin-panel-review" role="tabpanel" aria-labelledby="admin-tab-review" hidden={section !== "review"}>
      {!selectedItem ? <section id="admin-review-inbox" className="portalPanel adminPanel" aria-labelledby="inbox-title">
        <SectionHeading id="inbox-title" title="Review inbox" description="Flagged uploads and marketplace scans appear once, with their evidence and source details."><button className="portalSecondary" type="button" disabled={loading || flagsLoading || historyLoading} onClick={() => void loadAdminData()}><RefreshCw size={15} />{loading ? "Refreshing…" : "Refresh"}</button></SectionHeading>
        <div className="adminInboxFilters"><label className="portalField"><span className="portalFieldLabel">Show</span><select aria-label="Show" value={queueFilter} onChange={e => setQueueFilter(e.target.value)}><option value="pending">Needs review</option><option value="all">All stored flags</option></select></label><label className="portalField"><span className="portalFieldLabel">Find a record</span><input value={search} onChange={e => setSearch(e.target.value)} placeholder="Artwork, source or scan" /></label></div>
        {loading && !inbox.length ? <p className="cpLoading" role="status">Loading saved flags…</p> : visibleInbox.length ? <div className="adminInboxList" aria-label="Flagged scans">{visibleInbox.map(item => <button type="button" className="adminInboxRow" key={item.key} onClick={() => void selectItem(item)}>
          <QueueThumbnail item={item} /><span className="adminInboxMain"><b>{flagLabel(item)}</b><span>{item.title}</span><small>{sourceLabel(item)} · {dateLabel(item.createdAt)}</small></span><span className="adminInboxCountry">{item.detection?.country_code ? `Declared country: ${item.detection.country_code}` : "Country not provided"}</span><span className="adminInboxState">{statusLabel(item)}<ArrowUpRight size={16} /></span>
        </button>)}</div> : <EmptyState icon="inbox" title={queueFilter === "pending" && inbox.length ? "You’re up to date" : "No flagged scans yet"}>New flags appear here automatically. Clean scans do not need an Admin decision.</EmptyState>}
        {moreAvailable && <button className="portalSecondary adminLoadMore" type="button" disabled={loading || flagsLoading} onClick={() => void loadMore()}>{flagsLoading ? "Loading older flags…" : "Load older flags"}</button>}
      </section> : <section id="admin-review-inbox" className="portalPanel adminPanel adminCaseWorkspace" aria-label="Selected scan review">
        <div className="adminCaseTop"><button type="button" className="cpTextButton" onClick={backToInbox}><ArrowLeft size={16} />Back to inbox</button>{caseRecord && <Status value={caseRecord.state} />}</div>
        <h2>{flagLabel(selectedItem)}</h2><p className="adminCaseSubtitle">{selectedItem.title} · {sourceLabel(selectedItem)}</p>
        <div className="adminDetailNav" role="tablist" aria-label="Selected case tools">{DETAILS.map(({ key, label }) => <button key={key} id={`admin-detail-${key}`} type="button" role="tab" aria-selected={detail === key} aria-controls={`admin-detail-panel-${key}`} tabIndex={detail === key ? 0 : -1} onClick={() => setDetail(key)} onKeyDown={e => { const index = DETAILS.findIndex(tab => tab.key === key); const next = e.key === "ArrowRight" ? (index + 1) % DETAILS.length : e.key === "ArrowLeft" ? (index + DETAILS.length - 1) % DETAILS.length : e.key === "Home" ? 0 : e.key === "End" ? DETAILS.length - 1 : -1; if (next >= 0) { e.preventDefault(); setDetail(DETAILS[next].key); document.getElementById(`admin-detail-${DETAILS[next].key}`)?.focus(); } }}>{label}</button>)}</div>
        {selectionBusy && <p className="cpLoading" role="status">Loading the image, evidence and review record…</p>}<Feedback error={selectionError} />
        {selectedScan && <>
          <div role="tabpanel" id="admin-detail-panel-summary" aria-labelledby="admin-detail-summary" hidden={detail !== "summary"}>
            <div className="adminReasonBox"><h3>Why this needs review</h3><p>{str(detection?.review_summary, "Check the recorded findings and intended use before deciding what to do.")}</p>{labels(detection?.flag_reasons).length > 0 && <ul>{labels(detection?.flag_reasons).map(reason => <li key={reason}>{readable(reason)}</li>)}</ul>}</div>
            <div className="adminComparison" aria-label="Submitted and registered image comparison">
              <ComparisonImage label="Submitted image" src={detection?.candidate_media_status && detection.candidate_media_status !== "available" ? "" : mediaProxyPath(detection?.candidate_media_url) || `/api/scans/${encodeURIComponent(selectedItem.scanId)}/media`} />
              <ComparisonImage label={referenceWork.id && !matchedWork.id && labels(detection?.flag_reasons).includes("CREATOR_RESEMBLANCE") ? "Artist reference for resemblance" : "Registered artwork"} src={mediaProxyPath(detection?.reference_media_url) || (referenceId ? `/api/works/${encodeURIComponent(referenceId)}/media` : "")} missing={referenceId ? "The registered reference image is unavailable." : "No registered artwork match was established. Review the other findings."} />
            </div>
            <dl className="adminFacts"><Fact label="Reference artwork" value={str(referenceWork.title, referenceId ? "Registered work" : "No confirmed match")} /><Fact label="Artist / claimant" value={str(referenceWork.claimant, "Not supplied")} /><Fact label="Intended use" value={str(detection?.intended_use, str(selectedScan.intended_use, "Not supplied"))} /><Fact label="Catalog checked" value={str(detection?.catalog_id, str(selectedScan.catalog_id, "Not supplied"))} /><Fact label="Country declaration" value={detection?.country_code ? `${detection.country_code} · supplied by the submitting user` : "Not supplied; residence is unknown"} /><Fact label="Policy outcome" value={readable(selectedScan.policy_action || "UNKNOWN")} /></dl>
            {Object.keys(record(detection?.use_context)).length > 0 && <dl className="adminFacts">{Object.entries(record(detection?.use_context)).map(([key, value]) => <Fact key={key} label={key === "territory" ? "Intended publication country" : readable(key)} value={String(value)} />)}</dl>}
            {Object.keys(referenceWork).length > 0 && <details className="cpDetails"><summary>Rights and registered-work details</summary><dl className="adminFacts cpDetailBody"><Fact label="Claim state" value={readable(referenceWork.claim_state)} /><Fact label="Recorded rights path" value={readable(referenceWork.rights_path)} /><Fact label="Recorded allowed uses" value={labels(referenceWork.allowed_uses).join(", ") || "Not supplied"} /></dl></details>}
            <div className="adminSourceSummary"><b>Public source</b>{sourceUrl ? <a href={sourceUrl} target="_blank" rel="noreferrer">{sourceUrl}<ArrowUpRight size={14} /></a> : <p>No public URL was supplied. Add the published location before preparing a notice.</p>}{asset?.provider === "ebay" && <p>Item location: {String(asset.metadata?.item_location_country || "Not supplied")}. This does not establish the seller’s country of residence.</p>}{detection?.candidate_media_expires_at && <p>Submitted comparison image retained until {dateLabel(detection.candidate_media_expires_at)}. Stored evidence remains available after media expiry.</p>}</div>
            <ProtectionActionPanel key={selectedItem.scanId} scan={selectedScan} reviewRequired={Boolean(caseRecord)} onDecisionRecorded={reviewCase => { const actionScanId = selectedItem.scanId; setSelectedItem(current => current && current.scanId === actionScanId && selectionEpoch.current === selectedEpoch ? { ...current, reviewCase: { ...current.reviewCase, ...reviewCase } } : current); setCases(current => [...current.filter(row => row.scan_id !== actionScanId), { ...caseRecord, ...reviewCase, scan_id: actionScanId }]); void loadAdminData(true); }} />
          </div>
          <div role="tabpanel" id="admin-detail-panel-evidence" aria-labelledby="admin-detail-evidence" hidden={detail !== "evidence"}>
            {detail === "evidence" && <><EvidenceMatrixPanel key={`matrix-${selectedItem.scanId}`} scanId={selectedItem.scanId} canCorrect /><details className="cpDetails adminAdvanced"><summary>Optional AI investigation assistant</summary><InvestigationPanel key={`investigation-${selectedItem.scanId}`} scanId={selectedItem.scanId} scanState={str(selectedScan.state)} /></details><details className="cpDetails"><summary>Technical record and evidence export</summary><div className="cpDetailBody"><dl className="adminFacts"><Fact label="Scan ID" value={selectedItem.scanId} /><Fact label="Submitted image hash" value={str(detection?.candidate_sha256, str(selectedScan.candidate_sha256))} /><Fact label="Recorded at" value={dateLabel(detection?.completed_at || selectedScan.completed_at)} /></dl><button className="portalSecondary" type="button" onClick={() => downloadJson(selectedScan.evidence_packet, `creatorproof-evidence-${selectedItem.scanId}.json`)}>Download evidence packet</button></div></details></>}
          </div>
          <div role="tabpanel" id="admin-detail-panel-notice" aria-labelledby="admin-detail-notice" hidden={detail !== "notice"}>
            <h3 className="adminNoticeTitle">Prepare a takedown request</h3>
            {draftsLoading && <p className="cpLoading" role="status">Loading saved drafts…</p>}
            {savedDrafts.length > 0 && <details className="cpDetails"><summary>Saved notice drafts ({savedDrafts.length})</summary><div className="cpDetailBody adminSavedDrafts">{savedDrafts.map(saved => <article key={saved.id}><div><b>{str(saved.subject)}</b><small>{saved.jurisdiction} · {dateLabel(saved.created_at)} · {readable(saved.state)}</small></div><button className="portalSecondary" type="button" onClick={() => { setDraft(saved); setDraftReadyForEmail(false); setNoticeReviewed(false); }}>View saved draft</button>{draft?.id === saved.id && !noticeEligible && <pre>{str(saved.body)}</pre>}</article>)}</div></details>}
            {!noticeEligible ? <div className="adminReasonBox"><b>A copyright notice needs a supported artwork match.</b><p>{str(detection?.takedown_block_reason, "This record can be reviewed and given an internal decision. Verify a protected work, claimant authority and the actual public use before drafting a copyright notice.")}</p></div> : <>
              <p className="adminSectionSummary">Confirm the protected work, public location and claimant details. Choose the jurisdiction after reviewing the facts.</p>
              <form className="portalForm adminDraftForm" onSubmit={createDraft}>
                <label className="portalField"><span className="portalFieldLabel">Jurisdiction</span><select aria-label="Jurisdiction" value={draftForm.jurisdiction} disabled={draftBusy} onChange={e => { setDraftForm({ ...draftForm, jurisdiction: e.target.value }); setDraft(null); setDraftReadyForEmail(false); }}><option value="US">United States — DMCA</option><option value="EU">European Union — DSA</option><option value="UK">United Kingdom</option><option value="CA">Canada</option><option value="AU">Australia</option><option value="GENERIC">International platform notice</option></select></label>
                {([{ key: "claimant_name", label: "Claimant name", required: true }, { key: "claimant_email", label: "Claimant email", required: true, type: "email" }, { key: "protected_title", label: "Protected work title", required: true }, { key: "protected_url", label: "Protected work URL", required: true, type: "url" }, { key: "infringing_url", label: "Public URL of the flagged image", required: false, type: "url" }, { key: "recipient_email", label: "Recipient email (optional)", required: false, type: "email" }] as const).map(field => <label className="portalField" key={field.key}><span className="portalFieldLabel">{field.label}</span><input required={field.required} type={"type" in field ? field.type : "text"} disabled={draftBusy} value={draftForm[field.key]} onChange={e => { setDraftForm({ ...draftForm, [field.key]: e.target.value }); setDraft(null); setDraftReadyForEmail(false); }} /></label>)}
                <label className="portalField adminFull"><span className="portalFieldLabel">Evidence summary</span><textarea required rows={4} disabled={draftBusy} maxLength={4000} value={draftForm.evidence_summary} onChange={e => { setDraftForm({ ...draftForm, evidence_summary: e.target.value }); setDraft(null); setDraftReadyForEmail(false); }} /></label><div className="adminFull adminActions"><button className="portalPrimary" type="submit" disabled={draftBusy}><FileText size={16} />{draftBusy ? "Preparing notice…" : "Generate notice"}</button></div>
              </form>
              <Feedback error={draftError} />
              {draft && <div className="adminDraftOutput"><h3>{str(draft.subject)}</h3><p className="adminHint">Saved draft · {str(draft.generation_provider, "template")}{draft.generation_model ? ` · ${draft.generation_model}` : ""}</p><textarea aria-label="Generated takedown notice" readOnly value={str(draft.body)} rows={16} /><label className="adminNoticeReview"><input type="checkbox" checked={noticeReviewed} onChange={e => setNoticeReviewed(e.target.checked)} /><span>I have reviewed the claimant authority, evidence, URLs and notice wording.</span></label><div className="adminActions"><button className="portalSecondary" type="button" onClick={async () => { try { await navigator.clipboard.writeText(`${draft.subject}\n\n${draft.body}`); setCopied(true); } catch { setDraftError("Select the draft text to copy it."); } }}>{copied ? "Copied" : "Copy draft"}</button><button className="portalPrimary" type="button" disabled={!emailReady || deliveryBusy} onClick={() => void openMailto()}>{deliveryBusy ? "Recording handoff…" : "Open notice in email"}<ArrowUpRight size={15} /></button></div><p className="adminHint">{!draftReadyForEmail ? "Saved drafts are read-only here. Generate the notice again after confirming the current URLs to unlock email handoff." : !str(draft.recipient_email, draftForm.recipient_email).trim() ? "Add a recipient email before opening the notice in email." : !publicNoticeReady ? "Add both exact public URLs before opening the notice in email." : "Your mail client opens with the reviewed draft. You choose whether to send it through the recipient’s official channel."}</p></div>}
            </>}
          </div>
        </>}
      </section>}
    </div>

    <div id="admin-panel-monitor" role="tabpanel" aria-labelledby="admin-tab-monitor" hidden={section !== "monitor"}>
      <section id="admin-monitor" className="portalPanel adminPanel" aria-labelledby="monitor-title"><SectionHeading id="monitor-title" title="Marketplace monitoring" description="Choose a source and the registered artist catalog. New photos are saved and scanned; repeat listings stay out of new discoveries."><span className={`adminStatus ${monitoring ? "isLive" : ""}`}><i />{monitoring ? "Monitoring active" : "Monitor paused"}</span></SectionHeading>
        <div className="portalForm adminFormGrid"><MarketplaceSourceSelect value={provider} label="Image source" disabled={monitoring || monitorBusy} onAvailabilityChange={setSourceConfigured} onChange={source => { setProvider(source); setSourceConfigured(null); setNewImages([]); setMonitorError(null); if (source === "ebay" && query === "digital art") setQuery("print"); }} /><label className="portalField"><span className="portalFieldLabel">Search query</span><input maxLength={100} disabled={monitoring || monitorBusy} value={query} onChange={e => setQuery(e.target.value)} /></label><label className="portalField"><span className="portalFieldLabel">Artist catalog</span><input maxLength={120} disabled={monitoring || monitorBusy} value={catalogId} onChange={e => setCatalogId(e.target.value)} /></label><details className="cpDetails adminMonitorOptions"><summary>More options</summary><label className="portalField cpDetailBody"><span className="portalFieldLabel">Intended use</span><input maxLength={160} disabled={monitoring || monitorBusy} value={intendedUse} onChange={e => setIntendedUse(e.target.value)} /></label></details></div>
        <div className="adminActions"><button className="portalPrimary" type="button" disabled={monitoring || monitorBusy || sourceConfigured === false || !query.trim() || !catalogId.trim()} onClick={() => { setMonitorError(null); setMonitoring(true); }}><Play size={15} />Start monitor</button><button className="portalSecondary" type="button" disabled={!monitoring} onClick={() => setMonitoring(false)}><Pause size={15} />Pause monitor</button><span className="adminMonitorTiming">{monitorBusy ? "Checking and scanning new photos…" : lastChecked ? `Last checked ${dateLabel(lastChecked)}` : "First check after one minute. Monitoring continues while this page is open."}</span></div><Feedback error={monitorError} />
      </section>
      <section className="portalPanel adminPanel"><SectionHeading title="Latest discoveries" description={`${newImages.length} new photos · ${duplicates} repeat listings already saved`} />{newImages.length ? <div className="adminImageGrid">{newImages.map(asset => <AssetCard key={asset.id} asset={asset} onSelect={selectAsset} />)}</div> : <EmptyState icon="images" title="No new discoveries yet">The next completed check will show new photos here. Previously saved photos remain in History.</EmptyState>}</section>
    </div>

    <div id="admin-panel-history" role="tabpanel" aria-labelledby="admin-tab-history" hidden={section !== "history"}>
      <section className="portalPanel adminPanel"><SectionHeading title="Saved source history" description="Every observed source image is kept here. Choose a scanned photo to open its review workspace." /><div className="adminHistoryFilters" role="group" aria-label="Saved image filter">{[{ value: "all", label: "All photos" }, { value: "COPIED", label: "Artwork matches" }, { value: "AI_GENERATED_VERSION", label: "Matches with AI indicators" }].map(filter => <button type="button" key={filter.value} aria-pressed={historyFilter === filter.value} onClick={() => setHistoryFilter(filter.value)}>{filter.label}</button>)}</div>{visibleHistory.length ? <div className="adminImageGrid">{visibleHistory.map(asset => <AssetCard key={asset.id} asset={asset} onSelect={selectAsset} />)}</div> : <EmptyState icon="images" title="No saved photos in this view">Source photos appear after a monitoring check. Your stored flags remain in the Review inbox.</EmptyState>}{historyMoreAvailable && <button className="portalSecondary adminLoadMore" type="button" disabled={historyLoading} onClick={() => void loadMoreHistory()}>{historyLoading ? "Loading older history…" : "Load older history"}</button>}</section>
    </div>
  </div>;
}

function SectionHeading({ id, title, description, children }: { id?: string; title: string; description?: string; children?: ReactNode }) { return <><header className="adminSectionHead"><h2 id={id}>{title}</h2>{children}</header>{description && <p className="adminSectionSummary">{description}</p>}</>; }
function EmptyState({ icon, title, children }: { icon: "inbox" | "images"; title: string; children: ReactNode }) { const Icon = icon === "inbox" ? Inbox : Images; return <div className="adminEmpty"><span className="adminEmptyIcon"><Icon size={22} /></span><b>{title}</b><p>{children}</p></div>; }
function Fact({ label, value }: { label: string; value: string }) { return <div><dt>{label}</dt><dd>{value}</dd></div>; }
function QueueThumbnail({ item }: { item: InboxItem }) { const [failed, setFailed] = useState(false); const src = item.asset?.thumbnail_url || item.asset?.image_url || (item.detection?.candidate_media_status === "available" ? mediaProxyPath(item.detection.candidate_media_url) : ""); return <span className="adminQueueThumbnail">{src && !failed ? <img src={src} alt="" loading="lazy" onError={() => setFailed(true)} /> : <ScanSearch size={23} />}</span>; }
function AssetCard({ asset, onSelect }: { asset: Json; onSelect: (asset: Json) => void }) { const [failed, setFailed] = useState(false); return <button type="button" className="adminAssetCard" onClick={() => onSelect(asset)}>{failed ? <span className="adminAssetMissing"><Images size={24} />Preview unavailable</span> : <img src={String(asset.thumbnail_url || asset.image_url)} alt="" loading="lazy" onError={() => setFailed(true)} />}<span><b>{String(asset.title || "Observed image")}</b><small>{marketplaceLabel(String(asset.provider), asset.metadata?.environment)} · {asset.provider === "ebay" ? "Seller " : ""}{String(asset.creator || "Not supplied")}</small><small>{String(asset.classification || "UNCLASSIFIED").replaceAll("_", " ").toLowerCase()}</small></span></button>; }
function ComparisonImage({ label, src, missing = "The submitted image is no longer retained. Its saved evidence is still available." }: { label: string; src: string; missing?: string }) { const [failed, setFailed] = useState<string | null>(null); return <figure className="adminComparisonFigure"><figcaption>{label}</figcaption>{src && failed !== src ? <img src={src} alt={label} onError={() => setFailed(src)} /> : <div className="adminComparisonMissing"><span>{missing}</span></div>}</figure>; }
