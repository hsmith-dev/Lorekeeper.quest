export type Genre = "fantasy" | "scifi" | "horror" | "videogame" | "other";

export interface UserProfile {
  id: string;
  email: string;
  display_name: string;
  avatar_data: string | null;
  access_granted: boolean;
  access_source: "promo" | "subscription" | "grandfathered" | null;
  is_admin: boolean;
  has_completed_tutorial: boolean;
}
export type TagType = "character" | "location" | "item" | "quest" | "faction";

export interface User {
  id: string;
  email: string;
  display_name: string;
}

export interface AuthToken {
  access_token: string;
  token_type: string;
  user_id: string;
  display_name: string;
  access_granted: boolean;
}

export type SubscriptionPlan = "byok" | "hosted";

export interface BillingStatus {
  access_granted: boolean;
  access_source: "promo" | "subscription" | "grandfathered" | null;
  subscription_status: "incomplete" | "active" | "past_due" | "canceled" | "unpaid" | null;
  plan: SubscriptionPlan | null;
  tokens_used_current_period: number | null;
  tokens_included_per_period: number | null;
  current_period_end: string | null;
  stripe_configured: boolean;
  promo_code_used: string | null;
}

export interface Campaign {
  id: string;
  name: string;
  genre: Genre;
  description: string | null;
  created_at: string;
  is_owner: boolean;
  // Only set when is_owner is false — who shared this campaign with you.
  // Two campaigns (yours and a shared one) can share a name, so the UI needs
  // this to tell them apart.
  owner_display_name: string | null;
}

export type ShareKind = "read_only" | "collaborate";

export interface ShareToken {
  id: string;
  token: string;
  kind: ShareKind;
  revoked: boolean;
  created_at: string;
}

export interface PublicCampaign {
  id: string;
  name: string;
  genre: Genre;
  description: string | null;
  share_kind: ShareKind;
}

export interface JoinCampaignResult {
  campaign_id: string;
  campaign_name: string;
  already_member: boolean;
}

export interface CampaignMember {
  id: string;
  user_id: string;
  display_name: string;
  email: string;
  created_at: string;
}

export interface TagCategoryRef {
  id: string;
  name: string;
  campaign_id: string;
  created_at: string;
}

export interface Tag {
  id: string;
  name: string;
  tag_type: TagType | null;
  custom_category: TagCategoryRef | null;
}

export interface TagWithCount extends Tag {
  entry_count: number;
}

export interface JournalEntry {
  id: string;
  campaign_id: string;
  shorthand: string;
  narrative: string;
  session_date: string | null;
  tags: Tag[];
  created_at: string;
}

export interface JournalListResponse {
  items: JournalEntry[];
  total: number;
  page: number;
  limit: number;
}

export interface GenerateRequest {
  notes: string;
  campaign_id: string;
  session_date?: string;
  entry_hash: string;
  // The (possibly user-edited) narrative from a prior draft generation —
  // when set, the backend saves it as-is instead of generating one.
  narrative?: string;
}

export interface GenerateDraftRequest {
  notes: string;
  campaign_id: string;
}

export interface GenerateDraftResponse {
  narrative: string;
}

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

export interface ChatRequest {
  message: string;
  campaign_id?: string;
  session_id?: string;
}

export interface JournalSource {
  distance?: number | null;
  method?: string | null;
  id: string;
  snippet: string;
  session_date: string | null;
  shorthand: string;
}

export interface ChatResponse {
  reply: string;
  session_id: string;
  sources: JournalSource[];
  canon_sources: string[];
  // False when a campaign was selected but nothing relevant was retrieved —
  // the reply is model invention, not campaign record; the UI labels it.
  grounded: boolean;
  retrieval?: RetrievalDebug | null;
}

export interface WeeklyCount {
  week_start: string;
  count: number;
}

export interface TagCount {
  name: string;
  count: number;
}

export interface CampaignAnalytics {
  total_entries: number;
  avg_entry_length: number;
  entries_per_week: WeeklyCount[];
  top_characters: TagCount[];
  top_quests: TagCount[];
}

export interface SourceDocument {
  id: string;
  campaign_id: string;
  title: string;
  filename: string;
  chunk_count: number;
  created_at: string;
}

export interface ChatSessionSummary {
  id: string;
  title: string;
  campaign_id: string | null;
  campaign_name: string | null;
  message_count: number;
  created_at: string;
  updated_at: string;
}

export interface ChatSessionDetail extends ChatSessionSummary {
  messages: ChatMessage[];
}

export type NpcRole = "npc" | "pc" | "monster" | "faction";
export type NpcStatus = "alive" | "dead" | "unknown";

export interface NpcEntry {
  id: string;
  campaign_id: string;
  name: string;
  role: NpcRole;
  status: NpcStatus;
  description: string | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
}

export type CharacterFieldType = "text" | "number" | "long_text" | "list";

export interface CharacterTemplateField {
  key: string;
  label: string;
  type: CharacterFieldType;
}

export interface CharacterSheetTemplate {
  id: string;
  campaign_id: string;
  name: string;
  fields: CharacterTemplateField[];
  character_count: number;
  created_at: string;
  updated_at: string;
}

export type CharacterFieldValue = string | number | string[] | null;

export interface CharacterSheet {
  id: string;
  campaign_id: string;
  template_id: string;
  name: string;
  data: Record<string, CharacterFieldValue>;
  created_at: string;
  updated_at: string;
}

export type LLMProvider = "kobold" | "openai" | "anthropic" | "gemini" | "custom";
export type HostedModelVariant = "finetuned" | "base";

export interface LLMSettings {
  llm_provider: LLMProvider;
  llm_api_url: string | null;
  llm_api_key_set: boolean;
  llm_model: string | null;
  llm_temperature: number;
  llm_max_tokens: number;
  narrative_paragraph_limit: number | null;
  hosted_model_variant: HostedModelVariant;
}

export interface LLMSettingsUpdate {
  llm_provider?: LLMProvider;
  llm_api_url?: string;
  llm_api_key?: string;
  llm_model?: string;
  llm_temperature?: number;
  llm_max_tokens?: number;
  narrative_paragraph_limit?: number;
  hosted_model_variant?: HostedModelVariant;
}

export interface JournalLite {
  id: string;
  shorthand: string;
  session_date: string | null;
  created_at: string;
}

export type QuestStatus = "active" | "completed" | "failed" | "abandoned";

export interface Quest {
  id: string;
  campaign_id: string;
  title: string;
  description: string | null;
  notes: string | null;
  status: QuestStatus;
  created_at: string;
  updated_at: string;
}

export interface ShorthandTerm {
  id: string;
  campaign_id: string;
  term: string;
  meaning: string;
  usage: string | null;
  created_at: string;
  updated_at: string;
}

export interface SessionPlan {
  id: string;
  campaign_id: string;
  title: string;
  content: string;
  created_at: string;
  updated_at: string;
}

export type FeedbackCategory = "bug" | "model_quality" | "feature_request" | "other";

export interface Feedback {
  id: string;
  category: FeedbackCategory;
  message: string;
  campaign_id: string | null;
  created_at: string;
}

export interface FeedbackAdmin extends Feedback {
  user_email: string;
  user_display_name: string;
  campaign_name: string | null;
}

export interface AdminUser {
  id: string;
  email: string;
  display_name: string;
  created_at: string;
  access_granted: boolean;
  access_source: "promo" | "subscription" | "grandfathered" | null;
  is_suspended: boolean;
  suspended_reason: string | null;
  is_admin: boolean;
  subscription_plan: SubscriptionPlan | null;
  subscription_status: string | null;
  tokens_used_current_period: number | null;
  tokens_included_per_period: number | null;
  promo_code_used: string | null;
  campaign_count: number;
  journal_entry_count: number;
}

export interface PromoCodeRedemption {
  user_id: string;
  user_email: string;
  user_display_name: string;
  redeemed_at: string;
}

export interface PromoCodeAdmin {
  id: string;
  code: string;
  active: boolean;
  max_redemptions: number | null;
  redemption_count: number;
  expires_at: string | null;
  note: string | null;
  grants_plan: SubscriptionPlan;
  created_at: string;
  redemptions: PromoCodeRedemption[];
}

export interface FeedbackContext {
  campaign_id: string;
  campaign_name: string;
  campaign_genre: string;
  campaign_description: string | null;
  recent_journal_narratives: string[];
  npc_names: string[];
  quest_titles: string[];
  source_document_titles: string[];
}

export interface ModelEvaluation {
  id: string;
  label: string;
  sample_size: number;
  avg_length: number;
  avg_word_overlap: number;
  avg_semantic_similarity: number | null;
  has_content_pct: number;
  error_count: number;
  created_at: string;
}

export interface AdminConfig {
  open_access_mode: boolean;
  stripe_configured: boolean;
}

export interface ManagedModelStatus {
  name: string;
  installed: boolean;
  source: string;
}

export interface ModelLibrary {
  ollama_url: string;
  ollama_reachable: boolean;
  ollama_error: string | null;
  installed_models: string[];
  finetuned: ManagedModelStatus;
  base: ManagedModelStatus;
}

export interface ModelStatus {
  uses_local_default: boolean;
  server_reachable: boolean;
  model_installed: boolean;
  model_name: string;
}

export interface AdminLogs {
  source: "file" | "memory";
  lines: string[];
}

export interface RetrievalCandidate {
  id: string;
  shorthand: string;
  session_date: string | null;
  vector_distance: number | null;
  lexical_rank: number | null;
  rrf_score: number;
  passed_gate: boolean;
  used: boolean;
}

export interface RetrievalDebug {
  query: string;
  rewritten_from: string | null;
  threshold: number;
  candidates: RetrievalCandidate[];
  system_prompt: string | null;
}
