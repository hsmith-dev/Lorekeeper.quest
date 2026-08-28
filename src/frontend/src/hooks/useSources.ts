import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import * as api from "../services/api";
import type { SourceDocument } from "../types";

export function useSources(campaign_id: string) {
  return useQuery<SourceDocument[]>({
    queryKey: ["sources", campaign_id],
    queryFn: async () => {
      const { data } = await api.getSources(campaign_id);
      return data;
    },
    enabled: !!campaign_id,
  });
}

export function useUploadSource(campaign_id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ file, title }: { file: File; title?: string }) =>
      api.uploadSource(campaign_id, file, title),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["sources", campaign_id] }),
  });
}

export function useDeleteSource(campaign_id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.deleteSource(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["sources", campaign_id] }),
  });
}
