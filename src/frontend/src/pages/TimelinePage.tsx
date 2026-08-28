import { useState } from "react";
import { Link } from "react-router-dom";
import { useCampaigns } from "../hooks/useCampaigns";
import { useJournals } from "../hooks/useJournals";
import { PageHeader } from "../components/PageHeader";
import type { Campaign, JournalEntry, TagType } from "../types";
import { formatDate } from "../utils/formatDate";

const TAG_STYLES: Record<TagType, string> = {
  character: "bg-primary/15 text-primary border-primary/30",
  location:  "bg-accent/15 text-accent-foreground border-accent/30",
  item:      "bg-secondary/20 text-secondary-foreground border-secondary/40",
  quest:     "bg-muted text-muted-foreground border-border",
  faction:   "bg-destructive/15 text-destructive-foreground border-destructive/30",
};

// Solid fills for the timeline node itself — TAG_STYLES above are all
// translucent (/15, /20) for badge backgrounds, which reads as washed-out
// at 12px. A node takes its color from the entry's first tag, so at a
// glance the spine hints at what kind of session it was (a fight, a
// shopping trip, a big reveal) before you've read a word of the card.
const TAG_NODE_COLOR: Record<TagType, string> = {
  character: "bg-primary",
  location: "bg-accent",
  item: "bg-secondary",
  quest: "bg-foreground",
  faction: "bg-destructive",
};

function effectiveTime(entry: JournalEntry): number {
  return new Date(entry.session_date ?? entry.created_at).getTime();
}

function monthYearLabel(entry: JournalEntry): string {
  return new Date(entry.session_date ?? entry.created_at).toLocaleDateString(undefined, {
    month: "long",
    year: "numeric",
  });
}

function TimelineEntry({
  entry,
  sessionNumber,
  isLast,
  isLatest,
}: {
  entry: JournalEntry;
  sessionNumber: number;
  isLast: boolean;
  isLatest: boolean;
}) {
  const [expanded, setExpanded] = useState(false);
  const dateStr = entry.session_date ? formatDate(entry.session_date) : formatDate(entry.created_at);
  const nodeColor = entry.tags[0]?.tag_type ? TAG_NODE_COLOR[entry.tags[0].tag_type] : "bg-primary";

  return (
    <div className="relative flex gap-4">
      {/* Spine: node + connecting line down to the next row (entry or month header) */}
      <div className="flex flex-col items-center shrink-0 w-3">
        <div className="relative mt-1 shrink-0">
          {isLatest && (
            <span className={`absolute inset-0 rounded-full ${nodeColor} opacity-60 animate-ping`} />
          )}
          <div className={`relative w-3 h-3 rounded-full ${nodeColor} border-2 border-background ring-2 ring-primary/30`} />
        </div>
        {!isLast && <div className="w-px flex-1 bg-gradient-to-b from-border to-border/50 mt-1" />}
      </div>

      {/* Card */}
      <div className="pb-6 flex-1 min-w-0">
        <div className="flex items-baseline gap-2 mb-1.5">
          <span className="text-xs font-bold text-primary tabular-nums">Session {sessionNumber}</span>
          <span className="text-xs text-muted-foreground">·</span>
          <span className="text-xs font-medium text-muted-foreground">{dateStr}</span>
          {isLatest && (
            <span className="text-[10px] font-semibold uppercase tracking-wide text-primary/80 bg-primary/10 border border-primary/20 rounded-full px-1.5 py-0.5">
              Latest
            </span>
          )}
        </div>
        <Link to={`/journal/${entry.id}`} className="block group">
          <div className="rounded-lg border border-border bg-card p-4 flex flex-col gap-2.5 transition-all group-hover:border-primary/40 group-hover:bg-card/80 group-hover:shadow-sm group-hover:-translate-y-0.5">
            <p className="text-xs text-muted-foreground italic line-clamp-1">
              Notes: {entry.shorthand}
            </p>
            <p className={`text-sm leading-relaxed text-card-foreground ${expanded ? "" : "line-clamp-3"}`}>
              {entry.narrative}
            </p>
            {entry.narrative.length > 200 && (
              <button
                type="button"
                onClick={(e) => { e.preventDefault(); setExpanded((v) => !v); }}
                className="text-xs text-muted-foreground hover:text-foreground transition-colors self-start"
              >
                {expanded ? "Show less ↑" : "Read more ↓"}
              </button>
            )}
            {entry.tags.length > 0 && (
              <div className="flex flex-wrap gap-1.5">
                {entry.tags.map((tag) => (
                  <span key={tag.id} className={`text-xs px-2 py-0.5 rounded-full border font-medium ${(tag.tag_type && TAG_STYLES[tag.tag_type]) ?? "bg-muted text-muted-foreground border-border"}`}>
                    {tag.custom_category ? `${tag.custom_category.name}: ` : ""}{tag.name}
                  </span>
                ))}
              </div>
            )}
          </div>
        </Link>
      </div>
    </div>
  );
}

function MonthHeaderRow({ label, isLast }: { label: string; isLast: boolean }) {
  return (
    <div className="relative flex gap-4">
      {/* Spine keeps running through the header — a timeline shouldn't ever
          visually break just because the calendar page turned. */}
      <div className="flex flex-col items-center shrink-0 w-3">
        {!isLast && <div className="w-px flex-1 bg-gradient-to-b from-border to-border/50 my-1" />}
      </div>
      <div className="flex-1 flex items-center gap-2 pt-1 pb-3">
        <span className="text-[11px] font-bold tracking-widest uppercase text-primary/70 shrink-0">
          {label}
        </span>
        <div className="h-px flex-1 bg-gradient-to-r from-border to-transparent" />
      </div>
    </div>
  );
}

type Row =
  | { type: "header"; key: string; label: string }
  | { type: "entry"; key: string; entry: JournalEntry; sessionNumber: number };

function CampaignTimeline({ campaign }: { campaign: Campaign }) {
  const [order, setOrder] = useState<"asc" | "desc">("asc");
  const { data, isLoading } = useJournals({ campaign_id: campaign.id, limit: 100 } as Parameters<typeof useJournals>[0]);

  // Session numbers always reflect actual chronological order, regardless of
  // which way the list is currently sorted — "Session 1" stays "Session 1"
  // whether you're reading oldest-first or newest-first.
  const chronological = data?.items
    ? [...data.items].sort((a, b) => effectiveTime(a) - effectiveTime(b))
    : [];
  const numbered = chronological.map((entry, i) => ({ entry, sessionNumber: i + 1 }));
  const displayed = order === "asc" ? numbered : [...numbered].reverse();
  const latestId = chronological[chronological.length - 1]?.id;

  const rows: Row[] = [];
  let lastLabel: string | null = null;
  for (const { entry, sessionNumber } of displayed) {
    const label = monthYearLabel(entry);
    if (label !== lastLabel) {
      rows.push({ type: "header", key: `h-${label}-${rows.length}`, label });
      lastLabel = label;
    }
    rows.push({ type: "entry", key: entry.id, entry, sessionNumber });
  }

  const first = chronological[0];
  const last = chronological[chronological.length - 1];

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <span className="text-xs text-muted-foreground">
          {data?.total ?? 0} session{data?.total !== 1 ? "s" : ""}
          {first && last && first !== last && (
            <> · {formatDate(first.session_date ?? first.created_at)} → {formatDate(last.session_date ?? last.created_at)}</>
          )}
        </span>
        <button
          onClick={() => setOrder((o) => (o === "asc" ? "desc" : "asc"))}
          className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors px-2.5 py-1.5 rounded-md border border-border hover:bg-muted/60"
        >
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <line x1="8" y1="6" x2="21" y2="6" /><line x1="8" y1="12" x2="21" y2="12" /><line x1="8" y1="18" x2="21" y2="18" />
            <line x1="3" y1="6" x2="3.01" y2="6" /><line x1="3" y1="12" x2="3.01" y2="12" /><line x1="3" y1="18" x2="3.01" y2="18" />
          </svg>
          {order === "asc" ? "Oldest first" : "Newest first"}
        </button>
      </div>

      {isLoading && (
        <div className="flex flex-col gap-4">
          {[...Array(4)].map((_, i) => (
            <div key={i} className="flex gap-4">
              <div className="flex flex-col items-center shrink-0">
                <div className="w-3 h-3 rounded-full bg-muted mt-1" />
                <div className="w-px flex-1 bg-border mt-1" />
              </div>
              <div className="flex-1 pb-6">
                <div className="h-3 w-20 bg-muted rounded mb-2 animate-pulse" />
                <div className="h-24 rounded-lg border border-border bg-muted/40 animate-pulse" />
              </div>
            </div>
          ))}
        </div>
      )}

      {!isLoading && !rows.length && (
        <div className="text-center py-16 text-muted-foreground">
          <p className="text-4xl mb-3">📜</p>
          <p className="text-sm">No journal entries yet. Head to the Journal page and add your first session!</p>
        </div>
      )}

      {rows.map((row, i) => {
        const isLastRow = i === rows.length - 1;
        return row.type === "header" ? (
          <MonthHeaderRow key={row.key} label={row.label} isLast={isLastRow} />
        ) : (
          <TimelineEntry
            key={row.key}
            entry={row.entry}
            sessionNumber={row.sessionNumber}
            isLast={isLastRow}
            isLatest={row.entry.id === latestId}
          />
        );
      })}
    </div>
  );
}

export function TimelinePage() {
  const { data: campaigns } = useCampaigns();
  const [selected, setSelected] = useState<Campaign | null>(null);

  return (
    <div className="max-w-3xl mx-auto px-4 py-6 md:py-10 flex flex-col gap-6">
      <PageHeader
        dataTour="timeline-heading"
        title="Campaign Timeline"
        description="Your adventure, told in order. Every session, every entry."
      />

      {campaigns && campaigns.length > 0 && (
        <div className="flex gap-1.5 flex-wrap border-b border-border pb-3">
          {campaigns.map((c) => (
            <button
              key={c.id}
              onClick={() => setSelected(c)}
              className={`px-3 py-1.5 rounded-md text-sm transition-colors ${
                selected?.id === c.id
                  ? "bg-muted text-foreground font-medium"
                  : "text-muted-foreground hover:text-foreground hover:bg-muted/60"
              }`}
            >
              {c.name}
            </button>
          ))}
        </div>
      )}

      {!selected && (
        <div className="text-center py-16 text-muted-foreground">
          <p className="text-4xl mb-3">⏳</p>
          <p className="text-sm">Select a campaign above to view its timeline.</p>
        </div>
      )}

      {selected && <CampaignTimeline campaign={selected} />}
    </div>
  );
}
