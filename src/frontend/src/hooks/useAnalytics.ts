import { useQuery } from "@tanstack/react-query";
import * as api from "../services/api";
import type { CampaignAnalytics } from "../types";

export function useCampaignAnalytics(campaign_id: string) {
  return useQuery<CampaignAnalytics>({
    queryKey: ["analytics", campaign_id],
    queryFn: async () => {
      const { data } = await api.getCampaignAnalytics(campaign_id);
      return data;
    },
    enabled: !!campaign_id,
  });
}
