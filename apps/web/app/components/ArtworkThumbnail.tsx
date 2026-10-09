"use client";
import { useState } from "react";
import { Image } from "lucide-react";
export default function ArtworkThumbnail({ workId, title }: { workId: string; title: string }) {
  const [missing, setMissing] = useState(false);
  return <div className="cpArtworkThumb">{missing ? <Image size={22} aria-hidden="true" /> : <img src={`/api/works/${encodeURIComponent(workId)}/media`} alt={title} loading="lazy" onError={() => setMissing(true)} />}</div>;
}
