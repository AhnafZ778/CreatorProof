"use client";

import { Suspense } from "react";

import AdminConsole from "@/app/components/AdminConsole";
import PortalNav from "@/app/components/PortalNav";

export default function AdminPage() {
  return (
    <Suspense fallback={<div className="portalPage isAdmin" />}>
      <div className="portalPage isAdmin">
        <PortalNav active="admin" />
        <main className="portalMain"><AdminConsole /></main>
      </div>
    </Suspense>
  );
}
