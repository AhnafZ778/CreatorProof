import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "CreatorProof v0.9.2 - Truthful Scope and Visual Rights Evidence",
  description: "Plain-language AI-use and creative-rights evidence workspace",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
