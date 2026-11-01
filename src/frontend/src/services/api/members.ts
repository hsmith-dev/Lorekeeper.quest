// Members API client (E0-Access). Uses the shared axios instance in
// services/api.ts (auth header, preview header, 401/402 handling).
import api from "../api";
import type { CampaignRoleMe } from "../../types/members";

/** The caller's Role in `campaignId`. 404 when they are not the Owner or a Member. */
export const getMyCampaignRole = (campaignId: string) =>
  api.get<CampaignRoleMe>(`/api/campaigns/${encodeURIComponent(campaignId)}/me`);
