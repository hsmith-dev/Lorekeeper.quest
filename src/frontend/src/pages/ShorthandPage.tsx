import { useState } from "react";
import { useCampaigns } from "../hooks/useCampaigns";
import {
  useShorthandTerms,
  useCreateShorthand,
  useUpdateShorthand,
  useDeleteShorthand,
} from "../hooks/useShorthand";
import { PageHeader } from "../components/PageHeader";
import type { Campaign, ShorthandTerm } from "../types";

function TermForm({
  campaignId,
  editing,
  onDone,
}: {
  campaignId: string;
  editing?: ShorthandTerm;
  onDone: () => void;
}) {
  const [term, setTerm] = useState(editing?.term ?? "");
  const [meaning, setMeaning] = useState(editing?.meaning ?? "");
  const [usage, setUsage] = useState(editing?.usage ?? "");
  const create = useCreateShorthand(campaignId);
  const update = useUpdateShorthand(campaignId);
  const pending = create.isPending || update.isPending;

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const data = { term: term.trim(), meaning: meaning.trim(), usage: usage.trim() || undefined };
    if (editing) {
      update.mutate({ id: editing.id, data }, { onSuccess: onDone });
    } else {
      create.mutate(data, { onSuccess: onDone });
    }
  };

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-2 bg-muted/40 rounded-md p-3">
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
        <input
          value={term} onChange={(e) => setTerm(e.target.value)} placeholder="Term (e.g. BBEG)" required maxLength={50}
          className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
        />
        <input
          value={meaning} onChange={(e) => setMeaning(e.target.value)} placeholder="What it means" required
          className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
        />
      </div>
      <textarea
        value={usage} onChange={(e) => setUsage(e.target.value)} placeholder="How it's used (optional — an example or note)" rows={2}
        className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm resize-y focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
      />
      <div className="flex gap-2">
        <button
          type="submit" disabled={pending || !term.trim() || !meaning.trim()}
          className="rounded-md bg-primary px-3 py-1.5 text-xs font-semibold text-primary-foreground hover:opacity-90 disabled:opacity-50"
        >
          {pending ? "Saving…" : editing ? "Save" : "Add Term"}
        </button>
        {editing && (
          <button type="button" onClick={onDone} className="rounded-md border border-input px-3 py-1.5 text-xs text-muted-foreground hover:text-foreground">
            Cancel
          </button>
        )}
      </div>
    </form>
  );
}

function TermRow({ term, campaignId }: { term: ShorthandTerm; campaignId: string }) {
  const [editing, setEditing] = useState(false);
  const del = useDeleteShorthand(campaignId);

  const handleDelete = () => {
    if (!confirm(`Delete the shorthand term "${term.term}"?`)) return;
    del.mutate(term.id);
  };

  if (editing) {
    return <TermForm campaignId={campaignId} editing={term} onDone={() => setEditing(false)} />;
  }

  return (
    <div className="rounded-lg border border-border bg-card p-4 flex items-start justify-between gap-3">
      <div className="min-w-0 flex flex-col gap-1">
        <div className="flex items-baseline gap-2 flex-wrap">
          <span className="text-sm font-mono font-semibold text-card-foreground">{term.term}</span>
          <span className="text-sm text-foreground">{term.meaning}</span>
        </div>
        {term.usage && <p className="text-xs text-muted-foreground">{term.usage}</p>}
      </div>
      <div className="flex gap-1.5 shrink-0">
        <button onClick={() => setEditing(true)} className="text-xs px-2.5 py-1 rounded-md border border-input text-foreground hover:bg-muted/60 transition-colors">
          Edit
        </button>
        <button
          onClick={handleDelete} disabled={del.isPending}
          className="text-xs px-2.5 py-1 rounded-md border border-destructive/30 text-destructive hover:bg-destructive/10 transition-colors disabled:opacity-50"
        >
          Delete
        </button>
      </div>
    </div>
  );
}

function CampaignShorthand({ campaign }: { campaign: Campaign }) {
  const { data: terms, isLoading } = useShorthandTerms(campaign.id);
  const [adding, setAdding] = useState(false);

  return (
    <div className="flex flex-col gap-4">
      {adding ? (
        <TermForm campaignId={campaign.id} onDone={() => setAdding(false)} />
      ) : (
        <button
          onClick={() => setAdding(true)}
          className="self-start rounded-md bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground hover:opacity-90 transition-opacity"
          style={{ fontFamily: "var(--font-heading)" }}
        >
          + Add Shorthand Term
        </button>
      )}

      {isLoading && <p className="text-sm text-muted-foreground">Loading…</p>}

      {terms && terms.length === 0 && !adding && (
        <div className="text-center py-16 text-muted-foreground border border-dashed border-border rounded-xl">
          <p className="text-4xl mb-3">✍️</p>
          <p className="text-sm font-medium text-foreground mb-1">No shorthand terms yet</p>
          <p className="text-xs">
            Define abbreviations your table actually uses — Lorekeeper will use them when
            expanding your session notes into narrative, and understand them in chat.
          </p>
        </div>
      )}

      {terms && terms.length > 0 && (
        <div className="flex flex-col gap-2">
          {terms.map((t) => (
            <TermRow key={t.id} term={t} campaignId={campaign.id} />
          ))}
        </div>
      )}
    </div>
  );
}

export function ShorthandPage() {
  const { data: campaigns } = useCampaigns();
  const [selected, setSelected] = useState<Campaign | null>(null);

  return (
    <div className="max-w-3xl mx-auto px-4 py-6 md:py-10 flex flex-col gap-6">
      <PageHeader
        title="Shorthand Glossary"
        description="Define what your campaign's own abbreviations mean and how they're used — Lorekeeper reads this glossary when turning your notes into narrative and when chatting, so your table's shorthand gets understood instead of guessed at."
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
          <p className="text-xs">Choose a campaign above to manage its shorthand glossary.</p>
        </div>
      )}

      {selected && <CampaignShorthand campaign={selected} />}
    </div>
  );
}
