import { useState } from "react";
import { useCampaigns } from "../hooks/useCampaigns";
import {
  useSessionPlans,
  useGenerateSessionPlanDraft,
  useCreateSessionPlan,
  useUpdateSessionPlan,
  useDeleteSessionPlan,
} from "../hooks/useSessionPlans";
import { NarrativeReviewPanel } from "../components/NarrativeReviewPanel";
import { PageHeader } from "../components/PageHeader";
import { apiErrorMessage } from "../utils/apiError";
import type { Campaign, SessionPlan } from "../types";

function formatDate(iso: string) {
  return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

function SessionPlanCard({ plan, campaignId }: { plan: SessionPlan; campaignId: string }) {
  const [expanded, setExpanded] = useState(false);
  const [editing, setEditing] = useState(false);
  const [title, setTitle] = useState(plan.title);
  const [content, setContent] = useState(plan.content);
  const update = useUpdateSessionPlan(campaignId);
  const remove = useDeleteSessionPlan(campaignId);

  const handleSave = () => {
    update.mutate(
      { id: plan.id, data: { title: title.trim(), content } },
      { onSuccess: () => setEditing(false) }
    );
  };

  return (
    <div className="rounded-lg border border-border bg-card overflow-hidden">
      <button
        onClick={() => setExpanded((v) => !v)}
        className="w-full flex items-center justify-between gap-3 px-4 py-3 text-left hover:bg-muted/40 transition-colors"
      >
        <div className="min-w-0">
          <p className="text-sm font-medium text-card-foreground truncate">{plan.title}</p>
          <p className="text-xs text-muted-foreground">{formatDate(plan.created_at)}</p>
        </div>
        <svg
          width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
          className={`shrink-0 transition-transform ${expanded ? "rotate-180" : ""}`}
        >
          <polyline points="6 9 12 15 18 9" />
        </svg>
      </button>

      {expanded && (
        <div className="px-4 pb-4 flex flex-col gap-3 border-t border-border pt-3">
          {editing ? (
            <>
              <input
                type="text"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm font-medium focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
              />
              <textarea
                value={content}
                onChange={(e) => setContent(e.target.value)}
                rows={10}
                className="w-full resize-y rounded-md border border-input bg-background px-3 py-2.5 text-sm leading-relaxed focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
              />
              <div className="flex items-center gap-2">
                <button
                  onClick={handleSave}
                  disabled={update.isPending || !title.trim()}
                  className="rounded-md bg-primary px-3 py-1.5 text-xs font-semibold text-primary-foreground hover:opacity-90 disabled:opacity-50 transition-opacity"
                >
                  {update.isPending ? "Saving…" : "Save Changes"}
                </button>
                <button
                  onClick={() => { setEditing(false); setTitle(plan.title); setContent(plan.content); }}
                  className="text-xs text-muted-foreground hover:text-foreground transition-colors"
                >
                  Cancel
                </button>
              </div>
            </>
          ) : (
            <>
              <p className="text-sm text-foreground whitespace-pre-wrap leading-relaxed">{plan.content}</p>
              <div className="flex items-center gap-3">
                <button
                  onClick={() => setEditing(true)}
                  className="text-xs text-muted-foreground hover:text-foreground underline underline-offset-2 transition-colors"
                >
                  Edit
                </button>
                <button
                  onClick={() => remove.mutate(plan.id)}
                  className="text-xs text-destructive hover:underline underline-offset-2 transition-colors"
                >
                  Delete
                </button>
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}

function CampaignSessionPlans({ campaign }: { campaign: Campaign }) {
  const { data: plans, isLoading } = useSessionPlans(campaign.id);
  const generateDraft = useGenerateSessionPlanDraft();
  const create = useCreateSessionPlan(campaign.id);
  const [focus, setFocus] = useState("");
  const [draft, setDraft] = useState<string | null>(null);
  const [draftTitle, setDraftTitle] = useState("");
  const [saveError, setSaveError] = useState<string | null>(null);

  const handleGenerate = () => {
    setSaveError(null);
    generateDraft.mutate(
      { campaign_id: campaign.id, focus: focus.trim() || undefined },
      {
        onSuccess: ({ data }) => {
          setDraft(data.content);
          setDraftTitle(`Session Plan — ${new Date().toLocaleDateString(undefined, { month: "short", day: "numeric" })}`);
        },
      }
    );
  };

  const handleRegenerate = () => {
    setSaveError(null);
    generateDraft.mutate(
      { campaign_id: campaign.id, focus: focus.trim() || undefined },
      { onSuccess: ({ data }) => setDraft(data.content) }
    );
  };

  const handleSave = () => {
    if (draft === null || !draftTitle.trim()) return;
    setSaveError(null);
    create.mutate(
      { title: draftTitle.trim(), content: draft },
      {
        onSuccess: () => { setDraft(null); setDraftTitle(""); setFocus(""); },
        onError: (err) => setSaveError(apiErrorMessage(err, "Could not save this session plan. Try again.")),
      }
    );
  };

  return (
    <div className="flex flex-col gap-5">
      {draft === null ? (
        <div className="flex flex-col gap-2 rounded-lg border border-border bg-muted/20 p-4">
          <label className="text-xs font-medium text-muted-foreground">
            What should this session focus on? (optional)
          </label>
          <div className="flex gap-2 flex-wrap">
            <input
              type="text"
              placeholder="e.g. the confrontation at the goblin camp"
              value={focus}
              onChange={(e) => setFocus(e.target.value)}
              className="flex-1 min-w-48 rounded-md border border-input bg-background px-3 py-2 text-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
            />
            <button
              onClick={handleGenerate}
              disabled={generateDraft.isPending}
              className="shrink-0 rounded-md bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground hover:opacity-90 disabled:opacity-50 transition-opacity"
              style={{ fontFamily: "var(--font-heading)" }}
            >
              {generateDraft.isPending ? "Drafting…" : "Generate Session Plan"}
            </button>
          </div>
          <p className="text-xs text-muted-foreground">
            Draws on this campaign's recent entries, open quests, and known NPCs.
          </p>
          {generateDraft.isError && (
            <p className="text-sm text-destructive bg-destructive/10 rounded-md px-3 py-2">Something went wrong. Try again.</p>
          )}
        </div>
      ) : (
        <NarrativeReviewPanel
          title="Review your session plan"
          narrative={draft}
          onChange={setDraft}
          itemTitle={draftTitle}
          onItemTitleChange={setDraftTitle}
          itemTitlePlaceholder="Plan title"
          onSave={handleSave}
          onDiscard={() => { setDraft(null); setDraftTitle(""); setSaveError(null); }}
          onRegenerate={handleRegenerate}
          saving={create.isPending}
          regenerating={generateDraft.isPending}
          saveLabel="Save Plan"
          rows={14}
          error={saveError}
        />
      )}

      {isLoading && (
        <div className="flex flex-col gap-2">
          {[...Array(3)].map((_, i) => <div key={i} className="h-14 rounded-lg border border-border animate-pulse bg-muted/40" />)}
        </div>
      )}

      {!isLoading && !plans?.length && (
        <div className="text-center py-16 text-muted-foreground border border-dashed border-border rounded-xl">
          <p className="text-4xl mb-3">🗺️</p>
          <p className="text-sm font-medium text-foreground mb-1">No session plans yet</p>
          <p className="text-xs">Generate one above to outline your next session.</p>
        </div>
      )}

      {!isLoading && plans && plans.length > 0 && (
        <div className="flex flex-col gap-2">
          {plans.map((p) => (
            <SessionPlanCard key={p.id} plan={p} campaignId={campaign.id} />
          ))}
        </div>
      )}
    </div>
  );
}

export function SessionPlansPage() {
  const { data: campaigns } = useCampaigns();
  const [selected, setSelected] = useState<Campaign | null>(null);

  return (
    <div className="max-w-3xl mx-auto px-4 py-6 md:py-10 flex flex-col gap-6">
      <PageHeader
        title="Session Plans"
        description="Let AI draft an outline for your next session — recap, likely objectives, encounters, NPCs to feature, and a complication or two. Review and edit before saving."
      />

      {campaigns && campaigns.length > 0 && (
        <div className="flex gap-1.5 flex-wrap border-b border-border pb-3">
          {campaigns.map((c) => (
            <button key={c.id} onClick={() => setSelected(c)}
              className={`px-3 py-1.5 rounded-md text-sm transition-colors ${
                selected?.id === c.id ? "bg-muted text-foreground font-medium" : "text-muted-foreground hover:text-foreground hover:bg-muted/60"
              }`}>
              {c.name}
            </button>
          ))}
        </div>
      )}

      {!selected && (
        <div className="text-center py-16 text-muted-foreground border border-dashed border-border rounded-xl">
          <p className="text-4xl mb-3">🗺️</p>
          <p className="text-sm font-medium text-foreground mb-1">Select a campaign</p>
          <p className="text-xs">Choose a campaign above to plan its next session.</p>
        </div>
      )}

      {selected && <CampaignSessionPlans campaign={selected} />}
    </div>
  );
}
