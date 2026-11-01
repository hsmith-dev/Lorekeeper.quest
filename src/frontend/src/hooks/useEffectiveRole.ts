import { usePreview } from "@/contexts/PreviewContext";
import type { CampaignRole } from "@/components/ui/role-badge";
import { useCurrentCampaign } from "./useCurrentCampaign";
import type { Campaign } from "../types";

// The user's Role in a campaign, for the shell (E0-UX.7).
//
// Roles here are cosmetic: they decide which controls to show, never what data
// a user may read or change. The server enforces membership and role on every
// request (AD-13), so a wrong value here can only make the UI look wrong.
//
// Until E0-Access.2 ships `useCampaignRole` (backed by
// GET /api/campaigns/{id}/me), the role is stubbed from `is_owner`: owners are
// GM, everyone else Player. `useRoleFor` is the single seam: E0-Access.2
// replaces its body with `useCampaignRole(campaign.id)` mapped through
// `roleFromMe`. No speculative /me call is made today: the endpoint would 404,
// and 404 also means "not a member", so a probe could not tell them apart.

export interface CampaignRoleState {
  role: CampaignRole;
  isOwner: boolean;
  /** GM or Co-GM. */
  isGm: boolean;
  isLoading: boolean;
}

export interface EffectiveRoleState extends CampaignRoleState {
  /** "Preview as Player" is on, so `role` is forced to player. */
  previewing: boolean;
}

/** Stub role until E0-Access.2: owner = GM, anyone else (or unknown) = Player. */
export function stubRole(campaign: Pick<Campaign, "is_owner"> | null | undefined): CampaignRole {
  return campaign?.is_owner === true ? "gm" : "player";
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

export function isGmRole(role: CampaignRole): boolean {
  return role === "gm" || role === "co_gm";
}

/** Role state for one campaign, shaped like E0-Access.2's useCampaignRole. */
export function roleStateFor(campaign: Campaign | null | undefined): CampaignRoleState {
  const role = stubRole(campaign);
  return { role, isOwner: campaign?.is_owner === true, isGm: isGmRole(role), isLoading: false };
}

/** The real (not preview-adjusted) role in `campaign`. */
export function useRoleFor(campaign: Campaign | null | undefined): CampaignRoleState {
  // E0-Access.2: return useCampaignRole(campaign?.id) mapped through roleFromMe.
  return roleStateFor(campaign);
}

/** Force the Player view while previewing. */
export function effectiveRoleState(real: CampaignRoleState, previewing: boolean): EffectiveRoleState {
  if (!previewing) return { ...real, previewing: false };
  // Owner-gated controls must hide too: the preview shows a Player's screen.
  return { role: "player", isOwner: false, isGm: false, isLoading: real.isLoading, previewing: true };
}

/**
 * The role the UI should render for: the user's role in `campaignId` (default:
 * the current campaign), forced to `player` while "Preview as Player" is on.
 */
export function useEffectiveRole(campaignId?: string): EffectiveRoleState {
  const { current, campaigns } = useCurrentCampaign();
  const { active } = usePreview();
  const campaign =
    campaignId === undefined || campaignId === current?.id
      ? current
      : campaigns.find((c) => c.id === campaignId) ?? null;
  return effectiveRoleState(useRoleFor(campaign), active);
}
