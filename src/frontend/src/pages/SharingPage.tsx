import { useEffect, useId, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { Users } from "lucide-react";
import { useCampaigns, useLeaveCampaign } from "../hooks/useCampaigns";
import { usePageCampaign } from "../hooks/useCurrentCampaign";
import {
  useShareTokens, useCreateShareToken, useRevokeShareToken,
  useCampaignMembers, useChangeMemberRole, useRemoveCampaignMember,
} from "../hooks/useSharing";
import { PageHeader } from "../components/PageHeader";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { InlineError } from "@/components/ui/inline-error";
import { Input } from "@/components/ui/input";
import { RoleBadge, type CampaignRole } from "@/components/ui/role-badge";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { Skeleton } from "@/components/ui/skeleton";
import { pushLayer } from "@/lib/layers";
import {
  archiveNotice, archivesChats, expiryDateToIso, isLiveLink, isOwnerRow, todayDateValue, type GrantRole,
} from "@/lib/members";
import type { Campaign, CampaignMember, ShareKind, ShareToken } from "../types";

// Sharing › Members (E0-Access.12): the Owner picks each Member's Role
// (Player / Co-GM) and each collaborate link's Role and expiry. Cosmetic
// only: the server allows these only to the Owner (AD-13).

const ROLE_OPTIONS = [
  { value: "player", label: "Player" },
  { value: "co_gm", label: "Co-GM" },
] as const satisfies readonly { value: GrantRole; label: string }[];

function shareUrl(kind: ShareKind, token: string): string {
  const base = window.location.origin;
  return kind === "read_only" ? `${base}/shared/${token}` : `${base}/join/${token}`;
}

function badgeRole(role: CampaignMember["role"]): CampaignRole {
  return role === "owner" ? "gm" : role;
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString();
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
    <div className="flex flex-col gap-2 rounded-lg border border-border bg-card p-3 sm:flex-row sm:items-center sm:justify-between sm:gap-3">
      <div className="min-w-0">
        <p className="text-sm font-mono text-card-foreground truncate">{shareUrl(tok.kind, tok.token)}</p>
        <p className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
          {tok.role && <RoleBadge role={tok.role} />}
          <span>Created {formatDate(tok.created_at)}</span>
          <span>{tok.expires_at ? `Expires ${formatDate(tok.expires_at)}` : "No expiry"}</span>
        </p>
      </div>
      <div className="flex items-center gap-2 shrink-0">
        <Button type="button" variant="outline" size="sm" className="h-11 md:h-9" onClick={handleCopy}>
          {copied ? "Copied!" : "Copy"}
        </Button>
        <Button
          type="button"
          variant="outline"
          size="sm"
          write
          className="h-11 border-destructive/30 text-danger hover:bg-destructive/10 md:h-9"
          onClick={() => revoke.mutate(tok.id)}
          disabled={revoke.isPending}
        >
          Revoke
        </Button>
      </div>
    </div>
  );
}

function ShareKindSection({ campaignId, kind, title, description }: {
  campaignId: string; kind: ShareKind; title: string; description: string;
}) {
  const { data: tokens, isLoading, isError, error, refetch } = useShareTokens(campaignId);
  const create = useCreateShareToken(campaignId);
  const [role, setRole] = useState<GrantRole>("player");
  const [expiry, setExpiry] = useState("");
  const [expiryError, setExpiryError] = useState<string | null>(null);
  const ids = useId();
  const active = (tokens ?? []).filter((t) => t.kind === kind && isLiveLink(t));

  const handleCreate = () => {
    const expires_at = expiryDateToIso(expiry);
    if (expires_at === undefined || (expiry !== "" && expiry < todayDateValue())) {
      setExpiryError("Pick today or a later date, or leave it empty for no expiry.");
      return;
    }
    setExpiryError(null);
    create.mutate(
      { kind, ...(kind === "collaborate" ? { role } : {}), ...(expires_at ? { expires_at } : {}) },
      { onSuccess: () => setExpiry("") },
    );
  };

  return (
    <section className="rounded-lg border border-border bg-muted/20 p-4 flex flex-col gap-3" aria-labelledby={`${ids}-title`}>
      <div>
        <h3 id={`${ids}-title`} className="text-sm font-semibold text-foreground" style={{ fontFamily: "var(--font-heading)" }}>
          {title}
        </h3>
        <p className="text-xs text-muted-foreground mt-0.5">{description}</p>
      </div>
      <div className="flex flex-wrap items-end gap-3">
        {kind === "collaborate" && (
          <div className="flex flex-col gap-1">
            <span id={`${ids}-role`} className="text-xs font-medium text-muted-foreground">Joins as</span>
            <SegmentedControl<GrantRole>
              aria-labelledby={`${ids}-role`}
              options={ROLE_OPTIONS}
              value={role}
              onValueChange={setRole}
            />
          </div>
        )}
        <div className="flex flex-col gap-1">
          <label htmlFor={`${ids}-expiry`} className="text-xs font-medium text-muted-foreground">
            Expires (optional)
          </label>
          <Input
            id={`${ids}-expiry`}
            type="date"
            min={todayDateValue()}
            value={expiry}
            onChange={(e) => setExpiry(e.target.value)}
            aria-invalid={expiryError ? true : undefined}
            aria-describedby={expiryError ? `${ids}-expiry-error` : undefined}
            className="w-44"
          />
        </div>
        <Button type="button" write onClick={handleCreate} disabled={create.isPending} className="h-11 md:h-10">
          {create.isPending ? "Creating…" : "+ New Link"}
        </Button>
      </div>
      {expiryError && <p id={`${ids}-expiry-error`} role="alert" className="text-xs text-danger">{expiryError}</p>}
      {create.isError && <InlineError error={create.error} fallback="Couldn't create the link." />}
      {isLoading && (
        <div className="flex flex-col gap-2" aria-busy="true">
          <Skeleton className="h-16 w-full" />
        </div>
      )}
      {isError && <InlineError error={error} fallback="Couldn't load the links." onRetry={() => void refetch()} />}
      {!isLoading && !isError && active.length === 0 && (
        <p className="text-xs text-muted-foreground">No active links yet.</p>
      )}
      {active.length > 0 && (
        <div className="flex flex-col gap-2">
          {active.map((t) => <TokenRow key={t.id} campaignId={campaignId} tok={t} />)}
        </div>
      )}
    </section>
  );
}

/** Focus the selected option of the radiogroup inside `root`. */
function focusSelected(root: HTMLElement | null) {
  root?.querySelector<HTMLButtonElement>('[role="radio"][aria-checked="true"]')?.focus();
}

function MemberRowView({ campaignId, member, onRemoved }: {
  campaignId: string; member: CampaignMember; onRemoved: (name: string) => void;
}) {
  const change = useChangeMemberRole(campaignId);
  const remove = useRemoveCampaignMember(campaignId);
  const [pendingRole, setPendingRole] = useState<GrantRole | null>(null);
  const [removing, setRemoving] = useState(false);
  // Where focus returns once the control there is enabled again (after the
  // re-render that clears the pending state).
  const [focusAfter, setFocusAfter] = useState<"picker" | "remove" | null>(null);
  const pickerRef = useRef<HTMLDivElement>(null);
  const confirmRef = useRef<HTMLButtonElement>(null);
  const removeRef = useRef<HTMLButtonElement>(null);
  const removeConfirmRef = useRef<HTMLButtonElement>(null);
  const ids = useId();
  const owner = isOwnerRow(member);
  const memberId = member.member_id;

  const cancelDemotion = () => {
    setPendingRole(null);
    setFocusAfter("picker");
  };
  const cancelRemove = () => {
    setRemoving(false);
    setFocusAfter("remove");
  };

  useEffect(() => {
    if (focusAfter === "picker" && !change.isPending) {
      focusSelected(pickerRef.current);
      setFocusAfter(null);
    } else if (focusAfter === "remove" && !remove.isPending && !removing) {
      removeRef.current?.focus();
      setFocusAfter(null);
    }
  }, [focusAfter, change.isPending, remove.isPending, removing]);

  useEffect(() => {
    if (pendingRole === null) return;
    confirmRef.current?.focus();
    return pushLayer(cancelDemotion);
  }, [pendingRole]);

  useEffect(() => {
    if (!removing) return;
    removeConfirmRef.current?.focus();
    return pushLayer(cancelRemove);
  }, [removing]);

  const removeMember = (deleteEntries: boolean) => {
    if (memberId === null) return;
    remove.mutate({ memberId, deleteEntries }, {
      onSuccess: () => onRemoved(member.display_name),
      onError: () => {
        setRemoving(false);
        setFocusAfter("remove");
      },
    });
  };

  const pick = (role: GrantRole) => {
    if (owner || memberId === null || role === member.role) return;
    if (archivesChats(member.role, role)) {
      setPendingRole(role);
      return;
    }
    change.mutate({ memberId, role });
  };

  const confirmDemotion = () => {
    if (memberId === null || pendingRole === null) return;
    change.mutate({ memberId, role: pendingRole }, {
      onSettled: () => {
        setPendingRole(null);
        setFocusAfter("picker");
      },
    });
  };

  return (
    <li className="flex flex-col gap-2 border-t border-border pt-3 first:border-t-0 first:pt-0">
      <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-2">
        <div className="min-w-0">
          <p className="flex flex-wrap items-center gap-2 text-sm text-foreground">
            <span id={`${ids}-name`} className="min-w-0 break-words">{member.display_name}</span>
            <RoleBadge role={badgeRole(member.role)} label={owner ? "Owner" : undefined} />
          </p>
          <p className="text-xs text-muted-foreground">
            {owner ? "Created the campaign" : "Joined"} {formatDate(member.joined_at)}
          </p>
        </div>
        {!owner && memberId !== null && (
          <div className="flex flex-wrap items-center gap-2">
            <div ref={pickerRef}>
              <SegmentedControl<GrantRole>
                aria-label={`Role for ${member.display_name}`}
                options={ROLE_OPTIONS.map((o) => ({ ...o, disabled: change.isPending }))}
                value={member.role === "owner" ? null : member.role}
                onValueChange={pick}
              />
            </div>
            <Button
              ref={removeRef}
              type="button"
              variant="outline"
              size="sm"
              write
              className="h-11 border-destructive/30 text-danger hover:bg-destructive/10 md:h-9"
              onClick={() => setRemoving(true)}
              disabled={remove.isPending || removing}
            >
              Remove
            </Button>
          </div>
        )}
      </div>

      {pendingRole !== null && (
        <div className="flex flex-col gap-2 rounded-md border border-warning/40 bg-warning/14 p-3">
          <p role="alert" className="text-sm text-foreground">{archiveNotice(member.display_name)}</p>
          <div className="flex flex-wrap gap-2">
            <Button ref={confirmRef} type="button" size="sm" write className="h-11 md:h-9"
              onClick={confirmDemotion} disabled={change.isPending}>
              {change.isPending ? "Saving…" : "Make Player"}
            </Button>
            <Button type="button" variant="outline" size="sm" className="h-11 md:h-9" onClick={cancelDemotion}>
              Cancel
            </Button>
          </div>
        </div>
      )}

      {removing && memberId !== null && (
        <div className="flex flex-col gap-2 rounded-md border border-destructive/30 bg-destructive/10 p-3">
          <p role="alert" className="text-sm text-foreground">
            Remove {member.display_name}? Their journal entries stay in the campaign. “Remove and delete
            their entries” permanently deletes every entry they wrote in this campaign and cannot be undone.
          </p>
          <div className="flex flex-wrap gap-2">
            <Button ref={removeConfirmRef} type="button" variant="destructive" size="sm" write className="h-11 md:h-9"
              onClick={() => removeMember(false)}
              disabled={remove.isPending}>
              Remove
            </Button>
            <Button type="button" variant="outline" size="sm" write
              className="h-11 border-destructive/30 text-danger hover:bg-destructive/10 md:h-9"
              onClick={() => removeMember(true)}
              disabled={remove.isPending}>
              Remove and delete their entries
            </Button>
            <Button type="button" variant="outline" size="sm" className="h-11 md:h-9" onClick={cancelRemove}>
              Cancel
            </Button>
          </div>
        </div>
      )}

      {change.isError && <InlineError error={change.error} fallback="Couldn't change the Role." />}
      {remove.isError && <InlineError error={remove.error} fallback="Couldn't remove them." />}
    </li>
  );
}

function MembersSection({ campaignId }: { campaignId: string }) {
  const { data: members, isLoading, isError, error, refetch } = useCampaignMembers(campaignId);
  const rows = members ?? [];
  const onlyOwner = rows.every(isOwnerRow);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const [status, setStatus] = useState("");
  // The removed row unmounts: focus the section heading and announce it.
  const onRemoved = (name: string) => {
    setStatus(`Removed ${name}.`);
    headingRef.current?.focus();
  };

  return (
    <section className="rounded-lg border border-border bg-card p-4 flex flex-col gap-3" aria-labelledby="sharing-members">
      <h3 id="sharing-members" ref={headingRef} tabIndex={-1} className="text-xs font-semibold uppercase tracking-widest text-muted-foreground" style={{ fontFamily: "var(--font-heading)" }}>
        Members
      </h3>
      <p role="status" aria-live="polite" className="sr-only">{status}</p>
      {isLoading && (
        <div className="flex flex-col gap-3" aria-busy="true">
          <Skeleton className="h-10 w-full" />
          <Skeleton className="h-10 w-full" />
        </div>
      )}
      {isError && <InlineError error={error} fallback="Couldn't load the members." onRetry={() => void refetch()} />}
      {!isLoading && !isError && rows.length > 0 && (
        <ul className="flex flex-col gap-3">
          {rows.map((m) => <MemberRowView key={m.member_id ?? `owner-${m.user_id}`} campaignId={campaignId} member={m}
            onRemoved={onRemoved} />)}
        </ul>
      )}
      {!isLoading && !isError && onlyOwner && (
        <EmptyState icon={Users} className="py-8">
          No one has joined yet. Share a collaborate link above to invite party members.
        </EmptyState>
      )}
    </section>
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
        description="Whoever redeems this link (with an account) joins with the Role you pick. You can change it later."
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
            className="text-xs px-2.5 py-1.5 rounded-md border border-destructive/30 text-danger hover:bg-destructive/10 transition-colors"
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
        <p className="text-xs text-danger">Couldn't leave — try again in a moment.</p>
      )}
    </div>
  );
}

export function SharingPage() {
  const { data: campaigns } = useCampaigns();
  const [selected, setSelected] = usePageCampaign((c) => c.is_owner);
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

          {selected && <CampaignSharing key={selected.id} campaign={selected} />}
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
