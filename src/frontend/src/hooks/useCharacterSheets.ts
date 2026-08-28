import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import * as api from "../services/api";
import type { CharacterSheetTemplate, CharacterSheet, CharacterTemplateField, CharacterFieldValue } from "../types";

export function useCharacterTemplates(campaign_id: string | undefined) {
  return useQuery<CharacterSheetTemplate[]>({
    queryKey: ["characterTemplates", campaign_id],
    queryFn: async () => (await api.getCharacterTemplates(campaign_id!)).data,
    enabled: !!campaign_id,
  });
}

export function useCreateCharacterTemplate(campaign_id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: { name: string; fields: CharacterTemplateField[] }) =>
      api.createCharacterTemplate({ campaign_id, ...data }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["characterTemplates", campaign_id] }),
  });
}

export function useUpdateCharacterTemplate(campaign_id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: Partial<{ name: string; fields: CharacterTemplateField[] }> }) =>
      api.updateCharacterTemplate(id, data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["characterTemplates", campaign_id] }),
  });
}

export function useDeleteCharacterTemplate(campaign_id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.deleteCharacterTemplate(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["characterTemplates", campaign_id] });
      qc.invalidateQueries({ queryKey: ["characterSheets", campaign_id] });
    },
  });
}

export function useCharacterSheets(campaign_id: string | undefined) {
  return useQuery<CharacterSheet[]>({
    queryKey: ["characterSheets", campaign_id],
    queryFn: async () => (await api.getCharacterSheets(campaign_id!)).data,
    enabled: !!campaign_id,
  });
}

export function useCreateCharacterSheet(campaign_id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: { template_id: string; name: string; data: Record<string, CharacterFieldValue> }) =>
      api.createCharacterSheet({ campaign_id, ...data }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["characterSheets", campaign_id] }),
  });
}

export function useUpdateCharacterSheet(campaign_id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: Partial<{ name: string; data: Record<string, CharacterFieldValue> }> }) =>
      api.updateCharacterSheet(id, data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["characterSheets", campaign_id] }),
  });
}

export function useDeleteCharacterSheet(campaign_id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.deleteCharacterSheet(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["characterSheets", campaign_id] }),
  });
}
