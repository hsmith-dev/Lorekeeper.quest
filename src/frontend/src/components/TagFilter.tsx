import { useTags } from "../hooks/useTags";
import type { TagType } from "../types";

const TAG_TYPE_ORDER: TagType[] = ["character", "location", "quest", "item", "faction"];

interface TagFilterProps {
  campaign_id: string;
  selectedTagId: string | undefined;
  onSelect: (tag_id: string | undefined) => void;
}

export function TagFilter({ campaign_id, selectedTagId, onSelect }: TagFilterProps) {
  const { data: tags } = useTags(campaign_id);
  if (!tags?.length) return null;

  const grouped = TAG_TYPE_ORDER.reduce<Record<string, typeof tags>>((acc, type) => {
    acc[type] = tags.filter((t) => t.tag_type === type);
    return acc;
  }, {});

  const customGroups = new Map<string, typeof tags>();
  for (const tag of tags) {
    if (!tag.custom_category) continue;
    const key = tag.custom_category.name;
    if (!customGroups.has(key)) customGroups.set(key, []);
    customGroups.get(key)!.push(tag);
  }

  const renderGroup = (label: string, groupTags: typeof tags) => (
    <div key={label}>
      <p className="text-xs font-semibold uppercase text-muted-foreground mb-1">{label}</p>
      <div className="flex flex-wrap gap-1">
        {groupTags.map((tag) => (
          <button
            key={tag.id}
            onClick={() => onSelect(selectedTagId === tag.id ? undefined : tag.id)}
            className={`text-xs px-2 py-1 rounded-full border transition-colors ${
              selectedTagId === tag.id
                ? "bg-primary text-primary-foreground border-primary"
                : "bg-card border-border hover:bg-accent"
            }`}
          >
            {tag.name} ({tag.entry_count})
          </button>
        ))}
      </div>
    </div>
  );

  return (
    <div className="flex flex-col gap-2">
      {TAG_TYPE_ORDER.map((type) => (grouped[type]?.length ? renderGroup(`${type}s`, grouped[type]) : null))}
      {[...customGroups.entries()].map(([name, groupTags]) => renderGroup(name, groupTags))}
      {selectedTagId && (
        <button className="text-xs underline text-muted-foreground" onClick={() => onSelect(undefined)}>
          Clear filter
        </button>
      )}
    </div>
  );
}
