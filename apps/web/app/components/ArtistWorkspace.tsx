"use client";

import { useRef, useState, type KeyboardEvent } from "react";
import { Fingerprint, GitCommitHorizontal, Link2, ShieldCheck } from "lucide-react";
import ContributionLedger from "./ContributionLedger";
import ProvenancePanel from "./ProvenancePanel";
import RightsPassport from "./RightsPassport";
import ShareVerification from "./ShareVerification";
import ArtworkThumbnail from "./ArtworkThumbnail";

const TABS = [
  { key: "passport", label: "Permissions", Icon: ShieldCheck },
  { key: "history", label: "Creation history", Icon: GitCommitHorizontal },
  { key: "provenance", label: "Origin evidence", Icon: Fingerprint },
  { key: "share", label: "Share & export", Icon: Link2 },
] as const;
type Tool = (typeof TABS)[number]["key"];

export default function ArtistWorkspace({ workId, title }: { workId: string; title: string }) {
  const [tab, setTab] = useState<Tool>("passport");
  const [visited, setVisited] = useState<Set<Tool>>(() => new Set(["passport"]));
  const tabs = useRef<Array<HTMLButtonElement | null>>([]);

  function openTool(key: Tool) {
    setTab(key);
    // A tool loads only when opened. Keeping opened tools mounted preserves
    // unsaved form changes when the artist switches between them.
    setVisited((old) => old.has(key) ? old : new Set([...old, key]));
  }

  function navigate(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    const next = event.key === "ArrowRight" ? (index + 1) % TABS.length
      : event.key === "ArrowLeft" ? (index + TABS.length - 1) % TABS.length
      : event.key === "Home" ? 0 : event.key === "End" ? TABS.length - 1 : -1;
    if (next < 0) return;
    event.preventDefault();
    openTool(TABS[next].key);
    tabs.current[next]?.focus();
  }

  return (
    <section id="artwork-workspace" className="portalPanel cpWorkspace artistWorkspace" aria-label={`Artwork workspace for ${title}`}>
      <div className="cpWorkspaceIntro">
        <ArtworkThumbnail workId={workId} title={title} />
        <div><small>SELECTED ARTWORK</small><h2>{title}</h2><p>Manage this artwork’s permissions and record.</p></div>
      </div>
      <div className="cpTabs" role="tablist" aria-label="Artwork tools">
        {TABS.map(({ key, label, Icon }, index) => (
          <button
            type="button"
            key={key}
            role="tab"
            id={`work-tab-${key}`}
            aria-selected={tab === key}
            aria-controls={`work-panel-${key}`}
            tabIndex={tab === key ? 0 : -1}
            ref={(element) => { tabs.current[index] = element; }}
            onClick={() => openTool(key)}
            onKeyDown={(event) => navigate(event, index)}
          ><Icon size={16} aria-hidden="true" />{label}</button>
        ))}
      </div>
      <div role="tabpanel" id="work-panel-passport" aria-labelledby="work-tab-passport" hidden={tab !== "passport"}>{visited.has("passport") && <RightsPassport workId={workId} />}</div>
      <div role="tabpanel" id="work-panel-history" aria-labelledby="work-tab-history" hidden={tab !== "history"}>{visited.has("history") && <ContributionLedger workId={workId} />}</div>
      <div role="tabpanel" id="work-panel-provenance" aria-labelledby="work-tab-provenance" hidden={tab !== "provenance"}>{visited.has("provenance") && <ProvenancePanel resource="works" resourceId={workId} />}</div>
      <div role="tabpanel" id="work-panel-share" aria-labelledby="work-tab-share" hidden={tab !== "share"}>{visited.has("share") && <ShareVerification resource="works" resourceId={workId} exports />}</div>
    </section>
  );
}
