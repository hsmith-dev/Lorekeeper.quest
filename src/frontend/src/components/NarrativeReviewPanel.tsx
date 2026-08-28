interface NarrativeReviewPanelProps {
  narrative: string;
  onChange: (text: string) => void;
  onSave: () => void;
  onDiscard: () => void;
  onRegenerate?: () => void;
  saving: boolean;
  regenerating?: boolean;
  title?: string;
  saveLabel?: string;
  rows?: number;
  // Optional short editable title field shown above the body textarea — used
  // by session plans (which need a title + content), left unset for journal
  // entries (which only ever have the one field).
  itemTitle?: string;
  onItemTitleChange?: (text: string) => void;
  itemTitlePlaceholder?: string;
  // Shown when a save/regenerate attempt fails — every caller must pass its
  // own mutation's error state in here, since this component's rendered
  // instead of (not alongside) whatever "input" view holds a generic error
  // message, so nothing else has a chance to show one while this is up.
  error?: string | null;
}

/** Shown after an AI draft comes back and before it's persisted — lets the
 * user read, hand-edit, regenerate, or throw away the generated text. Used
 * anywhere a draft is generated before being saved (journal entries, session
 * plans) so the review step looks and behaves the same everywhere. */
export function NarrativeReviewPanel({
  narrative,
  onChange,
  onSave,
  onDiscard,
  onRegenerate,
  saving,
  regenerating,
  title = "Review before saving",
  saveLabel = "Save Entry",
  rows = 8,
  itemTitle,
  onItemTitleChange,
  itemTitlePlaceholder = "Title",
  error,
}: NarrativeReviewPanelProps) {
  const hasTitleField = itemTitle !== undefined && onItemTitleChange !== undefined;
  return (
    <div className="flex flex-col gap-2 rounded-lg border border-primary/30 bg-primary/5 p-3">
      <div className="flex items-center justify-between">
        <h3 className="text-xs font-semibold uppercase tracking-widest text-muted-foreground" style={{ fontFamily: "var(--font-heading)" }}>
          {title}
        </h3>
        <span className="text-[10px] text-muted-foreground">Edit freely — nothing's saved yet</span>
      </div>
      {hasTitleField && (
        <input
          type="text"
          value={itemTitle}
          onChange={(e) => onItemTitleChange!(e.target.value)}
          placeholder={itemTitlePlaceholder}
          disabled={saving || regenerating}
          className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm font-medium focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:opacity-60"
        />
      )}
      <textarea
        value={narrative}
        onChange={(e) => onChange(e.target.value)}
        rows={rows}
        disabled={saving || regenerating}
        className="w-full resize-y rounded-md border border-input bg-background px-3 py-2.5 text-sm leading-relaxed focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:opacity-60"
      />
      <div className="flex items-center gap-2 flex-wrap">
        <button
          onClick={onSave}
          disabled={saving || regenerating || !narrative.trim() || (hasTitleField && !itemTitle.trim())}
          className="rounded-md bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground hover:opacity-90 disabled:opacity-50 transition-opacity"
          style={{ fontFamily: "var(--font-heading)" }}
        >
          {saving ? "Saving…" : saveLabel}
        </button>
        {onRegenerate && (
          <button
            onClick={onRegenerate}
            disabled={saving || regenerating}
            className="rounded-md border border-input bg-background px-3 py-2 text-sm font-medium text-foreground hover:bg-accent/60 disabled:opacity-50 transition-colors"
          >
            {regenerating ? "Regenerating…" : "Regenerate"}
          </button>
        )}
        <button
          onClick={onDiscard}
          disabled={saving || regenerating}
          className="text-sm text-muted-foreground hover:text-foreground disabled:opacity-50 transition-colors"
        >
          Discard
        </button>
      </div>
      {error && (
        <p className="text-sm text-destructive bg-destructive/10 rounded-md px-3 py-2">{error}</p>
      )}
    </div>
  );
}
