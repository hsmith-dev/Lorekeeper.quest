// "Preview as Player" store (E0-UX.6). A tiny non-React store shared by the
// usePreview() hook and the axios request interceptor, so both always agree on
// whether preview is on. No runtime imports (loadable by Node type stripping).
//
// State is per tab: it lives in sessionStorage, so it survives a reload or an
// in-app navigation, and a newly opened tab starts without preview. Every
// storage access is wrapped in try/catch; when storage is unavailable (private
// mode, blocked site data) the state is kept in memory for this page load.
//
// Preview is cosmetic on the client. The real hiding is server-side (AD-13):
// the request header below asks the server to answer as a campaign member, and
// it can only ever narrow what the server returns.

export const PREVIEW_STORAGE_KEY = "lk-preview";
export const PREVIEW_HEADER = "X-Lorekeeper-Preview";
export const PREVIEW_HEADER_VALUE = "member";

type Listener = () => void;

const listeners = new Set<Listener>();
// undefined = storage not read yet in this page load.
let current: string | null | undefined;

function storage(): Storage | null {
  try {
    return typeof sessionStorage === "undefined" ? null : sessionStorage;
  } catch {
    return null;
  }
}

function readStored(): string | null {
  try {
    const raw = storage()?.getItem(PREVIEW_STORAGE_KEY);
    if (!raw) return null;
    const parsed: unknown = JSON.parse(raw);
    if (parsed && typeof parsed === "object") {
      const id = (parsed as { campaignId?: unknown }).campaignId;
      if (typeof id === "string" && id.length > 0) return id;
    }
    return null;
  } catch {
    return null;
  }
}

/** The campaign being previewed as a Player in this tab, or null. */
export function getPreviewCampaignId(): string | null {
  if (current === undefined) current = readStored();
  return current;
}

/** Start (campaign id) or stop (null) preview for this tab. */
export function setPreviewCampaignId(campaignId: string | null): void {
  const next = campaignId && campaignId.length > 0 ? campaignId : null;
  const changed = next !== getPreviewCampaignId();
  current = next;
  try {
    const s = storage();
    if (next === null) s?.removeItem(PREVIEW_STORAGE_KEY);
    else s?.setItem(PREVIEW_STORAGE_KEY, JSON.stringify({ campaignId: next }));
  } catch {
    // In-memory only; the state still holds until the page is reloaded.
  }
  if (changed) for (const listener of [...listeners]) listener();
}

/** Subscribe to preview changes. Returns an unsubscribe function. */
export function subscribePreview(listener: Listener): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function isPreviewActive(): boolean {
  return getPreviewCampaignId() !== null;
}

/** Headers to add to an API request: the preview header while active, else none. */
export function previewHeaders(): Record<string, string> {
  return isPreviewActive() ? { [PREVIEW_HEADER]: PREVIEW_HEADER_VALUE } : {};
}
