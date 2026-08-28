import { useState } from "react";
import { Link } from "react-router-dom";
import { useCampaigns, useLeaveCampaign } from "../hooks/useCampaigns";
import {
  useShareTokens, useCreateShareToken, useRevokeShareToken,
  useCampaignMembers, useRemoveCampaignMember,
} from "../hooks/useSharing";
import { PageHeader } from "../components/PageHeader";
import type { Campaign, ShareKind, ShareToken } from "../types";

function shareUrl(kind: ShareKind, token: string): string {
  const base = window.location.origin;
  return kind === "read_only" ? `${base}/shared/${token}` : `${base}/join/${token}`;
}

function TokenRow({ campaignId, tok }: { campaignId: string; tok: ShareToken }) {
  const revoke = useRevokeShareToken(campaignId);
  const [copied, setCopied] = useState(false);

  const handleCopy = () => {
    navigator.clipboard.writeText(shareUrl(tok.kind, tok.token));
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  return (
    <div className="flex items-center justify-between gap-3 rounded-lg border border-border bg-card p-3">
      <div className="min-w-0">
        <p className="text-sm font-mono text-card-foreground truncate">{shareUrl(tok.kind, tok.token)}</p>
        <p className="text-xs text-muted-foreground mt-0.5">
          Created {new Date(tok.created_at).toLocaleDateString()}
        </p>
      </div>
      <div className="flex items-center gap-2 shrink-0">
        <button
          onClick={handleCopy}
          className="text-xs px-2.5 py-1 rounded-md border border-input text-muted-foreground hover:text-foreground hover:bg-muted/60 transition-colors"
        >
          {copied ? "Copied!" : "Copy"}
        </button>
        <button
          onClick={() => revoke.mutate(tok.id)}
          disabled={revoke.isPending}
          className="text-xs px-2.5 py-1 rounded-md border border-destructive/30 text-destructive hover:bg-destructive/10 transition-colors disabled:opacity-50"
        >
          Revoke
        </button>
      </div>
    </div>
  );
}

function ShareKindSection({ campaignId, kind, title, description }: {
  campaignId: string; kind: ShareKind; title: string; description: string;
}) {
  const { data: tokens, isLoading } = useShareTokens(campaignId);
  const create = useCreateShareToken(campaignId);
  const active = (tokens ?? []).filter((t) => t.kind === kind && !t.revoked);

  return (
    <div className="rounded-lg border border-border bg-muted/20 p-4 flex flex-col gap-3">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-foreground" style={{ fontFamily: "var(--font-heading)" }}>
            {title}
          </h3>
          <p className="text-xs text-muted-foreground mt-0.5">{description}</p>
        </div>
        <button
          onClick={() => create.mutate(kind)}
          disabled={create.isPending}
          className="shrink-0 text-xs px-3 py-1.5 rounded-md bg-primary text-primary-foreground font-medium hover:bg-primary/90 disabled:opacity-50"
        >
          {create.isPending ? "Creating…" : "+ New Link"}
        </button>
      </div>
      {isLoading && <p className="text-xs text-muted-foreground">Loading…</p>}
      {!isLoading && active.length === 0 && (
        <p className="text-xs text-muted-foreground">No active links yet.</p>
      )}
      {active.length > 0 && (
        <div className="flex flex-col gap-2">
          {active.map((t) => <TokenRow key={t.id} campaignId={campaignId} tok={t} />)}
        </div>
      )}
    </div>
  );
}

function MembersSection({ campaignId }: { campaignId: string }) {
  const { data: members, isLoading } = useCampaignMembers(campaignId);
  const remove = useRemoveCampaignMember(campaignId);

  return (
    <div className="rounded-lg border border-border bg-card p-4 flex flex-col gap-3">
      <h3 className="text-xs font-semibold uppercase tracking-widest text-muted-foreground" style={{ fontFamily: "var(--font-heading)" }}>
        Collaborators
      </h3>
      {isLoading && <p className="text-xs text-muted-foreground">Loading…</p>}
      {!isLoading && (members ?? []).length === 0 && (
        <p className="text-sm text-muted-foreground">
          No one has joined yet. Share a collaborate link above to invite party members.
        </p>
      )}
      {(members ?? []).map((m) => (
        <div key={m.id} className="flex items-center justify-between gap-3">
          <div>
            <p className="text-sm text-foreground">{m.display_name}</p>
            <p className="text-xs text-muted-foreground">{m.email}</p>
          </div>
          <div className="flex gap-2">
            <button
              onClick={() => remove.mutate({ memberId: m.id })}
              disabled={remove.isPending}
              title="Revoke their access — their existing entries stay in the campaign, visible to everyone"
              className="text-xs px-2.5 py-1 rounded-md border border-destructive/30 text-destructive hover:bg-destructive/10 transition-colors disabled:opacity-50"
            >
              Remove
            </button>
            <button
              onClick={() => {
                if (!confirm(`Remove ${m.display_name} AND permanently delete every entry they wrote in this campaign? This cannot be undone.`)) return;
                remove.mutate({ memberId: m.id, deleteEntries: true });
              }}
              disabled={remove.isPending}
              title="Also permanently deletes everything they wrote in this campaign"
              className="text-xs px-2.5 py-1 rounded-md border border-destructive/30 bg-destructive/10 text-destructive hover:bg-destructive/20 transition-colors disabled:opacity-50"
            >
              Remove + Delete Entries
            </button>
          </div>
        </div>
      ))}
    </div>
  );
}

function CampaignSharing({ campaign }: { campaign: Campaign }) {
  return (
    <div className="flex flex-col gap-4">
      <ShareKindSection
        campaignId={campaign.id}
        kind="read_only"
        title="Read-Only Links"
        description="Anyone with the link can browse the journal, characters, and quests — no account needed."
      />
      <ShareKindSection
        campaignId={campaign.id}
        kind="collaborate"
        title="Collaborate Invites"
        description="Whoever redeems this link (with an account) can write journal entries, characters, and quests into this campaign."
      />
      <MembersSection campaignId={campaign.id} />
    </div>
  );
}

const GENRE_LABEL: Record<string, string> = {
  fantasy: "Fantasy", scifi: "Sci-Fi", horror: "Horror", videogame: "Video Game", other: "Other",
};

function SharedWithMeCard({ campaign }: { campaign: Campaign }) {
  const leave = useLeaveCampaign();
  const [confirming, setConfirming] = useState(false);

  return (
    <div className="rounded-lg border border-border bg-card p-4 flex flex-col gap-2.5">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-sm font-semibold text-card-foreground truncate">{campaign.name}</p>
          <p className="text-xs text-primary/80 mt-0.5">Shared by {campaign.owner_display_name ?? "someone"}</p>
        </div>
        <span className="shrink-0 text-[10px] uppercase tracking-wide text-muted-foreground border border-border rounded-full px-2 py-0.5">
          {GENRE_LABEL[campaign.genre] ?? campaign.genre}
        </span>
      </div>
      <p className="text-xs text-muted-foreground italic line-clamp-2">
        {campaign.description || "No description."}
      </p>
      <div className="flex items-center gap-2 pt-1">
        <Link
          to={`/dashboard?campaign=${campaign.id}`}
          className="text-xs px-2.5 py-1.5 rounded-md bg-primary text-primary-foreground font-medium hover:opacity-90 transition-opacity"
        >
          Open Journal →
        </Link>
        {!confirming ? (
          <button
            onClick={() => setConfirming(true)}
            className="text-xs px-2.5 py-1.5 rounded-md border border-destructive/30 text-destructive hover:bg-destructive/10 transition-colors"
          >
            Leave Campaign
          </button>
        ) : (
          <div className="flex items-center gap-1.5">
            <span className="text-xs text-muted-foreground">Leave for good?</span>
            <button
              onClick={() => leave.mutate(campaign.id)}
              disabled={leave.isPending}
              className="text-xs px-2 py-1 rounded-md bg-destructive text-destructive-foreground font-medium hover:opacity-90 disabled:opacity-50 transition-opacity"
            >
              {leave.isPending ? "Leaving…" : "Confirm"}
            </button>
            <button
              onClick={() => setConfirming(false)}
              className="text-xs px-2 py-1 rounded-md border border-input text-muted-foreground hover:text-foreground transition-colors"
            >
              Cancel
            </button>
          </div>
        )}
      </div>
      {leave.isError && (
        <p className="text-xs text-destructive">Couldn't leave — try again in a moment.</p>
      )}
    </div>
  );
}

export function SharingPage() {
  const { data: campaigns } = useCampaigns();
  const [selected, setSelected] = useState<Campaign | null>(null);
  const ownedCampaigns = (campaigns ?? []).filter((c) => c.is_owner);
  const sharedCampaigns = (campaigns ?? []).filter((c) => !c.is_owner);
  const [tab, setTab] = useState<"mine" | "shared">("mine");

  return (
    <div className="max-w-3xl mx-auto px-4 py-6 md:py-10 flex flex-col gap-6">
      <PageHeader
        title="Sharing & Collaboration"
        description="Share a campaign for others to read, or invite party members to contribute directly."
      />

      <div className="flex gap-1 p-0.5 rounded-md bg-muted/60 text-sm max-w-sm" data-tour="sharing-tabs">
        <button
          onClick={() => setTab("mine")}
          className={`flex-1 rounded px-3 py-1.5 font-medium transition-colors ${
            tab === "mine" ? "bg-background text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"
          }`}
        >
          Share Mine ({ownedCampaigns.length})
        </button>
        <button
          onClick={() => setTab("shared")}
          className={`flex-1 rounded px-3 py-1.5 font-medium transition-colors ${
            tab === "shared" ? "bg-background text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"
          }`}
        >
          Shared With Me ({sharedCampaigns.length})
        </button>
      </div>

      {tab === "mine" && (
        <>
          {ownedCampaigns.length > 0 && (
            <div className="flex gap-1.5 flex-wrap border-b border-border pb-3">
              {ownedCampaigns.map((c) => (
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
              <p className="text-4xl mb-3">🔗</p>
              <p className="text-sm font-medium text-foreground mb-1">Select a campaign you own</p>
              <p className="text-xs">Only campaign owners can manage sharing — joined campaigns won't appear here.</p>
            </div>
          )}

          {selected && <CampaignSharing campaign={selected} />}
        </>
      )}

      {tab === "shared" && (
        <div className="flex flex-col gap-3">
          {sharedCampaigns.length === 0 && (
            <div className="text-center py-16 text-muted-foreground border border-dashed border-border rounded-xl">
              <p className="text-4xl mb-3">📭</p>
              <p className="text-sm font-medium text-foreground mb-1">Nothing shared with you yet</p>
              <p className="text-xs">When someone sends you a Collaborate Invite and you redeem it, the campaign shows up here.</p>
            </div>
          )}
          {sharedCampaigns.map((c) => <SharedWithMeCard key={c.id} campaign={c} />)}
        </div>
      )}
    </div>
  );
}
