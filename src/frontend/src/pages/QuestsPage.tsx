import { useState } from "react";
import { useCampaigns } from "../hooks/useCampaigns";
import { useQuests, useCreateQuest, useUpdateQuest, useDeleteQuest, useSuggestQuests } from "../hooks/useQuests";
import { QuestDetailPanel } from "../components/QuestDetailPanel";
import { PageHeader } from "../components/PageHeader";
import type { Campaign, Quest, QuestStatus } from "../types";

const STATUS_STYLES: Record<QuestStatus, string> = {
  active:    "text-blue-600 bg-blue-500/10 border-blue-500/20",
  completed: "text-green-600 bg-green-500/10 border-green-500/20",
  failed:    "text-red-500 bg-red-500/10 border-red-500/20",
  abandoned: "text-muted-foreground bg-muted/40 border-border",
};
const STATUS_ICONS: Record<QuestStatus, string> = {
  active: "⚔️", completed: "✅", failed: "💀", abandoned: "🌫️",
};
const STATUS_CYCLE: Record<QuestStatus, QuestStatus> = {
  active: "completed", completed: "failed", failed: "abandoned", abandoned: "active",
};
const STATUS_ORDER: QuestStatus[] = ["active", "completed", "failed", "abandoned"];

function QuestCard({ quest, onCycle, onDelete, onSelect }: { quest: Quest; onCycle: () => void; onDelete: () => void; onSelect: () => void }) {
  return (
    <div
      className={`rounded-lg border bg-card p-4 flex flex-col gap-2 transition-colors hover:border-primary/30 cursor-pointer ${quest.status !== "active" ? "opacity-75" : ""}`}
      onClick={onSelect}
    >
      <div className="flex items-start justify-between gap-3">
        <p className="text-sm font-medium text-card-foreground leading-snug flex-1">{quest.title}</p>
        <div className="flex items-center gap-1.5 shrink-0">
          <button
            onClick={(e) => { e.stopPropagation(); onCycle(); }}
            title="Cycle status"
            className={`rounded-full border px-2.5 py-0.5 text-[10px] font-semibold capitalize transition-colors ${STATUS_STYLES[quest.status]}`}
          >
            {quest.status}
          </button>
          <button
            onClick={(e) => { e.stopPropagation(); onDelete(); }}
            className="p-1 rounded text-muted-foreground hover:text-destructive transition-colors"
            title="Delete"
          >
            <svg width="13" height="13" viewBox="0 0 20 20" fill="currentColor">
              <path fillRule="evenodd" clipRule="evenodd" d="M9 2a1 1 0 00-.894.553L7.382 4H4a1 1 0 000 2v10a2 2 0 002 2h8a2 2 0 002-2V6a1 1 0 100-2h-3.382l-.724-1.447A1 1 0 0011 2H9zM7 8a1 1 0 012 0v6a1 1 0 11-2 0V8zm4 0a1 1 0 012 0v6a1 1 0 11-2 0V8z" />
            </svg>
          </button>
        </div>
      </div>
      {quest.description && <p className="text-xs text-muted-foreground leading-relaxed line-clamp-2">{quest.description}</p>}
      <p className="text-xs text-muted-foreground/60 mt-1">Click to edit details</p>
    </div>
  );
}

function CampaignQuests({ campaign }: { campaign: Campaign }) {
  const { data: quests, isLoading } = useQuests(campaign.id);
  const create = useCreateQuest();
  const update = useUpdateQuest(campaign.id);
  const remove = useDeleteQuest(campaign.id);
  const suggest = useSuggestQuests();
  const [title, setTitle] = useState("");
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [selectedQuest, setSelectedQuest] = useState<Quest | null>(null);

  const handleAdd = () => {
    if (!title.trim()) return;
    create.mutate({ title: title.trim(), campaign_id: campaign.id }, { onSuccess: () => setTitle("") });
  };

  const handleSuggest = () => {
    suggest.mutate(campaign.id, { onSuccess: ({ data }) => setSuggestions(data.suggestions) });
  };

  const addSuggestion = (t: string) => {
    create.mutate({ title: t, campaign_id: campaign.id }, { onSuccess: () => setSuggestions((s) => s.filter((x) => x !== t)) });
  };

  const grouped = STATUS_ORDER.reduce<Record<QuestStatus, Quest[]>>(
    (acc, s) => ({ ...acc, [s]: [] }),
    {} as Record<QuestStatus, Quest[]>
  );
  quests?.forEach((q) => grouped[q.status].push(q));
  const activeCount = grouped.active.length;

  return (
    <div className="flex flex-col gap-5">
      {/* Add quest + AI suggest */}
      <div className="flex gap-2 flex-wrap items-center">
        <input type="text" placeholder="New quest title…" value={title}
          onChange={(e) => setTitle(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleAdd()}
          className="flex-1 min-w-48 rounded-md border border-input bg-background px-3 py-2 text-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring" />
        <button onClick={handleAdd} disabled={create.isPending || !title.trim()}
          className="rounded-md bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground hover:opacity-90 disabled:opacity-50 transition-opacity shrink-0">
          Add Quest
        </button>
        <button onClick={handleSuggest} disabled={suggest.isPending}
          className="flex items-center gap-1.5 text-sm px-3 py-2 rounded-md border border-border text-muted-foreground hover:text-foreground hover:bg-muted/60 transition-colors disabled:opacity-50 shrink-0">
          {suggest.isPending ? (
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="animate-spin"><path d="M21 12a9 9 0 11-6.219-8.56" /></svg>
          ) : (
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" />
            </svg>
          )}
          AI Suggest
        </button>
        {quests && quests.length > 0 && (
          <span className="ml-auto text-xs text-muted-foreground shrink-0">
            {activeCount} active · {quests.length} total
          </span>
        )}
      </div>

      {/* AI suggestions */}
      {suggestions.length > 0 && (
        <div className="rounded-lg border border-border bg-muted/20 p-4 flex flex-col gap-3">
          <p className="text-xs font-semibold uppercase tracking-widest text-muted-foreground" style={{ fontFamily: "var(--font-heading)" }}>
            AI quest suggestions
          </p>
          <div className="flex flex-col gap-2">
            {suggestions.map((t) => (
              <div key={t} className="flex items-center justify-between gap-3 rounded-lg bg-background border border-border px-4 py-2.5">
                <span className="text-sm text-foreground">{t}</span>
                <button onClick={() => addSuggestion(t)}
                  className="text-xs px-3 py-1 rounded-md bg-primary text-primary-foreground hover:opacity-90 shrink-0 font-medium">
                  + Add
                </button>
              </div>
            ))}
          </div>
        </div>
      )}

      {isLoading && (
        <div className="flex flex-col gap-2">
          {[...Array(4)].map((_, i) => <div key={i} className="h-16 rounded-lg border border-border animate-pulse bg-muted/40" />)}
        </div>
      )}

      {!isLoading && !quests?.length && (
        <div className="text-center py-16 text-muted-foreground border border-dashed border-border rounded-xl">
          <p className="text-4xl mb-3">📜</p>
          <p className="text-sm font-medium text-foreground mb-1">No quests yet</p>
          <p className="text-xs">Add one above or let AI suggest from your journal entries.</p>
        </div>
      )}

      {/* Grouped quest lists */}
      {!isLoading && quests && quests.length > 0 &&
        STATUS_ORDER.filter((s) => grouped[s].length > 0).map((status) => (
          <div key={status} className="flex flex-col gap-2">
            <h3 className="flex items-center gap-2 text-xs font-semibold uppercase tracking-widest text-muted-foreground" style={{ fontFamily: "var(--font-heading)" }}>
              <span>{STATUS_ICONS[status]}</span>
              {status}
              <span className="rounded-full bg-muted px-2 py-0.5 font-mono">{grouped[status].length}</span>
            </h3>
            <div className="flex flex-col gap-2">
              {grouped[status].map((q) => (
                <QuestCard key={q.id} quest={q}
                  onCycle={() => update.mutate({ id: q.id, data: { status: STATUS_CYCLE[q.status] } })}
                  onDelete={() => remove.mutate(q.id)}
                  onSelect={() => setSelectedQuest(q)} />
              ))}
            </div>
          </div>
        ))
      }

      <QuestDetailPanel
        quest={selectedQuest}
        campaignId={campaign.id}
        onClose={() => setSelectedQuest(null)}
      />
    </div>
  );
}

export function QuestsPage() {
  const { data: campaigns } = useCampaigns();
  const [selected, setSelected] = useState<Campaign | null>(null);

  return (
    <div className="max-w-3xl mx-auto px-4 py-6 md:py-10 flex flex-col gap-6">
      <PageHeader
        title="Quest Tracker"
        description="Track active, completed, and failed quests. Click a status badge to cycle it."
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
          <p className="text-4xl mb-3">⚔️</p>
          <p className="text-sm font-medium text-foreground mb-1">Select a campaign</p>
          <p className="text-xs">Choose a campaign above to manage its quests.</p>
        </div>
      )}

      {selected && <CampaignQuests campaign={selected} />}
    </div>
  );
}
