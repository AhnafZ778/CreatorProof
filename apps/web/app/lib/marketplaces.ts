export type MarketplaceName = "pixabay" | "unsplash" | "ebay";
export type MarketplaceProvider = {
  provider: MarketplaceName;
  configured: boolean;
  environment: "sandbox" | "production";
  marketplace_id: string | null;
};

export function marketplaceLabel(provider: string, environment?: unknown): string {
  if (provider === "ebay") {
    return environment === "sandbox" ? "eBay · Sandbox" : environment === "production" ? "eBay · Production" : "eBay";
  }
  return provider === "pixabay" ? "Pixabay" : provider === "unsplash" ? "Unsplash" : provider;
}

export function marketplaceDescription(source: MarketplaceProvider): string {
  if (!source.configured) return `${marketplaceLabel(source.provider)} is not configured on the API server.`;
  if (source.provider === "ebay") {
    const market = source.marketplace_id?.replace("EBAY_", "") || "selected marketplace";
    return source.environment === "sandbox"
      ? `Sandbox test listings · ${market}. Try “print” to find sample listing photos. Production keys are needed for real listings.`
      : `Production eBay listings · ${market}. Listing photos are checked against your registered artist catalog.`;
  }
  return `${marketplaceLabel(source.provider)} is configured. Search images and check them against your artist catalog.`;
}
