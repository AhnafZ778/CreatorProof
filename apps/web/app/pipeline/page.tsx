import Link from "next/link";
import { ArrowRight, FileSearch, Palette, ScanSearch } from "lucide-react";
import PortalNav from "@/app/components/PortalNav";
import SystemPipeline from "@/app/components/SystemPipeline";

export default function PipelinePage() {
  return <div className="portalPage isUser"><PortalNav active="pipeline" /><main className="portalMain"><section className="portalHero"><div className="portalHeroKicker">Inside CreatorProof</div><h1>See how evidence<br />becomes a decision.</h1><p>Follow an artwork from recorded permissions to independent checks, policy evaluation, and a human review. Every finding keeps its meaning.</p></section><SystemPipeline /><section className="portalGrid cpJourneyPortals" aria-label="Continue to your workspace">{[{ href: "/artist", title: "For artists", detail: "Register art, record your permissions and process, inspect provenance, and share a safe record.", Icon: Palette }, { href: "/user", title: "For image checkers", detail: "Declare intended use, scan against a catalog, and inspect independent evidence and policy outcomes.", Icon: ScanSearch }, { href: "/admin", title: "For reviewers", detail: "Inspect stored detections, request an investigation, record your judgment, and prepare factual notices.", Icon: FileSearch }].map(({ href, title, detail, Icon }) => <Link key={href} className="portalCard" href={href}><Icon size={23} /><h3>{title}</h3><p>{detail}</p><span>Open workspace <ArrowRight size={15} /></span></Link>)}</section></main></div>;
}
