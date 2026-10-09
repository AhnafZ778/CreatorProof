"use client";

import { useEffect, useState, type CSSProperties } from "react";
import { ArrowRight, BookOpenCheck, Fingerprint, Focus, GitCommitHorizontal, ImagePlus, Layers3, Link2, LockKeyhole, Pause, Play, RotateCcw, ScanEye, ShieldCheck, UserRound, type LucideIcon } from "lucide-react";
import { Status } from "./Phase1UI";

type Scenario = "licensed" | "unlicensed" | "resemblance";
type Node = { id: string; title: string; subtitle: string; Icon: LucideIcon; x: number; y: number; explanation: string };
const NODES: Node[] = [
  { id: "inputs", title: "Artwork & candidate", subtitle: "Two separate inputs", Icon: ImagePlus, x: 10, y: 46, explanation: "An artist registers a reference. A checker submits a candidate image against the chosen catalog. Their hashes and declared use are recorded separately." },
  { id: "passport", title: "Rights Passport", subtitle: "Versioned permissions", Icon: LockKeyhole, x: 10, y: 222, explanation: "The artist records eleven preferences and any attribution, licensing, geographic, platform, or model conditions. Unspecified permissions stay unknown." },
  { id: "history", title: "Creation history", subtitle: "An append-only record", Icon: GitCommitHorizontal, x: 10, y: 398, explanation: "The artist records creation events and human decisions in a hash chain. This documents their stated process; it does not automatically determine ownership or copyrightability." },
  { id: "copy", title: "Visual reuse", subtitle: "Correspondence & geometry", Icon: Focus, x: 270, y: 6, explanation: "Hashes nominate exact matches. Retrieval finds candidates. Geometry and aligned structural checks determine whether a correspondence is supported; a semantic neighbor alone is insufficient." },
  { id: "origin", title: "AI origin", subtitle: "An independent question", Icon: ScanEye, x: 270, y: 145, explanation: "Available origin providers and visible labels contribute separate indicators. An unavailable detector remains unavailable and an AI signal does not establish copying." },
  { id: "provenance", title: "Provenance", subtitle: "Content Credentials", Icon: Fingerprint, x: 270, y: 284, explanation: "Read-only inspection checks manifest presence, validity, signatures, trust, actions, and ingredients. Missing credentials do not establish human authorship." },
  { id: "profile", title: "Creator resemblance", subtitle: "Advisory evidence", Icon: UserRound, x: 270, y: 423, explanation: "Creator-profile evidence can describe resemblance. Style resemblance does not identify a creator and is kept separate from validated visual reuse." },
  { id: "matrix", title: "Evidence Matrix", subtitle: "Eight lanes; explicit gaps", Icon: Layers3, x: 530, y: 145, explanation: "Copy, origin, provenance, creator profile, rights, policy, source coverage, and integrity are persisted independently. Missing or contradictory evidence can cause abstention." },
  { id: "policy", title: "Publication policy", subtitle: "Permission meets intended use", Icon: ShieldCheck, x: 530, y: 322, explanation: "Deterministic rules compare licenses and artist preferences with the declared use. A visual match and permission to publish are separate results." },
  { id: "review", title: "Human review", subtitle: "The operator decides", Icon: BookOpenCheck, x: 790, y: 145, explanation: "An operator inspects the evidence and may request a structured AI investigation or draft notice. Generated content is hash-bound and a human records its disposition. Generation never sends a notice." },
  { id: "public", title: "Safe verification", subtitle: "An expiring, revocable link", Icon: Link2, x: 790, y: 322, explanation: "An authorized operator creates a scoped link to safe registration, provenance, rights, or packet information. Private contacts, uploaded media, and internal outputs are excluded." },
];
const STEPS = [["inputs"], ["passport", "history"], ["copy", "origin", "provenance", "profile"], ["matrix"], ["policy"], ["review"], ["public"]];
const SCENARIOS: Record<Scenario, { title: string; detail: string; match: string; policy: string; evidence: string }> = {
  licensed: { title: "Licensed visual reuse", detail: "The image matches a registered work, and the recorded license covers the declared use.", match: "MATCH_FOUND", policy: "PASS_BY_POLICY", evidence: "PARTIALLY_SUPPORTED" },
  unlicensed: { title: "Reuse with missing permission", detail: "A visual correspondence is supported, but the required permission is not recorded. This example organization requests review.", match: "MATCH_FOUND", policy: "REVIEW", evidence: "PARTIALLY_SUPPORTED" },
  resemblance: { title: "Resemblance without validated reuse", detail: "A candidate resembles a creator's work, but geometric correspondence is not established. The system keeps that uncertainty visible.", match: "INCONCLUSIVE", policy: "REVIEW", evidence: "INCONCLUSIVE" },
};
const CONNECTIONS: [string, string, string][] = [
  ["inputs", "copy", "M220 101 C245 101 245 61 270 61"], ["inputs", "origin", "M220 101 C247 101 245 200 270 200"], ["inputs", "provenance", "M220 101 C245 101 245 339 270 339"], ["inputs", "profile", "M220 101 C244 101 244 478 270 478"],
  ["passport", "policy", "M220 277 C500 277 255 377 530 377"], ["history", "matrix", "M220 453 C512 453 250 200 530 200"],
  ["copy", "matrix", "M480 61 C505 61 505 200 530 200"], ["origin", "matrix", "M480 200 L530 200"], ["provenance", "matrix", "M480 339 C505 339 505 200 530 200"], ["profile", "matrix", "M480 478 C512 478 505 200 530 200"],
  ["matrix", "policy", "M635 255 L635 322"], ["policy", "review", "M740 377 C765 377 765 200 790 200"], ["matrix", "public", "M740 200 C765 200 765 377 790 377"], ["review", "public", "M895 255 L895 322"],
];

export default function SystemPipeline() {
  const [scenario, setScenario] = useState<Scenario>("licensed");
  const [selected, setSelected] = useState("inputs");
  const [step, setStep] = useState(-1);
  const [playing, setPlaying] = useState(false);
  const example = SCENARIOS[scenario];
  const selectedNode = NODES.find((node) => node.id === selected)!;
  useEffect(() => {
    if (!playing) return;
    if (step >= STEPS.length - 1) { setPlaying(false); return; }
    const timer = setTimeout(() => { const next = step + 1; setStep(next); setSelected(STEPS[next][0]); }, 1700);
    return () => clearTimeout(timer);
  }, [playing, step]);
  function nodeState(id: string) { if (id === "copy") return scenario === "resemblance" ? "INCONCLUSIVE" : "SUPPORTED"; if (id === "origin") return "PROVIDER_UNAVAILABLE"; if (id === "provenance") return "ABSENT"; if (id === "profile") return scenario === "resemblance" ? "STYLE_SIGNAL" : "NOT_RUN"; if (id === "matrix") return example.evidence; if (id === "policy") return example.policy; return null; }
  return <section className="portalPanel cpPipeline" aria-label="Interactive system pipeline"><header className="cpPanelHeading"><div><small>FOLLOW THE EVIDENCE</small><h2>One system. Separate questions.</h2></div><span className="cpExampleBadge">Illustrative walkthrough</span></header><p className="cpDescription">Explore an example, click a node, or play the journey. These examples use no artist data and do not run detectors or generate notices.</p>
    <div className="cpScenarioPicker" role="group" aria-label="Pipeline example">{(Object.keys(SCENARIOS) as Scenario[]).map((key, index) => <button key={key} type="button" aria-pressed={scenario === key} className={scenario === key ? "isSelected" : ""} onClick={() => { setScenario(key); setPlaying(false); setStep(-1); }}><span>0{index + 1}</span>{SCENARIOS[key].title}</button>)}</div>
    <div className="cpPipelineToolbar"><p>{example.detail}</p><div className="cpActions"><button type="button" className="portalSecondary" onClick={() => { if (!playing && step >= STEPS.length - 1) setStep(-1); setPlaying((old) => !old); }}>{playing ? <Pause size={15} /> : <Play size={15} />}{playing ? "Pause" : "Play walkthrough"}</button><button type="button" className="cpIconButton" aria-label="Reset walkthrough" onClick={() => { setPlaying(false); setStep(-1); setSelected("inputs"); }}><RotateCcw size={16} /></button></div></div>
    <div className="cpPipelineColumnHeads"><span>Record the work</span><span>Inspect independently</span><span>Evaluate the evidence</span><span>Review & share</span></div>
    <div className="cpPipelineStage">
      <svg viewBox="0 0 1000 560" preserveAspectRatio="none" className="cpPipelineConnections" aria-hidden="true"><defs><linearGradient id="pipeline-blue"><stop stopColor="#60a5fa" stopOpacity=".45" /><stop offset="1" stopColor="#818cf8" stopOpacity=".9" /></linearGradient></defs>{CONNECTIONS.map(([from, to, path]) => <g key={`${from}-${to}`}><path d={path} className="cpConnectionBase" /><path d={path} className={`cpConnectionFlow ${step >= 0 && (STEPS[step].includes(from) || STEPS[step].includes(to)) ? "isActive" : ""}`} /></g>)}</svg>
      {NODES.map(({ id, title, subtitle, Icon, x, y }) => { const active = step >= 0 && STEPS[step].includes(id); return <button key={id} type="button" className={`cpPipelineNode ${selected === id ? "isSelected" : ""} ${active ? "isActive" : ""}`} style={{ "--node-x": `${x / 10}%`, "--node-y": `${y / 5.6}%` } as CSSProperties} aria-pressed={selected === id} aria-controls="pipeline-node-description" onClick={() => { setSelected(id); setPlaying(false); }}><span className="cpNodeIcon"><Icon size={20} /></span><div><b>{title}</b><small>{subtitle}</small></div>{nodeState(id) && <Status value={nodeState(id)} />}</button>; })}
    </div>
    <div id="pipeline-node-description" className="cpPipelineExplanation" aria-live="polite"><div className="cpFeatureIcon"><selectedNode.Icon size={26} /></div><div><small>SELECTED NODE</small><h3>{selectedNode.title}</h3><p>{selectedNode.explanation}</p></div><span className="cpCaption">{step >= 0 ? `Step ${step + 1} of ${STEPS.length}` : "Click any node"}</span></div>
    <div className="cpPipelineOutcome"><div><span>Example match</span><Status value={example.match} /></div><ArrowRight size={20} aria-hidden="true" /><div><span>Example evidence</span><Status value={example.evidence} /></div><ArrowRight size={20} aria-hidden="true" /><div><span>Example publication policy</span><Status value={example.policy} /></div></div>
    <p className="cpCaption">An origin signal, resemblance, permission record, or packet hash does not independently establish infringement or ownership. Real scan results appear in the User and Admin evidence workspaces.</p>
  </section>;
}
