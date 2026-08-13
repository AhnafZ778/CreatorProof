"use client";

import { Suspense } from "react";

import PortalNav from "@/app/components/PortalNav";
import UserScanDesk from "@/app/components/UserScanDesk";

export default function UserPortalPage() {
  return (
    <Suspense fallback={<div className="portalPage isUser" />}>
      <div className="portalPage isUser">
        <PortalNav active="user" />
        <main className="portalMain">
          <UserScanDesk />
        </main>
      </div>
    </Suspense>
  );
}
