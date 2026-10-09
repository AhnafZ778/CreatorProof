"use client";

import { Suspense } from "react";
import Link from "next/link";
import { ArrowRight } from "lucide-react";

import PortalNav from "@/app/components/PortalNav";
import UserScanDesk from "@/app/components/UserScanDesk";

export default function UserPortalPage() {
  return (
    <Suspense fallback={<div className="portalPage isUser" />}>
      <div className="portalPage isUser">
        <PortalNav active="user" />
        <main className="portalMain">
          <section className="portalHero"><div className="portalHeroKicker">User portal</div><h1>Know what matches.<br />Understand what matters.</h1><p>Check an image against registered references, describe how you plan to use it, and explore the evidence behind each independent finding.</p><div className="portalHeroActions"><a className="portalPrimary" href="#scan-work">Check an image</a><Link className="portalSecondary" href="/pipeline">Explore the pipeline <ArrowRight size={16} /></Link></div></section>
          <UserScanDesk />
        </main>
      </div>
    </Suspense>
  );
}
