import { useRef, useState } from "react";
import { useCampaigns } from "../hooks/useCampaigns";
import { useSources, useUploadSource, useDeleteSource } from "../hooks/useSources";
import { PageHeader } from "../components/PageHeader";
import type { Campaign, SourceDocument } from "../types";

function SourceRow({ doc, onDelete }: { doc: SourceDocument; onDelete: () => void }) {
  return (
    <div className="rounded-lg border border-border bg-card p-4 flex items-center justify-between gap-3">
      <div className="min-w-0">
        <p className="font-medium text-card-foreground truncate">{doc.title}</p>
        <p className="text-xs text-muted-foreground mt-0.5">
          {doc.filename} · {doc.chunk_count} chunk{doc.chunk_count === 1 ? "" : "s"}
        </p>
      </div>
      <button
        onClick={onDelete}
        className="p-1.5 rounded text-muted-foreground hover:text-destructive transition-colors shrink-0"
        title="Remove source document"
      >
        <svg width="14" height="14" viewBox="0 0 20 20" fill="currentColor">
          <path fillRule="evenodd" clipRule="evenodd" d="M9 2a1 1 0 00-.894.553L7.382 4H4a1 1 0 000 2v10a2 2 0 002 2h8a2 2 0 002-2V6a1 1 0 100-2h-3.382l-.724-1.447A1 1 0 0011 2H9zM7 8a1 1 0 012 0v6a1 1 0 11-2 0V8zm4 0a1 1 0 012 0v6a1 1 0 11-2 0V8z" />
        </svg>
      </button>
    </div>
  );
}

function CampaignSources({ campaign }: { campaign: Campaign }) {
  const { data: sources, isLoading } = useSources(campaign.id);
  const upload = useUploadSource(campaign.id);
  const del = useDeleteSource(campaign.id);
  const [title, setTitle] = useState("");
  const [error, setError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setError(null);
    upload.mutate(
      { file, title: title.trim() || undefined },
      {
        onSuccess: () => { setTitle(""); if (fileInputRef.current) fileInputRef.current.value = ""; },
        onError: (err: any) => setError(err?.response?.data?.detail || "Upload failed."),
      }
    );
  };

  return (
    <div className="flex flex-col gap-6">
      <div className="rounded-lg border border-border bg-muted/20 p-4 flex flex-col gap-3">
        <h3 className="text-xs font-semibold uppercase tracking-widest text-muted-foreground" style={{ fontFamily: "var(--font-heading)" }}>
          Upload Canon Source
        </h3>
        <p className="text-xs text-muted-foreground">
          Upload DM notes, a campaign bible, or published adventure text (.txt, .md, .pdf). The AI will
          ground narrative generation and chat answers in this material instead of inventing details.
        </p>
        <div className="flex flex-col sm:flex-row gap-2">
          <input
            type="text"
            placeholder="Title (optional)"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            className="flex-1 rounded-md border border-border bg-background px-3 py-2 text-sm"
          />
          <input
            ref={fileInputRef}
            type="file"
            accept=".txt,.md,.pdf,text/plain,text/markdown,application/pdf"
            onChange={handleFileChange}
            disabled={upload.isPending}
            className="text-sm text-muted-foreground file:mr-3 file:rounded-md file:border-0 file:bg-primary file:text-primary-foreground file:px-3 file:py-2 file:text-sm file:font-medium file:cursor-pointer disabled:opacity-50"
          />
        </div>
        {upload.isPending && <p className="text-xs text-muted-foreground">Uploading and embedding…</p>}
        {error && <p className="text-xs text-destructive">{error}</p>}
      </div>

      {isLoading && <p className="text-sm text-muted-foreground">Loading sources…</p>}

      {sources && sources.length === 0 && (
        <div className="text-center py-10 text-muted-foreground border border-dashed border-border rounded-xl">
          <p className="text-sm">No source documents yet for this campaign.</p>
        </div>
      )}

      {sources && sources.length > 0 && (
        <div className="flex flex-col gap-2">
          {sources.map((doc) => (
            <SourceRow key={doc.id} doc={doc} onDelete={() => del.mutate(doc.id)} />
          ))}
        </div>
      )}
    </div>
  );
}

export function SourcesPage() {
  const { data: campaigns } = useCampaigns();
  const [selected, setSelected] = useState<Campaign | null>(null);

  return (
    <div className="max-w-5xl mx-auto px-4 py-6 md:py-10 flex flex-col gap-6">
      <PageHeader
        title="Campaign Sources"
        description="Upload canonical reference material to ground the AI's narratives and chat answers in your campaign's actual history."
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
          <p className="text-4xl mb-3">📜</p>
          <p className="text-sm font-medium text-foreground mb-1">Select a campaign</p>
          <p className="text-xs">Choose a campaign above to manage its source documents.</p>
        </div>
      )}

      {selected && <CampaignSources campaign={selected} />}
    </div>
  );
}
