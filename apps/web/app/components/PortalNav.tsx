"use client";

import Link from "next/link";

import {
  portalPath,
  type PortalRole,
} from "@/app/lib/portalSession";

type Props = {
  active: PortalRole;
};

export default function PortalNav({ active }: Props) {
  return (
    <header className="portalNav">
      <div className="portalNavInner">
        <Link href="/" className="portalBrand">
          <span className="portalBrandMark" aria-hidden>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
              <path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z" />
            </svg>
          </span>
          <span>CreatorProof</span>
        </Link>

        <div className="portalToggle" role="group" aria-label="Switch portal">
          <Link
            href={portalPath("artist")}
            className={active === "artist" ? "active" : ""}
            aria-current={active === "artist" ? "page" : undefined}
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden>
              <path d="M12 20h9" />
              <path d="M16.376 3.622a1 1 0 0 1 3.002 3.002L7.368 18.635a2 2 0 0 1-.855.506l-2.872.838a.5.5 0 0 1-.62-.62l.838-2.872a2 2 0 0 1 .506-.854z" />
            </svg>
            Artist
          </Link>
          <Link
            href={portalPath("user")}
            className={active === "user" ? "active" : ""}
            aria-current={active === "user" ? "page" : undefined}
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden>
              <path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" />
              <circle cx="9" cy="7" r="4" />
              <path d="M22 21v-2a4 4 0 0 0-3-3.87" />
              <path d="M16 3.13a4 4 0 0 1 0 7.75" />
            </svg>
            User
          </Link>
        </div>

        <div className="portalNavSpacer" aria-hidden="true" />
      </div>
    </header>
  );
}
