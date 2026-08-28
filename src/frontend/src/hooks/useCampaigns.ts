import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import * as api from "../services/api";
import type { Campaign } from "../types";

export function useCampaigns() {
  return useQuery<Campaign[]>({
    queryKey: ["campaigns"],
    queryFn: async () => {
      const { data } = await api.getCampaigns();
      return data;
    },
  });
}

export function useCreateCampaign() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: { name: string; genre: string; description?: string }) =>
      api.createCampaign(data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["campaigns"] }),
  });
}

export function useGenerateCampaignConcept() {
  return useMutation({
    mutationFn: (data: { genre: string; prompt?: string }) => api.generateCampaignConcept(data),
  });
}

export function useLeaveCampaign() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (campaignId: string) => api.leaveCampaign(campaignId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["campaigns"] }),
  });
}
