import {
  createContext,
  createElement,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useLocation } from "react-router-dom";

import { toast } from "@/components/ui/toast";
import { usePreview } from "@/contexts/PreviewContext";
import { useCampaigns } from "./useCampaigns";
import type { Campaign } from "../types";

// The app-wide current Campaign (E0-UX.7). One source of truth: the nav's
// CampaignSwitcher and every page's campaign picker read and write it, so
// picking anywhere moves the whole app. The choice is remembered per device
// and per user under `lk-current-campaign:{userId}` in localStorage.
//
// This is a UI preference only. Which campaigns a user may open is decided by
// the server; a stale or foreign id here simply falls back to the first
// campaign the server lists (and says so).

const KEY_PREFIX = "lk-current-campaign:";

export const LOST_ACCESS_PREFIX = "You no longer have access to that campaign.";

/** localStorage key holding this user's current campaign id. */
export function currentCampaignKey(userId: string): string {
  return `${KEY_PREFIX}${userId}`;
}

/** The toast shown when the remembered campaign is no longer in the list. */
export function lostAccessMessage(fallback: Pick<Campaign, "name">): string {
  return `${LOST_ACCESS_PREFIX} Switched to ${fallback.name}.`;
}

// ─── Storage ─────────────────────────────────────────────────────────────────

type StorageLike = Pick<Storage, "getItem" | "setItem" | "removeItem">;

// Used when there is no user id, or storage is unavailable or throws: the
// choice then lasts for this page load only.
const memory = new Map<string | null, string | null>();

function defaultStorage(): StorageLike | null {
  try {
    return typeof localStorage === "undefined" ? null : localStorage;
  } catch {
    return null;
  }
}

/** The stored campaign id for `userId`, or null. Never throws. */
export function readStoredCampaignId(
  userId: string | null,
  storage: StorageLike | null = defaultStorage(),
): string | null {
  if (userId === null || storage === null) return memory.get(userId) ?? null;
  try {
    const raw = storage.getItem(currentCampaignKey(userId));
    return raw && raw.length > 0 ? raw : null;
  } catch {
    return memory.get(userId) ?? null;
  }
}

/** Store (or, with null, clear) the campaign id for `userId`. Never throws. */
export function writeStoredCampaignId(
  userId: string | null,
  campaignId: string | null,
  storage: StorageLike | null = defaultStorage(),
): void {
  memory.set(userId, campaignId);
  if (userId === null || storage === null) return;
  try {
    if (campaignId === null) storage.removeItem(currentCampaignKey(userId));
    else storage.setItem(currentCampaignKey(userId), campaignId);
  } catch {
    // Memory only; the choice still holds until the page is reloaded.
  }
}

/** The logged-in user's id from `lk_user` (written by useAuth), or null. */
export function readUserId(storage: StorageLike | null = defaultStorage()): string | null {
  try {
    const raw = storage?.getItem("lk_user");
    if (!raw) return null;
    const parsed: unknown = JSON.parse(raw);
    const id = parsed && typeof parsed === "object" ? (parsed as { id?: unknown }).id : undefined;
    if (typeof id === "string" && id.length > 0) return id;
    if (typeof id === "number") return String(id);
    return null;
  } catch {
    return null;
  }
}

function hasToken(storage: StorageLike | null = defaultStorage()): boolean {
  try {
    return !!storage?.getItem("lk_token");
  } catch {
    return false;
  }
}

// ─── Resolution (pure) ───────────────────────────────────────────────────────

/** A campaign picked in this page load, with when it was picked. */
export interface PickedCampaign {
  campaign: Campaign;
  at: number;
}

export interface ResolveInput {
  /** The campaigns query data; may be stale or undefined. */
  campaigns: readonly Campaign[] | undefined;
  /** True only when the list was fetched successfully for this user. */
  listReady: boolean;
  /** When the list was last fetched (react-query `dataUpdatedAt`). */
  listUpdatedAt: number;
  storedId: string | null;
  picked: PickedCampaign | null;
}

export interface Resolution {
  current: Campaign | null;
  /** The id storage should hold after this resolution (null clears it). */
  persistId: string | null;
  /** The stored campaign was lost: tell the user about the fallback. */
  lostAccess: boolean;
}

/**
 * Which campaign is current, given the stored id and the fetched list.
 *
 * - The stored id is in the list: that campaign.
 * - It was just picked (e.g. a campaign created a moment ago) and no list
 *   fetched after the pick has come back yet: the picked campaign.
 * - The list is still loading or failed: keep the stored id, no fallback.
 * - Otherwise fall back to the first campaign (or none), and flag lost access
 *   when a stored id was replaced.
 */
export function resolveCurrentCampaign({
  campaigns,
  listReady,
  listUpdatedAt,
  storedId,
  picked,
}: ResolveInput): Resolution {
  const list = campaigns ?? [];
  if (storedId !== null) {
    const found = list.find((c) => c.id === storedId);
    if (found) return { current: found, persistId: storedId, lostAccess: false };
    if (picked && picked.campaign.id === storedId && (!listReady || picked.at >= listUpdatedAt)) {
      return { current: picked.campaign, persistId: storedId, lostAccess: false };
    }
  }
  if (!listReady) return { current: null, persistId: storedId, lostAccess: false };
  const fallback = list[0] ?? null;
  return {
    current: fallback,
    persistId: fallback?.id ?? null,
    lostAccess: storedId !== null && fallback !== null,
  };
}

// ─── Provider ────────────────────────────────────────────────────────────────

export interface CurrentCampaignState {
  /** The current campaign, or null (none yet, list loading, or no campaigns). */
  current: Campaign | null;
  /** The user's campaigns (empty while loading). */
  campaigns: Campaign[];
  /** The campaigns list has been fetched for this user. */
  ready: boolean;
  /** Make `campaign` current everywhere and remember it on this device. */
  setCurrent: (campaign: Campaign) => void;
}

const CurrentCampaignContext = createContext<CurrentCampaignState | null>(null);

interface Slot {
  userId: string | null;
  storedId: string | null;
  picked: PickedCampaign | null;
  /** Lists fetched before this time belong to a previous user. */
  since: number;
}

export function CurrentCampaignProvider({ children }: { children: ReactNode }) {
  // Login and logout navigate, so re-reading the user on each location change
  // is enough to follow them.
  useLocation();
  const loggedIn = hasToken();
  const userId = readUserId();

  const query = useCampaigns({ enabled: loggedIn });
  const queryClient = useQueryClient();
  const preview = usePreview();

  const [slot, setSlot] = useState<Slot>(() => ({
    userId,
    storedId: readStoredCampaignId(userId),
    picked: null,
    since: 0,
  }));

  // Another user on this device: read only their key, and don't trust a list
  // cached for the previous user.
  let active = slot;
  if (slot.userId !== userId) {
    active = { userId, storedId: readStoredCampaignId(userId), picked: null, since: Date.now() };
    setSlot(active);
  }

  const firstUser = useRef(userId);
  useEffect(() => {
    if (userId === firstUser.current) return;
    firstUser.current = userId;
    if (userId !== null) void queryClient.invalidateQueries({ queryKey: ["campaigns"] });
  }, [userId, queryClient]);

  const listReady = loggedIn && query.isSuccess && query.dataUpdatedAt >= active.since;
  const resolution = resolveCurrentCampaign({
    campaigns: query.data,
    listReady,
    listUpdatedAt: query.dataUpdatedAt,
    storedId: active.storedId,
    picked: active.picked,
  });

  // Persist fallbacks and clears; toast once per lost campaign.
  const toastedFor = useRef<string | null>(null);
  const { persistId, lostAccess, current } = resolution;
  useEffect(() => {
    if (persistId === active.storedId) return;
    const lostId = active.storedId;
    writeStoredCampaignId(userId, persistId);
    setSlot((s) => (s.userId === userId ? { ...s, storedId: persistId, picked: null } : s));
    if (lostAccess && current && lostId !== null && toastedFor.current !== lostId) {
      toastedFor.current = lostId;
      toast({ text: lostAccessMessage(current) });
    }
  }, [persistId, lostAccess, current, active.storedId, userId]);

  const { active: previewActive, campaignId: previewId, exit: exitPreview } = preview;
  const setCurrent = useCallback(
    (campaign: Campaign) => {
      writeStoredCampaignId(userId, campaign.id);
      setSlot((s) => ({ ...s, storedId: campaign.id, picked: { campaign, at: Date.now() } }));
      // Previewing another campaign as a Player makes no sense once you leave it.
      if (previewActive && previewId !== campaign.id) exitPreview();
    },
    [userId, previewActive, previewId, exitPreview],
  );

  const campaigns = query.data;
  const value = useMemo<CurrentCampaignState>(
    () => ({ current, campaigns: campaigns ?? [], ready: listReady, setCurrent }),
    [current, campaigns, listReady, setCurrent],
  );

  return createElement(CurrentCampaignContext.Provider, { value }, children);
}

/** The app-wide current campaign. Must be used under CurrentCampaignProvider. */
export function useCurrentCampaign(): CurrentCampaignState {
  const ctx = useContext(CurrentCampaignContext);
  if (!ctx) throw new Error("useCurrentCampaign must be used inside <CurrentCampaignProvider>");
  return ctx;
}

/**
 * A page's campaign picker state, backed by the global current campaign.
 * `accept` narrows what the page can show (e.g. owner-only pages): when the
 * current campaign is not accepted the page shows nothing selected, and a pick
 * there still becomes the global current campaign.
 */
export function usePageCampaign(
  accept?: (campaign: Campaign) => boolean,
): [Campaign | null, (campaign: Campaign) => void] {
  const { current, setCurrent } = useCurrentCampaign();
  const selected = current && (!accept || accept(current)) ? current : null;
  return [selected, setCurrent];
}
