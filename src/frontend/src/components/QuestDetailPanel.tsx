import { useState, useEffect } from "react";
import { Link } from "react-router-dom";
import { SlideOver } from "./SlideOver";
import { useUpdateQuest, useQuestEntries, useGenerateQuestDescription } from "../hooks/useQuests";
import { formatDate } from "../utils/formatDate";
import type { Quest, QuestStatus } from "../types";

const STATUS_OPTIONS: { value: QuestStatus; label: string }[] = [
  { value: "active", label: "Active" },
  { value: "completed", label: "Completed" },
  { value: "failed", label: "Failed" },
  { value: "abandoned", label: "Abandoned" },
];

interface Props {
  quest: Quest | null;
  campaignId: string;
  onClose: () => void;
}

export function QuestDetailPanel({ quest, campaignId, onClose }: Props) {
  const [title, setTitle] = useState("");
  const [status, setStatus] = useState<QuestStatus>("active");
  const [description, setDescription] = useState("");
  const [notes, setNotes] = useState("");
  const [saved, setSaved] = useState(false);

  const update = useUpdateQuest(campaignId);
  const generate = useGenerateQuestDescription(campaignId);
  const { data: entries, isLoading: entriesLoading } = useQuestEntries(quest?.id ?? null);

  useEffect(() => {
    if (!quest) return;
    setTitle(quest.title);
    setStatus(quest.status);
    setDescription(quest.description ?? "");
    setNotes(quest.notes ?? "");
    setSaved(false);
  }, [quest?.id]);

  if (!quest) return null;

  const handleSave = () => {
    update.mutate(
      { id: quest.id, data: { title, status, description: description || undefined, notes: notes || undefined } },
      { onSuccess: () => { setSaved(true); setTimeout(() => setSaved(false), 2000); } }
    );
  };

  const handleGenerate = () => {
    generate.mutate(quest.id, {
      onSuccess: ({ data }) => setDescription(data.description),
    });
  };

  const inputClass =
    "w-full rounded-md border border-input bg-background px-3 py-2 text-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring";

  return (
    <SlideOver open={!!quest} onClose={onClose} title={quest.title}>
      <div className="flex flex-col gap-5">
        {/* Core fields */}
        <div className="flex flex-col gap-3">
          <div className="flex flex-col gap-1.5">
            <label className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Title</label>
            <input type="text" value={title} onChange={(e) => setTitle(e.target.value)} className={inputClass} />
          </div>

          <div className="flex flex-col gap-1.5">
            <label className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Status</label>
            <select value={status} onChange={(e) => setStatus(e.target.value as QuestStatus)} className={inputClass}>
              {STATUS_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>{o.label}</option>
              ))}
            </select>
          </div>

          <div className="flex flex-col gap-1.5">
            <div className="flex items-center justify-between">
              <label className="text-xs font-medium text-muted-foreground uppercase tracking-wide">Description</label>
              <button
                onClick={handleGenerate}
                disabled={generate.isPending}
                className="flex items-center gap-1 text-xs text-primary hover:text-primary/80 transition-colors disabled:opacity-50"
              >
                {generate.isPending ? (
                  <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="animate-spin"><path d="M21 12a9 9 0 11-6.219-8.56" /></svg>
                ) : (
                  <span>✨</span>
                )}
                {generate.isPending ? "Generating…" : "Generate from journals"}
              </button>
            </div>
            <textarea
              rows={5}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Describe this quest…"
              className={`${inputClass} resize-none`}
            />
          </div>

          <div className="flex flex-col gap-1.5">
            <label className="text-xs font-medium text-muted-foreground uppercase tracking-wide">GM Notes</label>
            <textarea
              rows={3}
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="Private notes…"
              className={`${inputClass} resize-none`}
            />
          </div>
        </div>

        {/* Save */}
        <button
          onClick={handleSave}
          disabled={update.isPending || !title.trim()}
          className="w-full rounded-md bg-primary py-2 text-sm font-semibold text-primary-foreground hover:opacity-90 disabled:opacity-50 transition-opacity"
        >
          {update.isPending ? "Saving…" : saved ? "Saved ✓" : "Save Changes"}
        </button>

        {/* Related entries */}
        <div className="border-t border-border pt-4 flex flex-col gap-3">
          <h3 className="text-xs font-semibold uppercase tracking-widest text-muted-foreground" style={{ fontFamily: "var(--font-heading)" }}>
            Related Journal Entries
          </h3>

          {entriesLoading && (
            <div className="flex flex-col gap-2">
              {[...Array(3)].map((_, i) => (
                <div key={i} className="h-12 rounded-lg border border-border bg-muted/40 animate-pulse" />
              ))}
            </div>
          )}

          {!entriesLoading && !entries?.length && (
            <p className="text-xs text-muted-foreground italic">
              No journal entries mention "{quest.title}" yet.
            </p>
          )}

          {entries && entries.length > 0 && (
            <div className="flex flex-col gap-2">
              {entries.map((entry) => (
                <Link
                  key={entry.id}
                  to={`/journal/${entry.id}`}
                  onClick={onClose}
                  className="block rounded-lg border border-border bg-card p-3 hover:border-primary/40 transition-colors"
                >
                  <p className="text-xs text-primary mb-1">{formatDate(entry.session_date ?? entry.created_at)}</p>
                  <p className="text-sm text-card-foreground line-clamp-2">{entry.shorthand}</p>
                </Link>
              ))}
            </div>
          )}
        </div>
      </div>
    </SlideOver>
  );
}
