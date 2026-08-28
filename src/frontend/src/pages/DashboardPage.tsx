import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { JournalInput } from "../components/JournalInput";
import { JournalList } from "../components/JournalList";
import { CampaignSelector } from "../components/CampaignSelector";
import { TagFilter } from "../components/TagFilter";
import { useCampaigns } from "../hooks/useCampaigns";
import { useRecap } from "../hooks/useJournals";
import type { Campaign } from "../types";

function RecapPanel({ campaign }: { campaign: Campaign }) {
  const [recap, setRecap] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const [copied, setCopied] = useState(false);
  const recapMutation = useRecap();

  const handleGenerate = () => {
    recapMutation.mutate(campaign.id, {
      onSuccess: ({ data }) => {
        setRecap(data.recap);
        setOpen(true);
      },
    });
  };

  const handleCopy = () => {
    if (!recap) return;
    navigator.clipboard.writeText(recap).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  };

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <button
          onClick={handleGenerate}
          disabled={recapMutation.isPending}
          className="flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground transition-colors disabled:opacity-50"
        >
          {recapMutation.isPending ? (
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="animate-spin">
              <path d="M21 12a9 9 0 11-6.219-8.56" />
            </svg>
          ) : (
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
              <polyline points="14 2 14 8 20 8" />
              <line x1="16" y1="13" x2="8" y2="13" />
              <line x1="16" y1="17" x2="8" y2="17" />
              <polyline points="10 9 9 9 8 9" />
            </svg>
          )}
          {recapMutation.isPending ? "Generating recap…" : recap ? "Regenerate Recap" : "Generate Session Recap"}
        </button>

        {recap && (
          <button
            onClick={() => setOpen((o) => !o)}
            className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors"
          >
            <svg
              width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
              className={`transition-transform ${open ? "rotate-180" : ""}`}
            >
              <polyline points="6 9 12 15 18 9" />
            </svg>
            {open ? "Hide" : "Show"} recap
          </button>
        )}
      </div>

      {recapMutation.isError && (
        <p className="text-sm text-destructive bg-destructive/10 rounded-md px-3 py-2">
          Could not generate recap. Make sure the AI model is running.
        </p>
      )}

      {recap && open && (
        <div className="rounded-lg border border-border bg-muted/20 p-4 flex flex-col gap-3">
          <div className="flex items-center justify-between">
            <h3 className="text-xs font-semibold uppercase tracking-widest text-muted-foreground" style={{ fontFamily: "var(--font-heading)" }}>
              Session Recap — {campaign.name}
            </h3>
            <button
              onClick={handleCopy}
              className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors"
              title="Copy to clipboard"
            >
              {copied ? (
                <>
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                    <polyline points="20 6 9 17 4 12" />
                  </svg>
                  Copied
                </>
              ) : (
                <>
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <rect x="9" y="9" width="13" height="13" rx="2" ry="2" />
                    <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
                  </svg>
                  Copy
                </>
              )}
            </button>
          </div>
          <p className="text-sm text-foreground leading-relaxed whitespace-pre-wrap">{recap}</p>
        </div>
      )}
    </div>
  );
}

export function DashboardPage() {
  const { data: campaigns } = useCampaigns();
  const [selectedCampaign, setSelectedCampaign] = useState<Campaign | null>(null);
  const [selectedTagId, setSelectedTagId] = useState<string | undefined>();
  const [searchParams, setSearchParams] = useSearchParams();

  // Lets other pages (e.g. Sharing's "Shared With Me" cards) deep-link
  // straight into a specific campaign here rather than just dropping the
  // user on the page and making them find it in the picker themselves.
  useEffect(() => {
    const campaignId = searchParams.get("campaign");
    if (!campaignId || !campaigns || selectedCampaign?.id === campaignId) return;
    const match = campaigns.find((c) => c.id === campaignId);
    if (match) setSelectedCampaign(match);
  }, [searchParams, campaigns, selectedCampaign]);

  const handleSelect = (c: Campaign) => {
    setSelectedCampaign(c);
    setSelectedTagId(undefined);
    if (searchParams.get("campaign")) {
      // Clear it once acted on so it doesn't fight subsequent manual picks
      // (e.g. deep-link into a shared campaign, then switch to another one).
      const next = new URLSearchParams(searchParams);
      next.delete("campaign");
      setSearchParams(next, { replace: true });
    }
  };

  return (
    <div className="max-w-5xl mx-auto px-4 py-6 md:py-10">
      <div className="grid grid-cols-1 md:grid-cols-[280px_1fr] gap-6 items-start">

        {/* Sidebar */}
        <aside className="md:sticky md:top-20 flex flex-col gap-5">
          <div>
            <h2
              className="text-xs font-semibold uppercase tracking-widest text-muted-foreground mb-3"
              style={{ fontFamily: "var(--font-heading)" }}
            >
              Campaign
            </h2>
            <CampaignSelector
              campaigns={campaigns ?? []}
              selected={selectedCampaign}
              onSelect={handleSelect}
            />
          </div>

          {selectedCampaign && (
            <div>
              <h2
                className="text-xs font-semibold uppercase tracking-widest text-muted-foreground mb-3"
                style={{ fontFamily: "var(--font-heading)" }}
              >
                Filter by Tag
              </h2>
              <TagFilter
                campaign_id={selectedCampaign.id}
                selectedTagId={selectedTagId}
                onSelect={setSelectedTagId}
              />
            </div>
          )}
        </aside>

        {/* Main content */}
        <main className="flex flex-col gap-6 min-w-0">
          {!selectedCampaign ? (
            <div className="flex flex-col items-center justify-center py-20 text-center gap-3">
              <span className="text-5xl">⚔️</span>
              <h1
                className="text-2xl font-bold text-foreground"
                style={{ fontFamily: "var(--font-heading)" }}
              >
                {campaigns && campaigns.length > 0 ? "Choose Your Campaign" : "Begin Your First Chronicle"}
              </h1>
              <p className="text-muted-foreground max-w-sm">
                {campaigns && campaigns.length > 0
                  ? "Select an existing campaign from the sidebar, or create a new one to begin recording your adventures."
                  : "Create your first campaign in the sidebar to start turning session notes into journal entries."}
              </p>
            </div>
          ) : (
            <>
              <div>
                <h1
                  className="text-xl font-bold text-foreground mb-4"
                  style={{ fontFamily: "var(--font-heading)" }}
                >
                  {selectedCampaign.name}
                  <span className="ml-2 text-sm font-normal text-muted-foreground capitalize">
                    · {selectedCampaign.genre}
                  </span>
                </h1>
                <h2 className="text-xs font-semibold uppercase tracking-widest text-muted-foreground mb-3" style={{ fontFamily: "var(--font-heading)" }}>
                  New Entry
                </h2>
                <JournalInput campaign={selectedCampaign} />
              </div>

              <div className="border-t border-border pt-4">
                <RecapPanel campaign={selectedCampaign} />
              </div>

              <div className="border-t border-border pt-4">
                <h2 className="text-xs font-semibold uppercase tracking-widest text-muted-foreground mb-3" style={{ fontFamily: "var(--font-heading)" }}>
                  Journal History
                </h2>
                <JournalList campaign_id={selectedCampaign.id} tag_id={selectedTagId} />
              </div>
            </>
          )}
        </main>
      </div>
    </div>
  );
}
