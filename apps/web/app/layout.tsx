import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "CreatorProof — Pre-publication creative-rights evidence",
  description: "Plain-language AI-use and creative-rights evidence workspace",
  icons: {
    icon: "/favicon.svg",
  },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  // `data-scroll-behavior` opts the smooth scrolling declared in globals.css into
  // applying to route transitions too, which Next otherwise warns about.
  return (
    <html lang="en" data-scroll-behavior="smooth">
      <head>
        {/*
          Preloaded rather than left to CSS discovery: the font is declared in an
          imported stylesheet, so without this the first paint uses the fallback
          face and reflows. Both files are also what `public/landing.html` loads,
          so the marketing page and the portals share one cached download.
        */}
        <link
          rel="preload"
          href="/fonts/GeistVariable.woff2"
          as="font"
          type="font/woff2"
          crossOrigin="anonymous"
        />
        <link
          rel="preload"
          href="/fonts/GeistMonoVariable.woff2"
          as="font"
          type="font/woff2"
          crossOrigin="anonymous"
        />
      </head>
      <body>{children}</body>
    </html>
  );
}
