// Pure rules for Sharing › Members (E0-Access.12). No runtime imports, so
// scripts/check-members.mjs can load it directly.
//
// Cosmetic only: the server decides who may change what (AD-13).

/** A row's Role in `GET /api/campaigns/{id}/members`. */
export type MemberRole = "owner" | "co_gm" | "player";
/** A Role the Owner can give a Member or a collaborate link. */
export type GrantRole = "co_gm" | "player";

export interface MemberRow {
  member_id: string | null;
  role: MemberRole;
}

/** The Owner row: `member_id: null` (nothing to change or remove). */
export function isOwnerRow(row: MemberRow): boolean {
  return row.member_id === null || row.role === "owner";
}

/** Only a co_gm → player demotion archives the Member's chat sessions. */
export function archivesChats(from: MemberRole, to: GrantRole): boolean {
  return from === "co_gm" && to === "player";
}

/** The notice EXPERIENCE.md asks for (role change notice, FR-9). */
export const ARCHIVE_NOTICE = "Their NPC Conversations and chat history in this Campaign will be archived.";

/** The demotion notice shown before the PATCH is sent. */
export function archiveNotice(name: string): string {
  return `Make ${name} a Player? ${ARCHIVE_NOTICE} Their journal entries stay, but only GMs can edit them.`;
}

/** Where login goes: a paid account, or an unpaid one that is already in a
 *  Campaign (a Player reads the Party for free), goes to the dashboard. */
export function loginDestination(accessGranted: boolean, campaignCount: number): "/dashboard" | "/subscribe" {
  return accessGranted || campaignCount > 0 ? "/dashboard" : "/subscribe";
}

function pad(n: number, width = 2): string {
  return String(Math.trunc(Math.abs(n))).padStart(width, "0");
}

/**
 * An `<input type="date">` value ("YYYY-MM-DD") → the end of that local day
 * as ISO 8601 with the local offset ("2026-12-01T23:59:59.999-05:00").
 * "" → null (no expiry). Anything else that is not a real date → undefined.
 */
export function expiryDateToIso(value: string): string | null | undefined {
  if (value === "") return null;
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
  if (!m) return undefined;
  const [year, month, day] = [Number(m[1]), Number(m[2]), Number(m[3])];
  const end = new Date(year, month - 1, day, 23, 59, 59, 999);
  if (end.getFullYear() !== year || end.getMonth() !== month - 1 || end.getDate() !== day) return undefined;
  const offset = -end.getTimezoneOffset();
  const sign = offset >= 0 ? "+" : "-";
  return (
    `${m[1]}-${m[2]}-${m[3]}T23:59:59.999` + `${sign}${pad(offset / 60)}:${pad(offset % 60)}`
  );
}

/** Today's local date as an `<input type="date">` value (the earliest expiry). */
export function todayDateValue(now: Date = new Date()): string {
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

/** A link still works: not revoked and not past its expiry. */
export function isLiveLink(link: { revoked: boolean; expires_at: string | null }, now: Date = new Date()): boolean {
  if (link.revoked) return false;
  return link.expires_at === null || new Date(link.expires_at).getTime() > now.getTime();
}
