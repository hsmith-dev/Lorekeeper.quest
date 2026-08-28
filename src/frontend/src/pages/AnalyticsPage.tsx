import { useState } from "react";
import { useCampaigns } from "../hooks/useCampaigns";
import { useCampaignAnalytics } from "../hooks/useAnalytics";
import { PageHeader } from "../components/PageHeader";
import type { Campaign, TagCount } from "../types";

function StatTile({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded-lg border border-border bg-card p-4 flex flex-col gap-1">
      <span className="text-2xl font-bold text-foreground" style={{ fontFamily: "var(--font-heading)" }}>
        {value}
      </span>
      <span className="text-xs text-muted-foreground uppercase tracking-wide">{label}</span>
    </div>
  );
}

function shortWeekLabel(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

function WeeklyBarChart({ data }: { data: { week_start: string; count: number }[] }) {
  const [hovered, setHovered] = useState<number | null>(null);
  if (data.length === 0) {
    return <p className="text-sm text-muted-foreground">No entries yet.</p>;
  }
  const max = Math.max(...data.map((d) => d.count), 1);

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-end gap-2 h-40 border-b border-border pb-0.5">
        {data.map((d, i) => (
          <div
            key={d.week_start}
            className="flex-1 flex flex-col items-center justify-end h-full group cursor-default"
            onMouseEnter={() => setHovered(i)}
            onMouseLeave={() => setHovered(null)}
          >
            <span className={`text-[10px] text-muted-foreground mb-1 transition-opacity ${hovered === i ? "opacity-100" : "opacity-0"}`}>
              {d.count}
            </span>
            <div
              className="w-full max-w-8 rounded-t-[4px] bg-primary transition-opacity"
              style={{
                height: `${Math.max((d.count / max) * 100, 4)}%`,
                opacity: hovered === null || hovered === i ? 1 : 0.5,
              }}
            />
          </div>
        ))}
      </div>
      <div className="flex gap-2">
        {data.map((d) => (
          <span key={d.week_start} className="flex-1 text-center text-[10px] text-muted-foreground truncate">
            {shortWeekLabel(d.week_start)}
          </span>
        ))}
      </div>
    </div>
  );
}

function TagRankList({ items }: { items: TagCount[] }) {
  if (items.length === 0) {
    return <p className="text-sm text-muted-foreground">No tagged mentions yet.</p>;
  }
  const max = Math.max(...items.map((t) => t.count), 1);
  return (
    <div className="flex flex-col gap-2.5">
      {items.map((t) => (
        <div key={t.name} className="flex items-center gap-3">
          <span className="text-sm text-foreground w-28 truncate shrink-0">{t.name}</span>
          <div className="flex-1 h-2 rounded-full bg-muted overflow-hidden">
            <div className="h-full rounded-full bg-primary" style={{ width: `${(t.count / max) * 100}%` }} />
          </div>
          <span className="text-xs text-muted-foreground w-6 text-right shrink-0">{t.count}</span>
        </div>
      ))}
    </div>
  );
}

function CampaignAnalyticsView({ campaign }: { campaign: Campaign }) {
  const { data, isLoading } = useCampaignAnalytics(campaign.id);

  if (isLoading) {
    return <div className="h-64 rounded-lg border border-border bg-card/50 animate-pulse" />;
  }
  if (!data) return null;

  return (
    <div className="flex flex-col gap-6">
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
        <StatTile label="Total Entries" value={data.total_entries} />
        <StatTile label="Avg Entry Length (chars)" value={Math.round(data.avg_entry_length)} />
        <StatTile label="Weeks Active" value={data.entries_per_week.length} />
      </div>

      <div className="rounded-lg border border-border bg-card p-4">
        <h3 className="text-xs font-semibold uppercase tracking-widest text-muted-foreground mb-4" style={{ fontFamily: "var(--font-heading)" }}>
          Entries per Week
        </h3>
        <WeeklyBarChart data={data.entries_per_week} />
      </div>

      <div className="grid sm:grid-cols-2 gap-4">
        <div className="rounded-lg border border-border bg-card p-4">
          <h3 className="text-xs font-semibold uppercase tracking-widest text-muted-foreground mb-4" style={{ fontFamily: "var(--font-heading)" }}>
            Most-Mentioned Characters
          </h3>
          <TagRankList items={data.top_characters} />
        </div>
        <div className="rounded-lg border border-border bg-card p-4">
          <h3 className="text-xs font-semibold uppercase tracking-widest text-muted-foreground mb-4" style={{ fontFamily: "var(--font-heading)" }}>
            Most-Mentioned Quests
          </h3>
          <TagRankList items={data.top_quests} />
        </div>
      </div>
    </div>
  );
}

export function AnalyticsPage() {
  const { data: campaigns } = useCampaigns();
  const [selected, setSelected] = useState<Campaign | null>(null);

  return (
    <div className="max-w-5xl mx-auto px-4 py-6 md:py-10 flex flex-col gap-6">
      <PageHeader
        title="Campaign Analytics"
        description="Session activity and the characters and quests that come up most."
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
          <p className="text-4xl mb-3">📊</p>
          <p className="text-sm font-medium text-foreground mb-1">Select a campaign</p>
          <p className="text-xs">Choose a campaign above to see its analytics.</p>
        </div>
      )}

      {selected && <CampaignAnalyticsView campaign={selected} />}
    </div>
  );
}
