import { useState, useEffect } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ThemeSelector } from "../components/ThemeSelector";
import {
  useLLMSettings,
  useUpdateLLMSettings,
  useTestLLMConnection,
  useReindexJournals,
  useBillingStatus,
  useOpenBillingPortal,
} from "../hooks/useSettings";
import { Link } from "react-router-dom";
import { useCampaigns } from "../hooks/useCampaigns";
import { useTour } from "../contexts/TourContext";
import { PageHeader } from "../components/PageHeader";
import * as api from "../services/api";
import type { LLMProvider, ModelEvaluation, HostedModelVariant } from "../types";

// ── Provider metadata ─────────────────────────────────────────────────────────

// Three top-level modes, not five flat provider buttons — "which LLM
// actually generates my content" is really three different DECISIONS
// (use ours / host your own / bring a key), and "kobold" as a provider
// value used to silently mean either "our hosted default" or "your own
// server" depending on whether a URL happened to be filled in, which is
// exactly the ambiguity that produced the localhost:5002 button bug. The
// underlying LLMProvider values sent to the backend are unchanged (still
// "kobold" | "openai" | "anthropic" | "gemini" | "custom" — renaming those
// would need a data migration for every user's already-saved settings), this
// is purely a clearer UI on top of the same four values.
type SettingsMode = "lorekeeper" | "self-hosted" | "api-key";

const MODES: { value: SettingsMode; label: string; description: string }[] = [
  { value: "lorekeeper", label: "Use Lorekeeper AI", description: "Our fine-tuned model, hosted for you — nothing to configure. Included with the Hosted Model ($15/mo) tier." },
  { value: "self-hosted", label: "Host It Yourself", description: "Point at your own KoboldCpp, Ollama, or LM Studio server — port-forwarded or reachable on the internet." },
  { value: "api-key", label: "Bring Your Own API Key", description: "Use your own OpenAI, Anthropic, Gemini, or custom-compatible API key." },
];

const API_KEY_PROVIDERS: { value: LLMProvider; label: string; description: string }[] = [
  { value: "openai", label: "OpenAI", description: "GPT-4o, GPT-4-turbo, and other OpenAI models." },
  { value: "anthropic", label: "Anthropic Claude", description: "Claude Opus, Sonnet, and Haiku models." },
  { value: "gemini", label: "Google Gemini", description: "Gemini Flash, Gemini Pro (always the latest version)." },
  { value: "custom", label: "Custom (OpenAI-compatible)", description: "Any API server using the OpenAI chat completions format — needs both a URL and a key." },
];

const PROVIDER_MODELS: Record<LLMProvider, string[]> = {
  kobold: [],
  openai: ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-3.5-turbo"],
  anthropic: ["claude-opus-4-8", "claude-sonnet-4-6", "claude-haiku-4-5-20251001"],
  // Only the "-latest" aliases, deliberately — no pinned versions. Google
  // retired the whole 1.5 line outright (shutdown completed Sept 2025), and
  // a pinned "gemini-2.5-flash" id 404'd for a real key even after that fix
  // while the alias worked, so pinned ids are a maintenance trap here: every
  // model generation eventually needs another dropdown update, but the
  // aliases just move forward on Google's own schedule. Keep the default
  // fallback (llm_provider.py's _gemini) in sync with the first entry here.
  gemini: ["gemini-flash-latest", "gemini-pro-latest"],
  custom: [],
};

// ── Section wrapper ───────────────────────────────────────────────────────────

function Section({ title, description, children, id, dataTour }: { title: string; description?: string; children: React.ReactNode; id?: string; dataTour?: string }) {
  return (
    <div id={id} data-tour={dataTour} className="rounded-xl border border-border bg-card p-6 flex flex-col gap-4 scroll-mt-20">
      <div>
        <h2 className="text-base font-semibold text-foreground" style={{ fontFamily: "var(--font-heading)" }}>{title}</h2>
        {description && <p className="text-sm text-muted-foreground mt-0.5">{description}</p>}
      </div>
      {children}
    </div>
  );
}

// ── AI Provider Section ───────────────────────────────────────────────────────

function LLMSettingsSection() {
  const { data: saved, isLoading } = useLLMSettings();
  const update = useUpdateLLMSettings();
  const test = useTestLLMConnection();

  const [mode, setMode] = useState<SettingsMode>("lorekeeper");
  const [apiKeyProvider, setApiKeyProvider] = useState<LLMProvider>("openai");
  const [apiUrl, setApiUrl] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [keyPlaceholder, setKeyPlaceholder] = useState("Enter API key…");
  const [model, setModel] = useState("");
  const [temperature, setTemperature] = useState(0.72);
  const [maxTokens, setMaxTokens] = useState(800);
  // 0 = no preference (genre default of 2-4 paragraphs) — the backend's
  // explicit "clear" sentinel, see LLMSettingsUpdate.narrative_paragraph_limit.
  const [paragraphLimit, setParagraphLimit] = useState(0);
  const [hostedVariant, setHostedVariant] = useState<HostedModelVariant>("finetuned");
  const [saved_, setSaved_] = useState(false);
  const [testResult, setTestResult] = useState<{ success: boolean; message: string } | null>(null);

  useEffect(() => {
    if (!saved) return;
    if (saved.llm_provider === "kobold") {
      setMode(saved.llm_api_url ? "self-hosted" : "lorekeeper");
    } else {
      setMode("api-key");
      setApiKeyProvider(saved.llm_provider);
    }
    setApiUrl(saved.llm_api_url ?? "");
    setApiKey("");
    setKeyPlaceholder(saved.llm_api_key_set ? "••••••••••••••••" : "Enter API key…");
    setModel(saved.llm_model ?? "");
    setTemperature(saved.llm_temperature);
    setMaxTokens(saved.llm_max_tokens);
    setParagraphLimit(saved.narrative_paragraph_limit ?? 0);
    setHostedVariant(saved.hosted_model_variant ?? "finetuned");
  }, [saved]);

  // The actual LLMProvider value sent to the backend — "lorekeeper" and
  // "self-hosted" both mean provider="kobold" (that's the value
  // get_user_llm_config checks to decide personal-vs-platform-default
  // routing — see app/api/deps.py), the only difference being whether a URL
  // is set at all.
  const effectiveProvider: LLMProvider = mode === "api-key" ? apiKeyProvider : "kobold";
  const needsUrl = mode === "self-hosted" || (mode === "api-key" && apiKeyProvider === "custom");
  const needsKey = mode === "api-key";
  const modelSuggestions = mode === "api-key" ? PROVIDER_MODELS[apiKeyProvider] : [];

  const handleModeChange = (m: SettingsMode) => {
    setMode(m);
    setTestResult(null);
  };

  const handleSave = () => {
    update.mutate(
      {
        llm_provider: effectiveProvider,
        // "" explicitly clears a field the backend previously had saved
        // (see settings.py's update route — empty string clears, omitting
        // the field leaves the old value untouched) — needed so e.g.
        // switching back to "Use Lorekeeper AI" actually drops a
        // previously-saved self-hosted URL instead of silently keeping it.
        llm_api_url: needsUrl ? apiUrl : "",
        llm_api_key: needsKey ? (apiKey || undefined) : "",
        llm_model: mode === "lorekeeper" ? "" : (model || ""),
        llm_temperature: temperature,
        llm_max_tokens: maxTokens,
        narrative_paragraph_limit: paragraphLimit,
        hosted_model_variant: hostedVariant,
      },
      { onSuccess: () => { setSaved_(true); setTimeout(() => setSaved_(false), 2500); } }
    );
  };

  const handleTest = () => {
    setTestResult(null);
    test.mutate(
      {
        llm_provider: effectiveProvider,
        llm_api_url: needsUrl ? (apiUrl || undefined) : undefined,
        llm_api_key: needsKey ? (apiKey || undefined) : undefined,
        llm_model: mode === "lorekeeper" ? undefined : (model || undefined),
        hosted_model_variant: mode === "lorekeeper" ? hostedVariant : undefined,
      },
      { onSuccess: ({ data }) => setTestResult(data) }
    );
  };

  const inputClass = "w-full rounded-md border border-input bg-background px-3 py-2 text-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring";
  const canSave = !(needsUrl && !apiUrl.trim()) && !(needsKey && !apiKey.trim() && !saved?.llm_api_key_set);

  if (isLoading) {
    return <div className="h-32 rounded-lg bg-muted/40 animate-pulse" />;
  }

  return (
    <Section
      title="AI Provider"
      description="Choose which AI powers Lorekeeper's journal generation, chat, and other AI features."
      dataTour="ai-settings-section"
    >
      {/* Mode selector — the three real decisions, not five flat provider
          buttons (see MODES' comment above for why that used to be
          ambiguous enough to cause a real bug). */}
      <div className="flex flex-col gap-1.5">
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
          {MODES.map((m) => (
            <button
              key={m.value}
              onClick={() => handleModeChange(m.value)}
              className={`text-left px-3 py-2.5 rounded-lg border text-sm transition-colors ${
                mode === m.value
                  ? "border-primary bg-primary/10 text-foreground font-medium"
                  : "border-border text-muted-foreground hover:text-foreground hover:border-border/80 hover:bg-muted/40"
              }`}
            >
              <div className="font-medium text-sm leading-tight">{m.label}</div>
              <div className="text-xs text-muted-foreground mt-0.5 leading-snug">{m.description}</div>
            </button>
          ))}
        </div>
      </div>

      {mode === "lorekeeper" && (
        <div className="flex flex-col gap-3">
          <div className="rounded-lg border border-primary/30 bg-primary/5 px-4 py-3 text-sm text-foreground">
            Lorekeeper AI is used automatically once you're on the{" "}
            <Link to="/settings#billing" className="text-primary hover:underline underline-offset-2">Hosted Model ($15/mo)</Link>{" "}
            tier. If you're not subscribed to it yet, generation will ask you to add a personal
            key or upgrade instead.
          </div>

          <div>
            <label className="text-xs font-medium text-muted-foreground uppercase tracking-wide mb-1.5 block">
              Model
            </label>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
              {(
                [
                  {
                    value: "finetuned" as HostedModelVariant,
                    label: "Fine-Tuned Lorekeeper",
                    description: "Our model, LoRA fine-tuned on TTRPG/gaming session logs. Recommended — this is the whole point of the hosted tier.",
                  },
                  {
                    value: "base" as HostedModelVariant,
                    label: "Base Model",
                    description: "The un-fine-tuned starting point (Mistral 7B Instruct) — pick this to see exactly what the fine-tuning changed.",
                  },
                ]
              ).map((v) => (
                <button
                  key={v.value}
                  onClick={() => setHostedVariant(v.value)}
                  className={`text-left px-3 py-2.5 rounded-lg border text-sm transition-colors ${
                    hostedVariant === v.value
                      ? "border-primary bg-primary/10 text-foreground font-medium"
                      : "border-border text-muted-foreground hover:text-foreground hover:border-border/80 hover:bg-muted/40"
                  }`}
                >
                  <div className="font-medium text-sm leading-tight">{v.label}</div>
                  <div className="text-xs text-muted-foreground mt-0.5 leading-snug">{v.description}</div>
                </button>
              ))}
            </div>
          </div>
        </div>
      )}

      {mode === "self-hosted" && (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <div className="flex flex-col gap-1.5 sm:col-span-2">
            <label className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
              Server URL — reachable from the internet (port-forwarded, a VPS, etc.), not "localhost"
            </label>
            <input
              type="url"
              value={apiUrl}
              onChange={(e) => setApiUrl(e.target.value)}
              placeholder="https://your-llm-server.example.com"
              className={inputClass}
            />
            <p className="text-xs text-muted-foreground">
              "localhost" here means Lorekeeper's own server, not your device — it needs a real
              address your router forwards to your machine, or a public server you run.
            </p>
          </div>
          <div className="flex flex-col gap-1.5 sm:col-span-2">
            <label className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Model Name (optional)</label>
            <input
              type="text"
              value={model}
              onChange={(e) => setModel(e.target.value)}
              placeholder="e.g. mistral-7b-instruct"
              className={inputClass}
            />
          </div>
        </div>
      )}

      {mode === "api-key" && (
        <div className="flex flex-col gap-3">
          <div className="flex flex-col gap-1.5">
            <label className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Provider</label>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
              {API_KEY_PROVIDERS.map((p) => (
                <button
                  key={p.value}
                  onClick={() => { setApiKeyProvider(p.value); setModel(""); setTestResult(null); }}
                  className={`text-left px-3 py-2.5 rounded-lg border text-sm transition-colors ${
                    apiKeyProvider === p.value
                      ? "border-primary bg-primary/10 text-foreground font-medium"
                      : "border-border text-muted-foreground hover:text-foreground hover:border-border/80 hover:bg-muted/40"
                  }`}
                >
                  <div className="font-medium text-sm leading-tight">{p.label}</div>
                  <div className="text-xs text-muted-foreground mt-0.5 leading-snug">{p.description}</div>
                </button>
              ))}
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            {apiKeyProvider === "custom" && (
              <div className="flex flex-col gap-1.5 sm:col-span-2">
                <label className="text-xs font-medium text-muted-foreground uppercase tracking-wide">API URL</label>
                <input
                  type="url"
                  value={apiUrl}
                  onChange={(e) => setApiUrl(e.target.value)}
                  placeholder="https://your-api-endpoint.com"
                  className={inputClass}
                />
              </div>
            )}

            <div className="flex flex-col gap-1.5 sm:col-span-2">
              <label className="text-xs font-medium text-muted-foreground uppercase tracking-wide">API Key</label>
              <input
                type="password"
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                placeholder={keyPlaceholder}
                autoComplete="new-password"
                className={inputClass}
              />
              {saved?.llm_api_key_set && !apiKey && (
                <p className="text-xs text-muted-foreground">A key is saved. Leave blank to keep it, or enter a new one to replace it.</p>
              )}
            </div>

            <div className="flex flex-col gap-1.5 sm:col-span-2">
              <label className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Model Name (optional)</label>
              {modelSuggestions.length > 0 ? (
                <select value={model} onChange={(e) => setModel(e.target.value)} className={inputClass}>
                  <option value="">— default —</option>
                  {modelSuggestions.map((m) => (
                    <option key={m} value={m}>{m}</option>
                  ))}
                </select>
              ) : (
                <input
                  type="text"
                  value={model}
                  onChange={(e) => setModel(e.target.value)}
                  placeholder="e.g. local-model"
                  className={inputClass}
                />
              )}
            </div>
          </div>
        </div>
      )}

      {mode !== "lorekeeper" && (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          {/* Temperature/max tokens only apply to a personal config — the
              platform default (Lorekeeper AI mode) uses the server's own
              fixed values regardless of what's saved here, so showing these
              sliders in that mode would imply control that doesn't exist. */}
          <div className="flex flex-col gap-1.5">
            <label className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
              Temperature ({temperature.toFixed(2)})
            </label>
            <input
              type="range"
              min="0" max="2" step="0.01"
              value={temperature}
              onChange={(e) => setTemperature(parseFloat(e.target.value))}
              className="w-full accent-primary"
            />
            <div className="flex justify-between text-xs text-muted-foreground">
              <span>0 — Deterministic</span>
              <span>2 — Creative</span>
            </div>
          </div>

          <div className="flex flex-col gap-1.5">
            <label className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
              Max Tokens ({maxTokens})
            </label>
            <input
              type="range"
              min="64" max="4096" step="64"
              value={maxTokens}
              onChange={(e) => setMaxTokens(parseInt(e.target.value))}
              className="w-full accent-primary"
            />
            <div className="flex justify-between text-xs text-muted-foreground">
              <span>64</span>
              <span>4096</span>
            </div>
          </div>
        </div>
      )}

      {/* Quick-entry length — unlike temperature/max tokens above, this is
          prompt-shaped rather than a decode parameter, so it applies in
          every mode including the platform default. */}
      <div className="flex flex-col gap-1.5">
        <label className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
          Quick Entry Length
        </label>
        <select
          value={paragraphLimit}
          onChange={(e) => setParagraphLimit(parseInt(e.target.value))}
          className={inputClass}
        >
          <option value={0}>Default (2–4 paragraphs)</option>
          <option value={1}>1 paragraph</option>
          <option value={2}>Up to 2 paragraphs</option>
          <option value={3}>Up to 3 paragraphs</option>
          <option value={4}>Up to 4 paragraphs</option>
          <option value={6}>Up to 6 paragraphs</option>
          <option value={8}>Up to 8 paragraphs</option>
        </select>
        <p className="text-xs text-muted-foreground">
          How long generated journal narratives should be. Shorter is faster.
        </p>
      </div>

      {/* Test result */}
      {testResult && (
        <div className={`rounded-lg px-4 py-2.5 text-sm border ${
          testResult.success
            ? "bg-green-500/10 border-green-500/30 text-green-700 dark:text-green-400"
            : "bg-destructive/10 border-destructive/30 text-destructive"
        }`}>
          {testResult.success ? "✓ " : "✗ "}{testResult.message}
        </div>
      )}

      {/* Actions */}
      <div className="flex gap-2 flex-wrap">
        <button
          onClick={handleSave}
          disabled={update.isPending || !canSave}
          className="rounded-md bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground hover:opacity-90 disabled:opacity-50 transition-opacity"
        >
          {update.isPending ? "Saving…" : saved_ ? "Saved ✓" : "Save Settings"}
        </button>
        <button
          onClick={handleTest}
          disabled={test.isPending || !canSave}
          className="flex items-center gap-1.5 rounded-md border border-border px-4 py-2 text-sm text-muted-foreground hover:text-foreground hover:bg-muted/60 transition-colors disabled:opacity-50"
        >
          {test.isPending && (
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="animate-spin"><path d="M21 12a9 9 0 11-6.219-8.56" /></svg>
          )}
          {test.isPending ? "Testing…" : "Test Connection"}
        </button>
      </div>
    </Section>
  );
}

// ── Theme Section ─────────────────────────────────────────────────────────────

function ThemeSection() {
  return (
    <Section title="Appearance" description="Customize the look of Lorekeeper. Import community themes or export your own.">
      <ThemeSelector />
    </Section>
  );
}

// ── RAG Reindex Section ───────────────────────────────────────────────────────

function ReindexSection() {
  const { data: campaigns } = useCampaigns();
  const reindex = useReindexJournals();
  const [campaignId, setCampaignId] = useState<string>("");
  const [result, setResult] = useState<string | null>(null);

  const handleReindex = () => {
    if (!campaignId) return;
    setResult(null);
    reindex.mutate(campaignId, {
      onSuccess: ({ data }) => setResult(`Rebuilt embeddings for ${data.reindexed} journal entries.`),
    });
  };

  return (
    <Section
      title="AI Search Index"
      description="Lorekeeper uses vector embeddings to find relevant journal entries during chat (RAG). Rebuild the index if entries are missing from chat context."
    >
      <div className="flex flex-col gap-3">
        <div className="flex gap-2 flex-wrap items-end">
          <div className="flex flex-col gap-1.5 flex-1 min-w-48">
            <label className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Campaign</label>
            <select
              value={campaignId}
              onChange={(e) => setCampaignId(e.target.value)}
              className="rounded-md border border-input bg-background px-3 py-2 text-sm text-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
            >
              <option value="">Select campaign…</option>
              {campaigns?.map((c) => (
                <option key={c.id} value={c.id}>{c.name}</option>
              ))}
            </select>
          </div>
          <button
            onClick={handleReindex}
            disabled={reindex.isPending || !campaignId}
            className="flex items-center gap-1.5 rounded-md border border-border px-4 py-2 text-sm text-muted-foreground hover:text-foreground hover:bg-muted/60 transition-colors disabled:opacity-50"
          >
            {reindex.isPending ? (
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="animate-spin"><path d="M21 12a9 9 0 11-6.219-8.56" /></svg>
            ) : (
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <polyline points="1 4 1 10 7 10" /><polyline points="23 20 23 14 17 14" />
                <path d="M20.49 9A9 9 0 0 0 5.64 5.64L1 10m22 4l-4.64 4.36A9 9 0 0 1 3.51 15" />
              </svg>
            )}
            {reindex.isPending ? "Rebuilding…" : "Rebuild Index"}
          </button>
        </div>

        {result && (
          <div className="rounded-lg px-4 py-2.5 text-sm border bg-green-500/10 border-green-500/30 text-green-700 dark:text-green-400">
            ✓ {result}
          </div>
        )}

        <p className="text-xs text-muted-foreground">
          This regenerates search vectors for all journal entries in the selected campaign. Runs locally using the all-MiniLM-L6-v2 sentence embedding model.
        </p>
      </div>
    </Section>
  );
}

function EvaluationSection() {
  const qc = useQueryClient();
  const [label, setLabel] = useState("");
  const [sampleSize, setSampleSize] = useState(10);
  const [running, setRunning] = useState(false);
  const [runningVariant, setRunningVariant] = useState<HostedModelVariant | null>(null);
  const [error, setError] = useState<string | null>(null);

  const { data: evaluations, isLoading } = useQuery<ModelEvaluation[]>({
    queryKey: ["evaluations"],
    queryFn: async () => (await api.getEvaluations()).data,
  });

  const handleRun = async () => {
    if (!label.trim()) return;
    setRunning(true);
    setError(null);
    try {
      await api.runEvaluation(label.trim(), sampleSize);
      setLabel("");
      qc.invalidateQueries({ queryKey: ["evaluations"] });
    } catch (err: any) {
      setError(err?.response?.data?.detail || "Evaluation failed. Is the configured provider reachable?");
    } finally {
      setRunning(false);
    }
  };

  // Quick compare — forces the platform's hosted model with a given variant
  // regardless of what's saved in Settings above, so seeing the fine-tune's
  // effect doesn't mean changing (and remembering to change back) your real
  // AI Provider config. Auto-labeled so both runs land in the table below,
  // sortable/comparable at a glance.
  const handleQuickRun = async (variant: HostedModelVariant) => {
    setRunning(true);
    setRunningVariant(variant);
    setError(null);
    try {
      const autoLabel = variant === "base" ? "Base Model (quick compare)" : "Fine-Tuned Lorekeeper (quick compare)";
      await api.runEvaluation(autoLabel, sampleSize, variant);
      qc.invalidateQueries({ queryKey: ["evaluations"] });
    } catch (err: any) {
      setError(err?.response?.data?.detail || "Evaluation failed — is Ollama reachable and does this model exist?");
    } finally {
      setRunning(false);
      setRunningVariant(null);
    }
  };

  const handleDelete = async (id: string) => {
    await api.deleteEvaluation(id);
    qc.invalidateQueries({ queryKey: ["evaluations"] });
  };

  return (
    <Section
      title="Model Evaluation"
      description="Run the validation set against whichever provider is configured above and store the result, so you can compare narrative quality across models. Or use the quick-compare buttons below to test the platform's fine-tuned and base models directly, without touching your own AI Provider settings."
    >
      <div className="flex flex-col gap-3">
        <div className="flex gap-2 flex-wrap">
          <button
            onClick={() => handleQuickRun("finetuned")}
            disabled={running}
            className="rounded-md border border-primary/40 bg-primary/5 px-3 py-2 text-xs font-medium text-foreground hover:bg-primary/10 disabled:opacity-50 transition-colors"
          >
            {runningVariant === "finetuned" ? "Running…" : "▶ Quick Compare: Fine-Tuned Model"}
          </button>
          <button
            onClick={() => handleQuickRun("base")}
            disabled={running}
            className="rounded-md border border-input px-3 py-2 text-xs font-medium text-muted-foreground hover:text-foreground hover:bg-muted/60 disabled:opacity-50 transition-colors"
          >
            {runningVariant === "base" ? "Running…" : "▶ Quick Compare: Base Model"}
          </button>
        </div>

        <div className="flex gap-2 flex-wrap items-end pt-1 border-t border-border">
          <div className="flex flex-col gap-1.5 flex-1 min-w-40">
            <label className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Label</label>
            <input
              type="text"
              placeholder="e.g. Fine-tuned Lorekeeper"
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              className="rounded-md border border-input bg-background px-3 py-2 text-sm"
            />
          </div>
          <div className="flex flex-col gap-1.5 w-28">
            <label className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Samples</label>
            <input
              type="number"
              min={1}
              max={50}
              value={sampleSize}
              onChange={(e) => setSampleSize(Math.min(50, Math.max(1, Number(e.target.value) || 1)))}
              className="rounded-md border border-input bg-background px-3 py-2 text-sm"
            />
          </div>
          <button
            onClick={handleRun}
            disabled={running || !label.trim()}
            className="rounded-md bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground disabled:opacity-50 hover:opacity-90 transition-opacity"
          >
            {running ? "Running…" : "Run Evaluation"}
          </button>
        </div>
        {running && (
          <p className="text-xs text-muted-foreground">
            Generating {sampleSize} sample{sampleSize === 1 ? "" : "s"} against{" "}
            {runningVariant ? `the ${runningVariant === "base" ? "base" : "fine-tuned"} model` : "the currently configured provider"}
            {" "}— this can take a minute or more depending on the model.
          </p>
        )}
        {error && <p className="text-sm text-destructive">{error}</p>}

        {isLoading && <div className="h-16 rounded-lg bg-muted/40 animate-pulse" />}

        {evaluations && evaluations.length === 0 && !isLoading && (
          <p className="text-sm text-muted-foreground">No evaluation runs yet.</p>
        )}

        {evaluations && evaluations.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-muted-foreground uppercase tracking-wide border-b border-border">
                  <th className="py-2 pr-3 font-medium">Label</th>
                  <th className="py-2 pr-3 font-medium">Samples</th>
                  <th className="py-2 pr-3 font-medium">Avg Length</th>
                  <th className="py-2 pr-3 font-medium">Word Overlap</th>
                  <th className="py-2 pr-3 font-medium">Semantic Sim.</th>
                  <th className="py-2 pr-3 font-medium">Has Content</th>
                  <th className="py-2 pr-3 font-medium">Errors</th>
                  <th className="py-2" />
                </tr>
              </thead>
              <tbody>
                {evaluations.map((e) => (
                  <tr key={e.id} className="border-b border-border/50">
                    <td className="py-2 pr-3 font-medium text-foreground">{e.label}</td>
                    <td className="py-2 pr-3 text-muted-foreground">{e.sample_size}</td>
                    <td className="py-2 pr-3 text-muted-foreground">{Math.round(e.avg_length)} chars</td>
                    <td className="py-2 pr-3 text-muted-foreground">{(e.avg_word_overlap * 100).toFixed(1)}%</td>
                    <td className="py-2 pr-3 text-muted-foreground">{e.avg_semantic_similarity != null ? `${(e.avg_semantic_similarity * 100).toFixed(1)}%` : "—"}</td>
                    <td className="py-2 pr-3 text-muted-foreground">{e.has_content_pct.toFixed(0)}%</td>
                    <td className="py-2 pr-3 text-muted-foreground">{e.error_count}</td>
                    <td className="py-2">
                      <button onClick={() => handleDelete(e.id)} className="text-xs text-muted-foreground hover:text-destructive transition-colors">
                        Remove
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </Section>
  );
}

// ── Billing Section ─────────────────────────────────────────────────────────

function BillingSection() {
  const { data: status, isLoading } = useBillingStatus();
  const portal = useOpenBillingPortal();

  if (isLoading || !status) {
    return (
      <Section title="Billing" description="Subscription and hosted-model usage." id="billing">
        <p className="text-sm text-muted-foreground">Loading…</p>
      </Section>
    );
  }

  const pct =
    status.tokens_included_per_period && status.tokens_used_current_period != null
      ? Math.min(100, Math.round((status.tokens_used_current_period / status.tokens_included_per_period) * 100))
      : null;

  const planLabel = status.plan === "hosted" ? "Hosted Model ($15/mo)" : status.plan === "byok" ? "Bring Your Own Key ($5/mo)" : null;
  const isSubscriber = status.access_source === "subscription";
  const nextPaymentDate =
    status.current_period_end && status.subscription_status === "active"
      ? new Date(status.current_period_end).toLocaleDateString(undefined, {
          year: "numeric",
          month: "long",
          day: "numeric",
        })
      : null;

  // Headline: for a real Stripe subscriber, name the plan they're paying for.
  // For promo/grandfathered access, still name the *granted* plan (this used
  // to always say "Free account" with no plan info, hiding what tier an
  // admin- or promo-granted account actually had) — only fall back to the
  // generic label if somehow no plan was ever set on the row.
  const headline = isSubscriber
    ? planLabel ?? "Subscribed"
    : status.access_source === "promo"
    ? planLabel
      ? `${planLabel} — free via promo code`
      : "Free account (promo code)"
    : status.access_source === "grandfathered"
    ? planLabel
      ? `${planLabel} — free, granted by admin`
      : "Free account (legacy)"
    : "No active plan";

  const description = isSubscriber
    ? status.subscription_status === "past_due"
      ? "Your last payment failed — update your card via Manage Subscription to avoid losing access."
      : status.plan === "byok"
      ? "Bring your own LLM API key above. Want the hosted model instead? Manage Subscription to switch plans."
      : status.plan === "hosted"
      ? nextPaymentDate
        ? `Active — next payment on ${nextPaymentDate}.`
        : "Active"
      : null
    : status.access_source === "promo"
    ? status.plan === "hosted"
      ? "No payment due — your promo code covers hosted-model access. Subscribing below starts real billing at Stripe's configured price; your promo doesn't discount it."
      : "No payment due — your promo code covers full app access with your own LLM API key."
    : status.access_source === "grandfathered"
    ? "No payment due — access was granted directly by an admin."
    : "Add your own LLM API key above, or subscribe for hosted-model access.";

  return (
    <Section title="Billing" description="Subscription status and hosted-model usage." id="billing">
      <div className="flex flex-col gap-3">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm font-medium text-foreground">{headline}</p>
            <p className="text-xs text-muted-foreground mt-0.5">{description}</p>
            {status.promo_code_used && (
              <p className="text-xs text-muted-foreground mt-0.5">
                Promo code used: <span className="font-mono">{status.promo_code_used}</span>
              </p>
            )}
          </div>
          {isSubscriber ? (
            <button
              onClick={() => portal.mutate()}
              disabled={portal.isPending}
              className="rounded-md border border-input bg-background px-3 py-2 text-sm font-medium hover:bg-accent transition-colors disabled:opacity-50"
            >
              {portal.isPending ? "Opening…" : "Manage Subscription"}
            </button>
          ) : (
            <Link
              to="/subscribe"
              className="rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground hover:opacity-90 transition-opacity"
            >
              Subscribe
            </Link>
          )}
        </div>

        {status.plan === "hosted" && status.access_granted && pct !== null && (
          <div>
            <div className="flex justify-between text-xs text-muted-foreground mb-1">
              <span>Hosted-model usage this period</span>
              <span>
                {status.tokens_used_current_period?.toLocaleString()} /{" "}
                {status.tokens_included_per_period?.toLocaleString()} tokens (est.)
              </span>
            </div>
            <div className="h-2 rounded-full bg-muted overflow-hidden">
              <div
                className={`h-full rounded-full ${pct >= 90 ? "bg-destructive" : "bg-primary"}`}
                style={{ width: `${pct}%` }}
              />
            </div>
            {pct >= 100 && (
              <p className="text-xs text-destructive mt-1">
                Quota used up — add your own LLM API key above to keep generating until it resets.
              </p>
            )}
          </div>
        )}

        {!status.stripe_configured && (
          <p className="text-xs text-muted-foreground bg-muted/50 rounded-md px-3 py-2">
            Billing isn't configured on this server yet — see docs/PAYMENT_PROCESSOR_SETUP.md.
          </p>
        )}
      </div>
    </Section>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

function TutorialSection() {
  const { start } = useTour();
  return (
    <Section title="Tutorial" description="Take the guided tour of Lorekeeper's core features again, any time.">
      <button
        data-tour="tutorial-replay"
        onClick={start}
        className="self-start rounded-md border border-input px-4 py-2 text-sm font-medium text-foreground hover:bg-accent/60 transition-colors"
      >
        ▶ Replay Tutorial
      </button>
    </Section>
  );
}

export function SettingsPage() {
  return (
    <div className="max-w-3xl mx-auto px-4 py-6 md:py-10 flex flex-col gap-6">
      <PageHeader title="Settings" description="Configure your AI provider, appearance, and search index." />

      <BillingSection />
      <LLMSettingsSection />
      <ThemeSection />
      <ReindexSection />
      <EvaluationSection />
      <TutorialSection />
    </div>
  );
}
