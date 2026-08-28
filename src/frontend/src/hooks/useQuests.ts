import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import * as api from "../services/api";
import type { Quest, JournalLite } from "../types";

export function useQuests(campaign_id: string) {
  return useQuery<Quest[]>({
    queryKey: ["quests", campaign_id],
    queryFn: async () => {
      const { data } = await api.getQuests(campaign_id);
      return data;
    },
    enabled: !!campaign_id,
  });
}

export function useCreateQuest() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: Parameters<typeof api.createQuest>[0]) => api.createQuest(data),
    onSuccess: (_, vars) => qc.invalidateQueries({ queryKey: ["quests", vars.campaign_id] }),
  });
}

export function useUpdateQuest(campaign_id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: Parameters<typeof api.updateQuest>[1] }) =>
      api.updateQuest(id, data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["quests", campaign_id] }),
  });
}

export function useDeleteQuest(campaign_id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.deleteQuest(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["quests", campaign_id] }),
  });
}

export function useSuggestQuests() {
  return useMutation({
    mutationFn: (campaign_id: string) => api.suggestQuests(campaign_id),
  });
}

export function useQuestEntries(quest_id: string | null) {
  return useQuery<JournalLite[]>({
    queryKey: ["quest-entries", quest_id],
    queryFn: async () => {
      const { data } = await api.getQuestEntries(quest_id!);
      return data;
    },
    enabled: !!quest_id,
  });
}

export function useGenerateQuestDescription(campaign_id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (quest_id: string) => api.generateQuestDescription(quest_id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["quests", campaign_id] }),
  });
}
