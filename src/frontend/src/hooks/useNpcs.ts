import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import * as api from "../services/api";
import type { NpcEntry, JournalLite } from "../types";

export function useNpcs(campaign_id: string) {
  return useQuery<NpcEntry[]>({
    queryKey: ["npcs", campaign_id],
    queryFn: async () => {
      const { data } = await api.getNpcs(campaign_id);
      return data;
    },
    enabled: !!campaign_id,
  });
}

export function useCreateNpc() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: Parameters<typeof api.createNpc>[0]) => api.createNpc(data),
    onSuccess: (_, vars) => qc.invalidateQueries({ queryKey: ["npcs", vars.campaign_id] }),
  });
}

export function useUpdateNpc(campaign_id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: Parameters<typeof api.updateNpc>[1] }) =>
      api.updateNpc(id, data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["npcs", campaign_id] }),
  });
}

export function useDeleteNpc(campaign_id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.deleteNpc(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["npcs", campaign_id] }),
  });
}

export function useExtractNpcs() {
  return useMutation({
    mutationFn: (campaign_id: string) => api.extractNpcs(campaign_id),
  });
}

export function useNpcEntries(npc_id: string | null) {
  return useQuery<JournalLite[]>({
    queryKey: ["npc-entries", npc_id],
    queryFn: async () => {
      const { data } = await api.getNpcEntries(npc_id!);
      return data;
    },
    enabled: !!npc_id,
  });
}

export function useGenerateNpcBio(campaign_id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (npc_id: string) => api.generateNpcBio(npc_id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["npcs", campaign_id] }),
  });
}
