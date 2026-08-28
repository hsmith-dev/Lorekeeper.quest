import { useEffect, useState } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import * as api from "../services/api";
import { JournalCard } from "../components/JournalCard";
import type { PublicCampaign, JournalListResponse, NpcEntry, Quest } from "../types";

const TABS = ["Journal", "Characters", "Quests"] as const;
type Tab = (typeof TABS)[number];

function JournalTab({ token }: { token: string }) {
  const [page, setPage] = useState(1);
  const { data, isLoading } = useQuery<JournalListResponse>({
    queryKey: ["sharedJournals", token, page],
    queryFn: async () => (await api.getSharedJournals(token, page)).data,
  });

  if (isLoading) return <p className="text-sm text-muted-foreground">Loading…</p>;
  if (!data || data.items.length === 0) {
    return <p className="text-sm text-muted-foreground py-8 text-center">No journal entries yet.</p>;
  }

  return (
    <div className="flex flex-col gap-3">
      {data.items.map((entry) => <JournalCard key={entry.id} entry={entry} preview />)}
      {data.total > data.limit && (
        <div className="flex gap-3 justify-center items-center pt-2">
          <button disabled={page === 1} onClick={() => setPage((p) => p - 1)}
            className="text-sm px-4 py-1.5 rounded-md border border-border disabled:opacity-40 hover:bg-muted/60 transition-colors">
            ← Prev
          </button>
          <span className="text-sm text-muted-foreground">{page} / {Math.ceil(data.total / data.limit)}</span>
          <button disabled={page * data.limit >= data.total} onClick={() => setPage((p) => p + 1)}
            className="text-sm px-4 py-1.5 rounded-md border border-border disabled:opacity-40 hover:bg-muted/60 transition-colors">
            Next →
          </button>
        </div>
      )}
    </div>
  );
}

function NpcsTab({ token }: { token: string }) {
  const { data, isLoading } = useQuery<NpcEntry[]>({
    queryKey: ["sharedNpcs", token],
    queryFn: async () => (await api.getSharedNpcs(token)).data,
  });
  if (isLoading) return <p className="text-sm text-muted-foreground">Loading…</p>;
  if (!data || data.length === 0) return <p className="text-sm text-muted-foreground py-8 text-center">No characters recorded yet.</p>;
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
      {data.map((npc) => (
        <div key={npc.id} className="rounded-lg border border-border bg-card p-4">
          <p className="font-medium text-card-foreground">{npc.name}</p>
          <p className="text-xs text-muted-foreground capitalize">{npc.role} · {npc.status}</p>
          {npc.description && <p className="text-sm text-muted-foreground mt-2 leading-relaxed">{npc.description}</p>}
        </div>
      ))}
    </div>
  );
}

function QuestsTab({ token }: { token: string }) {
  const { data, isLoading } = useQuery<Quest[]>({
    queryKey: ["sharedQuests", token],
    queryFn: async () => (await api.getSharedQuests(token)).data,
  });
  if (isLoading) return <p className="text-sm text-muted-foreground">Loading…</p>;
  if (!data || data.length === 0) return <p className="text-sm text-muted-foreground py-8 text-center">No quests recorded yet.</p>;
  return (
    <div className="flex flex-col gap-3">
      {data.map((q) => (
        <div key={q.id} className="rounded-lg border border-border bg-card p-4">
          <div className="flex items-center justify-between gap-2">
            <p className="font-medium text-card-foreground">{q.title}</p>
            <span className="text-xs px-2 py-0.5 rounded-full border border-border text-muted-foreground capitalize">{q.status}</span>
          </div>
          {q.description && <p className="text-sm text-muted-foreground mt-2 leading-relaxed">{q.description}</p>}
        </div>
      ))}
    </div>
  );
}

export function SharedCampaignPage() {
  const { token } = useParams<{ token: string }>();
  const navigate = useNavigate();
  const [tab, setTab] = useState<Tab>("Journal");

  const { data: campaign, isLoading, isError } = useQuery<PublicCampaign>({
    queryKey: ["sharedCampaign", token],
    queryFn: async () => (await api.getSharedCampaign(token!)).data,
    enabled: !!token,
    retry: false,
  });

  useEffect(() => {
    if (campaign?.share_kind === "collaborate") {
      navigate(`/join/${token}`, { replace: true });
    }
  }, [campaign, token, navigate]);

  if (campaign?.share_kind === "collaborate") return null;

  return (
    <div className="min-h-screen bg-background">
      <div className="max-w-3xl mx-auto px-4 py-8 flex flex-col gap-6">
        <div>
          <p className="text-xs text-muted-foreground uppercase tracking-widest mb-2">Shared Campaign (read-only)</p>
          {isLoading && <div className="h-10 w-64 bg-muted rounded animate-pulse" />}
          {isError && <p className="text-sm text-destructive">This link is invalid or has been revoked.</p>}
          {campaign && (
            <>
              <h1 className="text-2xl font-bold text-foreground" style={{ fontFamily: "var(--font-heading)" }}>
                {campaign.name}
              </h1>
              <p className="text-sm text-muted-foreground mt-1 capitalize">{campaign.genre} campaign</p>
              {campaign.description && <p className="text-sm text-muted-foreground mt-2">{campaign.description}</p>}
            </>
          )}
        </div>

        {campaign && (
          <>
            <div className="flex gap-1.5 border-b border-border pb-3">
              {TABS.map((t) => (
                <button key={t} onClick={() => setTab(t)}
                  className={`px-3 py-1.5 rounded-md text-sm transition-colors ${
                    tab === t ? "bg-muted text-foreground font-medium" : "text-muted-foreground hover:text-foreground hover:bg-muted/60"
                  }`}>
                  {t}
                </button>
              ))}
            </div>
            {tab === "Journal" && <JournalTab token={token!} />}
            {tab === "Characters" && <NpcsTab token={token!} />}
            {tab === "Quests" && <QuestsTab token={token!} />}
          </>
        )}
      </div>
    </div>
  );
}
