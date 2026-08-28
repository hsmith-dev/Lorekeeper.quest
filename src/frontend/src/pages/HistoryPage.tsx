import { useState } from "react";
import { useJournals } from "../hooks/useJournals";
import { JournalCard } from "../components/JournalCard";
import { PageHeader } from "../components/PageHeader";
import { useDebounce } from "../hooks/useDebounce";

export function HistoryPage() {
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const debouncedSearch = useDebounce(search, 300);

  const { data, isLoading } = useJournals({ search: debouncedSearch || undefined, page });
  const totalPages = data ? Math.ceil(data.total / data.limit) : 1;

  return (
    <div className="max-w-3xl mx-auto px-4 py-6 md:py-10 flex flex-col gap-6">
      <PageHeader title="Chronicle Archive" description="All journal entries across every campaign." />

      <div className="relative">
        <svg
          width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
          strokeLinecap="round" strokeLinejoin="round"
          className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground pointer-events-none"
        >
          <circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" />
        </svg>
        <input
          type="text"
          placeholder="Search all entries…"
          value={search}
          onChange={(e) => { setSearch(e.target.value); setPage(1); }}
          className="w-full rounded-md border border-input bg-background pl-9 pr-3 py-2.5 text-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring transition-shadow"
        />
      </div>

      {!isLoading && data && data.total > 0 && (
        <p className="text-xs text-muted-foreground -mt-3">
          {data.total} entr{data.total === 1 ? "y" : "ies"}{search.trim() ? ` matching “${search.trim()}”` : ""}
        </p>
      )}

      {isLoading && (
        <div className="flex flex-col gap-3">
          {[...Array(4)].map((_, i) => (
            <div key={i} className="rounded-lg border border-border bg-card/50 h-28 animate-pulse" />
          ))}
        </div>
      )}

      {!isLoading && data?.items.length === 0 && (
        <div className="text-center py-16 text-muted-foreground">
          <p className="text-3xl mb-3">📜</p>
          {search.trim() ? (
            <p className="text-sm">No entries match “{search.trim()}”. Try a different search.</p>
          ) : (
            <p className="text-sm">No entries found. Start writing your adventure.</p>
          )}
        </div>
      )}

      <div className="flex flex-col gap-3">
        {data?.items.map((entry) => (
          <JournalCard key={entry.id} entry={entry} preview linkable />
        ))}
      </div>

      {data && data.total > data.limit && (
        <div className="flex gap-3 justify-center items-center">
          <button
            disabled={page === 1}
            onClick={() => setPage((p) => p - 1)}
            className="text-sm px-4 py-1.5 rounded-md border border-border disabled:opacity-40 hover:bg-muted/60 transition-colors"
          >
            ← Prev
          </button>
          <span className="text-sm text-muted-foreground">
            {page} / {totalPages}
          </span>
          <button
            disabled={page * data.limit >= data.total}
            onClick={() => setPage((p) => p + 1)}
            className="text-sm px-4 py-1.5 rounded-md border border-border disabled:opacity-40 hover:bg-muted/60 transition-colors"
          >
            Next →
          </button>
        </div>
      )}
    </div>
  );
}
