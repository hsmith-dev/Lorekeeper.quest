import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import * as api from "../services/api";
import type { SessionPlan } from "../types";

export function useSessionPlans(campaign_id: string) {
  return useQuery<SessionPlan[]>({
    queryKey: ["session-plans", campaign_id],
    queryFn: async () => {
      const { data } = await api.getSessionPlans(campaign_id);
      return data;
    },
    enabled: !!campaign_id,
  });
}

export function useGenerateSessionPlanDraft() {
  return useMutation({
    mutationFn: (data: { campaign_id: string; focus?: string }) => api.generateSessionPlanDraft(data),
  });
}

export function useCreateSessionPlan(campaign_id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: { title: string; content: string }) =>
      api.createSessionPlan({ campaign_id, ...data }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["session-plans", campaign_id] }),
  });
}

export function useUpdateSessionPlan(campaign_id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: Partial<{ title: string; content: string }> }) =>
      api.updateSessionPlan(id, data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["session-plans", campaign_id] }),
  });
}

export function useDeleteSessionPlan(campaign_id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.deleteSessionPlan(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["session-plans", campaign_id] }),
  });
}
