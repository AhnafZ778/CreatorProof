/**
 * The catalog the two portals share.
 *
 * A scan measures a candidate against one named catalog and nothing else, so
 * the Artist desk and the User desk have to agree on the name or the round trip
 * silently fails: the work registers, the scan runs, and the result is an empty
 * scope that looks identical to "nothing was found". Both desks default to this
 * value so the out-of-the-box path works, and both still accept a typed name
 * for anyone running more than one catalog.
 */
export const DEFAULT_CATALOG_ID = "artist-library";

export type CatalogWork = {
  id: string;
  title: string;
  claimant: string | null;
  catalog_id: string;
};

/**
 * What a catalog holds right now.
 *
 * Returns null when the count cannot be established, which is deliberately
 * distinct from zero: an unreachable API must not be presented as an empty
 * catalog, because those two states call for opposite actions.
 */
export async function readCatalogWorks(catalogId: string): Promise<CatalogWork[] | null> {
  if (!catalogId.trim()) return null;
  try {
    const response = await fetch(`/api/works?catalog_id=${encodeURIComponent(catalogId.trim())}`, {
      cache: "no-store",
    });
    if (!response.ok) return null;
    const body = (await response.json()) as unknown;
    return Array.isArray(body) ? (body as CatalogWork[]) : null;
  } catch {
    return null;
  }
}
