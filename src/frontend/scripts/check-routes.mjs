#!/usr/bin/env node
// Checks the E0-UX.8 route registry, nav sets, legacy redirects, the unified
// not-found page and the route announcer against the story's I/O matrix:
// registry shape, isRouteRegistered, GM/Player nav (real registry and with
// /world, /keepsakes, /portal fixtures), navAudience, activeRedirects,
// redirectTarget, canView, document title + badge, announcement text, title
// store precedence, and server renders of NotFound, NavBar and RoutePage.
// Pure functions plus renderToStaticMarkup; live-region timing, focus moves,
// keyboard, Back after a redirect and the 375 px layout are covered by the
// manual Playwright harness.
// No test runner and no new dependency: node:test + node:assert and the
// esbuild that Vite already installs (same harness as check-campaign-switcher).
//
//   node scripts/check-routes.mjs

import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, rmSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { beforeEach, describe, test } from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";

import { build } from "esbuild";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createElement as h } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter, Navigate, Route, Routes, createRoutesFromChildren, matchRoutes } from "react-router-dom";

const frontendDir = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const srcDir = join(frontendDir, "src");

class FakeStorage {
  #map = new Map();
  getItem(k) {
    return this.#map.has(k) ? this.#map.get(k) : null;
  }
  setItem(k, v) {
    this.#map.set(k, String(v));
  }
  removeItem(k) {
    this.#map.delete(k);
  }
  clear() {
    this.#map.clear();
  }
}
const consoleError = console.error;
console.error = (...args) => {
  if (typeof args[0] === "string" && args[0].includes("useLayoutEffect does nothing on the server")) return;
  consoleError(...args);
};

const local = new FakeStorage();
globalThis.localStorage = local;
globalThis.sessionStorage = new FakeStorage();

const cacheDir = join(frontendDir, "node_modules", ".cache");
mkdirSync(cacheDir, { recursive: true });
const outDir = mkdtempSync(join(cacheDir, "check-routes-"));
process.on("exit", () => rmSync(outDir, { recursive: true, force: true }));

await build({
  entryPoints: {
    routes: join(srcDir, "lib/routes.ts"),
    announcer: join(srcDir, "components/shell/RouteAnnouncer.tsx"),
    gate: join(srcDir, "components/shell/RouteGate.tsx"),
    notfound: join(srcDir, "pages/NotFoundPage.tsx"),
    navbar: join(srcDir, "components/NavBar.tsx"),
    "current-campaign": join(srcDir, "hooks/useCurrentCampaign.ts"),
    preview: join(srcDir, "lib/preview.ts"),
    app: join(srcDir, "App.tsx"),
    entry: join(srcDir, "pages/EntryDetailPage.tsx"),
  },
  outdir: outDir,
  outExtension: { ".js": ".mjs" },
  bundle: true,
  splitting: true,
  format: "esm",
  platform: "node",
  jsx: "automatic",
  alias: { "@": srcDir },
  external: ["react", "react-dom", "@tanstack/react-query", "react-router-dom", "lucide-react", "axios"],
  define: { "import.meta.env.VITE_API_URL": "undefined", "import.meta.env.DEV": "false" },
  logLevel: "error",
});

const load = (name) => import(pathToFileURL(join(outDir, `${name}.mjs`)).href);
const R = await load("routes");
const A = await load("announcer");
const { RoutePage } = await load("gate");
const { NotFound, NotFoundPage, notFoundHome } = await load("notfound");
const { NavBar } = await load("navbar");
const cc = await load("current-campaign");
const store = await load("preview");
const { AppRoutes } = await load("app");
const { EntryDetailPage, isNotFoundError, retryEntry } = await load("entry");
const { LegacyRedirect } = await load("gate");

const decode = (s) =>
  s
    .replace(/&#x27;|&#39;/g, "'")
    .replace(/&quot;/g, '"')
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&amp;/g, "&");
const text = (html) => decode(html.replace(/<[^>]+>/g, " ")).replace(/\s+/g, " ").trim();

const COPY = "This page doesn't exist or isn't shared with you.";
const Stub = () => null;
const fixture = (...paths) => [
  ...R.PAGE_ROUTES,
  ...paths.map((path) => ({ path, title: path, page: Stub, roles: ["gm", "player"] })),
];
const labels = (groups) => Object.fromEntries(groups.map((g) => [g.label, g.links.map((l) => l.label)]));

const campaign = (id, name, is_owner) => ({
  id,
  name,
  genre: "fantasy",
  description: null,
  created_at: "2026-01-01T00:00:00Z",
  is_owner,
  owner_display_name: is_owner ? null : "Someone",
});
const OWNED = campaign("a", "Ashfall", true);
const SHARED = campaign("b", "Brinewood", false);

beforeEach(() => {
  local.clear();
  store.setPreviewCampaignId(null);
  A.resetPageTitles();
});

// Server render inside the real provider. `stored` picks the current campaign:
// "a" (owned → GM), "b" (shared → Player); campaigns null = still loading.
function renderShell(child, { path = "/", stored, campaigns = [OWNED, SHARED], loggedIn = true, isAdmin = false, seed } = {}) {
  if (loggedIn) {
    local.setItem("lk_token", "t");
    local.setItem("lk_user", JSON.stringify({ id: "u1", display_name: "U" }));
  }
  if (stored !== undefined) local.setItem(cc.currentCampaignKey("u1"), stored);
  // retryOnMount off: a seeded error state renders as-is (no optimistic refetch).
  const client = new QueryClient({ defaultOptions: { queries: { retryOnMount: false } } });
  seed?.(client);
  if (campaigns && loggedIn) client.setQueryData(["campaigns"], campaigns);
  client.setQueryData(["me"], { display_name: "U", email: "u@example.com", is_admin: isAdmin });
  return renderToStaticMarkup(
    h(
      QueryClientProvider,
      { client },
      h(MemoryRouter, { initialEntries: [path] }, h(cc.CurrentCampaignProvider, null, child)),
    ),
  );
}

describe("registry shape", () => {
  test("unique paths; every route has a title, a page and roles", () => {
    const paths = R.PAGE_ROUTES.map((r) => r.path);
    assert.equal(new Set(paths).size, paths.length, "duplicate path");
    for (const r of R.PAGE_ROUTES) {
      assert.ok(typeof r.title === "string" && r.title.length > 0, r.path);
      assert.ok(r.page, r.path);
      assert.ok(Array.isArray(r.roles) && r.roles.length > 0, r.path);
      for (const role of r.roles) assert.ok(role === "gm" || role === "player", `${r.path}: ${role}`);
    }
  });

  test("every route App had before E0-UX.8 is still served", () => {
    const before = [
      "/login", "/register", "/forgot-password", "/reset-password", "/shared/:token", "/join/:token", "/",
      "/dashboard", "/history", "/journal/:id", "/chat", "/timeline", "/characters", "/character-sheets",
      "/quests", "/session-plans", "/sources", "/sharing", "/settings", "/subscribe", "/feedback",
      "/shorthand", "/admin", "/terms", "/privacy",
    ];
    const paths = new Set(R.PAGE_ROUTES.map((r) => r.path));
    for (const p of before) assert.ok(paths.has(p), p);
    // Renamed: served through the redirect table.
    const from = new Set(R.activeRedirects().map((r) => r.from));
    assert.ok(from.has("/analytics") && from.has("/record"));
    assert.ok(!paths.has("/analytics") && !paths.has("/record"));
  });

  test("/stats is AnalyticsPage 'Stats'; /live is RecordSessionPage 'Live Session'", () => {
    assert.equal(R.findRoute("/stats").title, "Stats");
    assert.equal(R.findRoute("/live").title, "Live Session");
  });

  test("GM-only routes; other epics' paths not registered", () => {
    const gmOnly = R.PAGE_ROUTES.filter((r) => !r.roles.includes("player")).map((r) => r.path).sort();
    assert.deepEqual(gmOnly, ["/live", "/session-plans", "/shorthand", "/sources"]);
    for (const r of R.PAGE_ROUTES.filter((r) => r.roles.includes("player"))) assert.ok(r.roles.includes("gm"), r.path);
    for (const p of ["/world", "/portal", "/portal/journal", "/keepsakes"]) assert.equal(R.isRouteRegistered(p), false, p);
  });

  test("public vs private", () => {
    const pub = R.PAGE_ROUTES.filter((r) => r.auth === "public").map((r) => r.path).sort();
    assert.deepEqual(pub, ["/", "/forgot-password", "/join/:token", "/login", "/privacy", "/register", "/reset-password", "/shared/:token", "/terms"]);
  });
});

describe("isRouteRegistered / findRoute", () => {
  test("matrix", () => {
    assert.equal(R.isRouteRegistered("/world"), false);
    assert.equal(R.isRouteRegistered("/stats"), true);
    assert.equal(R.isRouteRegistered("/stats?range=30#top"), true, "query and hash stripped");
    assert.equal(R.isRouteRegistered("/journal/x"), true);
    assert.equal(R.isRouteRegistered("/journal"), false);
    assert.equal(R.isRouteRegistered("/nope"), false);
    assert.equal(R.isRouteRegistered("/analytics"), false, "redirects are not page routes");
    assert.equal(R.isRouteRegistered("/world", fixture("/world")), true);
    assert.equal(R.findRoute("/journal/abc").path, "/journal/:id");
  });
});

describe("GM nav", () => {
  test("today: no World/Keepsakes", () => {
    assert.deepEqual(labels(R.gmNavGroups({ isAdmin: false })), {
      Chronicle: ["Journal", "History", "Timeline", "Live Session", "Stats"],
      Campaign: ["Characters", "Character Sheets", "Quests", "Session Plans", "Sources", "Shorthand"],
      Collaborate: ["Sharing", "Feedback"],
    });
    const hrefs = R.gmNavGroups({ isAdmin: false }).flatMap((g) => g.links.map((l) => l.to));
    assert.ok(hrefs.includes("/live") && hrefs.includes("/stats"));
    assert.ok(!hrefs.includes("/record") && !hrefs.includes("/analytics"));
  });

  test("admin group only for admins, last", () => {
    const groups = R.gmNavGroups({ isAdmin: true });
    assert.deepEqual(groups.map((g) => g.label), ["Chronicle", "Campaign", "Collaborate", "Admin"]);
    assert.deepEqual(groups[3].links, [{ to: "/admin", label: "Admin" }]);
  });

  test("World registered: replaces Characters and Quests", () => {
    assert.deepEqual(labels(R.gmNavGroups({ isAdmin: false }, fixture("/world"))).Campaign, [
      "World",
      "Character Sheets",
      "Session Plans",
      "Sources",
      "Shorthand",
    ]);
  });

  test("Keepsakes registered: between Live Session and Stats", () => {
    assert.deepEqual(labels(R.gmNavGroups({ isAdmin: false }, fixture("/keepsakes"))).Chronicle, [
      "Journal",
      "History",
      "Timeline",
      "Live Session",
      "Keepsakes",
      "Stats",
    ]);
  });

  test("a route naming an unlisted navGroup is appended to it", () => {
    const routes = [...R.PAGE_ROUTES, { path: "/maps", title: "Maps", page: Stub, roles: ["gm"], navGroup: "Campaign" }];
    assert.equal(labels(R.gmNavGroups({ isAdmin: false }, routes)).Campaign.at(-1), "Maps");
  });
});

describe("Player nav", () => {
  test("today: only Chronicler", () => {
    assert.deepEqual(R.playerNav(), [{ to: "/chat", label: "Chronicler" }]);
  });

  test("all registered: Portal, World, My Journal, Chronicler, Recaps", () => {
    const nav = R.playerNav(fixture("/portal", "/world", "/portal/journal", "/keepsakes"));
    assert.deepEqual(nav.map((l) => l.label), ["Portal", "World", "My Journal", "Chronicler", "Recaps"]);
    for (const l of nav) assert.ok(!["/sources", "/shorthand", "/session-plans", "/live", "/admin"].includes(l.to));
  });
});

describe("navAudience / canView", () => {
  test("player only with a campaign and a non-GM role", () => {
    assert.equal(R.navAudience({ hasCampaign: true, isGm: false }), "player");
    assert.equal(R.navAudience({ hasCampaign: true, isGm: true }), "gm");
    assert.equal(R.navAudience({ hasCampaign: false, isGm: false }), "gm", "no campaign: GM set, no gating");
    assert.equal(R.navAudience({ hasCampaign: false, isGm: true }), "gm");
  });

  test("canView", () => {
    assert.equal(R.canView(R.findRoute("/sources"), "player"), false);
    assert.equal(R.canView(R.findRoute("/sources"), "gm"), true);
    assert.equal(R.canView(R.findRoute("/chat"), "player"), true);
    assert.equal(R.canView(R.findRoute("/admin"), "player"), true, "AdminPage self-guards");
  });
});

describe("redirects", () => {
  test("activeRedirects today vs with /world", () => {
    assert.deepEqual(
      R.activeRedirects().map((r) => [r.from, r.to]),
      [
        ["/analytics", "/stats"],
        ["/record", "/live?mode=record"],
      ],
    );
    assert.deepEqual(
      R.activeRedirects(fixture("/world")).map((r) => [r.from, r.to]),
      [
        ["/analytics", "/stats"],
        ["/record", "/live?mode=record"],
        ["/characters", "/world?type=character"],
        ["/quests", "/world?type=quest"],
      ],
    );
  });

  test("redirectTarget keeps query and hash; target params override", () => {
    assert.equal(R.redirectTarget("/stats", "?range=30", "#top"), "/stats?range=30#top");
    assert.equal(R.redirectTarget("/stats", "", ""), "/stats");
    assert.equal(R.redirectTarget("/live?mode=record", "?x=1", ""), "/live?x=1&mode=record");
    assert.equal(R.redirectTarget("/live?mode=record", "?mode=foo", ""), "/live?mode=record");
    const merged = new URL(R.redirectTarget("/live?mode=record", "?mode=foo&x=1", "#h"), "http://x");
    assert.equal(merged.pathname, "/live");
    assert.equal(merged.searchParams.get("mode"), "record");
    assert.equal(merged.searchParams.get("x"), "1");
    assert.deepEqual(merged.searchParams.getAll("mode"), ["record"]);
    assert.equal(merged.hash, "#h");
    assert.equal(R.redirectTarget("/world?type=character", "?q=a", ""), "/world?q=a&type=character");
  });
});

describe("titles and announcements", () => {
  test("formatDocumentTitle and announcementText", () => {
    assert.equal(R.formatDocumentTitle("World"), "World · Lorekeeper");
    assert.equal(A.announcementText("World", "214 entities"), "World, 214 entities");
    assert.equal(A.announcementText("World"), "World");
  });

  test("applyDocumentTitle keeps the (n) badge", () => {
    globalThis.document = { title: "(3) History · Lorekeeper" };
    try {
      A.applyDocumentTitle("Stats");
      assert.equal(document.title, "(3) Stats · Lorekeeper");
      document.title = "History · Lorekeeper";
      A.applyDocumentTitle("Stats");
      assert.equal(document.title, "Stats · Lorekeeper");
    } finally {
      delete globalThis.document;
    }
  });

  test("title store: override beats default whatever the order; pop restores", () => {
    const pop = A.pushTitleOverride("World", "214 entities");
    A.setRouteTitle("Route default"); // parent effect runs after the child's
    assert.deepEqual(A.getPageTitle(), { title: "World", detail: "214 entities" });
    const pop2 = A.pushTitleOverride("Page not found");
    assert.equal(A.getPageTitle().title, "Page not found");
    pop2();
    pop2(); // idempotent
    assert.equal(A.getPageTitle().title, "World");
    pop();
    assert.deepEqual(A.getPageTitle(), { title: "Route default", detail: undefined });
    A.setRouteTitle(null);
    assert.equal(A.getPageTitle(), null);
  });

  test("snapshot is stable when nothing changed (no render loop)", () => {
    A.setRouteTitle("Stats");
    const a = A.getPageTitle();
    A.setRouteTitle("Stats");
    assert.equal(A.getPageTitle(), a);
  });
});

describe("NotFound (server render)", () => {
  const only = (html) => {
    assert.equal(text(html).includes(COPY), true, text(html));
    assert.match(html, /<h1[^>]*>Page not found<\/h1>/);
    const links = [...html.matchAll(/<a [^>]*href="([^"]*)"/g)].map((m) => m[1]);
    assert.equal(links.length, 1, "one home link");
    return links[0];
  };

  test("GM -> /dashboard", () => {
    assert.equal(only(renderShell(h(NotFound), { stored: "a" })), "/dashboard");
  });

  test("Player, /portal not registered -> /dashboard", () => {
    assert.equal(only(renderShell(h(NotFound), { stored: "b" })), "/dashboard");
  });

  test("logged out -> /", () => {
    assert.equal(only(renderShell(h(NotFoundPage), { loggedIn: false })), "/");
  });

  test("notFoundHome", () => {
    assert.equal(notFoundHome(false, "gm").to, "/");
    assert.equal(notFoundHome(true, "gm").to, "/dashboard");
    assert.equal(notFoundHome(true, "player").to, "/dashboard");
  });

  test("NotFoundPage renders exactly NotFound", () => {
    assert.equal(renderShell(h(NotFoundPage), { stored: "a" }), renderShell(h(NotFound), { stored: "a" }));
  });
});

describe("RoutePage (server render)", () => {
  const secret = (path, roles) => ({
    path,
    title: "Secret",
    roles,
    page: () => {
      throw new Error(`${path} page must not render`);
    },
  });
  const shown = (path, roles) => ({ path, title: "Shown", roles, page: () => h("h1", null, "SHOWN") });

  test("Player on a GM-only route: same render as a missing page; page not loaded", () => {
    const gated = renderShell(h(RoutePage, { route: secret("/sources", ["gm"]) }), { stored: "b", path: "/sources" });
    assert.ok(text(gated).includes(COPY));
    const missing = renderShell(h(NotFoundPage), { stored: "b", path: "/nope" });
    assert.equal(gated, missing, "identical markup");
  });

  test("real /sources route for a Player renders the not-found copy", () => {
    const html = renderShell(h(RoutePage, { route: R.findRoute("/sources") }), { stored: "b", path: "/sources" });
    assert.ok(text(html).includes(COPY));
  });

  test("GM on a GM-only route sees the page", () => {
    const html = renderShell(h(RoutePage, { route: shown("/sources", ["gm"]) }), { stored: "a", path: "/sources" });
    assert.match(html, /SHOWN/);
  });

  test("no campaign yet: no gating", () => {
    const html = renderShell(h(RoutePage, { route: shown("/sources", ["gm"]) }), { campaigns: [], path: "/sources" });
    assert.match(html, /SHOWN/);
  });

  test("campaign list loading: a GM-only route waits (chunk not fetched); others render", () => {
    const held = renderShell(h(RoutePage, { route: secret("/sources", ["gm"]) }), { campaigns: null, path: "/sources" });
    assert.match(held, /data-route-loading/);
    const open = renderShell(h(RoutePage, { route: shown("/chat", ["gm", "player"]) }), { campaigns: null, path: "/chat" });
    assert.match(open, /SHOWN/);
  });

  test("Preview as Player gates GM-only routes", () => {
    store.setPreviewCampaignId("a");
    try {
      const html = renderShell(h(RoutePage, { route: secret("/sources", ["gm"]) }), { stored: "a", path: "/sources" });
      assert.ok(text(html).includes(COPY));
    } finally {
      store.setPreviewCampaignId(null);
    }
  });

  test("private route logged out renders nothing (redirects to /login)", () => {
    const html = renderShell(h(RoutePage, { route: secret("/sources", ["gm", "player"]) }), {
      loggedIn: false,
      path: "/sources",
    });
    assert.equal(html, "");
  });
});

describe("NavBar (server render)", () => {
  const menuButton = (html) => html.match(/<button[^>]*aria-label="Menu[^"]*"[^>]*>/)?.[0] ?? "";

  test("GM (owned campaign): GM set names the page; disclosure attributes", () => {
    const html = renderShell(h(NavBar), { stored: "a", path: "/stats" });
    assert.match(html, /<nav aria-label="Main"/);
    const btn = menuButton(html);
    assert.match(btn, /aria-label="Menu: Stats"/);
    assert.match(btn, /aria-expanded="false"/);
    assert.doesNotMatch(btn, /aria-haspopup/);
    assert.match(menuButton(renderShell(h(NavBar), { stored: "a", path: "/live" })), /aria-label="Menu: Live Session"/);
    assert.match(menuButton(renderShell(h(NavBar), { stored: "a", path: "/journal/x" })), /aria-label="Menu"/);
  });

  test("Player (shared campaign): only the Player set", () => {
    assert.match(menuButton(renderShell(h(NavBar), { stored: "b", path: "/chat" })), /aria-label="Menu: Chronicler"/);
    // Journal and Sources are not in the Player set.
    assert.match(menuButton(renderShell(h(NavBar), { stored: "b", path: "/dashboard" })), /aria-label="Menu"/);
    assert.match(menuButton(renderShell(h(NavBar), { stored: "b", path: "/sources" })), /aria-label="Menu"/);
    // A GM sees Journal there.
    assert.match(menuButton(renderShell(h(NavBar), { stored: "a", path: "/dashboard" })), /aria-label="Menu: Journal"/);
  });

  test("admin link names the page only for admins in the GM set", () => {
    assert.match(menuButton(renderShell(h(NavBar), { stored: "a", path: "/admin", isAdmin: true })), /aria-label="Menu: Admin"/);
    assert.match(menuButton(renderShell(h(NavBar), { stored: "b", path: "/admin", isAdmin: true })), /aria-label="Menu"/);
  });

  test("logged out: no nav", () => {
    assert.equal(renderShell(h(NavBar), { loggedIn: false }), "");
  });
});

describe("AppRoutes wiring", () => {
  const appRoutes = () => createRoutesFromChildren(AppRoutes().props.children);
  const matched = (path) => matchRoutes(appRoutes(), path).at(-1).route;

  test("redirects first, redirected page routes dropped, `*` last", () => {
    const routes = appRoutes();
    const redirects = R.activeRedirects();
    assert.deepEqual(
      routes.slice(0, redirects.length).map((r) => r.path),
      redirects.map((r) => r.from),
    );
    assert.equal(routes.at(-1).path, "*");
    assert.equal(routes.filter((r) => r.path === "*").length, 1);
    for (const from of ["/analytics", "/record"]) assert.equal(routes.filter((r) => r.path === from).length, 1, from);
  });

  test("/analytics is LegacyRedirect -> /stats, keeping query and hash, with replace", () => {
    const route = matched("/analytics");
    assert.equal(route.element.type, LegacyRedirect);
    assert.equal(route.element.props.to, "/stats");
    let el;
    const Probe = () => {
      el = LegacyRedirect({ to: route.element.props.to });
      return null;
    };
    renderShell(h(Probe), { stored: "a", path: "/analytics?range=30#top" });
    assert.equal(el.type, Navigate);
    assert.equal(el.props.to, "/stats?range=30#top");
    assert.equal(el.props.replace, true);
    assert.equal(matched("/record").element.props.to, "/live?mode=record");
  });

  test("/characters is its page route, not a redirect", () => {
    const route = matched("/characters");
    assert.equal(route.element.type, RoutePage);
    assert.equal(route.element.props.route.path, "/characters");
    const html = renderShell(h(AppRoutes), { stored: "a", path: "/characters" });
    assert.match(html, /data-route-loading/, "lazy page behind its Suspense fallback");
  });

  test("/nope renders the not-found copy", () => {
    assert.equal(matched("/nope").path, "*");
    assert.ok(text(renderShell(h(AppRoutes), { stored: "a", path: "/nope" })).includes(COPY));
  });

  test("while the role settles, `*` waits exactly like a gated route", () => {
    const missing = renderShell(h(AppRoutes), { campaigns: null, path: "/nope" });
    const gated = renderShell(h(AppRoutes), { campaigns: null, path: "/sources" });
    assert.match(missing, /data-route-loading/);
    assert.equal(missing, gated);
    // Logged out: nothing to settle.
    local.clear();
    assert.ok(text(renderShell(h(AppRoutes), { loggedIn: false, path: "/nope" })).includes(COPY));
  });
});

describe("EntryDetailPage errors", () => {
  const withError = (error) => (client) =>
    client
      .getQueryCache()
      .build(client, { queryKey: ["journal", "x"] })
      .setState({ status: "error", error, fetchStatus: "idle", data: undefined });
  const entryPage = h(Routes, null, h(Route, { path: "/journal/:id", element: h(EntryDetailPage) }));

  test("404 and 422 render NotFound", () => {
    for (const status of [404, 422]) {
      const html = renderShell(entryPage, { stored: "a", path: "/journal/x", seed: withError({ response: { status } }) });
      assert.ok(text(html).includes(COPY), `${status}: ${text(html)}`);
    }
  });

  test("500 renders InlineError with Retry, no not-found copy", () => {
    const html = renderShell(entryPage, { stored: "a", path: "/journal/x", seed: withError({ response: { status: 500 } }) });
    assert.ok(text(html).includes("Could not load this entry."), text(html));
    assert.match(text(html), /Retry/);
    assert.ok(!text(html).includes(COPY));
  });

  test("retry predicate: never on 404/422, once otherwise", () => {
    assert.equal(isNotFoundError({ response: { status: 404 } }), true);
    assert.equal(isNotFoundError({ response: { status: 422 } }), true);
    assert.equal(isNotFoundError({ response: { status: 500 } }), false);
    assert.equal(isNotFoundError(new Error("network")), false);
    assert.equal(retryEntry(0, { response: { status: 404 } }), false);
    assert.equal(retryEntry(0, { response: { status: 422 } }), false);
    assert.equal(retryEntry(0, { response: { status: 500 } }), true);
    assert.equal(retryEntry(1, { response: { status: 500 } }), false);
  });
});
