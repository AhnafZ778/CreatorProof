"use client";

import { useRef, useState } from "react";
import MarketplaceSourceSelect from "./MarketplaceSourceSelect";
import { marketplaceLabel, type MarketplaceName } from "../lib/marketplaces";
import { errorMessage } from "../lib/phase1";
import { useContextFromForm } from "../lib/phase1Contract";
import NoticeCountryField from "./NoticeCountryField";
import UseContextFields from "./UseContextFields";

type Candidate = {
  observation_id: string;
  provider: MarketplaceName;
  external_id: string;
  title: string;
  source_url: string;
  image_url: string;
  thumbnail_url?: string | null;
  creator?: string | null;
  metadata?: { environment?: string; item_location_country?: string | null };
};

type Props = {
  disabled?: boolean;
  defaultCatalogId: string;
  onScanAccepted: (body: { scan: Record<string, unknown>; selected: Candidate }) => void;
};

export default function MarketplaceMonitorPanel({
  disabled = false,
  defaultCatalogId,
  onScanAccepted,
}: Props) {
  const [provider, setProvider] = useState<MarketplaceName>("pixabay");
  const [sourceConfigured, setSourceConfigured] = useState<boolean | null>(null);
  const [query, setQuery] = useState("painting");
  const [catalogId, setCatalogId] = useState(defaultCatalogId);
  const [intendedUse, setIntendedUse] = useState("marketplace-monitoring");
  const [countryCode, setCountryCode] = useState("");
  const contextForm = useRef<HTMLFormElement>(null);
  const [results, setResults] = useState<Candidate[]>([]);
  const [busy, setBusy] = useState(false);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  async function search() {
    setBusy(true);
    setMessage(null);
    try {
      const response = await fetch("/api/marketplaces/search", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ provider, query, per_page: 9 }),
      });
      const body = (await response.json()) as { results?: Candidate[]; detail?: unknown };
      if (!response.ok) throw new Error(errorMessage(body, "Provider search failed."));
      setResults(body.results ?? []);
      if (!body.results?.length) setMessage(provider === "ebay"
        ? "No listings with usable photos were returned. Sandbox inventory is limited; try “print” or publish a sandbox listing with your test artwork."
        : "No images were returned for that search.");
    } catch (caught) {
      setResults([]);
      setMessage(caught instanceof Error ? caught.message : "Provider search failed.");
    } finally {
      setBusy(false);
    }
  }

  async function scan(candidate: Candidate) {
    if (contextForm.current && !contextForm.current.reportValidity()) return;
    setSelectedId(candidate.observation_id);
    setMessage(null);
    try {
      const context = contextForm.current ? useContextFromForm(new FormData(contextForm.current)) : {};
      const response = await fetch("/api/marketplaces/scan", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          observation_id: candidate.observation_id,
          catalog_id: catalogId,
          intended_use: intendedUse,
          ...(countryCode ? { country_code: countryCode } : {}),
          ...(Object.keys(context).length ? { use_context: context } : {}),
        }),
      });
      const body = (await response.json()) as { scan?: Record<string, unknown>; detail?: unknown };
      if (!response.ok || !body.scan) {
        throw new Error(errorMessage(body, "Marketplace scan failed."));
      }
      onScanAccepted({ scan: body.scan, selected: candidate });
    } catch (caught) {
      setMessage(caught instanceof Error ? caught.message : "Marketplace scan failed.");
    } finally {
      setSelectedId(null);
    }
  }

  return (
    <section className="card marketplaceMonitor" aria-label="Marketplace monitor">
      <div className="cardHeading">
        <span>03</span>
        <div>
          <small>MARKETPLACE MONITOR</small>
          <h3>Search images and marketplace listings</h3>
        </div>
      </div>
      <p className="cardSummary">
        Search a source, then choose an image to check. Its listing URL and source details are preserved with the scan for Admin review if flagged.
      </p>
      <div className="marketplaceControls">
        <MarketplaceSourceSelect value={provider} disabled={disabled || busy || selectedId !== null} onAvailabilityChange={setSourceConfigured} onChange={(source) => {
          setProvider(source); setSourceConfigured(null); setResults([]); setMessage(null);
          if (source === "ebay" && query === "painting") setQuery("print");
        }} />
        <label className="portalField">
          <span className="portalFieldLabel">Search</span>
          <input value={query} onChange={(event) => setQuery(event.target.value)} maxLength={100} disabled={disabled || busy || selectedId !== null} />
        </label>
        <label className="portalField">
          <span className="portalFieldLabel">Catalog</span>
          <input value={catalogId} onChange={(event) => setCatalogId(event.target.value)} maxLength={120} disabled={disabled || selectedId !== null} />
        </label>
        <label className="portalField">
          <span className="portalFieldLabel">Intended use</span>
          <input value={intendedUse} onChange={(event) => setIntendedUse(event.target.value)} maxLength={160} disabled={disabled || selectedId !== null} />
        </label>
      </div>
      <button type="button" className="marketplaceSearch" onClick={() => void search()} disabled={disabled || busy || selectedId !== null || sourceConfigured === false || !query.trim() || !catalogId.trim()}>
        {busy ? "Searching…" : "Search source"}
      </button>
      <details className="cpSourceScanContext">
        <summary>Country and intended-use details <small>(optional)</small></summary>
        <form className="cpFormGrid" ref={contextForm} onSubmit={(event) => event.preventDefault()}>
          <NoticeCountryField value={countryCode} onChange={setCountryCode} disabled={disabled || selectedId !== null} />
          <UseContextFields disabled={disabled || selectedId !== null} />
        </form>
      </details>
      {message && <p className="marketplaceMessage" role="status">{message}</p>}
      {results.length > 0 && (
        <div className="marketplaceResults">
          {results.map((candidate) => (
            <article className="marketplaceResult" key={candidate.observation_id}>
              <img src={candidate.thumbnail_url ?? candidate.image_url} alt="" loading="lazy" />
              <div>
                <strong>{candidate.title}</strong>
                <small>{marketplaceLabel(candidate.provider, candidate.metadata?.environment)}</small>
                {candidate.creator && <small>{candidate.provider === "ebay" ? "Seller" : "By"} {candidate.creator}</small>}
                <a href={candidate.source_url} target="_blank" rel="noreferrer">Open source</a>
                <button type="button" onClick={() => void scan(candidate)} disabled={disabled || busy || selectedId !== null || !catalogId.trim() || !intendedUse.trim()}>
                  {selectedId === candidate.observation_id ? "Sending to scan…" : "Scan this image"}
                </button>
              </div>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}
