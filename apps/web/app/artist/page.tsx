"use client";

import Link from "next/link";
import { FormEvent, Suspense, useEffect, useRef, useState, type KeyboardEvent } from "react";
import { ArrowRight, Images, LoaderCircle, Plus, Search, ShieldCheck, SlidersHorizontal } from "lucide-react";

import ArtistWorkspace from "@/app/components/ArtistWorkspace";
import ArtworkThumbnail from "@/app/components/ArtworkThumbnail";
import ArtistArtworkUpload from "@/app/components/ArtistArtworkUpload";
import PortalNav from "@/app/components/PortalNav";
import { dateLabel } from "@/app/lib/phase1";
import { DEFAULT_CATALOG_ID } from "@/app/lib/catalog";
import { readPortalSession } from "@/app/lib/portalSession";
import { submitImageForm } from "@/app/lib/uploadClient";
import "@/app/styles/artist-workspace.css";

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
const SECTIONS = [
  { key: "library", label: "Artwork library", Icon: Images },
  { key: "register", label: "Register artwork", Icon: Plus },
] as const;

const CLAIM_LABELS: Record<string, string> = {
  ASSERTED: "Artist-recorded",
  CORROBORATED: "Supporting record declared",
  DISPUTED: "Under review",
  REVOKED: "Withdrawn",
};

function loadLibrary(): RegisteredWork[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(LIBRARY_KEY);
    const parsed: unknown = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? parsed.filter((work): work is RegisteredWork => isRecord(work) && typeof work.id === "string" && typeof work.title === "string" && typeof work.catalogId === "string") : [];
  } catch {
    return [];
  }
}

function saveLibrary(works: RegisteredWork[]) {
  try { window.localStorage.setItem(LIBRARY_KEY, JSON.stringify(works)); } catch { /* The server remains the source of truth when browser storage is unavailable. */ }
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
  const [section, setSection] = useState<(typeof SECTIONS)[number]["key"]>("library");
  const [libraryQuery, setLibraryQuery] = useState("");
  const [visibleCount, setVisibleCount] = useState(8);
  const [selectedWorkId, setSelectedWorkId] = useState<string | null>(null);
  const [libraryLoading, setLibraryLoading] = useState(true);
  const [libraryError, setLibraryError] = useState<string | null>(null);
  const pageTabs = useRef<Array<HTMLButtonElement | null>>([]);
  const libraryRequest = useRef(0);

  async function refreshLibrary(signal?: AbortSignal) {
    const requestId = ++libraryRequest.current;
    setLibraryLoading(true); setLibraryError(null);
    try {
      const response = await fetch("/api/works", { cache: "no-store", signal });
      const body: unknown = await response.json();
      if (!response.ok || !Array.isArray(body)) throw new Error("The saved library could not be loaded. Cached references may be out of date.");
      const works = body.filter(isRecord).filter((work) => typeof work.id === "string").map((work) => ({ id: String(work.id), title: text(work.title, "Untitled work"), claimant: text(work.claimant, "Claimant not recorded"), claimState: text(work.claim_state, "ASSERTED"), catalogId: text(work.catalog_id, DEFAULT_CATALOG_ID), createdAt: text(work.created_at) }));
      if (signal?.aborted || requestId !== libraryRequest.current) return;
      setLibrary(works); saveLibrary(works); setSelectedWorkId((old) => works.some((work) => work.id === old) ? old : works[0]?.id || null);
    } catch (e) { if (!signal?.aborted && requestId === libraryRequest.current) setLibraryError(e instanceof Error ? e.message : "Could not load your saved library."); }
    finally { if (!signal?.aborted && requestId === libraryRequest.current) setLibraryLoading(false); }
  }

  useEffect(() => {
    const session = readPortalSession();
    if (session?.name) setName(session.name);
    const cached = loadLibrary();
    setLibrary(cached); setSelectedWorkId(cached[0]?.id || null);
    const controller = new AbortController();
    const syncSectionFromHash = () => {
      if (window.location.hash === "#register") setSection("register");
      else if (window.location.hash === "#library") setSection("library");
    };
    syncSectionFromHash();
    window.addEventListener("hashchange", syncSectionFromHash);
    void refreshLibrary(controller.signal);
    return () => {
      controller.abort();
      window.removeEventListener("hashchange", syncSectionFromHash);
    };
  }, []);

  const selectedWork = library.find((work) => work.id === selectedWorkId);
  const matchingLibrary = library.filter((work) =>
    `${work.title} ${work.claimant}`.toLocaleLowerCase().includes(libraryQuery.trim().toLocaleLowerCase()),
  );
  const visibleLibrary = matchingLibrary.slice(0, visibleCount);

  function navigateSection(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    const next = event.key === "ArrowRight" ? (index + 1) % SECTIONS.length
      : event.key === "ArrowLeft" ? (index + SECTIONS.length - 1) % SECTIONS.length
      : event.key === "Home" ? 0 : event.key === "End" ? SECTIONS.length - 1 : -1;
    if (next < 0) return;
    event.preventDefault();
    setSection(SECTIONS[next].key);
    pageTabs.current[next]?.focus();
  }

  async function onRegister(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const formElement = event.currentTarget;
    setBusy(true);
    setError(null);
    setMessage(null);
    setRefusal(null);
    const form = new FormData(formElement);
    if (!form.get("claimant")) form.set("claimant", name);
    if (!form.get("catalog_id")) form.set("catalog_id", DEFAULT_CATALOG_ID);
    if (!form.get("claim_state")) form.set("claim_state", "ASSERTED");
    try {
      const response = await submitImageForm({
        endpoint: "/api/works",
        purpose: "work",
        form,
      });
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
      if (typeof body.id !== "string") throw new Error("The registration response did not identify a saved artwork. Refresh the library before retrying.");
      const entry: RegisteredWork = {
        id: body.id,
        title: String(form.get("title") || "Untitled work"),
        claimant: String(form.get("claimant") || name),
        claimState: String(form.get("claim_state") || "ASSERTED"),
        catalogId: String(form.get("catalog_id") || DEFAULT_CATALOG_ID),
        createdAt: new Date().toISOString(),
      };
      // A library request begun before this registration must not replace it
      // with an older server snapshot after enrollment has completed.
      libraryRequest.current += 1;
      setLibraryLoading(false);
      setLibrary((old) => {
        const next = [entry, ...old.filter((work) => work.id !== entry.id)];
        saveLibrary(next);
        return next;
      });
      setSelectedWorkId(entry.id);
      setLibraryQuery("");
      setSection("library");
      pageTabs.current[0]?.focus();
      setMessage(`“${entry.title}” registered. Set its permissions below; new artwork starts with unspecified permissions.`);
      formElement.reset();
      setFileKey((value) => value + 1);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Registration failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="portalPage isArtist artistDesk">
      <PortalNav active="artist" />
      <main className="portalMain">
        <section className="portalHero artistHero">
          <div>
            <div className="portalHeroKicker">Artist workspace</div>
            <h1>Your artwork, in one place.</h1>
            <p>Register your art, set its permissions, and keep a record of how you made it.</p>
          </div>
          <div className="artistHeroAside">
            <span><b>{library.length}</b> registered {library.length === 1 ? "artwork" : "artworks"}</span>
            <Link className="cpTextButton" href="/pipeline">How protection works <ArrowRight size={15} /></Link>
          </div>
        </section>

        <div className="artistSectionTabs" role="tablist" aria-label="Artist sections">
          {SECTIONS.map(({ key, label, Icon }, index) => (
            <button
              key={key}
              type="button"
              role="tab"
              id={`artist-tab-${key}`}
              aria-selected={section === key}
              aria-controls={`artist-panel-${key}`}
              tabIndex={section === key ? 0 : -1}
              ref={(element) => { pageTabs.current[index] = element; }}
              onClick={() => setSection(key)}
              onKeyDown={(event) => navigateSection(event, index)}
            >
              <Icon size={17} aria-hidden="true" />{label}
              {key === "library" && <span className="artistTabCount">{library.length}</span>}
            </button>
          ))}
        </div>

        {message && <p className="cpFeedback" role="status">{message}</p>}

        <div
          role="tabpanel"
          id="artist-panel-library"
          aria-labelledby="artist-tab-library"
          hidden={section !== "library"}
          className="artistLibraryLayout"
        >
          <section className="portalPanel artistLibrary" aria-label="Artist library" aria-busy={libraryLoading}>
            <header>
              <div><small>Your collection</small><h2>Artwork library</h2></div>
              <button type="button" className="cpTextButton" disabled={libraryLoading} onClick={() => void refreshLibrary()}>
                {libraryLoading ? "Syncing…" : "Refresh"}
              </button>
            </header>
            {libraryError && <p className="cpFeedback isError" role="alert">{libraryError}</p>}
            {library.length > 0 && (
              <label className="artistLibrarySearch">
                <Search size={16} aria-hidden="true" />
                <input aria-label="Find your artwork" type="search" placeholder="Find an artwork…" value={libraryQuery} onChange={(event) => { setLibraryQuery(event.target.value); setVisibleCount(8); }} />
              </label>
            )}
            {libraryLoading && library.length === 0 ? (
              <p className="portalMuted" role="status">Loading your saved artworks…</p>
            ) : library.length === 0 ? (
              <div className="artistLibraryEmpty">
                <Images size={27} aria-hidden="true" />
                <h3>Add your first artwork.</h3>
                <p>Upload a reference image to start your library and set its permissions.</p>
                <button type="button" className="portalPrimary" onClick={() => setSection("register")}><Plus size={16} />Register artwork</button>
              </div>
            ) : (
              <>
                <p className="artistLibraryHint">Choose an artwork to open its tools.</p>
                <ul className="artistWorkList">
                  {visibleLibrary.map((work) => (
                    <li key={work.id}>
                      <button
                        type="button"
                        className={`artistWorkButton${selectedWorkId === work.id ? " isSelected" : ""}`}
                        aria-label={`Open workspace for ${work.title}`}
                        aria-pressed={selectedWorkId === work.id}
                        onClick={() => {
                          setSelectedWorkId(work.id);
                          if (window.matchMedia("(max-width: 760px)").matches) {
                            requestAnimationFrame(() => document.getElementById("artwork-workspace")?.scrollIntoView({ behavior: "smooth", block: "start" }));
                          }
                        }}
                      >
                        <ArtworkThumbnail workId={work.id} title={work.title} />
                        <span className="artistWorkIdentity">
                          <b>{work.title}</b>
                          <span>{work.claimant}</span>
                          <small>{CLAIM_LABELS[work.claimState] || "Claim not recorded"}</small>
                        </span>
                        <ArrowRight size={15} aria-hidden="true" />
                      </button>
                    </li>
                  ))}
                </ul>
                {matchingLibrary.length === 0 && <p className="portalMuted">No artworks match this search.</p>}
                {matchingLibrary.length > visibleCount && <button type="button" className="cpTextButton artistShowMore" onClick={() => setVisibleCount((old) => old + 8)}>Show more ({matchingLibrary.length - visibleCount} remaining)</button>}
                <button type="button" className="portalSecondary artistAddWork" onClick={() => setSection("register")}><Plus size={16} />Register another artwork</button>
              </>
            )}
          </section>
          {selectedWork ? (
            <div className="artistSelectedWork">
              <ArtistWorkspace key={selectedWork.id} workId={selectedWork.id} title={selectedWork.title} />
              <details className="cpDetails artistRecordDetails">
                <summary>Artwork registration details</summary>
                <dl className="cpDetailBody artistRegistrationFacts">
                  <div><dt>Artist / claimant</dt><dd>{selectedWork.claimant}</dd></div>
                  <div><dt>Registered</dt><dd>{dateLabel(selectedWork.createdAt)}</dd></div>
                  <div><dt>Claim</dt><dd>{CLAIM_LABELS[selectedWork.claimState] || selectedWork.claimState}</dd></div>
                  <div><dt>Catalog</dt><dd>{selectedWork.catalogId}</dd></div>
                  <div><dt>Artwork ID</dt><dd>{selectedWork.id}</dd></div>
                </dl>
              </details>
            </div>
          ) : (
            <section id="artwork-workspace" className="portalPanel artistWelcome" aria-label="Artwork tools">
              <span className="artistWelcomeIcon"><ShieldCheck size={29} aria-hidden="true" /></span>
              <h2>Start with your artwork.</h2>
              <p>Once you register an image, its permissions, creation history, origin evidence, and sharing tools will appear here.</p>
              <div className="artistWelcomeSteps">
                <span><b>1</b>Register your reference</span>
                <span><b>2</b>Decide how it may be used</span>
                <span><b>3</b>Keep and share your record</span>
              </div>
              <button type="button" className="portalPrimary" onClick={() => setSection("register")}>Register your first artwork <ArrowRight size={16} /></button>
            </section>
          )}
        </div>

        <section
          id="artist-panel-register"
          role="tabpanel"
          aria-labelledby="artist-tab-register"
          hidden={section !== "register"}
          className="portalPanel artistRegisterPanel"
        >
          <header id="register" className="artistRegisterHeading"><div><small>Add to your library</small><h2>Register your artwork</h2><p>Your original image is the starting point. Add it once, then manage its permissions and creative history.</p></div><span className="artistRegisterMark" aria-hidden="true"><Images size={27} strokeWidth={1.4} /></span></header>
          <form className="portalForm artistRegisterForm" onSubmit={onRegister}>
            <fieldset disabled={busy} className="artistRegisterLayout" aria-label="Artwork registration details">
              <ArtistArtworkUpload key={fileKey} />
              <div className="artistRegisterDetails">
                <div className="artistRegisterStep"><span>02</span>Artwork details</div>
                <label className="portalField"><span className="portalFieldLabel">Artwork title</span><input required name="title" placeholder="Give your artwork a name" autoComplete="off" /></label>
                <div className="portalField"><label className="portalFieldLabel" htmlFor="artist-registration-claimant">Artist / claimant name</label><input id="artist-registration-claimant" required name="claimant" defaultValue={name} autoComplete="name" aria-describedby="artist-claimant-hint" /><small id="artist-claimant-hint" className="portalFieldHint">The name associated with this artwork's record.</small></div>
                <details className="cpDetails artistAdvancedRegistration">
                  <summary><SlidersHorizontal size={15} aria-hidden="true" />Advanced registration settings<span>Optional</span></summary>
                  <div className="cpDetailBody cpFormGrid">
                    <label className="portalField"><span className="portalFieldLabel">Catalog</span><input aria-label="Catalog" aria-describedby="artist-catalog-hint" required name="catalog_id" defaultValue={DEFAULT_CATALOG_ID} /><small id="artist-catalog-hint" className="portalFieldHint">The default catalog works for ordinary registration.</small></label>
                    <label className="portalField"><span className="portalFieldLabel">Claim state</span><select aria-label="Claim state" name="claim_state" defaultValue="ASSERTED"><option value="ASSERTED">Artist-recorded</option><option value="CORROBORATED">Supporting record declared</option><option value="DISPUTED">Under review</option><option value="REVOKED">Withdrawn</option></select><small className="portalFieldHint">Only declare supporting records when you have them available.</small></label>
                  </div>
                </details>
                <div className="artistOriginNotice"><ShieldCheck size={18} aria-hidden="true" /><div><b>Screened before registration</b><p>We check your image for available AI-origin evidence.</p><details><summary>About this check</summary><p>Enrollment policy may refuse a flagged image. A passed screening or missing Content Credentials does not independently establish human authorship or ownership.</p></details></div></div>
              </div>
            </fieldset>
            <div className="artistRegisterFooter"><div><span className="artistRegisterNextIcon"><ShieldCheck size={18} aria-hidden="true" /></span><p><strong>Your record starts here.</strong><span>Set permissions and add your creation history after saving.</span></p></div><button className="portalPrimary" disabled={busy} type="submit">{busy ? <LoaderCircle size={17} className="artistRegisterSpinner" aria-hidden="true" /> : <Plus size={17} aria-hidden="true" />}{busy ? "Checking and registering…" : "Register reference"}{!busy && <ArrowRight size={16} aria-hidden="true" />}</button></div>
          </form>
          {refusal && (
            <section className="originRefusal" role="alert" aria-label="Registration refused">
              <div className="originRefusalHead"><span className="originRefusalTag">Not registered</span><b>{refusal.headline}</b></div>
              <p className="originRefusalLead">{refusal.message}</p>
              {refusal.summary && <p className="originRefusalBody">{refusal.summary}</p>}
              <details className="artistRefusalDetails"><summary>Screening details</summary><dl className="originRefusalFacts"><div><dt>Origin state</dt><dd>{refusal.originState}</dd></div><div><dt>Classification</dt><dd>{refusal.classification}</dd></div><div><dt>Evidence tier</dt><dd>{refusal.evidenceTier}</dd></div></dl>{refusal.boundary && <p className="originRefusalBoundary">{refusal.boundary}</p>}</details>
              <p className="originRefusalBody">Choose another reference image to try again. Your form details are kept.</p>
            </section>
          )}
          {error && <p className="cpFeedback isError" role="alert">{error}</p>}
        </section>
      </main>
    </div>
  );
}
