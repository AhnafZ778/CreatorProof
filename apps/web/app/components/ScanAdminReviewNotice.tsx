"use client";

import Link from "next/link";
import { ArrowUpRight, ShieldCheck } from "lucide-react";
import { readable } from "../lib/phase1";
import { adminReviewHref, savedAdminReview } from "../lib/scanAdminReview";

export default function ScanAdminReviewNotice({ scan }: { scan: Record<string, unknown> }) {
  const review = savedAdminReview(scan);
  if (!review) return null;
  return <section className="cpAdminReviewReceipt" aria-label="Admin review confirmation" role="status">
    <div className="cpAdminReviewReceiptHeading">
      <ShieldCheck size={20} aria-hidden="true" />
      <div><small>{review.category === "ASSESSMENT_GAP" ? "ASSESSMENT NEEDS REVIEW" : "REVIEW RECORD SAVED"}</small><h3>Saved for Admin review</h3></div>
      <Link className="portalSecondary" href={adminReviewHref(review.scanId)}>Open review <ArrowUpRight size={15} aria-hidden="true" /></Link>
    </div>
    <p>{review.category === "ASSESSMENT_GAP"
      ? "Part of this assessment needs a closer look. Admin can inspect the saved evidence and decide whether to rerun the scan or take another step."
      : "Admin has the saved scan and evidence, can compare it with any matched artist reference, and decides whether action is appropriate."} A notice is sent only after operator approval.</p>
    <dl className="cpAdminReviewReceiptFacts">
      <div><dt>Intended use</dt><dd>{review.intendedUse || "Not provided"}</dd></div>
      <div><dt>Notice country</dt><dd>{review.countryCode ? `${review.countryCode} · user declaration` : "Not provided; Admin will confirm"}</dd></div>
      <div><dt>Image location</dt><dd>{review.sourceUrl ? <a href={review.sourceUrl} target="_blank" rel="noreferrer">{review.sourceKind === "marketplace" ? "Stored source listing" : "User-provided page URL"} <ArrowUpRight size={12} aria-hidden="true" /></a> : "Uploaded file; no public URL supplied"}</dd></div>
      <div><dt>Artist reference</dt><dd>{review.matchedWorkId || "No confirmed registered-work match"}</dd></div>
      {review.useContext.territory && <div><dt>Publication country</dt><dd>{review.useContext.territory} · intended-use declaration</dd></div>}
      {review.useContext.channel && <div><dt>Publication channel</dt><dd>{review.useContext.channel}</dd></div>}
    </dl>
    {review.reasons.length > 0 && <div className="cpAdminReviewReceiptReasons" aria-label="Reasons for Admin review">{review.reasons.map((reason) => <span key={reason}>{readable(reason)}</span>)}</div>}
    <small className="cpAdminReviewReceiptNote">The scan ID, image hash, declared use, available source details and evidence stay together in the saved review record.</small>
  </section>;
}
