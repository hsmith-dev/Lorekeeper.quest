import { useQuery } from "@tanstack/react-query";
import * as api from "../services/api";
import type { TagWithCount } from "../types";

export function useTags(campaign_id?: string) {
  return useQuery<TagWithCount[]>({
    queryKey: ["tags", campaign_id],
    queryFn: async () => {
      const { data } = await api.getTags(campaign_id);
      return data;
    },
    enabled: !!campaign_id,
  });
}
