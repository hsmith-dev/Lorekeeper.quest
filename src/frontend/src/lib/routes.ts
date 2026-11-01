import { lazy, type ComponentType } from "react";
import { matchPath } from "react-router-dom";

import { HomePage } from "@/pages/HomePage";
import { LoginPage } from "@/pages/LoginPage";
import { RegisterPage } from "@/pages/RegisterPage";
import { ForgotPasswordPage } from "@/pages/ForgotPasswordPage";
import { ResetPasswordPage } from "@/pages/ResetPasswordPage";
import { DashboardPage } from "@/pages/DashboardPage";
import { HistoryPage } from "@/pages/HistoryPage";

// The route registry (E0-UX.8): one shared append point for every epic.
//
// App.tsx builds its <Route>s from PAGE_ROUTES and LEGACY_REDIRECTS, and the
// NavBar builds its menu from NAV_GROUPS / PLAYER_NAV filtered by what is
// registered here. A feature epic adds a page with one PAGE_ROUTES line; nav
// entries and redirects that wait on that path (World, Keepsakes, Portal…)
// switch on by themselves.
//
// Roles are cosmetic. `roles` only decides whether the shell renders the page
// or the not-found page for an audience; the server stays the control (AD-13).

export type NavAudience = "gm" | "player";
export type NavGroupLabel = "Chronicle" | "Campaign" | "Collaborate" | "Admin";

export interface PageRoute {
  /** A react-router path pattern, e.g. "/journal/:id". */
  path: string;
  /** Page title: document title "{title} · Lorekeeper" and the announcement. */
  title: string;
  page: ComponentType;
  /** Appends the route to this GM nav group when NAV_GROUPS does not list it. */
  navGroup?: NavGroupLabel;
  /** Nav link label; defaults to `title`. */
  navLabel?: string;
  /** Audiences that may open the page; others get the not-found page. */
  roles: readonly NavAudience[];
  /** "private" (default) sends logged-out users to /login. */
  auth?: "public" | "private";
}

export interface NavLink {
  to: string;
  label: string;
}

export interface NavGroup {
  label: NavGroupLabel;
  links: NavLink[];
}

export interface LegacyRedirect {
  from: string;
  to: string;
  /** Only active once this path is registered. */
  whenRegistered?: string;
}

/**
 * React.lazy for a named export. Pages here use `export function XPage()`, and
 * React.lazy only takes a module with a default export. Each lazy page gets its
 * own chunk, fetched the first time its route renders; the core loop (Home,
 * auth pages, Dashboard, History) stays in the main bundle.
 */
export function lazyPage<M>(load: () => Promise<M>, exportName: keyof M & string): ComponentType {
  return lazy(() => load().then((m) => ({ default: m[exportName] as unknown as ComponentType })));
}

const BOTH: readonly NavAudience[] = ["gm", "player"];
const GM_ONLY: readonly NavAudience[] = ["gm"];

/** Every page route. One line per page. */
export const PAGE_ROUTES: readonly PageRoute[] = [
  { path: "/", title: "Home", page: HomePage, roles: BOTH, auth: "public" },
  { path: "/login", title: "Log in", page: LoginPage, roles: BOTH, auth: "public" },
  { path: "/register", title: "Create account", page: RegisterPage, roles: BOTH, auth: "public" },
  { path: "/forgot-password", title: "Forgot password", page: ForgotPasswordPage, roles: BOTH, auth: "public" },
  { path: "/reset-password", title: "Reset password", page: ResetPasswordPage, roles: BOTH, auth: "public" },
  { path: "/shared/:token", title: "Shared campaign", page: lazyPage(() => import("@/pages/SharedCampaignPage"), "SharedCampaignPage"), roles: BOTH, auth: "public" },
  { path: "/join/:token", title: "Join campaign", page: lazyPage(() => import("@/pages/JoinCampaignPage"), "JoinCampaignPage"), roles: BOTH, auth: "public" },
  { path: "/terms", title: "Terms", page: lazyPage(() => import("@/pages/TermsPage"), "TermsPage"), roles: BOTH, auth: "public" },
  { path: "/privacy", title: "Privacy", page: lazyPage(() => import("@/pages/PrivacyPage"), "PrivacyPage"), roles: BOTH, auth: "public" },
  { path: "/dashboard", title: "Journal", page: DashboardPage, roles: BOTH },
  { path: "/history", title: "History", page: HistoryPage, roles: BOTH },
  { path: "/journal/:id", title: "Journal entry", page: lazyPage(() => import("@/pages/EntryDetailPage"), "EntryDetailPage"), roles: BOTH },
  { path: "/chat", title: "Chronicler", page: lazyPage(() => import("@/pages/ChatPage"), "ChatPage"), roles: BOTH },
  { path: "/timeline", title: "Timeline", page: lazyPage(() => import("@/pages/TimelinePage"), "TimelinePage"), roles: BOTH },
  { path: "/live", title: "Live Session", page: lazyPage(() => import("@/pages/RecordSessionPage"), "RecordSessionPage"), roles: GM_ONLY },
  { path: "/stats", title: "Stats", page: lazyPage(() => import("@/pages/AnalyticsPage"), "AnalyticsPage"), roles: BOTH },
  { path: "/characters", title: "Characters", page: lazyPage(() => import("@/pages/CharactersPage"), "CharactersPage"), roles: BOTH },
  { path: "/character-sheets", title: "Character Sheets", page: lazyPage(() => import("@/pages/CharacterSheetsPage"), "CharacterSheetsPage"), roles: BOTH },
  { path: "/quests", title: "Quests", page: lazyPage(() => import("@/pages/QuestsPage"), "QuestsPage"), roles: BOTH },
  { path: "/session-plans", title: "Session Plans", page: lazyPage(() => import("@/pages/SessionPlansPage"), "SessionPlansPage"), roles: GM_ONLY },
  { path: "/sources", title: "Sources", page: lazyPage(() => import("@/pages/SourcesPage"), "SourcesPage"), roles: GM_ONLY },
  { path: "/shorthand", title: "Shorthand", page: lazyPage(() => import("@/pages/ShorthandPage"), "ShorthandPage"), roles: GM_ONLY },
  { path: "/sharing", title: "Sharing", page: lazyPage(() => import("@/pages/SharingPage"), "SharingPage"), roles: BOTH },
  { path: "/feedback", title: "Feedback", page: lazyPage(() => import("@/pages/FeedbackPage"), "FeedbackPage"), roles: BOTH },
  { path: "/settings", title: "Settings", page: lazyPage(() => import("@/pages/SettingsPage"), "SettingsPage"), roles: BOTH },
  { path: "/subscribe", title: "Subscribe", page: lazyPage(() => import("@/pages/SubscribePage"), "SubscribePage"), roles: BOTH },
  { path: "/admin", title: "Admin", page: lazyPage(() => import("@/pages/AdminPage"), "AdminPage"), roles: BOTH },
];

/** GM nav: ordered paths per group. Unregistered paths are skipped. */
export const NAV_GROUPS: readonly { label: NavGroupLabel; links: readonly NavLink[] }[] = [
  {
    label: "Chronicle",
    links: [
      { to: "/dashboard", label: "Journal" },
      { to: "/history", label: "History" },
      { to: "/timeline", label: "Timeline" },
      { to: "/live", label: "Live Session" },
      { to: "/keepsakes", label: "Keepsakes" },
      { to: "/stats", label: "Stats" },
    ],
  },
  {
    label: "Campaign",
    links: [
      { to: "/world", label: "World" },
      { to: "/characters", label: "Characters" },
      { to: "/character-sheets", label: "Character Sheets" },
      { to: "/quests", label: "Quests" },
      { to: "/session-plans", label: "Session Plans" },
      { to: "/sources", label: "Sources" },
      { to: "/shorthand", label: "Shorthand" },
    ],
  },
  {
    label: "Collaborate",
    links: [
      { to: "/sharing", label: "Sharing" },
      { to: "/feedback", label: "Feedback" },
    ],
  },
  // Admins only (see gmNavGroups); AdminPage also self-guards.
  { label: "Admin", links: [{ to: "/admin", label: "Admin" }] },
];

/** Player nav: each link shows only once its route is registered. */
export const PLAYER_NAV: readonly NavLink[] = [
  { to: "/portal", label: "Portal" },
  { to: "/world", label: "World" },
  { to: "/portal/journal", label: "My Journal" },
  { to: "/chat", label: "Chronicler" },
  { to: "/keepsakes", label: "Recaps" },
];

/** Old URLs. Query strings and hashes are kept; redirects use `replace`. */
export const LEGACY_REDIRECTS: readonly LegacyRedirect[] = [
  { from: "/analytics", to: "/stats" },
  { from: "/record", to: "/live?mode=record" },
  { from: "/characters", to: "/world?type=character", whenRegistered: "/world" },
  { from: "/quests", to: "/world?type=quest", whenRegistered: "/world" },
];

/** Links that World replaces once it is registered. */
const REPLACED_BY_WORLD = new Set(["/characters", "/quests"]);

export const NOT_FOUND_TITLE = "Page not found";
export const NOT_FOUND_MESSAGE = "This page doesn't exist or isn't shared with you.";

function stripQueryAndHash(path: string): string {
  const cut = path.search(/[?#]/);
  return cut === -1 ? path : path.slice(0, cut);
}

/** The registered page route matching `pathname` (query and hash ignored). */
export function findRoute(pathname: string, routes: readonly PageRoute[] = PAGE_ROUTES): PageRoute | undefined {
  const bare = stripQueryAndHash(pathname) || "/";
  return routes.find((r) => matchPath({ path: r.path, end: true }, bare) !== null);
}

/** Whether a page route exists for `path`, e.g. isRouteRegistered("/world"). */
export function isRouteRegistered(path: string, routes: readonly PageRoute[] = PAGE_ROUTES): boolean {
  return findRoute(path, routes) !== undefined;
}

/** The GM nav groups: unregistered links and empty groups dropped. */
export function gmNavGroups(
  { isAdmin }: { isAdmin: boolean },
  routes: readonly PageRoute[] = PAGE_ROUTES,
): NavGroup[] {
  const worldRegistered = isRouteRegistered("/world", routes);
  const groups: NavGroup[] = NAV_GROUPS.filter((g) => g.label !== "Admin" || isAdmin).map((g) => ({
    label: g.label,
    links: g.links.filter(
      (l) => isRouteRegistered(l.to, routes) && !(worldRegistered && REPLACED_BY_WORLD.has(l.to)),
    ),
  }));
  // Routes that name a navGroup NAV_GROUPS does not list are appended to it.
  const listed = new Set(NAV_GROUPS.flatMap((g) => g.links.map((l) => l.to)));
  for (const r of routes) {
    if (!r.navGroup || listed.has(r.path)) continue;
    const group = groups.find((g) => g.label === r.navGroup);
    if (group) group.links.push({ to: r.path, label: r.navLabel ?? r.title });
  }
  return groups.filter((g) => g.links.length > 0);
}

/** The Player nav: PLAYER_NAV links whose routes are registered. */
export function playerNav(routes: readonly PageRoute[] = PAGE_ROUTES): NavLink[] {
  return PLAYER_NAV.filter((l) => isRouteRegistered(l.to, routes));
}

/**
 * Who the shell renders for. Player only when there is a current campaign and
 * the effective role (incl. "Preview as Player") is not GM: with no campaign
 * (none yet, or still loading) the user has no Role anywhere, and treating
 * that as Player would hide most of the app and flicker on every load.
 */
export function navAudience({ hasCampaign, isGm }: { hasCampaign: boolean; isGm: boolean }): NavAudience {
  return hasCampaign && !isGm ? "player" : "gm";
}

/** Redirects in force for this registry (gated ones wait on their target). */
export function activeRedirects(routes: readonly PageRoute[] = PAGE_ROUTES): LegacyRedirect[] {
  return LEGACY_REDIRECTS.filter((r) => !r.whenRegistered || isRouteRegistered(r.whenRegistered, routes));
}

/**
 * The redirect URL: `to` with the incoming query and hash kept. Target params
 * override same-named incoming ones.
 * redirectTarget("/live?mode=record", "?mode=foo&x=1", "#h") → "/live?mode=record&x=1#h"
 */
export function redirectTarget(to: string, search: string, hash: string): string {
  const hashAt = to.indexOf("#");
  const toHash = hashAt === -1 ? "" : to.slice(hashAt);
  const toNoHash = hashAt === -1 ? to : to.slice(0, hashAt);
  const queryAt = toNoHash.indexOf("?");
  const path = queryAt === -1 ? toNoHash : toNoHash.slice(0, queryAt);
  const params = new URLSearchParams(search);
  if (queryAt !== -1) {
    for (const [k, v] of new URLSearchParams(toNoHash.slice(queryAt + 1))) params.set(k, v);
  }
  const qs = params.toString();
  const h = hash && hash !== "#" ? hash : toHash;
  return `${path}${qs ? `?${qs}` : ""}${h}`;
}

export function canView(route: Pick<PageRoute, "roles">, audience: NavAudience): boolean {
  return route.roles.includes(audience);
}

export function formatDocumentTitle(title: string): string {
  return `${title} · Lorekeeper`;
}
