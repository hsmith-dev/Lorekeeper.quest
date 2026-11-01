// Members API types (E0-Access). E0-Access.12 adds invite / change Role /
// remove; E0-Access.2 ships the caller's own Role.

/**
 * `GET /api/campaigns/{id}/me`: the caller's Role in one Campaign.
 * `role` is the server's ctx Role (the Owner and a Co-GM are both "gm");
 * `display_role` is the label to show.
 */
export interface CampaignRoleMe {
  campaign_id: string;
  role: "gm" | "player";
  is_owner: boolean;
  display_role: "Owner" | "Co-GM" | "Player";
}
