import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import * as api from "../services/api";
import type { GenerateRequest, JournalListResponse } from "../types";

export function useJournals(params: {
  campaign_id?: string;
  search?: string;
  tag_id?: string;
  page?: number;
  limit?: number;
}) {
  return useQuery<JournalListResponse>({
    queryKey: ["journals", params],
    queryFn: async () => {
      const { data } = await api.getJournals(params);
      return data;
    },
  });
}

export function useGenerateJournal() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (req: GenerateRequest) => api.generateJournal(req),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["journals"] }),
  });
}

export function useGenerateJournalDraft() {
  return useMutation({
    mutationFn: (req: { notes: string; campaign_id: string }) => api.generateJournalDraft(req),
  });
}

export function useDeleteJournal() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.deleteJournal(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["journals"] }),
  });
}

export function useAutocomplete() {
  return useMutation({
    mutationFn: ({ text, campaign_id }: { text: string; campaign_id?: string }) =>
      api.autocompleteNotes(text, campaign_id),
  });
}

export function useRecap() {
  return useMutation({
    mutationFn: (campaign_id: string) => api.generateRecap(campaign_id),
  });
}
