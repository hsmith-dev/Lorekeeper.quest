import { useQuery } from "@tanstack/react-query";

import type { CampaignRole } from "@/components/ui/role-badge";
import { getMyCampaignRole } from "../services/api/members";
import type { CampaignRoleMe } from "../types/members";

// The caller's Role in one Campaign, from GET /api/campaigns/{id}/me
// (E0-Access.2, AR-24).
//
// Cosmetic only: it decides which controls to show, never what data a user
// may read or change. The server checks the Role on every request (AD-13).

export interface CampaignRoleState {
  role: CampaignRole;
  isOwner: boolean;
  /** GM or Co-GM. */
  isGm: boolean;
  isLoading: boolean;
}

export interface CampaignRoleQueryState extends CampaignRoleState {
  /** The /me body, once loaded. */
  me: CampaignRoleMe | undefined;
  isError: boolean;
}

/** React Query key for a campaign's /me. */
export function campaignRoleKey(campaignId: string | null | undefined) {
  return ["campaignRole", campaignId] as const;
}

export function isGmRole(role: CampaignRole): boolean {
  return role === "gm" || role === "co_gm";
}

/**
 * Map a `GET /api/campaigns/{id}/me` body to a CampaignRole.
 * `{role:"gm", display_role:"Co-GM"}` → co_gm, `{role:"gm"}` → gm, anything
 * else → player. Unknown values degrade to the least-privileged role (D-1b).
 */
export function roleFromMe(me: unknown): CampaignRole {
  if (!me || typeof me !== "object") return "player";
  const { role, display_role } = me as { role?: unknown; display_role?: unknown };
  if (role !== "gm") return "player";
  if (typeof display_role === "string" && display_role.trim().toLowerCase() === "co-gm") return "co_gm";
  return "gm";
}

/** Role state for a /me body (or none yet: player). */
export function campaignRoleState(me: unknown, isLoading = false): CampaignRoleState {
  const role = roleFromMe(me);
  const isOwner =
    role === "gm" && !!me && typeof me === "object" && (me as { is_owner?: unknown }).is_owner === true;
  return { role, isOwner, isGm: isGmRole(role), isLoading };
}

/**
 * `{role, isOwner, isGm, isLoading}` for `campaignId`, backed by
 * GET /api/campaigns/{id}/me under the key `["campaignRole", campaignId]`.
 * Until it loads (or when it fails) the role is player; `useRoleFor` falls
 * back to the campaign-list stub instead.
 */
export function useCampaignRole(campaignId: string | null | undefined): CampaignRoleQueryState {
  const query = useQuery<CampaignRoleMe>({
    queryKey: campaignRoleKey(campaignId),
    queryFn: async () => (await getMyCampaignRole(campaignId as string)).data,
    enabled: !!campaignId,
    staleTime: 60_000,
    // A 404 means "not a member": retrying will not change it.
    retry: (count, error) => (error as { response?: { status?: number } })?.response?.status !== 404 && count < 2,
  });
  return {
    ...campaignRoleState(query.data, query.isLoading),
    me: query.data,
    isError: query.isError,
  };
}
