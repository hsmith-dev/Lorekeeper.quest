import { useQuery, useMutation, useQueryClient, type QueryClient } from "@tanstack/react-query";
import * as api from "../services/api";
import { changeMemberRole, getCampaignMembers, removeCampaignMember } from "../services/api/members";
import type { ShareToken, ShareTokenCreate, CampaignMember } from "../types";
import type { GrantRole } from "../types/members";
import { campaignRoleKey } from "./useCampaignRole";

export function useShareTokens(campaign_id: string) {
  return useQuery<ShareToken[]>({
    queryKey: ["shareTokens", campaign_id],
    queryFn: async () => {
      const { data } = await api.getShareTokens(campaign_id);
      return data;
    },
    enabled: !!campaign_id,
  });
}

export function useCreateShareToken(campaign_id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: ShareTokenCreate) => api.createShareToken(campaign_id, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["shareTokens", campaign_id] }),
  });
}

export function useRevokeShareToken(campaign_id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (token_id: string) => api.revokeShareToken(campaign_id, token_id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["shareTokens", campaign_id] }),
  });
}

export function campaignMembersKey(campaign_id: string) {
  return ["campaignMembers", campaign_id] as const;
}

export function useCampaignMembers(campaign_id: string) {
  return useQuery<CampaignMember[]>({
    queryKey: campaignMembersKey(campaign_id),
    queryFn: async () => {
      const { data } = await getCampaignMembers(campaign_id);
      return data;
    },
    enabled: !!campaign_id,
  });
}

/** A Role or membership change: the Members list, the Campaign's Roles
 *  (`/me`) and the Campaign list all refetch. */
function invalidateMembership(qc: QueryClient, campaign_id: string) {
  void qc.invalidateQueries({ queryKey: campaignMembersKey(campaign_id) });
  void qc.invalidateQueries({ queryKey: campaignRoleKey(campaign_id) });
  void qc.invalidateQueries({ queryKey: ["campaigns"] });
}

export function useChangeMemberRole(campaign_id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ memberId, role }: { memberId: string; role: GrantRole }) =>
      changeMemberRole(campaign_id, memberId, role),
    onSuccess: () => invalidateMembership(qc, campaign_id),
  });
}

export function useRemoveCampaignMember(campaign_id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ memberId, deleteEntries }: { memberId: string; deleteEntries?: boolean }) =>
      removeCampaignMember(campaign_id, memberId, deleteEntries),
    onSuccess: () => invalidateMembership(qc, campaign_id),
  });
}
