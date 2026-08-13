"use client";

import Link from "next/link";
import { FormEvent, Suspense, useEffect, useMemo, useState } from "react";

import PortalFileField from "@/app/components/PortalFileField";
import PortalNav from "@/app/components/PortalNav";
import { readPortalSession } from "@/app/lib/portalSession";

type RegisteredWork = {
  id: string;
  title: string;
  claimant: string;
  claimState: string;
  catalogId: string;
  createdAt: string;
};

/** The API's code for a file the enrollment AI-origin gate refused. */
const ORIGIN_REFUSAL_CODE = "WORK_REGISTRATION_REFUSED_AI_ORIGIN";

type OriginRefusal = {
  message: string;
  headline: string;
  summary: string;
  originState: string;
  classification: string;
  evidenceTier: string;
  boundary: string;
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function text(value: unknown, fallback = ""): string {
  return typeof value === "string" && value.trim() ? value : fallback;
}

/**
 * A refusal arrives as a structured `detail`, unlike the plain-string details
 * the rest of the endpoint returns, because it has to be shown as its own
 * outcome rather than as a red line of error text.
 */
function readOriginRefusal(detail: unknown): OriginRefusal | null {
  if (!isRecord(detail) || detail.code !== ORIGIN_REFUSAL_CODE) return null;
  return {
    message: text(detail.message, "This file was not added to the protected-work catalog."),
    headline: text(detail.headline, "AI-generation indicators were found"),
    summary: text(detail.summary),
    originState: text(detail.origin_state, "UNKNOWN"),
    classification: text(detail.classification, "UNKNOWN"),
    evidenceTier: text(detail.evidence_tier, "UNKNOWN"),
    boundary: text(detail.boundary),
  };
}

function registrationFault(body: Record<string, unknown>): string {
  if (body.error_code === "BACKEND_UNREACHABLE") {
    return "The CreatorProof API is not running on port 8000. From apps/api, start it with `uv run uvicorn app.main:app --host 127.0.0.1 --port 8000`, then try again.";
  }
  if (body.error_code === "BACKEND_TIMEOUT") {
    return "The API did not finish screening this file in time. Confirm the API is still running, then try again.";
  }
  const detail = body.detail;
  if (typeof detail === "string" && detail.trim()) return detail;
  if (isRecord(detail) && typeof detail.message === "string" && detail.message.trim()) {
    return detail.message;
  }
  return "Registration failed";
}

const LIBRARY_KEY = "creatorproof.artist.library";

function loadLibrary(): RegisteredWork[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(LIBRARY_KEY);
    return raw ? (JSON.parse(raw) as RegisteredWork[]) : [];
  } catch {
    return [];
  }
}

function saveLibrary(works: RegisteredWork[]) {
  window.localStorage.setItem(LIBRARY_KEY, JSON.stringify(works));
}

export default function ArtistPortalPage() {
  return (
    <Suspense fallback={<div className="portalPage isArtist" />}>
      <ArtistPortal />
    </Suspense>
  );
}

function ArtistPortal() {
  const [name, setName] = useState("Artist");
  const [library, setLibrary] = useState<RegisteredWork[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [refusal, setRefusal] = useState<OriginRefusal | null>(null);
  const [fileKey, setFileKey] = useState(0);
  const [libraryExpanded, setLibraryExpanded] = useState(false);

  useEffect(() => {
    const session = readPortalSession();
    if (session?.name) setName(session.name);
    setLibrary(loadLibrary());
  }, []);

  const profileReady = library.length >= 3;
  const assertedCount = useMemo(
    () => library.filter((work) => work.claimState === "ASSERTED").length,
    [library],
  );
  const libraryPreviewCount = 4;
  const libraryCanCollapse = library.length > libraryPreviewCount;
  const visibleLibrary =
    libraryExpanded || !libraryCanCollapse ? library : library.slice(0, libraryPreviewCount);
  const peekLibraryWork =
    !libraryExpanded && libraryCanCollapse ? library[libraryPreviewCount] ?? null : null;

  async function onRegister(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const formElement = event.currentTarget;
    setBusy(true);
    setError(null);
    setMessage(null);
    setRefusal(null);
    const form = new FormData(formElement);
    if (!form.get("claimant")) form.set("claimant", name);
    if (!form.get("catalog_id")) form.set("catalog_id", "artist-library");
    if (!form.get("claim_state")) form.set("claim_state", "ASSERTED");
    try {
      const response = await fetch("/api/works", { method: "POST", body: form });
      const body = (await response.json()) as Record<string, unknown>;
      if (!response.ok) {
        // A refusal is a result, not a fault: the form keeps what the artist
        // entered so they can swap the file rather than fill it all in again.
        const refused = readOriginRefusal(body.detail);
        if (refused) {
          setRefusal(refused);
          return;
        }
        throw new Error(registrationFault(body));
      }
      const entry: RegisteredWork = {
        id: String(body.id ?? crypto.randomUUID()),
        title: String(form.get("title") || "Untitled work"),
        claimant: String(form.get("claimant") || name),
        claimState: String(form.get("claim_state") || "ASSERTED"),
        catalogId: String(form.get("catalog_id") || "artist-library"),
        createdAt: new Date().toISOString(),
      };
      const next = [entry, ...library];
      setLibrary(next);
      saveLibrary(next);
      setMessage("Work registered and added to your artist library.");
      formElement.reset();
      setFileKey((value) => value + 1);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Registration failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="portalPage isArtist">
      <PortalNav active="artist" />
      <main className="portalMain">
        <section className="portalHero">
          <div className="portalHeroKicker">Artist portal</div>
          <h1>Protect your work before it circulates.</h1>
          <p>
            Register references, assert authorship, and build a consent-backed creator profile.
            Teams checking assets before publish use the User portal — your works stay yours.
          </p>
          <div className="portalHeroActions">
            <a className="portalPrimary" href="#register">
              Register a work
            </a>
            <Link className="portalSecondary" href="/user">
              Switch to User portal
            </Link>
          </div>
        </section>

        <section className="portalGrid" aria-label="Artist status">
          <article className="portalCard">
            <h3>Work library</h3>
            <div className="portalStat">{library.length}</div>
            <p>Registered references in this browser session.</p>
          </article>
          <article className="portalCard">
            <h3>Creator profile</h3>
            <div className="portalStat">{profileReady ? "Ready" : `${library.length}/3`}</div>
            <p>
              {profileReady
                ? "Enough works for a multi-work creator profile."
                : "Add at least 3 representative works for a stronger profile."}
            </p>
          </article>
          <article className="portalCard">
            <h3>Asserted claims</h3>
            <div className="portalStat">{assertedCount}</div>
            <p>Claims waiting for operator corroboration when needed.</p>
          </article>
        </section>

        <section id="register" className="portalPanel">
          <header>
            <div>
              <small>Enrollment</small>
              <h2>Register protected work</h2>
            </div>
          </header>
          <p className="originGateNotice">
            <span className="originGateNoticeMark" aria-hidden="true">
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10Z" />
                <path d="m9 12 2 2 4-4" />
              </svg>
            </span>
            <span>
              <b>Every submission is screened for AI generation.</b> A file the origin lane
              identifies as AI-generated is refused, so this catalog only ever vouches for work
              a person made.
            </span>
          </p>
          <form className="portalForm" onSubmit={onRegister}>
            <PortalFileField
              key={fileKey}
              required
              name="file"
              label="Reference image"
              hint="PNG, JPG, or WEBP — used as your protected reference"
            />
            <label className="portalField">
              <span className="portalFieldLabel">Title</span>
              <input required name="title" defaultValue="Untitled work" />
            </label>
            <label className="portalField">
              <span className="portalFieldLabel">Artist / claimant name</span>
              <input required name="claimant" defaultValue={name} />
            </label>
            <label className="portalField">
              <span className="portalFieldLabel">Catalog</span>
              <input required name="catalog_id" defaultValue="artist-library" />
            </label>
            <label className="portalField">
              <span className="portalFieldLabel">Claim state</span>
              <select name="claim_state" defaultValue="ASSERTED">
                <option value="ASSERTED">ASSERTED — artist-recorded</option>
                <option value="CORROBORATED">CORROBORATED — verified record</option>
                <option value="DISPUTED">DISPUTED — active review</option>
                <option value="REVOKED">REVOKED — withdrawn</option>
              </select>
            </label>
            <button className="portalPrimary" disabled={busy} type="submit">
              {busy ? "Screening for AI origin…" : "Register reference"}
            </button>
          </form>
          {refusal && (
            <section className="originRefusal" role="alert" aria-label="Registration refused">
              <div className="originRefusalHead">
                <span className="originRefusalTag">Not registered</span>
                <b>{refusal.headline}</b>
              </div>
              <p className="originRefusalLead">{refusal.message}</p>
              {refusal.summary && <p className="originRefusalBody">{refusal.summary}</p>}
              <dl className="originRefusalFacts">
                <div>
                  <dt>Origin state</dt>
                  <dd>{refusal.originState}</dd>
                </div>
                <div>
                  <dt>Classification</dt>
                  <dd>{refusal.classification}</dd>
                </div>
                <div>
                  <dt>Evidence tier</dt>
                  <dd>{refusal.evidenceTier}</dd>
                </div>
              </dl>
              {refusal.boundary && <p className="originRefusalBoundary">{refusal.boundary}</p>}
            </section>
          )}
          {message && <p className="portalMuted">{message}</p>}
          {error && (
            <p className="error" role="alert">
              {error}
            </p>
          )}
        </section>

        <section className="portalPanel" aria-label="Artist library">
          <header>
            <div>
              <small>Library</small>
              <h2>My registered works</h2>
            </div>
          </header>
          {library.length === 0 ? (
            <p className="portalMuted">No works yet. Register your first reference above.</p>
          ) : (
            <div
              className={`portalLibraryStack${libraryExpanded || !libraryCanCollapse ? " isExpanded" : " isCollapsed"}`}
            >
              <ul className="portalList">
                {visibleLibrary.map((work) => (
                  <li key={work.id}>
                    <div>
                      <b>{work.title}</b>
                      <span>
                        {work.claimant} · {work.catalogId} ·{" "}
                        {new Date(work.createdAt).toLocaleString()}
                      </span>
                    </div>
                    <span className="portalBadge" data-state={work.claimState}>
                      {work.claimState}
                    </span>
                  </li>
                ))}
                {peekLibraryWork && (
                  <li className="portalListPeek" aria-hidden="true">
                    <div>
                      <b>{peekLibraryWork.title}</b>
                      <span>
                        {peekLibraryWork.claimant} · {peekLibraryWork.catalogId} ·{" "}
                        {new Date(peekLibraryWork.createdAt).toLocaleString()}
                      </span>
                    </div>
                    <span className="portalBadge" data-state={peekLibraryWork.claimState}>
                      {peekLibraryWork.claimState}
                    </span>
                  </li>
                )}
              </ul>
              {libraryCanCollapse && (
                <button
                  type="button"
                  className="portalLibraryToggle"
                  aria-expanded={libraryExpanded}
                  onClick={() => setLibraryExpanded((open) => !open)}
                >
                  <span>
                    {libraryExpanded
                      ? "Show less"
                      : `Show full history (${library.length - libraryPreviewCount} more)`}
                  </span>
                  <svg
                    className={libraryExpanded ? "isUp" : undefined}
                    width="16"
                    height="16"
                    viewBox="0 0 16 16"
                    fill="none"
                    aria-hidden="true"
                  >
                    <path
                      d="M4 6l4 4 4-4"
                      stroke="currentColor"
                      strokeWidth="1.5"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    />
                  </svg>
                </button>
              )}
            </div>
          )}
        </section>

        <section className="portalGrid">
          <article className="portalCard">
            <h3>Proofs & receipts</h3>
            <p>
              After teams scan against your catalog, verification packages remain independently
              checkable from the User portal proof tools.
            </p>
            <div className="portalHeroActions">
              <Link className="portalSecondary" href="/user#proof">
                Open User proof tools
              </Link>
            </div>
          </article>
          <article className="portalCard">
            <h3>Match review</h3>
            <p>
              When a User-portal scan cites your work or profile, reviewers inspect evidence there —
              without giving away org admin controls on this Artist portal.
            </p>
            <div className="portalHeroActions">
              <Link className="portalSecondary" href="/user#scan-work">
                Open User scan desk
              </Link>
            </div>
          </article>
          <article className="portalCard">
            <h3>Boundary</h3>
            <p>
              CreatorProof returns evidence and policy outcomes. It is not a legal infringement
              determination or automatic clearance.
            </p>
          </article>
        </section>
      </main>
    </div>
  );
}
