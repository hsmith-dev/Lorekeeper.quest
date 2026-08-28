import { useState } from "react";
import { useParams, Link, useNavigate } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useDeleteJournal } from "../hooks/useJournals";
import { useNarration } from "../hooks/useNarration";
import { formatDate } from "../utils/formatDate";
import * as api from "../services/api";
import type { JournalEntry, TagType } from "../types";

const BUILTIN_TAG_TYPES: TagType[] = ["character", "location", "item", "quest", "faction"];
const NEW_CATEGORY_VALUE = "__new__";

const TAG_STYLES: Record<TagType, string> = {
  character: "bg-primary/15 text-primary border-primary/30",
  location:  "bg-accent/15 text-accent-foreground border-accent/30",
  item:      "bg-secondary/20 text-secondary-foreground border-secondary/40",
  quest:     "bg-muted text-muted-foreground border-border",
  faction:   "bg-destructive/15 text-destructive-foreground border-destructive/30",
};

const TAG_LABELS: Record<TagType, string> = {
  character: "Character",
  location: "Location",
  item: "Item",
  quest: "Quest",
  faction: "Faction",
};

export function EntryDetailPage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const deleteJournal = useDeleteJournal();
  const narration = useNarration();
  const [adding, setAdding] = useState(false);
  const [tagName, setTagName] = useState("");
  const [category, setCategory] = useState<string>(BUILTIN_TAG_TYPES[0]);
  const [newCategoryName, setNewCategoryName] = useState("");
  const [tagError, setTagError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const { data: entry, isLoading } = useQuery<JournalEntry>({
    queryKey: ["journal", id],
    queryFn: async () => {
      const { data } = await api.getJournal(id!);
      return data;
    },
    enabled: !!id,
  });

  const { data: categories } = useQuery({
    queryKey: ["tagCategories", entry?.campaign_id],
    queryFn: async () => (await api.getTagCategories(entry!.campaign_id)).data,
    enabled: !!entry?.campaign_id,
  });

  const refreshEntry = () => qc.invalidateQueries({ queryKey: ["journal", id] });

  const handleAddTag = async () => {
    if (!entry || !tagName.trim()) return;
    setSaving(true);
    setTagError(null);
    try {
      let customCategoryId: string | undefined;
      let tagType: string | undefined;
      if (category === NEW_CATEGORY_VALUE) {
        if (!newCategoryName.trim()) { setTagError("Enter a name for the new category."); setSaving(false); return; }
        const { data: newCat } = await api.createTagCategory(entry.campaign_id, newCategoryName.trim());
        customCategoryId = newCat.id;
      } else if (BUILTIN_TAG_TYPES.includes(category as TagType)) {
        tagType = category;
      } else {
        customCategoryId = category;
      }
      await api.attachTag(entry.id, { name: tagName.trim(), tag_type: tagType, custom_category_id: customCategoryId });
      setTagName(""); setNewCategoryName(""); setAdding(false);
      qc.invalidateQueries({ queryKey: ["tagCategories", entry.campaign_id] });
      refreshEntry();
    } catch (err: any) {
      setTagError(err?.response?.data?.detail || "Could not add tag.");
    } finally {
      setSaving(false);
    }
  };

  const handleRemoveTag = async (tagId: string) => {
    if (!entry) return;
    await api.detachTag(entry.id, tagId);
    refreshEntry();
  };

  const handleDelete = async () => {
    if (!id || !confirm("Delete this entry? This cannot be undone.")) return;
    await deleteJournal.mutateAsync(id);
    navigate("/history");
  };

  if (isLoading) {
    return (
      <div className="max-w-2xl mx-auto px-4 py-10">
        <div className="flex flex-col gap-4 animate-pulse">
          <div className="h-4 bg-muted rounded w-24" />
          <div className="h-6 bg-muted rounded w-3/4" />
          <div className="h-40 bg-muted rounded" />
        </div>
      </div>
    );
  }

  if (!entry) {
    return (
      <div className="max-w-2xl mx-auto px-4 py-10 text-sm text-destructive">
        Entry not found.
      </div>
    );
  }

  return (
    <div className="max-w-2xl mx-auto px-4 py-6 md:py-10 flex flex-col gap-8">
      {/* Top bar */}
      <div className="flex items-center justify-between">
        <Link
          to="/history"
          className="text-sm text-muted-foreground hover:text-foreground transition-colors flex items-center gap-1"
        >
          ← Archive
        </Link>
        <button
          onClick={handleDelete}
          className="text-sm text-destructive hover:text-destructive/80 transition-colors"
        >
          Delete
        </button>
      </div>

      {/* Date */}
      <div className="flex flex-col gap-6">
        <p className="text-xs text-muted-foreground">
          {entry.session_date ? formatDate(entry.session_date) : formatDate(entry.created_at)}
        </p>

        {/* Original notes */}
        <section>
          <p
            className="text-xs font-semibold uppercase tracking-widest text-muted-foreground mb-2"
            style={{ fontFamily: "var(--font-heading)" }}
          >
            Session Notes
          </p>
          <p className="text-sm text-muted-foreground italic leading-relaxed border-l-2 border-border pl-4">
            {entry.shorthand}
          </p>
        </section>

        {/* Narrative */}
        <section>
          <div className="flex items-center justify-between mb-2">
            <p
              className="text-xs font-semibold uppercase tracking-widest text-muted-foreground"
              style={{ fontFamily: "var(--font-heading)" }}
            >
              Chronicle Entry
            </p>
            {narration.supported && (
              <button
                onClick={() => (narration.speaking ? narration.stop() : narration.speak(entry.narrative))}
                className="text-xs text-muted-foreground hover:text-foreground transition-colors flex items-center gap-1"
              >
                {narration.speaking ? "⏹ Stop" : "🔊 Read Aloud"}
              </button>
            )}
          </div>
          <p className="leading-relaxed whitespace-pre-wrap text-foreground">
            {entry.narrative}
          </p>
        </section>

        {/* Tags */}
        <section>
          <div className="flex items-center justify-between mb-3">
            <p
              className="text-xs font-semibold uppercase tracking-widest text-muted-foreground"
              style={{ fontFamily: "var(--font-heading)" }}
            >
              Entities
            </p>
            <button
              onClick={() => setAdding((v) => !v)}
              className="text-xs text-primary hover:underline underline-offset-2"
            >
              {adding ? "Cancel" : "+ Add Tag"}
            </button>
          </div>

          {entry.tags.length > 0 && (
            <div className="flex flex-wrap gap-2 mb-3">
              {entry.tags.map((tag) => (
                <span
                  key={tag.id}
                  className={`text-xs px-2.5 py-1 rounded-full border font-medium flex items-center gap-1.5 ${
                    (tag.tag_type && TAG_STYLES[tag.tag_type]) ?? "bg-muted text-muted-foreground border-border"
                  }`}
                >
                  <span className="opacity-60">
                    {tag.tag_type ? TAG_LABELS[tag.tag_type] : tag.custom_category?.name}:
                  </span>
                  {tag.name}
                  <button
                    onClick={() => handleRemoveTag(tag.id)}
                    className="opacity-50 hover:opacity-100 transition-opacity"
                    title="Remove tag"
                  >
                    ×
                  </button>
                </span>
              ))}
            </div>
          )}

          {entry.tags.length === 0 && !adding && (
            <p className="text-sm text-muted-foreground">No tags yet.</p>
          )}

          {adding && (
            <div className="rounded-lg border border-border bg-muted/20 p-3 flex flex-col gap-2">
              <div className="flex flex-col sm:flex-row gap-2">
                <input
                  type="text"
                  placeholder="Tag name"
                  value={tagName}
                  onChange={(e) => setTagName(e.target.value)}
                  className="flex-1 rounded-md border border-input bg-background px-3 py-2 text-sm"
                />
                <select
                  value={category}
                  onChange={(e) => setCategory(e.target.value)}
                  className="rounded-md border border-input bg-background px-3 py-2 text-sm"
                >
                  <optgroup label="Built-in">
                    {BUILTIN_TAG_TYPES.map((t) => <option key={t} value={t}>{TAG_LABELS[t]}</option>)}
                  </optgroup>
                  {categories && categories.length > 0 && (
                    <optgroup label="Custom">
                      {categories.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
                    </optgroup>
                  )}
                  <option value={NEW_CATEGORY_VALUE}>+ New category…</option>
                </select>
              </div>
              {category === NEW_CATEGORY_VALUE && (
                <input
                  type="text"
                  placeholder="New category name (e.g. Deity, House Rule)"
                  value={newCategoryName}
                  onChange={(e) => setNewCategoryName(e.target.value)}
                  className="rounded-md border border-input bg-background px-3 py-2 text-sm"
                />
              )}
              {tagError && <p className="text-xs text-destructive">{tagError}</p>}
              <button
                onClick={handleAddTag}
                disabled={saving || !tagName.trim()}
                className="self-start rounded-md bg-primary px-3 py-1.5 text-xs font-semibold text-primary-foreground disabled:opacity-50 hover:opacity-90 transition-opacity"
              >
                {saving ? "Adding…" : "Add Tag"}
              </button>
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
