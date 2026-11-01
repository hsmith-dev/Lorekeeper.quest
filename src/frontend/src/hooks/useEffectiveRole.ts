import { usePreview } from "@/contexts/PreviewContext";
import type { CampaignRole } from "@/components/ui/role-badge";
import { useCurrentCampaign } from "./useCurrentCampaign";
import { campaignRoleState, isGmRole, useCampaignRole, type CampaignRoleState } from "./useCampaignRole";
import type { Campaign } from "../types";

// The user's Role in a campaign, for the shell (E0-UX.7, E0-Access.2).
//
// Roles here are cosmetic: they decide which controls to show, never what data
// a user may read or change. The server enforces membership and role on every
// request (AD-13), so a wrong value here can only make the UI look wrong.
//
// `useRoleFor` is the single seam. It reads `useCampaignRole(campaign.id)`
// (GET /api/campaigns/{id}/me, key ["campaignRole", id]); while that loads, or
// when it fails, the role is stubbed from the campaign list's `is_owner`:
// owners are GM, everyone else Player.

export { campaignRoleState, isGmRole, roleFromMe } from "./useCampaignRole";
export type { CampaignRoleState } from "./useCampaignRole";

export interface EffectiveRoleState extends CampaignRoleState {
  /** "Preview as Player" is on, so `role` is forced to player. */
  previewing: boolean;
}

/** Stub role (no /me answer): owner = GM, anyone else (or unknown) = Player. */
export function stubRole(campaign: Pick<Campaign, "is_owner"> | null | undefined): CampaignRole {
  return campaign?.is_owner === true ? "gm" : "player";
}

/** Stub role state for one campaign, shaped like useCampaignRole's. */
export function roleStateFor(campaign: Campaign | null | undefined): CampaignRoleState {
  const role = stubRole(campaign);
  return { role, isOwner: campaign?.is_owner === true, isGm: isGmRole(role), isLoading: false };
}

/**
 * The real (not preview-adjusted) role in `campaign`: the /me answer when
 * there is one, else the stub (loading, failed, or no campaign).
 */
export function useRoleFor(campaign: Campaign | null | undefined): CampaignRoleState {
  const fromMe = useCampaignRole(campaign?.id);
  if (fromMe.me !== undefined) return campaignRoleState(fromMe.me, false);
  return { ...roleStateFor(campaign), isLoading: fromMe.isLoading };
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
