export type PortalRole = "artist" | "user" | "admin";

export type PortalSession = {
  role: PortalRole;
  name: string;
  loggedIn: boolean;
};

const KEY = "creatorproof.portal.session";

export function readPortalSession(): PortalSession | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as PortalSession;
    if (parsed?.role !== "artist" && parsed?.role !== "user" && parsed?.role !== "admin") return null;
    return parsed;
  } catch {
    return null;
  }
}

export function writePortalSession(session: PortalSession) {
  window.localStorage.setItem(KEY, JSON.stringify(session));
}

export function clearPortalSession() {
  window.localStorage.removeItem(KEY);
}

export function portalPath(role: PortalRole) {
  if (role === "artist") return "/artist";
  if (role === "admin") return "/admin";
  return "/user";
}
