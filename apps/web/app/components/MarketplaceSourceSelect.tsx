"use client";

import { useEffect, useId, useState } from "react";
import { marketplaceDescription, marketplaceLabel, type MarketplaceName, type MarketplaceProvider } from "../lib/marketplaces";

export default function MarketplaceSourceSelect({ value, onChange, disabled, label = "Source", onAvailabilityChange }: {
  value: MarketplaceName;
  onChange: (value: MarketplaceName) => void;
  disabled?: boolean;
  label?: string;
  onAvailabilityChange?: (configured: boolean | null) => void;
}) {
  const [sources, setSources] = useState<MarketplaceProvider[]>([]);
  const [statusError, setStatusError] = useState(false);
  const descriptionId = useId();
  useEffect(() => {
    const controller = new AbortController();
    void fetch("/api/marketplaces/providers", { cache: "no-store", signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) throw new Error("Configuration unavailable");
        const body: unknown = await response.json();
        if (!Array.isArray(body)) throw new Error("Configuration unavailable");
        setSources(body.filter((item): item is MarketplaceProvider =>
          item && ["ebay", "pixabay", "unsplash"].includes(item.provider)
          && typeof item.configured === "boolean" && ["sandbox", "production"].includes(item.environment)));
      })
      .catch(() => { if (!controller.signal.aborted) setStatusError(true); });
    return () => controller.abort();
  }, []);
  const selected = sources.find((source) => source.provider === value);
  useEffect(() => { onAvailabilityChange?.(selected?.configured ?? null); }, [selected, onAvailabilityChange]);
  return (
    <label className="portalField marketplaceSourceField">
      <span className="portalFieldLabel" id={`${descriptionId}-label`}>{label}</span>
      <select value={value} disabled={disabled} onChange={(event) => onChange(event.target.value as MarketplaceName)} aria-labelledby={`${descriptionId}-label`} aria-describedby={descriptionId}>
        {(["pixabay", "unsplash", "ebay"] as const).map((provider) => {
          const source = sources.find((entry) => entry.provider === provider);
          return <option key={provider} value={provider}>{marketplaceLabel(provider, source?.environment)}{source?.configured === false ? " · Not configured" : ""}</option>;
        })}
      </select>
      <small id={descriptionId} className={`marketplaceSourceHint ${selected?.environment === "sandbox" ? "isSandbox" : ""}`}>
        {selected ? marketplaceDescription(selected) : statusError ? "Source configuration is unavailable. Searching will verify access." : "Reading source configuration…"}
      </small>
    </label>
  );
}
