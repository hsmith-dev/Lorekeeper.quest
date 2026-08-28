import axios, { AxiosInstance } from "axios";

// In dev, Vite proxies /api → localhost:8000 (see vite.config.ts).
// In production, nginx serves both the frontend and proxies /api → backend.
// Either way, relative URLs work for both environments.
const api: AxiosInstance = axios.create({
  baseURL: import.meta.env.VITE_API_URL ?? "",
  headers: { "Content-Type": "application/json" },
});

api.interceptors.request.use((config) => {
  const token = localStorage.getItem("lk_token");
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

api.interceptors.response.use(
  (res) => res,
  (err) => {
    if (err.response?.status === 401) {
      localStorage.removeItem("lk_token");
      localStorage.removeItem("lk_user");
      window.location.href = "/login";
    }
    // 402 has two distinct causes that need two different destinations —
    // X-Gate-Reason (set in app/api/deps.py) tells them apart:
    //   - "account-gate" (require_active_account): access_granted is False,
    //     no promo/subscription at all → /subscribe is genuinely correct.
    //   - "llm-config" (get_user_llm_config): access_granted is True, but no
    //     personal API key and not hosted-tier-eligible (e.g. a promo/byok
    //     account trying to use the hosted model) → /subscribe is actively
    //     wrong here (they may already be subscribed/promo'd), and would
    //     just bounce them right back. /settings is where the fix actually
    //     lives (add a key, or see Billing to upgrade).
    // An untagged 402 (shouldn't happen, but if some other route ever
    // raises one without the header) falls back to /subscribe, the old
    // blanket behavior, rather than silently doing nothing.
    if (err.response?.status === 402 && !["/subscribe", "/settings", "/login", "/register"].includes(window.location.pathname)) {
      const reason = err.response?.headers?.["x-gate-reason"];
      window.location.href = reason === "llm-config" ? "/settings" : "/subscribe";
    }
    return Promise.reject(err);
  }
);

export default api;

// Auth
export const register = (email: string, password: string, display_name: string, promo_code?: string) =>
  api.post("/api/auth/register", { email, password, display_name, promo_code: promo_code || undefined });

export const login = (email: string, password: string) =>
  api.post("/api/auth/login", { email, password });

export const getMe = () =>
  api.get<import("../types").UserProfile>("/api/auth/me");

export const completeTutorial = () =>
  api.post<import("../types").UserProfile>("/api/auth/tutorial-complete");

export const forgotPassword = (email: string) =>
  api.post<{ detail: string }>("/api/auth/forgot-password", { email });

export const resetPassword = (token: string, new_password: string) =>
  api.post<{ detail: string }>("/api/auth/reset-password", { token, new_password });

export const uploadAvatar = (file: File) => {
  const form = new FormData();
  form.append("file", file);
  return api.put<import("../types").UserProfile>("/api/auth/me/avatar", form, {
    headers: { "Content-Type": "multipart/form-data" },
  });
};

// Campaigns
export const getCampaigns = () => api.get("/api/campaigns/");
export const createCampaign = (data: { name: string; genre: string; description?: string }) =>
  api.post("/api/campaigns/", data);

export const generateCampaignConcept = (data: { genre: string; prompt?: string }) =>
  api.post<{ name: string; description: string }>("/api/campaigns/generate-concept", data);

export const exportCampaign = async (campaign_id: string, format: "pdf" | "markdown") => {
  const res = await api.get(`/api/campaigns/${campaign_id}/export`, {
    params: { format },
    responseType: "blob",
  });
  const disposition: string = res.headers["content-disposition"] ?? "";
  const match = disposition.match(/filename="?([^"]+)"?/);
  const filename = match?.[1] ?? `campaign.${format === "pdf" ? "pdf" : "md"}`;
  const url = window.URL.createObjectURL(res.data);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.URL.revokeObjectURL(url);
};

export const getCampaignAnalytics = (campaign_id: string) =>
  api.get<import("../types").CampaignAnalytics>(`/api/campaigns/${campaign_id}/analytics`);

// Campaign sharing (read-only links + collaborate invites)
export const getShareTokens = (campaign_id: string) =>
  api.get<import("../types").ShareToken[]>(`/api/campaigns/${campaign_id}/share`);

export const createShareToken = (campaign_id: string, kind: import("../types").ShareKind) =>
  api.post<import("../types").ShareToken>(`/api/campaigns/${campaign_id}/share`, { kind });

export const revokeShareToken = (campaign_id: string, token_id: string) =>
  api.delete(`/api/campaigns/${campaign_id}/share/${token_id}`);

export const getCampaignMembers = (campaign_id: string) =>
  api.get<import("../types").CampaignMember[]>(`/api/campaigns/${campaign_id}/members`);

export const removeCampaignMember = (campaign_id: string, member_id: string, deleteEntries: boolean = false) =>
  api.delete(`/api/campaigns/${campaign_id}/members/${member_id}`, { params: { delete_entries: deleteEntries } });

export const leaveCampaign = (campaign_id: string) =>
  api.post(`/api/campaigns/${campaign_id}/leave`);

// Public share views (no auth required for read-only endpoints)
export const getSharedCampaign = (token: string) =>
  api.get<import("../types").PublicCampaign>(`/api/share/${token}`);

export const getSharedJournals = (token: string, page = 1) =>
  api.get<import("../types").JournalListResponse>(`/api/share/${token}/journals`, { params: { page } });

export const getSharedJournal = (token: string, journal_id: string) =>
  api.get<import("../types").JournalEntry>(`/api/share/${token}/journals/${journal_id}`);

export const getSharedNpcs = (token: string) =>
  api.get<import("../types").NpcEntry[]>(`/api/share/${token}/npcs`);

export const getSharedQuests = (token: string) =>
  api.get<import("../types").Quest[]>(`/api/share/${token}/quests`);

export const joinCampaign = (token: string) =>
  api.post<import("../types").JoinCampaignResult>(`/api/share/${token}/join`);

// Custom tag categories + manual tag attach/detach
export const getTagCategories = (campaign_id: string) =>
  api.get<import("../types").TagCategoryRef[]>(`/api/campaigns/${campaign_id}/tag-categories`);

export const createTagCategory = (campaign_id: string, name: string) =>
  api.post<import("../types").TagCategoryRef>(`/api/campaigns/${campaign_id}/tag-categories`, { name });

export const attachTag = (
  journal_id: string,
  body: { name: string; tag_type?: string; custom_category_id?: string }
) => api.post<import("../types").Tag>(`/api/journals/${journal_id}/tags`, body);

export const detachTag = (journal_id: string, tag_id: string) =>
  api.delete(`/api/journals/${journal_id}/tags/${tag_id}`);

// Model evaluation
export const runEvaluation = (
  label: string,
  sample_size: number,
  hosted_model_variant?: import("../types").HostedModelVariant
) => api.post<import("../types").ModelEvaluation>("/api/settings/evaluate", { label, sample_size, hosted_model_variant });

export const getEvaluations = () =>
  api.get<import("../types").ModelEvaluation[]>("/api/settings/evaluations");

export const deleteEvaluation = (id: string) =>
  api.delete(`/api/settings/evaluations/${id}`);

// Journals
export const generateJournal = (data: import("../types").GenerateRequest) =>
  api.post("/api/journals/generate", data);

export const generateJournalDraft = (data: import("../types").GenerateDraftRequest) =>
  api.post<import("../types").GenerateDraftResponse>("/api/journals/generate-draft", data);

export const getJournals = (params: {
  campaign_id?: string;
  search?: string;
  tag_id?: string;
  page?: number;
  limit?: number;
}) => api.get("/api/journals/", { params });

export const getJournal = (id: string) => api.get(`/api/journals/${id}`);

export const deleteJournal = (id: string) => api.delete(`/api/journals/${id}`);

// Tags
export const getTags = (campaign_id?: string) =>
  api.get("/api/tags/", { params: campaign_id ? { campaign_id } : {} });

// Chat
export const sendChatMessage = (data: import("../types").ChatRequest) =>
  api.post<import("../types").ChatResponse>("/api/chat/", data);

export const getChatHealth = () =>
  api.get<{ ai_online: boolean }>("/api/chat/health");


export const getChatSession = (id: string) =>
  api.get<import("../types").ChatSessionDetail>(`/api/chat/sessions/${id}`);

export const deleteChatSession = (id: string) =>
  api.delete(`/api/chat/sessions/${id}`);

// AI features
export const autocompleteNotes = (text: string, campaign_id?: string) =>
  api.post<{ suggestion: string }>("/api/journals/autocomplete", { text, campaign_id });

export const generateRecap = (campaign_id: string) =>
  api.post<{ recap: string }>("/api/journals/recap", { campaign_id });

// NPCs
export const getNpcs = (campaign_id: string) =>
  api.get<import("../types").NpcEntry[]>("/api/npcs/", { params: { campaign_id } });

export const createNpc = (data: {
  name: string; role: string; status: string;
  description?: string; notes?: string; campaign_id: string;
}) => api.post<import("../types").NpcEntry>("/api/npcs/", data);

export const updateNpc = (id: string, data: Partial<{ name: string; role: string; status: string; description: string; notes: string }>) =>
  api.put<import("../types").NpcEntry>(`/api/npcs/${id}`, data);

export const deleteNpc = (id: string) => api.delete(`/api/npcs/${id}`);

export const extractNpcs = (campaign_id: string) =>
  api.post<{ suggestions: string[] }>(`/api/npcs/extract?campaign_id=${campaign_id}`);

// Character sheets (templates + built characters)
export const getCharacterTemplates = (campaign_id: string) =>
  api.get<import("../types").CharacterSheetTemplate[]>("/api/character-sheets/templates", { params: { campaign_id } });

export const createCharacterTemplate = (data: {
  campaign_id: string; name: string; fields: import("../types").CharacterTemplateField[];
}) => api.post<import("../types").CharacterSheetTemplate>("/api/character-sheets/templates", data);

export const updateCharacterTemplate = (
  id: string,
  data: Partial<{ name: string; fields: import("../types").CharacterTemplateField[] }>
) => api.patch<import("../types").CharacterSheetTemplate>(`/api/character-sheets/templates/${id}`, data);

export const deleteCharacterTemplate = (id: string) => api.delete(`/api/character-sheets/templates/${id}`);

export const getCharacterSheets = (campaign_id: string) =>
  api.get<import("../types").CharacterSheet[]>("/api/character-sheets/", { params: { campaign_id } });

export const createCharacterSheet = (data: {
  campaign_id: string; template_id: string; name: string;
  data: Record<string, import("../types").CharacterFieldValue>;
}) => api.post<import("../types").CharacterSheet>("/api/character-sheets/", data);

export const updateCharacterSheet = (
  id: string,
  data: Partial<{ name: string; data: Record<string, import("../types").CharacterFieldValue> }>
) => api.patch<import("../types").CharacterSheet>(`/api/character-sheets/${id}`, data);

export const deleteCharacterSheet = (id: string) => api.delete(`/api/character-sheets/${id}`);

export const getNpc = (id: string) =>
  api.get<import("../types").NpcEntry>(`/api/npcs/${id}`);

export const getNpcEntries = (id: string) =>
  api.get<import("../types").JournalLite[]>(`/api/npcs/${id}/entries`);

export const generateNpcBio = (id: string) =>
  api.post<{ description: string }>(`/api/npcs/${id}/generate`);

// Quests
export const getQuests = (campaign_id: string) =>
  api.get<import("../types").Quest[]>("/api/quests/", { params: { campaign_id } });

export const createQuest = (data: {
  title: string; description?: string; notes?: string;
  status?: string; campaign_id: string;
}) => api.post<import("../types").Quest>("/api/quests/", data);

export const updateQuest = (id: string, data: Partial<{ title: string; description: string; notes: string; status: string }>) =>
  api.put<import("../types").Quest>(`/api/quests/${id}`, data);

export const deleteQuest = (id: string) => api.delete(`/api/quests/${id}`);

export const suggestQuests = (campaign_id: string) =>
  api.post<{ suggestions: string[] }>(`/api/quests/suggest?campaign_id=${campaign_id}`);

export const getQuest = (id: string) =>
  api.get<import("../types").Quest>(`/api/quests/${id}`);

export const getQuestEntries = (id: string) =>
  api.get<import("../types").JournalLite[]>(`/api/quests/${id}/entries`);

export const generateQuestDescription = (id: string) =>
  api.post<{ description: string }>(`/api/quests/${id}/generate`);

// Chat sessions search
export const getChatSessions = (search?: string) =>
  api.get<import("../types").ChatSessionSummary[]>("/api/chat/sessions", { params: search ? { search } : {} });

// Ingest
export const extractNotesFromImage = (file: File) => {
  const form = new FormData();
  form.append("file", file);
  return api.post<{ extracted_text: string }>("/api/ingest/image", form, {
    headers: { "Content-Type": "multipart/form-data" },
  });
};

export const transcribeVoice = (blob: Blob) => {
  const form = new FormData();
  form.append("file", blob, "recording.webm");
  return api.post<{ transcribed_text: string }>("/api/ingest/voice", form, {
    headers: { "Content-Type": "multipart/form-data" },
  });
};

export const ingestDiscord = (text: string) =>
  api.post<{ cleaned_text: string }>("/api/ingest/discord", { text });

// Source documents (RAG canon grounding)
export const getSources = (campaign_id: string) =>
  api.get<import("../types").SourceDocument[]>("/api/sources/", { params: { campaign_id } });

export const uploadSource = (campaign_id: string, file: File, title?: string) => {
  const form = new FormData();
  form.append("campaign_id", campaign_id);
  if (title) form.append("title", title);
  form.append("file", file);
  return api.post<import("../types").SourceDocument>("/api/sources/", form, {
    headers: { "Content-Type": "multipart/form-data" },
  });
};

export const deleteSource = (id: string) => api.delete(`/api/sources/${id}`);

// Session recording summarization
export const summarizeSession = (campaign_id: string, transcript: string) =>
  api.post<{ suggested_notes: string }>("/api/journals/summarize-session", { campaign_id, transcript });

// Settings
export const getLLMSettings = () =>
  api.get<import("../types").LLMSettings>("/api/settings/");

export const updateLLMSettings = (data: import("../types").LLMSettingsUpdate) =>
  api.put<import("../types").LLMSettings>("/api/settings/", data);

export const testLLMConnection = (data: {
  llm_provider: string;
  llm_api_url?: string;
  llm_api_key?: string;
  llm_model?: string;
  hosted_model_variant?: import("../types").HostedModelVariant;
}) => api.post<{ success: boolean; message: string }>("/api/settings/test", data);

export const reindexJournals = (campaign_id: string) =>
  api.post<{ reindexed: number }>(`/api/journals/reindex?campaign_id=${campaign_id}`);

// Billing (Stripe subscription — see docs/PAYMENT_PROCESSOR_SETUP.md)
export const getBillingStatus = () =>
  api.get<import("../types").BillingStatus>("/api/billing/status");

export const startCheckout = (plan: "byok" | "hosted") =>
  api.post<{ checkout_url: string }>("/api/billing/checkout", { plan });

export const openBillingPortal = () =>
  api.post<{ portal_url: string }>("/api/billing/portal");

export const redeemPromoCode = (code: string) =>
  api.post<import("../types").BillingStatus>("/api/billing/redeem-promo", { code });

// Session plans
export const generateSessionPlanDraft = (data: { campaign_id: string; focus?: string }) =>
  api.post<{ content: string }>("/api/session-plans/generate", data);

export const createSessionPlan = (data: { campaign_id: string; title: string; content: string }) =>
  api.post<import("../types").SessionPlan>("/api/session-plans/", data);

export const getSessionPlans = (campaign_id: string) =>
  api.get<import("../types").SessionPlan[]>("/api/session-plans/", { params: { campaign_id } });

export const updateSessionPlan = (id: string, data: Partial<{ title: string; content: string }>) =>
  api.put<import("../types").SessionPlan>(`/api/session-plans/${id}`, data);

export const deleteSessionPlan = (id: string) => api.delete(`/api/session-plans/${id}`);

// Shorthand glossary
export const getShorthand = (campaign_id: string) =>
  api.get<import("../types").ShorthandTerm[]>("/api/shorthand/", { params: { campaign_id } });

export const createShorthand = (data: { campaign_id: string; term: string; meaning: string; usage?: string }) =>
  api.post<import("../types").ShorthandTerm>("/api/shorthand/", data);

export const updateShorthand = (id: string, data: Partial<{ term: string; meaning: string; usage: string }>) =>
  api.put<import("../types").ShorthandTerm>(`/api/shorthand/${id}`, data);

export const deleteShorthand = (id: string) => api.delete(`/api/shorthand/${id}`);

// Feedback
export const submitFeedback = (data: { category: import("../types").FeedbackCategory; message: string; campaign_id?: string }) =>
  api.post<import("../types").Feedback>("/api/feedback/", data);

export const listFeedback = () => api.get<import("../types").FeedbackAdmin[]>("/api/feedback/");

export const getFeedbackContext = (id: string) =>
  api.get<import("../types").FeedbackContext>(`/api/feedback/${id}/context`);

// Admin — users
export const listAdminUsers = () => api.get<import("../types").AdminUser[]>("/api/admin/users");

export const suspendUser = (id: string, reason?: string) =>
  api.post<import("../types").AdminUser>(`/api/admin/users/${id}/suspend`, { reason });

export const unsuspendUser = (id: string) =>
  api.post<import("../types").AdminUser>(`/api/admin/users/${id}/unsuspend`);

export const messageUser = (id: string, subject: string, message: string) =>
  api.post<{ detail: string }>(`/api/admin/users/${id}/message`, { subject, message });

export const deleteUser = (id: string) => api.delete(`/api/admin/users/${id}`);

export const setUserAccess = (id: string, access_granted: boolean, plan?: import("../types").SubscriptionPlan | null) =>
  api.patch<import("../types").AdminUser>(`/api/admin/users/${id}/access`, { access_granted, plan });

export const promoteUser = (id: string) => api.post<import("../types").AdminUser>(`/api/admin/users/${id}/promote`);

export const demoteUser = (id: string) => api.post<import("../types").AdminUser>(`/api/admin/users/${id}/demote`);

// Admin — promo codes
export const listAdminPromoCodes = () => api.get<import("../types").PromoCodeAdmin[]>("/api/admin/promo-codes");

export const createAdminPromoCode = (data: {
  code: string;
  max_redemptions?: number | null;
  expires_at?: string | null;
  note?: string | null;
  grants_plan?: import("../types").SubscriptionPlan;
}) => api.post<import("../types").PromoCodeAdmin>("/api/admin/promo-codes", data);

export const updateAdminPromoCode = (
  id: string,
  data: Partial<{
    active: boolean;
    max_redemptions: number | null;
    expires_at: string | null;
    note: string | null;
    grants_plan: import("../types").SubscriptionPlan;
  }>
) => api.patch<import("../types").PromoCodeAdmin>(`/api/admin/promo-codes/${id}`, data);

export const deleteAdminPromoCode = (id: string) => api.delete(`/api/admin/promo-codes/${id}`);
