import Link from "next/link";
import { notFound } from "next/navigation";
import { collectionEntries } from "../../lib/caseLibrary";

export function generateStaticParams() { return Object.keys(collectionEntries).map(slug => ({ slug })); }
export default async function CollectionPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const entry = Object.hasOwn(collectionEntries, slug) ? collectionEntries[slug] : undefined;
  if (!entry) notFound();
  return <main className="collectionPage"><Link className="collectionBrand" href="/">CreatorProof <span>Collection</span></Link><div className="collectionLayout"><div><span className="collectionKicker">{entry.kind}</span><h1>{entry.title}</h1><p>{entry.description}</p><dl><dt>Collection</dt><dd>CreatorProof · first-party publication</dd><dt>Publication rights</dt><dd>Permission and claimant authority must be checked before external action.</dd></dl>{entry.original && <Link className="portalSecondary" href={`/collection/${entry.original}`}>View the registered original →</Link>}</div><figure><img src={`/case-library/${entry.image}`} alt={entry.title} /><figcaption>{entry.title} · CreatorProof collection</figcaption></figure></div></main>;
}
