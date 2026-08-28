import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import * as api from "../services/api";
import type { LLMSettings, LLMSettingsUpdate } from "../types";

export function useLLMSettings() {
  return useQuery<LLMSettings>({
    queryKey: ["llm-settings"],
    queryFn: async () => {
      const { data } = await api.getLLMSettings();
      return data;
    },
    staleTime: 60_000,
  });
}

export function useUpdateLLMSettings() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: LLMSettingsUpdate) => api.updateLLMSettings(data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["llm-settings"] }),
  });
}

export function useTestLLMConnection() {
  return useMutation({
    mutationFn: (data: {
      llm_provider: string;
      llm_api_url?: string;
      llm_api_key?: string;
      llm_model?: string;
      hosted_model_variant?: import("../types").HostedModelVariant;
    }) => api.testLLMConnection(data),
  });
}

export function useReindexJournals() {
  return useMutation({
    mutationFn: (campaign_id: string) => api.reindexJournals(campaign_id),
  });
}

// Billing (Stripe subscription)
export function useBillingStatus() {
  return useQuery({
    queryKey: ["billing-status"],
    queryFn: async () => {
      const { data } = await api.getBillingStatus();
      return data;
    },
    staleTime: 30_000,
  });
}

export function useStartCheckout() {
  return useMutation({
    mutationFn: (plan: "byok" | "hosted") => api.startCheckout(plan),
    onSuccess: ({ data }) => {
      window.location.href = data.checkout_url;
    },
  });
}

export function useOpenBillingPortal() {
  return useMutation({
    mutationFn: () => api.openBillingPortal(),
    onSuccess: ({ data }) => {
      window.location.href = data.portal_url;
    },
  });
}

export function useRedeemPromoCode() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (code: string) => api.redeemPromoCode(code),
    // "me" too, not just billing-status — access_granted lives there, and
    // TutorialWelcomePrompt/NavBar both read it. Without this, a user who
    // redeems a code and gets routed straight to /dashboard could still see
    // a stale access_granted: false for up to the query's staleTime.
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["billing-status"] });
      qc.invalidateQueries({ queryKey: ["me"] });
    },
  });
}
