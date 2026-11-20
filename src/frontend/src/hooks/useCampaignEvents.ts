import { useEffect, useSyncExternalStore } from "react";
import { useQueryClient, type QueryClient, type QueryKey } from "@tanstack/react-query";

import { getPreviewCampaignId, subscribePreview } from "../lib/preview";
import { openSse, type Connect, type SseFrame } from "../lib/sse";
import { campaignRoleKey } from "./useCampaignRole";
import { useCurrentCampaign } from "./useCurrentCampaign";

// Campaign invalidations pushed by the server (E0-Access.11, AD-5):
// GET /api/campaigns/{id}/events, a server-sent event stream.
//
//   event: subscribed      {}                    the subscription is live: refetch
//   event: invalidate      {domain, id | null}   refetch [domain, campaignId] (and friends)
//   event: ping            {}                    keep-alive
//   event: access_changed  {"detail":"Not found"} the grant changed; the stream ends
//
// Resync contract: there are no event ids and no replay. Anything read before
// `subscribed` may be stale, so every `subscribed` (the first one and the one
// after each reconnect) refetches the Campaign's queries. Every gap is closed
// by reconnect, then `subscribed`, then refetch.
//
// Reconnects: backoff 1 s doubling to 30 s with jitter, reset by `subscribed`.
// After `access_changed` it reconnects once at once (a promotion fires it
// too). It stops on 401 and 404 (no account, or no longer a Member), and
// then refetches the role and the Campaign's queries.
//
// Transport: lib/sse.ts `openSse` (E0-Jobs.9): fetch + ReadableStream with the
// bearer header (no EventSource, never a token in the URL), the 45 s idle
// watchdog and the reconnect policy above. The server filters every event for
// the caller; nothing here decides what a user may see.

// The same base URL as services/api.ts (empty: same origin).
const API_BASE: string = import.meta.env.VITE_API_URL ?? "";

export const EVENTS_PATH = (campaignId: string) =>
  `${API_BASE}/api/campaigns/${encodeURIComponent(campaignId)}/events`;

// The parser, the reconnect policy and the transport live in lib/sse.ts;
// re-exported for existing callers and checks.
export {
  BACKOFF_BASE_MS,
  BACKOFF_MAX_MS,
  IDLE_TIMEOUT_MS,
  backoffMs,
  createFrameSplitter,
  nextStep,
  parseSseFrame,
  sseHeaders as streamHeaders,
} from "../lib/sse";
export type { ReconnectDecision, ReconnectState, SseFrame, StreamOutcome } from "../lib/sse";

// ─── What to refetch ─────────────────────────────────────────────────────────

export interface Invalidation {
  domain: string;
  id: string | null;
}

/** Domains that say "refetch everything of this Campaign" (never an id). */
export const BROADCAST_DOMAINS = new Set(["visibility", "role"]);

// Query keys that hold this Campaign's rows without the Campaign id at
// position 1 (cross-Campaign lists and item details).
export const CROSS_CAMPAIGN_KEYS = new Set([
  "journals",
  "journal",
  "chat-sessions",
  "campaigns",
  "tags",
  "npc-entries",
  "quest-entries",
]);

// Existing query keys whose name differs from the event domain.
const DOMAIN_ALIASES: Record<string, (campaignId: string, id: string | null) => QueryKey[]> = {
  journal: (_c, id) => [["journals"], id ? ["journal", id] : ["journal"]],
  character_sheets: (c) => [["characterSheets", c]],
  session_plans: (c) => [["session-plans", c]],
};

export function campaignRoleQueryKey(campaignId: string): QueryKey {
  return campaignRoleKey(campaignId);
}

/** True for a query that holds data of `campaignId` (refetched on resync). */
export function isCampaignQuery(queryKey: QueryKey, campaignId: string): boolean {
  if (queryKey[1] === campaignId) return true;
  return typeof queryKey[0] === "string" && CROSS_CAMPAIGN_KEYS.has(queryKey[0]);
}

export function parseInvalidation(data: unknown): Invalidation | null {
  if (!data || typeof data !== "object") return null;
  const { domain, id } = data as { domain?: unknown; id?: unknown };
  if (typeof domain !== "string" || domain.length === 0) return null;
  if (id !== null && id !== undefined && typeof id !== "string") return null;
  return { domain, id: typeof id === "string" ? id : null };
}

export interface Refetch {
  all: boolean;
  keys: QueryKey[];
}

/** The query keys one invalidation refetches; `all` means every Campaign query. */
export function invalidationKeys(inv: Invalidation, campaignId: string): Refetch {
  const keys: QueryKey[] = [[inv.domain, campaignId]];
  if (inv.domain === "role") keys.push(campaignRoleQueryKey(campaignId));
  const alias = DOMAIN_ALIASES[inv.domain];
  if (alias) keys.push(...alias(campaignId, inv.id));
  return { all: BROADCAST_DOMAINS.has(inv.domain), keys };
}

function refetchCampaign(queryClient: QueryClient, campaignId: string): void {
  void queryClient.invalidateQueries({ predicate: (q) => isCampaignQuery(q.queryKey, campaignId) });
}

/**
 * Apply one frame to the query cache and say what it was. Refetches are
 * started, not awaited: the stream keeps being read while they run.
 */
export function applyFrame(
  queryClient: QueryClient,
  campaignId: string,
  frame: SseFrame,
): "subscribed" | "invalidate" | "access_changed" | "other" {
  if (frame.event === "subscribed") {
    refetchCampaign(queryClient, campaignId);
    return "subscribed";
  }
  if (frame.event === "access_changed") {
    void queryClient.invalidateQueries({ queryKey: campaignRoleQueryKey(campaignId) });
    return "access_changed";
  }
  if (frame.event !== "invalidate") return "other";
  const inv = parseInvalidation(frame.data);
  if (!inv) return "other";
  const { all, keys } = invalidationKeys(inv, campaignId);
  for (const queryKey of keys) void queryClient.invalidateQueries({ queryKey });
  if (all) refetchCampaign(queryClient, campaignId);
  return "invalidate";
}

// ─── The loop (lib/sse.ts) ───────────────────────────────────────────────────

export interface RunOptions {
  campaignId: string;
  queryClient: QueryClient;
  signal: AbortSignal;
  /** One connection (default lib/sse.ts `connectSse`); a seam for checks. */
  open?: Connect;
  headers?: () => Record<string, string> | null;
  sleep?: (ms: number, signal: AbortSignal) => Promise<void>;
  random?: () => number;
  /** Called once when the loop stops for good (not on abort). */
  onStop?: (reason: string) => void;
}

/** Connect, apply frames, reconnect per lib/sse.ts `nextStep`, until stopped or aborted. */
export function runCampaignEvents({
  campaignId,
  queryClient,
  signal,
  open,
  headers,
  sleep,
  random,
  onStop,
}: RunOptions): Promise<string> {
  return openSse(EVENTS_PATH(campaignId), {
    signal,
    connect: open,
    headers,
    sleep,
    random,
    onEvent: (frame) => void applyFrame(queryClient, campaignId, frame),
    onStop: (reason) => {
      if (reason === "401" || reason === "404") {
        // No account, or no longer a Member: let the screens notice (role and Campaign data).
        void queryClient.invalidateQueries({ queryKey: campaignRoleQueryKey(campaignId) });
        refetchCampaign(queryClient, campaignId);
      }
      onStop?.(reason);
    },
  });
}

// ─── React ───────────────────────────────────────────────────────────────────

/**
 * Keep `campaignId`'s queries fresh from the server's event stream while
 * mounted. Reopens when the Campaign or preview changes; does nothing
 * without a Campaign or a token.
 */
export function useCampaignEvents(campaignId: string | null | undefined): void {
  const queryClient = useQueryClient();
  const previewing = useSyncExternalStore(subscribePreview, getPreviewCampaignId, getPreviewCampaignId);
  useEffect(() => {
    if (!campaignId) return;
    const controller = new AbortController();
    void runCampaignEvents({ campaignId, queryClient, signal: controller.signal });
    return () => controller.abort();
  }, [campaignId, queryClient, previewing]);
}

/** Mounted once in the app shell: the current Campaign's event stream. */
export function CampaignEventsSubscriber(): null {
  const { current } = useCurrentCampaign();
  useCampaignEvents(current?.id);
  return null;
}
