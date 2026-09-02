import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "Not found — CreatorProof",
};

export default function NotFound() {
  return (
    <main style={{ padding: "4rem 1.5rem", maxWidth: 40 + "rem", margin: "0 auto" }}>
      <p>That page is not part of this CreatorProof deployment.</p>
      <p>
        <Link href="/">Return home</Link>
      </p>
    </main>
  );
}
