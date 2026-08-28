import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import * as api from "../services/api";
import type { ShorthandTerm } from "../types";

export function useShorthandTerms(campaign_id: string) {
  return useQuery<ShorthandTerm[]>({
    queryKey: ["shorthand", campaign_id],
    queryFn: async () => {
      const { data } = await api.getShorthand(campaign_id);
      return data;
    },
    enabled: !!campaign_id,
  });
}

export function useCreateShorthand(campaign_id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: { term: string; meaning: string; usage?: string }) =>
      api.createShorthand({ campaign_id, ...data }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["shorthand", campaign_id] }),
  });
}

export function useUpdateShorthand(campaign_id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: Partial<{ term: string; meaning: string; usage: string }> }) =>
      api.updateShorthand(id, data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["shorthand", campaign_id] }),
  });
}

export function useDeleteShorthand(campaign_id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.deleteShorthand(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["shorthand", campaign_id] }),
  });
}
