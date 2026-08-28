import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import * as api from "../services/api";
import type { ShareToken, ShareKind, CampaignMember } from "../types";

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
    mutationFn: (kind: ShareKind) => api.createShareToken(campaign_id, kind),
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

export function useCampaignMembers(campaign_id: string) {
  return useQuery<CampaignMember[]>({
    queryKey: ["campaignMembers", campaign_id],
    queryFn: async () => {
      const { data } = await api.getCampaignMembers(campaign_id);
      return data;
    },
    enabled: !!campaign_id,
  });
}

export function useRemoveCampaignMember(campaign_id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ memberId, deleteEntries }: { memberId: string; deleteEntries?: boolean }) =>
      api.removeCampaignMember(campaign_id, memberId, deleteEntries),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["campaignMembers", campaign_id] }),
  });
}
