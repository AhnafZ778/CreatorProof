import type { Metadata } from "next";
import PublicVerification from "@/app/components/PublicVerification";

export const metadata: Metadata = { title: "Verify a record — CreatorProof", robots: { index: false, follow: false }, referrer: "no-referrer" };
export default async function VerificationPage({ params }: { params: Promise<{ token: string }> }) {
  const { token } = await params;
  return <PublicVerification token={token} />;
}
