import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import * as api from "../services/api";
import type { AdminUser, PromoCodeAdmin } from "../types";

// All admin-gated server-side (see app/api/deps.py::require_admin) — these
// hooks don't self-guard, callers are expected to be inside AdminPage,
// which does the is_admin check once for every tab.

export function useAdminUsers() {
  return useQuery<AdminUser[]>({
    queryKey: ["admin-users"],
    queryFn: async () => (await api.listAdminUsers()).data,
  });
}

export function useSuspendUser() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, reason }: { id: string; reason?: string }) => api.suspendUser(id, reason),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin-users"] }),
  });
}

export function useUnsuspendUser() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.unsuspendUser(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin-users"] }),
  });
}

export function useMessageUser() {
  return useMutation({
    mutationFn: ({ id, subject, message }: { id: string; subject: string; message: string }) =>
      api.messageUser(id, subject, message),
  });
}

export function useDeleteUser() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.deleteUser(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin-users"] }),
  });
}

export function useSetUserAccess() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, access_granted, plan }: { id: string; access_granted: boolean; plan?: "byok" | "hosted" | null }) =>
      api.setUserAccess(id, access_granted, plan),
    // Also invalidate billing-status and me: an admin frequently uses this on
    // their own account (to test a tier, or to grant themselves access), and
    // without this both the Settings → Billing section and access_granted
    // itself (which TutorialWelcomePrompt/NavBar read from "me") keep
    // showing the pre-change state until their staleTime lapses.
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["admin-users"] });
      qc.invalidateQueries({ queryKey: ["billing-status"] });
      qc.invalidateQueries({ queryKey: ["me"] });
    },
  });
}

export function usePromoteUser() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.promoteUser(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin-users"] }),
  });
}

export function useDemoteUser() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.demoteUser(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin-users"] }),
  });
}

export function useAdminPromoCodes() {
  return useQuery<PromoCodeAdmin[]>({
    queryKey: ["admin-promo-codes"],
    queryFn: async () => (await api.listAdminPromoCodes()).data,
  });
}

export function useCreatePromoCode() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: {
      code: string;
      max_redemptions?: number | null;
      expires_at?: string | null;
      note?: string | null;
      grants_plan?: "byok" | "hosted";
    }) => api.createAdminPromoCode(data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin-promo-codes"] }),
  });
}

export function useUpdatePromoCode() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      id,
      data,
    }: {
      id: string;
      data: Partial<{
        active: boolean;
        max_redemptions: number | null;
        expires_at: string | null;
        note: string | null;
        grants_plan: "byok" | "hosted";
      }>;
    }) => api.updateAdminPromoCode(id, data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin-promo-codes"] }),
  });
}

export function useDeletePromoCode() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.deleteAdminPromoCode(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin-promo-codes"] }),
  });
}

export function useAdminConfig() {
  return useQuery<import("../types").AdminConfig>({
    queryKey: ["admin-config"],
    queryFn: async () => (await api.getAdminConfig()).data,
  });
}

export function useAdminModels() {
  return useQuery<import("../types").ModelLibrary>({
    queryKey: ["admin-models"],
    queryFn: async () => (await api.getAdminModels()).data,
  });
}

export function useAdminLogs(enabled: boolean) {
  return useQuery<import("../types").AdminLogs>({
    queryKey: ["admin-logs"],
    queryFn: async () => (await api.getAdminLogs(200)).data,
    enabled,
    refetchOnWindowFocus: false,
  });
}

export function useUpdateAdminConfig() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (data: { open_access_mode: boolean }) => (await api.updateAdminConfig(data)).data,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin-config"] }),
  });
}
