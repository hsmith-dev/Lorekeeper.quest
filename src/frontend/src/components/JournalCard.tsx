import { Link } from "react-router-dom";
import type { JournalEntry, TagType } from "../types";
import { formatDate } from "../utils/formatDate";

const TAG_STYLES: Record<TagType, string> = {
  character: "bg-primary/15 text-primary border-primary/30",
  location:  "bg-accent/15 text-accent-foreground border-accent/30",
  item:      "bg-secondary/20 text-secondary-foreground border-secondary/40",
  quest:     "bg-muted text-muted-foreground border-border",
  faction:   "bg-destructive/15 text-destructive-foreground border-destructive/30",
};

interface JournalCardProps {
  entry: JournalEntry;
  preview?: boolean;
  linkable?: boolean;
}

export function JournalCard({ entry, preview = true, linkable = false }: JournalCardProps) {
  const displayText = preview
    ? entry.narrative.slice(0, 220) + (entry.narrative.length > 220 ? "…" : "")
    : entry.narrative;

  const card = (
    <div className={`rounded-lg border border-border bg-card p-4 flex flex-col gap-3 transition-colors ${linkable ? "hover:border-primary/50 hover:bg-card/80" : ""}`}>
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs text-muted-foreground">
          {entry.session_date ? formatDate(entry.session_date) : formatDate(entry.created_at)}
        </span>
        {linkable && (
          <span className="text-xs text-muted-foreground">View →</span>
        )}
      </div>
      <p className="text-sm leading-relaxed text-card-foreground">{displayText}</p>
      {entry.tags.length > 0 && (
        <div className="flex flex-wrap gap-1.5 pt-1">
          {entry.tags.map((tag) => (
            <span
              key={tag.id}
              className={`text-xs px-2 py-0.5 rounded-full border font-medium ${(tag.tag_type && TAG_STYLES[tag.tag_type]) ?? "bg-muted text-muted-foreground border-border"}`}
            >
              {tag.custom_category ? `${tag.custom_category.name}: ` : ""}{tag.name}
            </span>
          ))}
        </div>
      )}
    </div>
  );

  if (linkable) {
    return <Link to={`/journal/${entry.id}`} className="block">{card}</Link>;
  }
  return card;
}
