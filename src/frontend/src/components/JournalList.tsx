import { useState } from "react";
import { useJournals } from "../hooks/useJournals";
import { JournalCard } from "./JournalCard";
import { useDebounce } from "../hooks/useDebounce";

interface JournalListProps {
  campaign_id: string;
  tag_id?: string;
}

export function JournalList({ campaign_id, tag_id }: JournalListProps) {
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const debouncedSearch = useDebounce(search, 300);

  const { data, isLoading } = useJournals({ campaign_id, search: debouncedSearch || undefined, tag_id, page });
  const totalPages = data ? Math.ceil(data.total / data.limit) : 1;

  return (
    <div className="flex flex-col gap-4">
      <input
        type="text"
        placeholder="Search journal entries…"
        value={search}
        onChange={(e) => { setSearch(e.target.value); setPage(1); }}
        className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring transition-shadow"
      />

      {isLoading && (
        <div className="flex flex-col gap-3">
          {[...Array(3)].map((_, i) => (
            <div key={i} className="rounded-lg border border-border bg-card/50 h-28 animate-pulse" />
          ))}
        </div>
      )}

      {!isLoading && data?.items.length === 0 && (
        <p className="text-sm text-muted-foreground text-center py-8">
          No entries yet — write your first session notes above.
        </p>
      )}

      <div className="flex flex-col gap-3">
        {data?.items.map((entry) => (
          <JournalCard key={entry.id} entry={entry} preview linkable />
        ))}
      </div>

      {data && data.total > data.limit && (
        <div className="flex gap-3 justify-center items-center pt-2">
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
