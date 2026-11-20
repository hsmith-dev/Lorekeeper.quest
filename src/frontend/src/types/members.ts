// Members API types (E0-Access). E0-Access.2 ships the caller's own Role;
// E0-Access.12 the Members list and Role change.

import type { GrantRole, MemberRole } from "../lib/members";

export type { GrantRole, MemberRole };

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

/**
 * One row of `GET /api/campaigns/{id}/members`: the Owner first
 * (`member_id: null`, `role: "owner"`), then the Members by `joined_at`.
 */
export interface CampaignMember {
  member_id: string | null;
  user_id: string;
  display_name: string;
  role: MemberRole;
  joined_at: string;
}

/** `PATCH /api/campaigns/{id}/members/{member_id}` body. */
export interface MemberRoleUpdate {
  role: GrantRole;
}
