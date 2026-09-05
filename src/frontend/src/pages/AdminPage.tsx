import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { getMe, getSupportBundle } from "../services/api";
import { PageHeader } from "../components/PageHeader";
import { useFeedbackList, useFeedbackContext } from "../hooks/useFeedback";
import {
  useAdminModels,
  useAdminLogs,
  useAdminUsers,
  useSuspendUser,
  useUnsuspendUser,
  useMessageUser,
  useDeleteUser,
  useSetUserAccess,
  usePromoteUser,
  useDemoteUser,
  useAdminPromoCodes,
  useCreatePromoCode,
  useUpdatePromoCode,
  useDeletePromoCode,
  useAdminConfig,
  useUpdateAdminConfig,
} from "../hooks/useAdmin";
import type { FeedbackAdmin, FeedbackCategory, AdminUser, PromoCodeAdmin } from "../types";

function formatDate(iso: string) {
  return new Date(iso).toLocaleString(undefined, { month: "short", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit" });
}
function formatDateOnly(iso: string) {
  return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

const TABS = [
  { key: "users", label: "Users" },
  { key: "promo-codes", label: "Promo Codes" },
  { key: "feedback", label: "Feedback" },
  { key: "platform", label: "Platform" },
  { key: "system", label: "System" },
] as const;
type TabKey = (typeof TABS)[number]["key"];

// ── Feedback tab ─────────────────────────────────────────────────────────────

const CATEGORY_LABELS: Record<FeedbackCategory, string> = {
  bug: "Bug",
  model_quality: "AI quality",
  feature_request: "Feature request",
  other: "Other",
};

function FeedbackContextPanel({ feedbackId }: { feedbackId: string }) {
  const { data, isLoading, isError } = useFeedbackContext(feedbackId);
  if (isLoading) return <p className="text-xs text-muted-foreground px-4 pb-4">Loading campaign context…</p>;
  if (isError || !data) return <p className="text-xs text-destructive px-4 pb-4">Couldn't load campaign context.</p>;
  return (
    <div className="px-4 pb-4 flex flex-col gap-3 border-t border-border pt-3 text-sm">
      <div>
        <p className="font-semibold text-card-foreground">
          {data.campaign_name} <span className="text-xs text-muted-foreground font-normal">({data.campaign_genre})</span>
        </p>
        {data.campaign_description && <p className="text-xs text-muted-foreground mt-1">{data.campaign_description}</p>}
      </div>
      {data.recent_journal_narratives.length > 0 && (
        <div>
          <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide mb-1">
            Recent journal entries ({data.recent_journal_narratives.length})
          </p>
          <div className="flex flex-col gap-2 max-h-64 overflow-y-auto">
            {data.recent_journal_narratives.map((n, i) => (
              <p key={i} className="text-xs text-foreground bg-muted/40 rounded-md p-2 line-clamp-4">{n}</p>
            ))}
          </div>
        </div>
      )}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        {data.npc_names.length > 0 && (
          <div><p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide mb-1">NPCs</p><p className="text-xs text-foreground">{data.npc_names.join(", ")}</p></div>
        )}
        {data.quest_titles.length > 0 && (
          <div><p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide mb-1">Quests</p><p className="text-xs text-foreground">{data.quest_titles.join(", ")}</p></div>
        )}
        {data.source_document_titles.length > 0 && (
          <div><p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide mb-1">Source docs</p><p className="text-xs text-foreground">{data.source_document_titles.join(", ")}</p></div>
        )}
      </div>
    </div>
  );
}

function FeedbackRow({ item }: { item: FeedbackAdmin }) {
  const [expanded, setExpanded] = useState(false);
  return (
    <div className="rounded-lg border border-border bg-card overflow-hidden">
      <button onClick={() => setExpanded((v) => !v)} className="w-full flex items-start justify-between gap-3 px-4 py-3 text-left hover:bg-muted/40 transition-colors">
        <div className="min-w-0 flex flex-col gap-1">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-xs font-semibold px-2 py-0.5 rounded-full bg-primary/15 text-primary">{CATEGORY_LABELS[item.category]}</span>
            <span className="text-xs text-muted-foreground">{formatDate(item.created_at)}</span>
            <span className="text-xs text-muted-foreground">·</span>
            <span className="text-xs text-muted-foreground">{item.user_display_name} ({item.user_email})</span>
            {item.campaign_name && (<><span className="text-xs text-muted-foreground">·</span><span className="text-xs text-muted-foreground">📖 {item.campaign_name}</span></>)}
          </div>
          <p className={`text-sm text-card-foreground ${expanded ? "" : "truncate"}`}>{item.message}</p>
        </div>
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={`shrink-0 mt-0.5 transition-transform ${expanded ? "rotate-180" : ""}`}>
          <polyline points="6 9 12 15 18 9" />
        </svg>
      </button>
      {expanded && item.campaign_id && <FeedbackContextPanel feedbackId={item.id} />}
    </div>
  );
}

function FeedbackTab() {
  const { data, isLoading, isError } = useFeedbackList();
  return (
    <div className="flex flex-col gap-4">
      <p className="text-sm text-muted-foreground">
        Everything submitted through Feedback. Expand an item linked to a campaign to pull that
        campaign's recent entries, NPCs, quests, and sources for research.
      </p>
      {isLoading && <p className="text-sm text-muted-foreground">Loading…</p>}
      {isError && <p className="text-sm text-destructive">Couldn't load feedback.</p>}
      {data && data.length === 0 && (
        <div className="text-center py-16 text-muted-foreground border border-dashed border-border rounded-xl">
          <p className="text-4xl mb-3">📭</p>
          <p className="text-sm font-medium text-foreground mb-1">No feedback yet</p>
        </div>
      )}
      {data && data.length > 0 && (
        <div className="flex flex-col gap-2">
          {data.map((item) => <FeedbackRow key={item.id} item={item} />)}
        </div>
      )}
    </div>
  );
}

// ── Users tab ────────────────────────────────────────────────────────────────

const PLAN_LABELS: Record<string, string> = { byok: "Bring Your Own Key ($5/mo)", hosted: "Hosted Model ($15/mo)" };

function MessageForm({ userId, onDone }: { userId: string; onDone: () => void }) {
  const [subject, setSubject] = useState("");
  const [message, setMessage] = useState("");
  const send = useMessageUser();
  return (
    <div className="flex flex-col gap-2 bg-muted/40 rounded-md p-3">
      <input
        value={subject} onChange={(e) => setSubject(e.target.value)} placeholder="Subject"
        className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
      />
      <textarea
        value={message} onChange={(e) => setMessage(e.target.value)} placeholder="Message" rows={3}
        className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm resize-y focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
      />
      {send.isError && <p className="text-xs text-destructive">Couldn't send. Try again.</p>}
      {send.isSuccess ? (
        <p className="text-xs text-primary">Sent.</p>
      ) : (
        <div className="flex gap-2">
          <button
            onClick={() => send.mutate({ id: userId, subject, message }, { onSuccess: onDone })}
            disabled={send.isPending || !subject.trim() || !message.trim()}
            className="rounded-md bg-primary px-3 py-1.5 text-xs font-semibold text-primary-foreground hover:opacity-90 disabled:opacity-50"
          >
            {send.isPending ? "Sending…" : "Send"}
          </button>
          <button onClick={onDone} className="rounded-md border border-input px-3 py-1.5 text-xs text-muted-foreground hover:text-foreground">Cancel</button>
        </div>
      )}
    </div>
  );
}

function AccessControl({ user, onDone }: { user: AdminUser; onDone: () => void }) {
  const [accessGranted, setAccessGranted] = useState(user.access_granted);
  const [plan, setPlan] = useState<"" | "byok" | "hosted">(user.subscription_plan ?? "");
  const setAccess = useSetUserAccess();
  return (
    <div className="flex flex-col gap-2 bg-muted/40 rounded-md p-3">
      <label className="flex items-center gap-2 text-xs text-foreground">
        <input type="checkbox" checked={accessGranted} onChange={(e) => setAccessGranted(e.target.checked)} />
        Access granted
      </label>
      <select
        value={plan} onChange={(e) => setPlan(e.target.value as "" | "byok" | "hosted")}
        className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
      >
        <option value="">No tier / leave as-is</option>
        <option value="byok">Bring Your Own Key ($5/mo tier — no hosted model)</option>
        <option value="hosted">Hosted Model ($15/mo tier — includes hosted model)</option>
      </select>
      <div className="flex gap-2">
        <button
          onClick={() => setAccess.mutate({ id: user.id, access_granted: accessGranted, plan: plan || null }, { onSuccess: onDone })}
          disabled={setAccess.isPending}
          className="rounded-md bg-primary px-3 py-1.5 text-xs font-semibold text-primary-foreground hover:opacity-90 disabled:opacity-50"
        >
          {setAccess.isPending ? "Saving…" : "Apply"}
        </button>
        <button onClick={onDone} className="rounded-md border border-input px-3 py-1.5 text-xs text-muted-foreground hover:text-foreground">Cancel</button>
      </div>
    </div>
  );
}

function UserRow({ user }: { user: AdminUser }) {
  const [expanded, setExpanded] = useState(false);
  const [messaging, setMessaging] = useState(false);
  const [suspending, setSuspending] = useState(false);
  const [settingAccess, setSettingAccess] = useState(false);
  const [reason, setReason] = useState("");
  const suspend = useSuspendUser();
  const unsuspend = useUnsuspendUser();
  const del = useDeleteUser();
  const promote = usePromoteUser();
  const demote = useDemoteUser();

  const handleDelete = () => {
    if (!confirm(`Permanently delete ${user.email}? This deletes all their campaigns, journals, and data. This cannot be undone.`)) return;
    del.mutate(user.id);
  };

  return (
    <div className={`rounded-lg border overflow-hidden ${user.is_suspended ? "border-destructive/40 bg-destructive/5" : "border-border bg-card"}`}>
      <button onClick={() => setExpanded((v) => !v)} className="w-full flex items-start justify-between gap-3 px-4 py-3 text-left hover:bg-muted/40 transition-colors">
        <div className="min-w-0 flex flex-col gap-1">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-sm font-medium text-card-foreground truncate">{user.display_name}</span>
            <span className="text-xs text-muted-foreground truncate">{user.email}</span>
            {user.is_admin && <span className="text-xs font-semibold px-2 py-0.5 rounded-full bg-accent/20 text-accent-foreground">Admin</span>}
            {user.is_suspended && <span className="text-xs font-semibold px-2 py-0.5 rounded-full bg-destructive/15 text-destructive">Suspended</span>}
            {user.access_granted && !user.is_suspended && <span className="text-xs font-semibold px-2 py-0.5 rounded-full bg-primary/15 text-primary">{user.subscription_plan ? PLAN_LABELS[user.subscription_plan] : (user.access_source ?? "active")}</span>}
            {!user.access_granted && <span className="text-xs text-muted-foreground">gated</span>}
          </div>
          <p className="text-xs text-muted-foreground">Joined {formatDateOnly(user.created_at)} · {user.campaign_count} campaigns · {user.journal_entry_count} journal entries{user.promo_code_used ? ` · promo: ${user.promo_code_used}` : ""}</p>
        </div>
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={`shrink-0 mt-0.5 transition-transform ${expanded ? "rotate-180" : ""}`}>
          <polyline points="6 9 12 15 18 9" />
        </svg>
      </button>

      {expanded && (
        <div className="px-4 pb-4 flex flex-col gap-3 border-t border-border pt-3 text-sm">
          {user.is_suspended && user.suspended_reason && (
            <p className="text-xs text-destructive">Suspended: {user.suspended_reason}</p>
          )}
          {user.subscription_status && (
            <p className="text-xs text-muted-foreground">
              Subscription status: {user.subscription_status}
              {user.tokens_included_per_period ? ` · usage: ${user.tokens_used_current_period ?? 0}/${user.tokens_included_per_period} tokens this period` : ""}
            </p>
          )}

          <div className="flex gap-2 flex-wrap">
            {user.is_suspended ? (
              <button
                onClick={() => unsuspend.mutate(user.id)}
                disabled={unsuspend.isPending}
                className="rounded-md bg-primary px-3 py-1.5 text-xs font-semibold text-primary-foreground hover:opacity-90 disabled:opacity-50"
              >
                {unsuspend.isPending ? "Reactivating…" : "Reactivate"}
              </button>
            ) : (
              <button
                onClick={() => setSuspending((v) => !v)}
                className="rounded-md border border-destructive/40 text-destructive px-3 py-1.5 text-xs font-semibold hover:bg-destructive/10"
              >
                Suspend
              </button>
            )}
            <button onClick={() => setMessaging((v) => !v)} className="rounded-md border border-input px-3 py-1.5 text-xs text-foreground hover:bg-muted/60">
              Message
            </button>
            <button onClick={() => setSettingAccess((v) => !v)} className="rounded-md border border-input px-3 py-1.5 text-xs text-foreground hover:bg-muted/60">
              Set Access
            </button>
            {user.is_admin ? (
              <button
                onClick={() => { if (confirm(`Revoke admin access from ${user.display_name}?`)) demote.mutate(user.id); }}
                disabled={demote.isPending}
                className="rounded-md border border-input px-3 py-1.5 text-xs text-foreground hover:bg-muted/60 disabled:opacity-50"
              >
                Revoke Admin
              </button>
            ) : (
              <button
                onClick={() => { if (confirm(`Grant admin access to ${user.display_name}? They'll be able to manage all users, promo codes, and feedback.`)) promote.mutate(user.id); }}
                disabled={promote.isPending}
                className="rounded-md border border-input px-3 py-1.5 text-xs text-foreground hover:bg-muted/60 disabled:opacity-50"
              >
                Make Admin
              </button>
            )}
            <button onClick={handleDelete} disabled={del.isPending} className="rounded-md border border-destructive/40 text-destructive px-3 py-1.5 text-xs font-semibold hover:bg-destructive/10 disabled:opacity-50">
              {del.isPending ? "Deleting…" : "Delete account"}
            </button>
          </div>

          {settingAccess && <AccessControl user={user} onDone={() => setSettingAccess(false)} />}

          {suspending && (
            <div className="flex flex-col gap-2 bg-muted/40 rounded-md p-3">
              <input
                value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Reason (shown to the user, optional)"
                className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
              />
              <div className="flex gap-2">
                <button
                  onClick={() => suspend.mutate({ id: user.id, reason: reason.trim() || undefined }, { onSuccess: () => setSuspending(false) })}
                  disabled={suspend.isPending}
                  className="rounded-md bg-destructive px-3 py-1.5 text-xs font-semibold text-destructive-foreground hover:opacity-90 disabled:opacity-50"
                >
                  {suspend.isPending ? "Suspending…" : "Confirm Suspend"}
                </button>
                <button onClick={() => setSuspending(false)} className="rounded-md border border-input px-3 py-1.5 text-xs text-muted-foreground hover:text-foreground">Cancel</button>
              </div>
            </div>
          )}

          {messaging && <MessageForm userId={user.id} onDone={() => setMessaging(false)} />}
        </div>
      )}
    </div>
  );
}

function UsersTab() {
  const { data, isLoading, isError } = useAdminUsers();
  return (
    <div className="flex flex-col gap-4">
      <p className="text-sm text-muted-foreground">
        {data ? `${data.length} registered account${data.length === 1 ? "" : "s"}.` : "All registered accounts, their tier, and usage."}
      </p>
      {isLoading && <p className="text-sm text-muted-foreground">Loading…</p>}
      {isError && <p className="text-sm text-destructive">Couldn't load users.</p>}
      {data && (
        <div className="flex flex-col gap-2">
          {data.map((u) => <UserRow key={u.id} user={u} />)}
        </div>
      )}
    </div>
  );
}

// ── Promo codes tab ──────────────────────────────────────────────────────────

function CreatePromoCodeForm() {
  const [code, setCode] = useState("");
  const [grantsPlan, setGrantsPlan] = useState<"byok" | "hosted">("byok");
  const [maxRedemptions, setMaxRedemptions] = useState("");
  const [expiresAt, setExpiresAt] = useState("");
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const create = useCreatePromoCode();

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    create.mutate(
      {
        code: code.trim(),
        grants_plan: grantsPlan,
        max_redemptions: maxRedemptions ? Number(maxRedemptions) : null,
        expires_at: expiresAt ? new Date(expiresAt).toISOString() : null,
        note: note.trim() || null,
      },
      {
        onSuccess: () => { setCode(""); setGrantsPlan("byok"); setMaxRedemptions(""); setExpiresAt(""); setNote(""); },
        onError: (err: unknown) => {
          const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
          setError(detail || "Couldn't create promo code.");
        },
      }
    );
  };

  return (
    <form onSubmit={handleSubmit} className="rounded-lg border border-border bg-card p-4 flex flex-col gap-3">
      <p className="text-sm font-semibold text-card-foreground">Create a promo code</p>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <input value={code} onChange={(e) => setCode(e.target.value)} placeholder="CODE (e.g. BETA2026)" required
          className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring" />
        <select value={grantsPlan} onChange={(e) => setGrantsPlan(e.target.value as "byok" | "hosted")}
          className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring">
          <option value="byok">Grants: Bring Your Own Key (no hosted model)</option>
          <option value="hosted">Grants: Hosted Model (includes hosted model)</option>
        </select>
        <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Note (optional, e.g. 'beta testers')"
          className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring" />
        <input type="number" min={1} value={maxRedemptions} onChange={(e) => setMaxRedemptions(e.target.value)} placeholder="Max redemptions (blank = unlimited)"
          className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring" />
        <input type="date" value={expiresAt} onChange={(e) => setExpiresAt(e.target.value)}
          className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring" />
      </div>
      {error && <p className="text-sm text-destructive bg-destructive/10 rounded-md px-3 py-2">{error}</p>}
      <button type="submit" disabled={create.isPending || !code.trim()} className="self-start rounded-md bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground hover:opacity-90 disabled:opacity-50">
        {create.isPending ? "Creating…" : "Create Code"}
      </button>
    </form>
  );
}

function EditPromoCodeForm({ promo, onDone }: { promo: PromoCodeAdmin; onDone: () => void }) {
  const [maxRedemptions, setMaxRedemptions] = useState(promo.max_redemptions?.toString() ?? "");
  const [expiresAt, setExpiresAt] = useState(promo.expires_at ? promo.expires_at.slice(0, 10) : "");
  const [note, setNote] = useState(promo.note ?? "");
  const [grantsPlan, setGrantsPlan] = useState<"byok" | "hosted">(promo.grants_plan);
  const update = useUpdatePromoCode();

  const handleSave = () => {
    update.mutate(
      {
        id: promo.id,
        data: {
          max_redemptions: maxRedemptions ? Number(maxRedemptions) : null,
          expires_at: expiresAt ? new Date(expiresAt).toISOString() : null,
          note: note.trim() || null,
          grants_plan: grantsPlan,
        },
      },
      { onSuccess: onDone }
    );
  };

  return (
    <div className="flex flex-col gap-2 bg-muted/40 rounded-md p-3">
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
        <input type="number" min={1} value={maxRedemptions} onChange={(e) => setMaxRedemptions(e.target.value)} placeholder="Max redemptions (blank = unlimited)"
          className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring" />
        <input type="date" value={expiresAt} onChange={(e) => setExpiresAt(e.target.value)}
          className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring" />
      </div>
      <select value={grantsPlan} onChange={(e) => setGrantsPlan(e.target.value as "byok" | "hosted")}
        className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring">
        <option value="byok">Grants: Bring Your Own Key (no hosted model)</option>
        <option value="hosted">Grants: Hosted Model (includes hosted model)</option>
      </select>
      <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Note"
        className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring" />
      <div className="flex gap-2">
        <button onClick={handleSave} disabled={update.isPending} className="rounded-md bg-primary px-3 py-1.5 text-xs font-semibold text-primary-foreground hover:opacity-90 disabled:opacity-50">
          {update.isPending ? "Saving…" : "Save"}
        </button>
        <button onClick={onDone} className="rounded-md border border-input px-3 py-1.5 text-xs text-muted-foreground hover:text-foreground">Cancel</button>
      </div>
    </div>
  );
}

function PromoCodeRow({ promo }: { promo: PromoCodeAdmin }) {
  const [expanded, setExpanded] = useState(false);
  const [editing, setEditing] = useState(false);
  const update = useUpdatePromoCode();
  const del = useDeletePromoCode();

  const expired = promo.expires_at ? new Date(promo.expires_at) < new Date() : false;
  const exhausted = promo.max_redemptions !== null && promo.redemption_count >= promo.max_redemptions;

  const handleDelete = () => {
    if (!confirm(`Delete promo code "${promo.code}"? This also deletes its redemption history. Consider disabling it instead if you want to keep the record.`)) return;
    del.mutate(promo.id);
  };

  return (
    <div className={`rounded-lg border overflow-hidden ${!promo.active ? "border-border bg-muted/20" : "border-border bg-card"}`}>
      <button onClick={() => setExpanded((v) => !v)} className="w-full flex items-start justify-between gap-3 px-4 py-3 text-left hover:bg-muted/40 transition-colors">
        <div className="min-w-0 flex flex-col gap-1">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-sm font-mono font-semibold text-card-foreground">{promo.code}</span>
            {!promo.active && <span className="text-xs font-semibold px-2 py-0.5 rounded-full bg-muted text-muted-foreground">Disabled</span>}
            {promo.active && expired && <span className="text-xs font-semibold px-2 py-0.5 rounded-full bg-destructive/15 text-destructive">Expired</span>}
            {promo.active && !expired && exhausted && <span className="text-xs font-semibold px-2 py-0.5 rounded-full bg-destructive/15 text-destructive">Exhausted</span>}
            {promo.active && !expired && !exhausted && <span className="text-xs font-semibold px-2 py-0.5 rounded-full bg-primary/15 text-primary">Active</span>}
            <span className="text-xs font-semibold px-2 py-0.5 rounded-full bg-accent/15 text-accent-foreground">{PLAN_LABELS[promo.grants_plan]}</span>
          </div>
          <p className="text-xs text-muted-foreground">
            {promo.redemption_count}{promo.max_redemptions !== null ? `/${promo.max_redemptions}` : ""} redemptions
            {promo.expires_at ? ` · expires ${formatDateOnly(promo.expires_at)}` : " · never expires"}
            {promo.note ? ` · ${promo.note}` : ""}
          </p>
        </div>
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={`shrink-0 mt-0.5 transition-transform ${expanded ? "rotate-180" : ""}`}>
          <polyline points="6 9 12 15 18 9" />
        </svg>
      </button>

      {expanded && (
        <div className="px-4 pb-4 flex flex-col gap-3 border-t border-border pt-3 text-sm">
          {promo.redemptions.length > 0 ? (
            <div>
              <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide mb-1">Redeemed by</p>
              <div className="flex flex-col gap-1">
                {promo.redemptions.map((r) => (
                  <p key={r.user_id} className="text-xs text-foreground">
                    {r.user_display_name} ({r.user_email}) — {formatDate(r.redeemed_at)}
                  </p>
                ))}
              </div>
            </div>
          ) : (
            <p className="text-xs text-muted-foreground">Not redeemed yet.</p>
          )}

          <div className="flex gap-2 flex-wrap">
            <button
              onClick={() => update.mutate({ id: promo.id, data: { active: !promo.active } })}
              disabled={update.isPending}
              className="rounded-md border border-input px-3 py-1.5 text-xs text-foreground hover:bg-muted/60 disabled:opacity-50"
            >
              {promo.active ? "Disable" : "Enable"}
            </button>
            <button onClick={() => setEditing((v) => !v)} className="rounded-md border border-input px-3 py-1.5 text-xs text-foreground hover:bg-muted/60">
              Edit
            </button>
            <button onClick={handleDelete} disabled={del.isPending} className="rounded-md border border-destructive/40 text-destructive px-3 py-1.5 text-xs font-semibold hover:bg-destructive/10 disabled:opacity-50">
              {del.isPending ? "Deleting…" : "Delete"}
            </button>
          </div>

          {editing && <EditPromoCodeForm promo={promo} onDone={() => setEditing(false)} />}
        </div>
      )}
    </div>
  );
}

function PromoCodesTab() {
  const { data, isLoading, isError } = useAdminPromoCodes();
  return (
    <div className="flex flex-col gap-4">
      <CreatePromoCodeForm />
      {isLoading && <p className="text-sm text-muted-foreground">Loading…</p>}
      {isError && <p className="text-sm text-destructive">Couldn't load promo codes.</p>}
      {data && data.length === 0 && (
        <div className="text-center py-16 text-muted-foreground border border-dashed border-border rounded-xl">
          <p className="text-4xl mb-3">🎟️</p>
          <p className="text-sm font-medium text-foreground mb-1">No promo codes yet</p>
        </div>
      )}
      {data && data.length > 0 && (
        <div className="flex flex-col gap-2">
          {data.map((p) => <PromoCodeRow key={p.id} promo={p} />)}
        </div>
      )}
    </div>
  );
}

// ── Page ─────────────────────────────────────────────────────────────────────

// ── Platform tab ─────────────────────────────────────────────────────────────

function PlatformTab() {
  const { data: config, isLoading } = useAdminConfig();
  const update = useUpdateAdminConfig();

  if (isLoading || !config) return <p className="text-sm text-muted-foreground">Loading platform settings…</p>;

  return (
    <div className="flex flex-col gap-4 max-w-2xl">
      <div className="rounded-lg border border-border bg-card p-5">
        <label className="flex items-start gap-3 cursor-pointer">
          <input
            type="checkbox"
            checked={config.open_access_mode}
            disabled={update.isPending}
            onChange={(e) => update.mutate({ open_access_mode: e.target.checked })}
            className="mt-1 h-4 w-4 accent-primary"
          />
          <span>
            <span className="font-semibold text-card-foreground block">Open access</span>
            <span className="text-sm text-muted-foreground">
              Anyone can sign up and use Lorekeeper — including the self-hosted AI model — with no
              promo code, subscription, or billing. The right mode for self-hosting, provisioning
              accounts for a team or company, or running a free community server. Applies
              immediately, including to existing accounts that were still gated.
            </span>
          </span>
        </label>
        {!config.open_access_mode && (
          <p className="mt-3 text-sm text-muted-foreground border-t border-border pt-3">
            Gated mode is active: new accounts need a promo code (Promo Codes tab) or a paid
            subscription to get access.
          </p>
        )}
      </div>

      <div className="rounded-lg border border-border bg-card p-5 text-sm">
        <p className="font-semibold text-card-foreground mb-1">Stripe billing</p>
        {config.stripe_configured ? (
          <p className="text-muted-foreground">
            <span className="text-green-600 dark:text-green-400">● Configured</span> — subscription
            checkout works whenever open access is off.
          </p>
        ) : (
          <p className="text-muted-foreground">
            <span className="text-amber-600 dark:text-amber-400">● Not configured</span> — with open
            access off, accounts can only get in via promo codes until the Stripe environment
            variables are set (see docs/PAYMENT_PROCESSOR_SETUP.md).
          </p>
        )}
      </div>
    </div>
  );
}

// ── System tab ───────────────────────────────────────────────────────────────

function formatGB(bytes: number) {
  return `${(bytes / 1024 ** 3).toFixed(2)} GB`;
}

type InstallProgress = { variant: "finetuned" | "base"; status: string; pct: number | null; detail: string };

function SystemTab() {
  const qc = useQueryClient();
  const { data: models, isLoading, isError } = useAdminModels();
  const [installing, setInstalling] = useState<InstallProgress | null>(null);
  const [installError, setInstallError] = useState<string | null>(null);
  const [showLogs, setShowLogs] = useState(false);
  const logs = useAdminLogs(showLogs);
  const [bundleBusy, setBundleBusy] = useState(false);

  const install = async (variant: "finetuned" | "base") => {
    setInstallError(null);
    setInstalling({ variant, status: "Starting download…", pct: null, detail: "" });
    try {
      const token = localStorage.getItem("lk_token");
      const resp = await fetch("/api/admin/models/install", {
        method: "POST",
        headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
        body: JSON.stringify({ variant }),
      });
      if (!resp.ok || !resp.body) throw new Error(`install request failed (HTTP ${resp.status})`);
      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let finished = false;
      // eslint-disable-next-line no-constant-condition
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const events = buffer.split("\n\n");
        buffer = events.pop() ?? "";
        for (const raw of events) {
          const dataLine = raw.split("\n").find((l) => l.startsWith("data:"));
          if (!dataLine) continue;
          let ev: { status?: string; total?: number; completed?: number; done?: boolean; error?: string };
          try {
            ev = JSON.parse(dataLine.slice(5));
          } catch {
            continue;
          }
          if (ev.error) throw new Error(ev.error);
          if (ev.done) {
            finished = true;
            continue;
          }
          setInstalling({
            variant,
            status: ev.status ?? "",
            pct: ev.total ? Math.round(((ev.completed ?? 0) / ev.total) * 100) : null,
            detail: ev.total ? `${formatGB(ev.completed ?? 0)} of ${formatGB(ev.total)}` : "",
          });
        }
      }
      if (!finished) throw new Error("The install stream ended before completing — check the logs below.");
    } catch (e) {
      setInstallError(e instanceof Error ? e.message : String(e));
    } finally {
      setInstalling(null);
      qc.invalidateQueries({ queryKey: ["admin-models"] });
    }
  };

  const downloadBundle = async () => {
    setBundleBusy(true);
    try {
      const resp = await getSupportBundle();
      const url = URL.createObjectURL(resp.data);
      const a = document.createElement("a");
      a.href = url;
      a.download = `lorekeeper-support-${new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-")}.zip`;
      a.click();
      URL.revokeObjectURL(url);
    } finally {
      setBundleBusy(false);
    }
  };

  const modelRow = (slot: { name: string; installed: boolean; source: string }, variant: "finetuned" | "base", label: string, blurb: string) => (
    <div className="flex flex-col gap-2 rounded-md border border-border p-4">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div>
          <p className="font-medium text-card-foreground">
            {label} <span className="text-xs text-muted-foreground font-mono">({slot.name})</span>
          </p>
          <p className="text-xs text-muted-foreground">{blurb}</p>
          <p className="text-xs text-muted-foreground mt-0.5">Source: {slot.source}</p>
        </div>
        {slot.installed ? (
          <span className="text-sm text-green-600 dark:text-green-400 whitespace-nowrap">● Installed</span>
        ) : (
          <button
            onClick={() => install(variant)}
            disabled={installing !== null || !models?.ollama_reachable}
            className="px-3 py-1.5 rounded-md text-sm bg-primary text-primary-foreground disabled:opacity-50"
          >
            Download &amp; install
          </button>
        )}
      </div>
      {installing?.variant === variant && (
        <div className="flex flex-col gap-1">
          <div className="h-2 rounded bg-muted overflow-hidden">
            <div
              className={`h-full bg-primary transition-all ${installing.pct === null ? "w-1/4 animate-pulse" : ""}`}
              style={installing.pct !== null ? { width: `${installing.pct}%` } : undefined}
            />
          </div>
          <p className="text-xs text-muted-foreground">
            {installing.status}
            {installing.detail && ` — ${installing.detail}`}
            {installing.pct !== null && ` (${installing.pct}%)`}
          </p>
          <p className="text-xs text-muted-foreground">
            Keep this tab open — a 4&nbsp;GB download can take a while on slower connections.
          </p>
        </div>
      )}
    </div>
  );

  return (
    <div className="flex flex-col gap-4 max-w-2xl">
      {/* ── Model library ── */}
      <div className="rounded-lg border border-border bg-card p-5 flex flex-col gap-3">
        <div>
          <p className="font-semibold text-card-foreground">Model Library</p>
          <p className="text-sm text-muted-foreground">
            The AI models this deployment serves locally. Nothing ships with the app itself — install
            them here once and they're stored in the model server's volume.
          </p>
        </div>

        {isLoading && <p className="text-sm text-muted-foreground">Checking the model server…</p>}
        {(isError || (models && !models.ollama_reachable)) && (
          <p className="text-sm text-destructive">
            Model server unreachable at <span className="font-mono">{models?.ollama_url ?? "?"}</span>
            {models?.ollama_error ? ` — ${models.ollama_error}` : ""}. Is the <span className="font-mono">ollama</span>{" "}
            container running? (<span className="font-mono">docker compose ps</span>)
          </p>
        )}

        {models?.ollama_reachable && (
          <>
            {modelRow(
              models.finetuned,
              "finetuned",
              "Lorekeeper (fine-tuned)",
              "The recommended model — Mistral 7B fine-tuned on RPG session journals. ~4.4 GB.",
            )}
            {modelRow(
              models.base,
              "base",
              "Base model",
              "Un-fine-tuned Mistral 7B Instruct — enables the fine-tuned vs. base comparison in Settings. Optional. ~4.1 GB.",
            )}
            {installError && <p className="text-sm text-destructive">Install failed: {installError}</p>}
            {models.installed_models.length > 0 && (
              <p className="text-xs text-muted-foreground">
                All installed models: {models.installed_models.join(", ")}
              </p>
            )}
          </>
        )}
      </div>

      {/* ── Troubleshooting ── */}
      <div className="rounded-lg border border-border bg-card p-5 flex flex-col gap-3">
        <div>
          <p className="font-semibold text-card-foreground">Troubleshooting</p>
          <p className="text-sm text-muted-foreground">
            The support bundle is a zip of recent backend logs plus a sanitized snapshot of this
            deployment's state (service reachability, versions, configuration flags — no secrets).
            Attach it when reporting a problem.
          </p>
        </div>
        <div className="flex gap-2 flex-wrap">
          <button
            onClick={downloadBundle}
            disabled={bundleBusy}
            className="px-3 py-1.5 rounded-md text-sm bg-primary text-primary-foreground disabled:opacity-50"
          >
            {bundleBusy ? "Building…" : "Download support bundle"}
          </button>
          <button
            onClick={() => (showLogs ? logs.refetch() : setShowLogs(true))}
            className="px-3 py-1.5 rounded-md text-sm border border-border text-foreground hover:bg-muted"
          >
            {showLogs ? "Refresh logs" : "View recent logs"}
          </button>
        </div>
        {showLogs && (
          <div className="flex flex-col gap-1">
            {logs.isLoading && <p className="text-xs text-muted-foreground">Loading logs…</p>}
            {logs.data && (
              <>
                <p className="text-xs text-muted-foreground">
                  Last {logs.data.lines.length} lines
                  {logs.data.source === "memory" && " (this worker's in-memory buffer — no log file configured)"}
                  :
                </p>
                <pre className="text-[11px] leading-4 bg-muted/40 rounded-md p-3 max-h-80 overflow-auto whitespace-pre-wrap break-all">
                  {logs.data.lines.join("\n") || "(no log lines yet)"}
                </pre>
              </>
            )}
          </div>
        )}
        <div className="border-t border-border pt-3 text-sm text-muted-foreground">
          <p className="font-medium text-card-foreground mb-1">Something broken?</p>
          <p>
            Download the support bundle above, then{" "}
            <a
              href="https://github.com/hsmith-dev/Lorekeeper.quest/issues/new"
              target="_blank"
              rel="noreferrer"
              className="underline text-foreground"
            >
              open an issue on GitHub
            </a>{" "}
            and attach it — it contains everything needed to diagnose most problems (recent logs +
            service status, no passwords or keys). You can unzip and read exactly what's in it first.
          </p>
        </div>
      </div>
    </div>
  );
}

export function AdminPage() {
  // ?tab=<key> deep-links straight to a tab — the dashboard's "no model
  // installed" banner points at /admin?tab=system.
  const [tab, setTab] = useState<TabKey>(() => {
    const wanted = new URLSearchParams(window.location.search).get("tab");
    return TABS.some((t) => t.key === wanted) ? (wanted as TabKey) : "users";
  });
  // The backend already 403s every /api/admin/* route for non-admins (see
  // app/api/deps.py::require_admin) — this is purely so a non-admin who
  // navigates here directly sees a clean message instead of raw failed
  // requests from every tab's hook firing at once.
  const { data: profile, isLoading: profileLoading } = useQuery({
    queryKey: ["me"],
    queryFn: () => getMe().then((r) => r.data),
    staleTime: 60_000,
  });
  const isAdmin = profile?.is_admin ?? false;

  if (profileLoading) return null;

  if (!isAdmin) {
    return (
      <div className="max-w-3xl mx-auto px-4 py-16 text-center text-muted-foreground">
        <p className="text-4xl mb-3">🔒</p>
        <p className="text-sm font-medium text-foreground mb-1">Admin access required</p>
        <p className="text-xs">This page isn't available on your account.</p>
      </div>
    );
  }

  return (
    <div className="max-w-3xl mx-auto px-4 py-6 md:py-10 flex flex-col gap-6">
      <PageHeader title="Admin" description="Manage users, promo codes, and platform access." />

      <div className="flex gap-1.5 flex-wrap border-b border-border pb-3">
        {TABS.map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={`px-3 py-1.5 rounded-md text-sm transition-colors ${
              tab === t.key ? "bg-muted text-foreground font-medium" : "text-muted-foreground hover:text-foreground hover:bg-muted/60"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === "users" && <UsersTab />}
      {tab === "promo-codes" && <PromoCodesTab />}
      {tab === "feedback" && <FeedbackTab />}
      {tab === "platform" && <PlatformTab />}
      {tab === "system" && <SystemTab />}
    </div>
  );
}
