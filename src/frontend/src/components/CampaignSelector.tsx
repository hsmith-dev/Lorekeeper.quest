import { useState } from "react";
import { useCreateCampaign, useGenerateCampaignConcept } from "../hooks/useCampaigns";
import { exportCampaign } from "../services/api";
import type { Campaign, Genre } from "../types";

interface CampaignSelectorProps {
  campaigns: Campaign[];
  selected: Campaign | null;
  onSelect: (campaign: Campaign) => void;
}

const GENRES: { value: Genre; label: string }[] = [
  { value: "fantasy", label: "Fantasy" },
  { value: "scifi", label: "Sci-Fi" },
  { value: "horror", label: "Horror" },
  { value: "videogame", label: "Video Game" },
  { value: "other", label: "Other" },
];

export function CampaignSelector({ campaigns, selected, onSelect }: CampaignSelectorProps) {
  const [showNew, setShowNew] = useState(false);
  const [name, setName] = useState("");
  const [genre, setGenre] = useState<Genre>("fantasy");
  const [description, setDescription] = useState("");
  const [showHomebrew, setShowHomebrew] = useState(false);
  const [homebrewPrompt, setHomebrewPrompt] = useState("");
  const [exporting, setExporting] = useState<"pdf" | "markdown" | null>(null);
  const createCampaign = useCreateCampaign();
  const generateConcept = useGenerateCampaignConcept();

  const mine = campaigns.filter((c) => c.is_owner);
  const shared = campaigns.filter((c) => !c.is_owner);
  // Two campaigns (yours and one shared with you) can have the same name —
  // default to whichever tab the current selection actually lives in, then
  // let the user flip manually. Only bother with a toggle at all if there's
  // something to toggle to.
  const [tab, setTab] = useState<"mine" | "shared">(
    selected && !selected.is_owner ? "shared" : "mine"
  );
  const visible = tab === "mine" ? mine : shared;

  const handleExport = async (format: "pdf" | "markdown") => {
    if (!selected) return;
    setExporting(format);
    try {
      await exportCampaign(selected.id, format);
    } finally {
      setExporting(null);
    }
  };

  const handleCreate = async () => {
    if (!name.trim()) return;
    const result = await createCampaign.mutateAsync({
      name: name.trim(),
      genre,
      description: description.trim() || undefined,
    });
    setName(""); setDescription(""); setHomebrewPrompt(""); setShowHomebrew(false);
    setShowNew(false);
    setTab("mine"); // a newly created campaign is always yours
    onSelect(result.data);
  };

  const handleHomebrew = () => {
    generateConcept.mutate(
      { genre, prompt: homebrewPrompt.trim() || undefined },
      { onSuccess: ({ data }) => { setName(data.name); setDescription(data.description); } }
    );
  };

  const handleKey = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") handleCreate();
    if (e.key === "Escape") setShowNew(false);
  };

  return (
    <div className="flex flex-col gap-3" data-tour="campaign-picker">
      {shared.length > 0 && (
        <div className="flex gap-1 p-0.5 rounded-md bg-muted/60 text-xs">
          <button
            onClick={() => setTab("mine")}
            className={`flex-1 rounded px-2 py-1 font-medium transition-colors ${
              tab === "mine" ? "bg-background text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"
            }`}
          >
            My Campaigns ({mine.length})
          </button>
          <button
            onClick={() => setTab("shared")}
            className={`flex-1 rounded px-2 py-1 font-medium transition-colors ${
              tab === "shared" ? "bg-background text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"
            }`}
          >
            Shared With Me ({shared.length})
          </button>
        </div>
      )}

      <div className="flex flex-col gap-1.5 max-h-72 overflow-y-auto pr-0.5">
        {visible.length === 0 && (
          <p className="text-xs text-muted-foreground px-1 py-2">
            {tab === "shared" ? "No one has shared a campaign with you yet." : "No campaigns yet — create one below."}
          </p>
        )}
        {visible.map((c) => (
          <button
            key={c.id}
            onClick={() => onSelect(c)}
            className={`text-left rounded-md border px-2.5 py-2 transition-colors ${
              selected?.id === c.id
                ? "border-primary/50 bg-primary/5"
                : "border-transparent hover:border-border hover:bg-muted/40"
            }`}
          >
            <div className="flex items-center justify-between gap-2">
              <span className="text-sm font-medium text-foreground truncate">{c.name}</span>
              <span className="shrink-0 text-[10px] uppercase tracking-wide text-muted-foreground">{c.genre}</span>
            </div>
            {!c.is_owner && c.owner_display_name && (
              <p className="text-[11px] text-primary/80 mt-0.5">Shared by {c.owner_display_name}</p>
            )}
            <p className="text-xs text-muted-foreground mt-0.5 line-clamp-1 italic">
              {c.description || "No description"}
            </p>
          </button>
        ))}
      </div>

      <button
        onClick={() => setShowNew((v) => !v)}
        className="text-sm px-3 py-2 rounded-md border border-input text-muted-foreground hover:text-foreground hover:bg-muted/60 transition-colors"
      >
        + New Campaign
      </button>

      {selected && (
        <div className="flex items-center gap-2 text-xs">
          <span className="text-muted-foreground">Export this campaign:</span>
          <button
            onClick={() => handleExport("pdf")}
            disabled={exporting !== null}
            className="px-2.5 py-1 rounded-md border border-input text-muted-foreground hover:text-foreground hover:bg-muted/60 transition-colors disabled:opacity-50"
          >
            {exporting === "pdf" ? "Exporting…" : "PDF"}
          </button>
          <button
            onClick={() => handleExport("markdown")}
            disabled={exporting !== null}
            className="px-2.5 py-1 rounded-md border border-input text-muted-foreground hover:text-foreground hover:bg-muted/60 transition-colors disabled:opacity-50"
          >
            {exporting === "markdown" ? "Exporting…" : "Markdown"}
          </button>
        </div>
      )}

      {showNew && (
        <div className="flex flex-col gap-2 p-4 rounded-lg border border-border bg-card">
          <select
            value={genre}
            onChange={(e) => setGenre(e.target.value as Genre)}
            className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-ring"
          >
            {GENRES.map((g) => (
              <option key={g.value} value={g.value}>{g.label}</option>
            ))}
          </select>

          {/* Homebrew AI helper — drafts a name + premise the user can edit or discard */}
          <div className="rounded-md border border-dashed border-border p-2.5 flex flex-col gap-2">
            {!showHomebrew ? (
              <button
                type="button"
                onClick={() => setShowHomebrew(true)}
                className="self-start flex items-center gap-1.5 text-xs text-primary hover:underline underline-offset-2"
              >
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M12 2a10 10 0 1 0 10 10" /><path d="M22 2 12 12" />
                </svg>
                Homebrew this campaign with AI
              </button>
            ) : (
              <>
                <label className="text-xs font-medium text-muted-foreground">
                  Optional idea or theme — leave blank to be surprised
                </label>
                <div className="flex gap-2">
                  <input
                    type="text"
                    placeholder="e.g. a city built on the back of a sleeping titan"
                    value={homebrewPrompt}
                    onChange={(e) => setHomebrewPrompt(e.target.value)}
                    className="flex-1 rounded-md border border-input bg-background px-3 py-2 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring"
                  />
                  <button
                    type="button"
                    onClick={handleHomebrew}
                    disabled={generateConcept.isPending}
                    className="shrink-0 rounded-md border border-input px-3 py-2 text-xs font-medium text-foreground hover:bg-accent/60 disabled:opacity-50 transition-colors"
                  >
                    {generateConcept.isPending ? "Brewing…" : "Generate"}
                  </button>
                </div>
                {generateConcept.isError && (
                  <p className="text-xs text-destructive">Couldn't generate a concept. Try again.</p>
                )}
                <p className="text-[10px] text-muted-foreground">Fills in the fields below — edit freely before creating.</p>
              </>
            )}
          </div>

          <input
            type="text"
            placeholder="Campaign name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            onKeyDown={handleKey}
            autoFocus
            className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring"
          />
          <textarea
            placeholder="Description (optional) — premise, setting, tone…"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            rows={4}
            className="w-full resize-y rounded-md border border-input bg-background px-3 py-2 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring"
          />
          <div className="flex gap-2 pt-1">
            <button
              onClick={handleCreate}
              disabled={!name.trim() || createCampaign.isPending}
              className="flex-1 rounded-md bg-primary px-3 py-2 text-sm font-semibold text-primary-foreground disabled:opacity-50 hover:opacity-90 transition-opacity"
            >
              {createCampaign.isPending ? "Creating…" : "Create"}
            </button>
            <button
              onClick={() => setShowNew(false)}
              className="px-3 py-2 text-sm rounded-md border border-input text-muted-foreground hover:text-foreground transition-colors"
            >
              Cancel
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
