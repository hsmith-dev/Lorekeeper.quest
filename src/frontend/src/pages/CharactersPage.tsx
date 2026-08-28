import { useState } from "react";
import { useCampaigns } from "../hooks/useCampaigns";
import { useNpcs, useCreateNpc, useUpdateNpc, useDeleteNpc, useExtractNpcs } from "../hooks/useNpcs";
import { NpcDetailPanel } from "../components/NpcDetailPanel";
import { PageHeader } from "../components/PageHeader";
import type { Campaign, NpcEntry, NpcRole, NpcStatus } from "../types";

const ROLE_LABELS: Record<NpcRole, string> = {
  npc: "NPC", pc: "Player", monster: "Monster", faction: "Faction",
};
const ROLE_COLORS: Record<NpcRole, string> = {
  npc: "bg-primary/15 text-primary border-primary/30",
  pc: "bg-accent/15 text-accent-foreground border-accent/30",
  monster: "bg-destructive/15 text-destructive border-destructive/30",
  faction: "bg-secondary/20 text-secondary-foreground border-secondary/30",
};
const STATUS_COLORS: Record<NpcStatus, string> = {
  alive: "text-green-600 bg-green-500/10 border-green-500/20",
  dead: "text-red-500 bg-red-500/10 border-red-500/20",
  unknown: "text-muted-foreground bg-muted/40 border-border",
};
const STATUS_CYCLE: Record<NpcStatus, NpcStatus> = { alive: "dead", dead: "unknown", unknown: "alive" };

function NpcCard({ npc, onStatusCycle, onDelete, onSelect }: { npc: NpcEntry; onStatusCycle: () => void; onDelete: () => void; onSelect: () => void }) {
  return (
    <div
      className="rounded-lg border border-border bg-card p-4 flex flex-col gap-3 hover:border-primary/30 transition-colors cursor-pointer"
      onClick={onSelect}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="flex flex-col gap-1.5 min-w-0">
          <span className="font-semibold text-card-foreground leading-tight truncate">{npc.name}</span>
          <span className={`self-start text-xs px-2 py-0.5 rounded-full border font-medium ${ROLE_COLORS[npc.role]}`}>
            {ROLE_LABELS[npc.role]}
          </span>
        </div>
        <div className="flex items-center gap-1.5 shrink-0">
          <button
            onClick={(e) => { e.stopPropagation(); onStatusCycle(); }}
            title="Cycle status"
            className={`rounded-full border px-2.5 py-0.5 text-[10px] font-semibold capitalize transition-colors ${STATUS_COLORS[npc.status]}`}
          >
            {npc.status}
          </button>
          <button
            onClick={(e) => { e.stopPropagation(); onDelete(); }}
            className="p-1 rounded text-muted-foreground hover:text-destructive transition-colors"
            title="Remove"
          >
            <svg width="13" height="13" viewBox="0 0 20 20" fill="currentColor">
              <path fillRule="evenodd" clipRule="evenodd" d="M9 2a1 1 0 00-.894.553L7.382 4H4a1 1 0 000 2v10a2 2 0 002 2h8a2 2 0 002-2V6a1 1 0 100-2h-3.382l-.724-1.447A1 1 0 0011 2H9zM7 8a1 1 0 012 0v6a1 1 0 11-2 0V8zm4 0a1 1 0 012 0v6a1 1 0 11-2 0V8z" />
            </svg>
          </button>
        </div>
      </div>
      {npc.description && <p className="text-sm text-muted-foreground leading-relaxed line-clamp-2">{npc.description}</p>}
      <p className="text-xs text-muted-foreground/60 mt-auto">Click to edit details</p>
    </div>
  );
}

function AddNpcInline({ campaign, onDone }: { campaign: Campaign; onDone: () => void }) {
  const [name, setName] = useState("");
  const [role, setRole] = useState<NpcRole>("npc");
  const [description, setDescription] = useState("");
  const create = useCreateNpc();

  const handleSubmit = () => {
    if (!name.trim()) return;
    create.mutate(
      { name: name.trim(), role, description: description.trim() || undefined, status: "unknown", campaign_id: campaign.id },
      { onSuccess: () => { setName(""); setDescription(""); onDone(); } }
    );
  };

  return (
    <div className="rounded-lg border border-border bg-muted/20 p-4 flex flex-col gap-3">
      <h3 className="text-xs font-semibold uppercase tracking-widest text-muted-foreground" style={{ fontFamily: "var(--font-heading)" }}>
        Add Character
      </h3>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <input type="text" placeholder="Name" value={name} onChange={(e) => setName(e.target.value)}
          className="rounded-md border border-input bg-background px-3 py-2 text-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring" />
        <select value={role} onChange={(e) => setRole(e.target.value as NpcRole)}
          className="rounded-md border border-input bg-background px-3 py-2 text-sm text-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring">
          <option value="npc">NPC</option>
          <option value="pc">Player Character</option>
          <option value="monster">Monster / Boss</option>
          <option value="faction">Faction / Group</option>
        </select>
        <div className="sm:col-span-2">
          <textarea placeholder="Description (optional)" value={description} onChange={(e) => setDescription(e.target.value)} rows={2}
            className="resize-none w-full rounded-md border border-input bg-background px-3 py-2 text-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring" />
        </div>
      </div>
      <div className="flex gap-2">
        <button onClick={handleSubmit} disabled={create.isPending || !name.trim()}
          className="rounded-md bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground hover:opacity-90 disabled:opacity-50 transition-opacity">
          {create.isPending ? "Adding…" : "Add Character"}
        </button>
        <button onClick={onDone} className="text-sm text-muted-foreground hover:text-foreground transition-colors px-3 py-2">Cancel</button>
      </div>
    </div>
  );
}

function CampaignCharacters({ campaign }: { campaign: Campaign }) {
  const { data: npcs, isLoading } = useNpcs(campaign.id);
  const update = useUpdateNpc(campaign.id);
  const remove = useDeleteNpc(campaign.id);
  const extract = useExtractNpcs();
  const create = useCreateNpc();
  const [showForm, setShowForm] = useState(false);
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [selectedNpc, setSelectedNpc] = useState<NpcEntry | null>(null);

  const handleExtract = () => {
    extract.mutate(campaign.id, { onSuccess: ({ data }) => setSuggestions(data.suggestions) });
  };

  const addSuggestion = (name: string) => {
    create.mutate(
      { name, role: "npc", status: "unknown", campaign_id: campaign.id },
      { onSuccess: () => setSuggestions((s) => s.filter((n) => n !== name)) }
    );
  };

  return (
    <div className="flex flex-col gap-5">
      {/* Toolbar */}
      <div className="flex items-center gap-2 flex-wrap">
        <button onClick={() => setShowForm((v) => !v)}
          className="flex items-center gap-1.5 text-sm px-3 py-1.5 rounded-md bg-primary text-primary-foreground hover:opacity-90 transition-opacity font-medium">
          <svg width="14" height="14" viewBox="0 0 20 20" fill="currentColor"><path fillRule="evenodd" d="M10 3a1 1 0 011 1v5h5a1 1 0 110 2h-5v5a1 1 0 11-2 0v-5H4a1 1 0 110-2h5V4a1 1 0 011-1z" /></svg>
          {showForm ? "Cancel" : "Add Character"}
        </button>
        <button onClick={handleExtract} disabled={extract.isPending}
          className="flex items-center gap-1.5 text-sm px-3 py-1.5 rounded-md border border-border text-muted-foreground hover:text-foreground hover:bg-muted/60 transition-colors disabled:opacity-50">
          {extract.isPending ? (
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="animate-spin"><path d="M21 12a9 9 0 11-6.219-8.56" /></svg>
          ) : (
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" />
            </svg>
          )}
          Extract from journals
        </button>
        {npcs && npcs.length > 0 && (
          <span className="ml-auto text-xs text-muted-foreground">{npcs.length} character{npcs.length !== 1 ? "s" : ""}</span>
        )}
      </div>

      {showForm && <AddNpcInline campaign={campaign} onDone={() => setShowForm(false)} />}

      {suggestions.length > 0 && (
        <div className="rounded-lg border border-border bg-muted/20 p-4 flex flex-col gap-3">
          <p className="text-xs font-semibold uppercase tracking-widest text-muted-foreground" style={{ fontFamily: "var(--font-heading)" }}>
            Detected in journals
          </p>
          <div className="flex flex-wrap gap-2">
            {suggestions.map((name) => (
              <button key={name} onClick={() => addSuggestion(name)}
                className="rounded-full border border-border bg-background px-3 py-1 text-sm text-foreground hover:bg-muted/60 transition-colors flex items-center gap-1">
                <svg width="11" height="11" viewBox="0 0 20 20" fill="currentColor"><path fillRule="evenodd" d="M10 3a1 1 0 011 1v5h5a1 1 0 110 2h-5v5a1 1 0 11-2 0v-5H4a1 1 0 110-2h5V4a1 1 0 011-1z" /></svg>
                {name}
              </button>
            ))}
          </div>
        </div>
      )}

      {isLoading && (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
          {[...Array(6)].map((_, i) => <div key={i} className="rounded-lg border border-border h-28 animate-pulse bg-muted/40" />)}
        </div>
      )}

      {!isLoading && !npcs?.length && !showForm && (
        <div className="text-center py-16 text-muted-foreground border border-dashed border-border rounded-xl">
          <p className="text-4xl mb-3">🧙</p>
          <p className="text-sm font-medium text-foreground mb-1">No characters yet</p>
          <p className="text-xs">Add one manually or use "Extract from journals" to detect NPCs.</p>
        </div>
      )}

      {npcs && npcs.length > 0 && (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
          {npcs.map((npc) => (
            <NpcCard key={npc.id} npc={npc}
              onStatusCycle={() => update.mutate({ id: npc.id, data: { status: STATUS_CYCLE[npc.status] } })}
              onDelete={() => remove.mutate(npc.id)}
              onSelect={() => setSelectedNpc(npc)} />
          ))}
        </div>
      )}

      <NpcDetailPanel
        npc={selectedNpc}
        campaignId={campaign.id}
        onClose={() => setSelectedNpc(null)}
      />
    </div>
  );
}

export function CharactersPage() {
  const { data: campaigns } = useCampaigns();
  const [selected, setSelected] = useState<Campaign | null>(null);

  return (
    <div className="max-w-5xl mx-auto px-4 py-6 md:py-10 flex flex-col gap-6">
      <PageHeader
        title="Character Wiki"
        description="Track NPCs, player characters, monsters, and factions. Click a status badge to cycle it."
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
          <p className="text-4xl mb-3">🗡️</p>
          <p className="text-sm font-medium text-foreground mb-1">Select a campaign</p>
          <p className="text-xs">Choose a campaign above to manage its characters.</p>
        </div>
      )}

      {selected && <CampaignCharacters campaign={selected} />}
    </div>
  );
}
