// Members API client (E0-Access). Uses the shared axios instance in
// services/api.ts (auth header, preview header, 401/402 handling).
import api from "../api";
import type { CampaignMember, CampaignRoleMe, GrantRole } from "../../types/members";

/** The caller's Role in `campaignId`. 404 when they are not the Owner or a Member. */
export const getMyCampaignRole = (campaignId: string) =>
  api.get<CampaignRoleMe>(`/api/campaigns/${encodeURIComponent(campaignId)}/me`);

const membersUrl = (campaignId: string) => `/api/campaigns/${encodeURIComponent(campaignId)}/members`;

/** The Owner row first (`member_id: null`), then the Members. Owner only. */
export const getCampaignMembers = (campaignId: string) => api.get<CampaignMember[]>(membersUrl(campaignId));

/** Set a Member's Role. A co_gm → player demotion archives their chat sessions. */
export const changeMemberRole = (campaignId: string, memberId: string, role: GrantRole) =>
  api.patch<CampaignMember>(`${membersUrl(campaignId)}/${encodeURIComponent(memberId)}`, { role });

/** Remove a Member; `deleteEntries` also deletes every entry they wrote here. */
export const removeCampaignMember = (campaignId: string, memberId: string, deleteEntries = false) =>
  api.delete(`${membersUrl(campaignId)}/${encodeURIComponent(memberId)}`, {
    params: { delete_entries: deleteEntries },
  });
