import { useQuery, useMutation } from "@tanstack/react-query";
import * as api from "../services/api";
import type { Feedback, FeedbackAdmin, FeedbackCategory, FeedbackContext } from "../types";

export function useSubmitFeedback() {
  return useMutation<Feedback, unknown, { category: FeedbackCategory; message: string; campaign_id?: string }>({
    mutationFn: (data) => api.submitFeedback(data).then((r) => r.data),
  });
}

// Admin-only — the underlying route 403s for anyone else, so this is only
// ever called from FeedbackInboxPage, which itself only renders when
// useAuth's profile.is_admin is true.
export function useFeedbackList(enabled: boolean = true) {
  return useQuery<FeedbackAdmin[]>({
    queryKey: ["feedback"],
    queryFn: async () => {
      const { data } = await api.listFeedback();
      return data;
    },
    enabled,
  });
}

export function useFeedbackContext(id: string | null) {
  return useQuery<FeedbackContext>({
    queryKey: ["feedback-context", id],
    queryFn: async () => {
      const { data } = await api.getFeedbackContext(id!);
      return data;
    },
    enabled: !!id,
  });
}
