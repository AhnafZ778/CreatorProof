"use client";
import { useState, type ReactNode } from "react";
import { Check, Copy, LoaderCircle, RefreshCw } from "lucide-react";
import { readable } from "@/app/lib/phase1";

export function Status({ value }: { value: unknown }) {
  const state = String(value || "UNKNOWN");
  const tone = /^(?:SUPPORTED|VALID|ALLOW|ACTIVE|COMPLETED|ACCEPTED|PASS_BY_POLICY)$/.test(state) ? "good" : /^(?:DENY|REVOKED|INVALID|REJECTED|ERROR|FAILED|BLOCK_BY_POLICY|INTEGRITY_MISMATCH)$/.test(state) ? "bad" : /REVIEW|INCONCLUSIVE|CONTRADICTORY|UNAVAILABLE|INSUFFICIENT|PARTIALLY|LICENSE_REQUIRED|UNTRUSTED/.test(state) ? "review" : "neutral";
  const label = state === "UNKNOWN" ? "Not specified" : state === "PASS_BY_POLICY" ? "Pass by policy" : readable(state);
  return <span className="cpStatus" data-tone={tone}><i aria-hidden="true" />{label}</span>;
}
export function PanelHeading({ eyebrow, title, description, children }: { eyebrow: string; title: string; description?: string; children?: ReactNode }) {
  return <><header className="cpPanelHeading"><div><small>{eyebrow}</small><h2>{title}</h2></div>{children}</header>{description && <p className="cpDescription">{description}</p>}</>;
}
export function Feedback({ error, message }: { error?: string | null; message?: string | null }) {
  return <>{error && <p className="cpFeedback isError" role="alert">{error}</p>}{message && <p className="cpFeedback" role="status">{message}</p>}</>;
}
export function Loading({ label = "Loading saved records…" }: { label?: string }) { return <div className="cpLoading" role="status"><LoaderCircle size={18} className="cpSpin" />{label}</div>; }
export function RefreshButton({ onClick, busy = false }: { onClick: () => void; busy?: boolean }) { return <button type="button" className="cpIconButton" onClick={onClick} disabled={busy} aria-label="Refresh saved records"><RefreshCw size={16} className={busy ? "cpSpin" : ""} /></button>; }
export function Hash({ value, label = "Record hash" }: { value: unknown; label?: string }) {
  const hash = typeof value === "string" ? value : "";
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState(false);
  if (!hash) return null;
  return <div className="cpHash"><span>{label}</span><code title={hash}>{hash}</code><button type="button" className="cpIconButton" aria-label={`Copy ${label.toLowerCase()}`} onClick={async () => { try { await navigator.clipboard.writeText(hash); setCopied(true); setError(false); setTimeout(() => setCopied(false), 2000); } catch { setError(true); } }}>{copied ? <Check size={14} /> : <Copy size={14} />}</button>{error && <small role="alert">Select the hash to copy it.</small>}</div>;
}
