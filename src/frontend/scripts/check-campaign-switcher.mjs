#!/usr/bin/env node
// Checks the E0-UX.7 global current Campaign and CampaignSwitcher against the
// story's I/O matrix: resolveCurrentCampaign (first load, stored, pick, lost
// access, just created, none left, loading/error), per-user storage keys with a
// memory fallback, the role stub and the /me adapter, the preview override,
// the switcher's menu layout and its server-rendered trigger, the nav's 44px
// targets and the CampaignSelector defaults.
// Pure functions plus renderToStaticMarkup; keyboard, focus, reload and the
// 375 px layout are covered by the manual Playwright harness.
// No test runner and no new dependency: node:test + node:assert and the
// esbuild that Vite already installs (same harness as check-spoiler-safety).
//
//   node scripts/check-campaign-switcher.mjs

import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, rmSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { afterEach, beforeEach, describe, test } from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";

import { build } from "esbuild";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createElement as h } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";

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
// React Router's routers use useLayoutEffect, which React warns about on every
// server render. Expected here; keep the output readable.
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
const outDir = mkdtempSync(join(cacheDir, "check-campaign-switcher-"));
process.on("exit", () => rmSync(outDir, { recursive: true, force: true }));

await build({
  entryPoints: {
    "current-campaign": join(srcDir, "hooks/useCurrentCampaign.ts"),
    "effective-role": join(srcDir, "hooks/useEffectiveRole.ts"),
    switcher: join(srcDir, "components/shell/CampaignSwitcher.tsx"),
    selector: join(srcDir, "components/CampaignSelector.tsx"),
    navbar: join(srcDir, "components/NavBar.tsx"),
    preview: join(srcDir, "lib/preview.ts"),
    toast: join(srcDir, "components/ui/toast.tsx"),
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
  define: { "import.meta.env.VITE_API_URL": "undefined" },
  logLevel: "error",
});

const load = (name) => import(pathToFileURL(join(outDir, `${name}.mjs`)).href);
const cc = await load("current-campaign");
const role = await load("effective-role");
const { CampaignSwitcher, switcherMenu, CREATE_CAMPAIGN_HREF } = await load("switcher");
const { CampaignSelector } = await load("selector");
const { NavBar } = await load("navbar");
const store = await load("preview");
const { getToastState, dismissToast } = await load("toast");

const decode = (s) =>
  s
    .replace(/&#x27;|&#39;/g, "'")
    .replace(/&quot;/g, '"')
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&amp;/g, "&");
const text = (html) => decode(html.replace(/<[^>]+>/g, " ")).replace(/\s+/g, " ").trim();

const campaign = (id, name, is_owner = true) => ({
  id,
  name,
  genre: "fantasy",
  description: null,
  created_at: "2026-01-01T00:00:00Z",
  is_owner,
  owner_display_name: is_owner ? null : "Someone",
});
const A = campaign("a", "Ashfall");
const B = campaign("b", "Brinewood", false);
const C = campaign("c", "Cinderreach");

const resolveWith = (over) =>
  cc.resolveCurrentCampaign({ campaigns: [A, B], listReady: true, listUpdatedAt: 100, storedId: null, picked: null, ...over });

beforeEach(() => {
  local.clear();
  store.setPreviewCampaignId(null);
});

describe("resolveCurrentCampaign (I/O matrix)", () => {
  test("first load: no stored id -> first campaign, stored, no toast", () => {
    assert.deepEqual(resolveWith({}), { current: A, persistId: "a", lostAccess: false });
  });

  test("stored valid -> that campaign", () => {
    assert.deepEqual(resolveWith({ storedId: "b" }), { current: B, persistId: "b", lostAccess: false });
  });

  test("lost access: stored X not in list -> first campaign, toast", () => {
    assert.deepEqual(resolveWith({ storedId: "x" }), { current: A, persistId: "a", lostAccess: true });
    assert.equal(
      cc.lostAccessMessage(A),
      "You no longer have access to that campaign. Switched to Ashfall.",
    );
  });

  test("just created: picked C before the list refetched -> C, no toast", () => {
    const picked = { campaign: C, at: 200 };
    assert.deepEqual(resolveWith({ storedId: "c", picked }), { current: C, persistId: "c", lostAccess: false });
    // Same while the refetch is in flight.
    assert.deepEqual(resolveWith({ storedId: "c", picked, listReady: false }), {
      current: C,
      persistId: "c",
      lostAccess: false,
    });
  });

  test("just created, then a list fetched after the pick lacks C -> fallback + toast", () => {
    const picked = { campaign: C, at: 50 };
    assert.deepEqual(resolveWith({ storedId: "c", picked }), { current: A, persistId: "a", lostAccess: true });
  });

  test("picked and listed -> the listed copy", () => {
    const picked = { campaign: { ...B, name: "stale" }, at: 50 };
    assert.equal(resolveWith({ storedId: "b", picked }).current, B);
  });

  test("none left: empty list -> no campaign, storage cleared, no toast", () => {
    assert.deepEqual(resolveWith({ campaigns: [], storedId: "x" }), { current: null, persistId: null, lostAccess: false });
    assert.deepEqual(resolveWith({ campaigns: [] }), { current: null, persistId: null, lostAccess: false });
  });

  test("list loading or failed: stored id kept, no fallback, no toast", () => {
    for (const campaigns of [undefined, [A, B]]) {
      assert.deepEqual(resolveWith({ campaigns, listReady: false, storedId: "x" }), {
        current: null,
        persistId: "x",
        lostAccess: false,
      });
    }
    // Stale data that still lists the stored campaign keeps it current.
    assert.equal(resolveWith({ listReady: false, storedId: "b" }).current, B);
    // Preview enter/exit resets the cache: the last resolved campaign stays.
    assert.deepEqual(resolveWith({ campaigns: undefined, listReady: false, storedId: "b", lastKnown: B }), {
      current: B,
      persistId: "b",
      lostAccess: false,
    });
    assert.equal(
      resolveWith({ campaigns: undefined, listReady: false, storedId: "x", lastKnown: B }).current,
      null,
      "lastKnown only stands in for the stored id",
    );
    // Once the list is back, it decides (no stale lastKnown).
    assert.equal(resolveWith({ campaigns: [A], storedId: "b", lastKnown: B }).current, A);
    assert.deepEqual(resolveWith({ campaigns: undefined, listReady: false }), {
      current: null,
      persistId: null,
      lostAccess: false,
    });
  });
});

describe("per-user storage", () => {
  test("key shape and per-user isolation", () => {
    assert.equal(cc.currentCampaignKey("u1"), "lk-current-campaign:u1");
    cc.writeStoredCampaignId("s1", "a", local);
    cc.writeStoredCampaignId("s2", "b", local);
    assert.equal(local.getItem("lk-current-campaign:s1"), "a");
    assert.equal(cc.readStoredCampaignId("s1", local), "a");
    assert.equal(cc.readStoredCampaignId("s2", local), "b");
    assert.equal(cc.readStoredCampaignId("s3", local), null);
    cc.writeStoredCampaignId("s1", null, local);
    assert.equal(local.getItem("lk-current-campaign:s1"), null);
    assert.equal(cc.readStoredCampaignId("s1", local), null);
  });

  test("storage that throws: memory only, no crash", () => {
    const boom = () => {
      throw new Error("denied");
    };
    const broken = { getItem: boom, setItem: boom, removeItem: boom };
    assert.equal(cc.readStoredCampaignId("t1", broken), null);
    cc.writeStoredCampaignId("t1", "b", broken);
    assert.equal(cc.readStoredCampaignId("t1", broken), "b");
    assert.equal(cc.readUserId(broken), null);
  });

  test("no user id: memory only, never written to storage", () => {
    cc.writeStoredCampaignId(null, "a", local);
    assert.equal(cc.readStoredCampaignId(null, local), "a");
    assert.equal(local.getItem("lk-current-campaign:null"), null);
    cc.writeStoredCampaignId(null, null, local);
  });

  test("readUserId from lk_user", () => {
    assert.equal(cc.readUserId(local), null);
    local.setItem("lk_user", JSON.stringify({ id: "u2", display_name: "Two" }));
    assert.equal(cc.readUserId(local), "u2");
    local.setItem("lk_user", "{not json");
    assert.equal(cc.readUserId(local), null);
  });
});

describe("per-user storage: memory wins in this page load", () => {
  test("setItem throws but getItem returns an older id -> the new id", () => {
    const stale = {
      getItem: (k) => (k === "lk-current-campaign:m1" ? "old" : null),
      setItem: () => {
        throw new Error("quota");
      },
      removeItem: () => {},
    };
    assert.equal(cc.readStoredCampaignId("m1", stale), "old", "nothing set yet: storage");
    cc.writeStoredCampaignId("m1", "new", stale);
    assert.equal(cc.readStoredCampaignId("m1", stale), "new");
  });

  test("a key written elsewhere (earlier page load) is read from storage", () => {
    local.setItem(cc.currentCampaignKey("m2"), "z");
    assert.equal(cc.readStoredCampaignId("m2", local), "z");
  });
});

describe("settleResolution / applyPick (provider side effects)", () => {
  // Real toast store and real preview store; a fake storage per test.
  const toastTexts = () => getToastState().toasts.map((t) => t.text);
  const clearToasts = () => {
    for (const t of getToastState().toasts) dismissToast(t.id);
  };
  const previewHandle = () => ({
    active: store.isPreviewActive(),
    campaignId: store.getPreviewCampaignId(),
    exit: () => store.setPreviewCampaignId(null),
  });
  const settle = (over) => {
    const storage = over.storage;
    return cc.settleResolution({ userId: over.userId, storedId: over.storedId, resolution: over.resolution, toastedFor: over.toastedFor ?? { current: null }, preview: previewHandle(), storage });
  };

  beforeEach(clearToasts);
  afterEach(clearToasts);

  test("(a) first-load fallback id persisted, no toast", () => {
    const storage = new FakeStorage();
    const resolution = resolveWith({});
    assert.equal(settle({ userId: "e1", storedId: null, resolution, storage }), true);
    assert.equal(storage.getItem("lk-current-campaign:e1"), "a");
    assert.deepEqual(toastTexts(), []);
    assert.equal(settle({ userId: "e1", storedId: "a", resolution, storage }), false, "already settled");
  });

  test("(b) lost id: exactly one toast, none on a repeat", () => {
    const storage = new FakeStorage();
    const toastedFor = { current: null };
    const resolution = resolveWith({ storedId: "x" });
    settle({ userId: "e2", storedId: "x", resolution, storage, toastedFor });
    assert.equal(storage.getItem("lk-current-campaign:e2"), "a");
    assert.deepEqual(toastTexts(), ["You no longer have access to that campaign. Switched to Ashfall."]);
    // StrictMode rerun / repeat with the same lost id.
    settle({ userId: "e2", storedId: "x", resolution, storage, toastedFor });
    assert.equal(toastTexts().length, 1);
  });

  test("(c) empty list clears storage", () => {
    const storage = new FakeStorage();
    storage.setItem("lk-current-campaign:e3", "x");
    settle({ userId: "e3", storedId: "x", resolution: resolveWith({ campaigns: [], storedId: "x" }), storage });
    assert.equal(storage.getItem("lk-current-campaign:e3"), null);
    assert.deepEqual(toastTexts(), []);
  });

  test("lost access or none left exits a preview of the lost campaign", () => {
    store.setPreviewCampaignId("x");
    settle({ userId: "e4", storedId: "x", resolution: resolveWith({ storedId: "x" }), storage: new FakeStorage() });
    assert.equal(store.isPreviewActive(), false);
    store.setPreviewCampaignId("x");
    settle({ userId: "e5", storedId: "x", resolution: resolveWith({ campaigns: [], storedId: "x" }), storage: new FakeStorage() });
    assert.equal(store.isPreviewActive(), false);
  });

  test("(d) a pick writes the key; (e) exits a preview of another campaign only", () => {
    const storage = new FakeStorage();
    cc.applyPick({ userId: "e6", campaign: B, preview: previewHandle(), storage });
    assert.equal(storage.getItem("lk-current-campaign:e6"), "b");

    store.setPreviewCampaignId("a");
    cc.applyPick({ userId: "e6", campaign: A, preview: previewHandle(), storage });
    assert.equal(store.getPreviewCampaignId(), "a", "same campaign: preview kept");
    cc.applyPick({ userId: "e6", campaign: B, preview: previewHandle(), storage });
    assert.equal(store.isPreviewActive(), false, "another campaign: preview exited");
    assert.equal(storage.getItem("lk-current-campaign:e6"), "b");
  });
});

describe("roles", () => {
  test("stub: is_owner -> gm, else player", () => {
    assert.equal(role.stubRole({ is_owner: true }), "gm");
    assert.equal(role.stubRole({ is_owner: false }), "player");
    assert.equal(role.stubRole(null), "player");
    assert.deepEqual(role.roleStateFor(A), { role: "gm", isOwner: true, isGm: true, isLoading: false });
    assert.deepEqual(role.roleStateFor(B), { role: "player", isOwner: false, isGm: false, isLoading: false });
  });

  test("/me adapter: Co-GM, GM, anything else -> player", () => {
    assert.equal(role.roleFromMe({ role: "gm", display_role: "Co-GM" }), "co_gm");
    assert.equal(role.roleFromMe({ role: "gm" }), "gm");
    assert.equal(role.roleFromMe({ role: "gm", display_role: "GM" }), "gm");
    for (const other of [{ role: "player" }, { role: "admin" }, { role: "GM" }, {}, null, "gm", 7]) {
      assert.equal(role.roleFromMe(other), "player", JSON.stringify(other));
    }
  });

  test("preview forces player", () => {
    const gm = role.roleStateFor(A);
    assert.deepEqual(role.effectiveRoleState(gm, false), { ...gm, previewing: false });
    const forced = role.effectiveRoleState(gm, true);
    assert.equal(forced.role, "player");
    assert.equal(forced.isGm, false);
    assert.equal(forced.isOwner, false, "owner controls hide in preview");
    assert.equal(forced.previewing, true);
  });
});

describe("switcher menu layout", () => {
  test("GM, not previewing: Preview item after the campaigns, focus on checked", () => {
    const m = switcherMenu({ campaigns: [A, B], currentId: "b", realRoleIsGm: true, previewActive: false });
    assert.deepEqual(m, { canPreview: true, previewIndex: 2, createIndex: 3, itemCount: 4, initialIndex: 1 });
  });

  test("Player or previewing: no Preview item", () => {
    for (const over of [{ realRoleIsGm: false }, { previewActive: true }, { currentId: null }]) {
      const m = switcherMenu({ campaigns: [A, B], currentId: "a", realRoleIsGm: true, previewActive: false, ...over });
      assert.equal(m.canPreview, false);
      assert.equal(m.previewIndex, -1);
      assert.equal(m.createIndex, 2);
    }
  });

  test("no campaigns: only Create", () => {
    const m = switcherMenu({ campaigns: [], currentId: null, realRoleIsGm: false, previewActive: false });
    assert.deepEqual(m, { canPreview: false, previewIndex: -1, createIndex: 0, itemCount: 1, initialIndex: 0 });
    assert.equal(CREATE_CAMPAIGN_HREF, "/dashboard?new=1");
  });
});

// Server render inside the real provider, with the campaigns query seeded.
function renderShell(child, { campaigns = [A, B], userId = "u1", stored, loggedIn = true } = {}) {
  if (loggedIn) {
    local.setItem("lk_token", "t");
    local.setItem("lk_user", JSON.stringify({ id: userId, display_name: "U" }));
  }
  if (stored !== undefined) local.setItem(cc.currentCampaignKey(userId), stored);
  const client = new QueryClient();
  if (campaigns) client.setQueryData(["campaigns"], campaigns);
  client.setQueryData(["me"], { display_name: "U", email: "u@example.com", is_admin: false });
  return renderToStaticMarkup(
    h(
      QueryClientProvider,
      { client },
      h(MemoryRouter, null, h(cc.CurrentCampaignProvider, null, child)),
    ),
  );
}

describe("CampaignSwitcher (server render)", () => {
  test("first load: first campaign with its role, 44px menu button", () => {
    const html = renderShell(h(CampaignSwitcher));
    assert.match(html, /<button[^>]*aria-haspopup="menu"/);
    assert.match(html, /aria-expanded="false"/);
    assert.match(html, /min-h-11/);
    assert.equal(text(html), "Current campaign: Ashfall , role GM");
    assert.match(html, /<svg[^>]*aria-hidden="true"/);
    assert.doesNotMatch(html, /role="menu"/);
  });

  test("stored valid: shows it; shared campaign shows Player", () => {
    assert.equal(text(renderShell(h(CampaignSwitcher), { stored: "b" })), "Current campaign: Brinewood , role Player");
  });

  test("per user: u2 reads only its own key", () => {
    local.setItem(cc.currentCampaignKey("u1"), "b");
    assert.match(text(renderShell(h(CampaignSwitcher), { userId: "u2" })), /Ashfall/);
  });

  test("lost access renders the fallback", () => {
    assert.match(text(renderShell(h(CampaignSwitcher), { stored: "x" })), /Ashfall/);
  });

  test("none left: 'No campaign'", () => {
    assert.equal(text(renderShell(h(CampaignSwitcher), { campaigns: [] })), "Current campaign: No campaign");
  });

  test("list loading: neutral label, no fallback", () => {
    assert.equal(text(renderShell(h(CampaignSwitcher), { campaigns: null, stored: "b" })), "Current campaign: Campaign");
  });

  test("preview active: trigger badge reads Player", () => {
    store.setPreviewCampaignId("a");
    try {
      assert.equal(text(renderShell(h(CampaignSwitcher))), "Current campaign: Ashfall , role Player");
    } finally {
      store.setPreviewCampaignId(null);
    }
  });

  test("no toast during render", () => {
    renderShell(h(CampaignSwitcher), { stored: "x" });
    assert.equal(getToastState().toasts.length, 0);
  });
});

describe("usePageCampaign / useEffectiveRole", () => {
  test("page view follows the global campaign; accept narrows it", () => {
    let seen;
    const Probe = ({ accept }) => {
      const [selected] = cc.usePageCampaign(accept);
      seen = selected;
      return null;
    };
    renderShell(h(Probe), { stored: "b" });
    assert.equal(seen?.id, "b");
    renderShell(h(Probe, { accept: (c) => c.is_owner }), { stored: "b" });
    assert.equal(seen, null, "an owner-only page shows nothing for a shared campaign");
  });

  test("useEffectiveRole: current or by id, forced to player in preview", () => {
    let seen;
    const Probe = ({ id }) => {
      seen = role.useEffectiveRole(id);
      return null;
    };
    renderShell(h(Probe));
    assert.equal(seen.role, "gm");
    renderShell(h(Probe, { id: "b" }));
    assert.equal(seen.role, "player");
    store.setPreviewCampaignId("a");
    try {
      renderShell(h(Probe));
      assert.equal(seen.role, "player");
      assert.equal(seen.previewing, true);
    } finally {
      store.setPreviewCampaignId(null);
    }
  });

  test("useCurrentCampaign outside the provider throws", () => {
    const Probe = () => {
      cc.useCurrentCampaign();
      return null;
    };
    assert.throws(() => renderToStaticMarkup(h(Probe)), /CurrentCampaignProvider/);
  });
});

describe("NavBar", () => {
  test("switcher sits between the menu and the avatar; every control is 44px", () => {
    const html = renderShell(h(NavBar));
    const menu = html.indexOf('aria-label="Menu');
    const switcher = html.indexOf('aria-haspopup="menu"');
    const avatar = html.indexOf('aria-label="Profile"');
    assert.ok(menu >= 0 && switcher > menu && avatar > switcher, "order: menu, switcher, avatar");
    const buttons = [...html.matchAll(/<button[^>]*>/g)].map((m) => m[0]);
    assert.ok(buttons.length >= 3, "menu, switcher, avatar (more may follow, e.g. JobTrayButton)");
    for (const b of buttons) assert.match(b, /min-h-11/, b);
    const links = [...html.matchAll(/<a [^>]*>/g)].map((m) => m[0]);
    assert.ok(links.length >= 1, "wordmark link rendered");
    for (const a of links) assert.match(a, /min-h-11/, a);
    // Icon-only menu label and tighter gap below sm.
    assert.match(html, /gap-2 sm:gap-3/);
    assert.match(html, /<span class="hidden sm:inline max-w-\[10rem\] truncate">/);
  });
});

describe("CampaignSelector defaults", () => {
  test("selected defaults to the global campaign; tab starts on its side", () => {
    const html = renderShell(h(CampaignSelector, { campaigns: [A, B] }), { stored: "b" });
    // The shared tab is active and lists the selected campaign highlighted.
    assert.match(html, /bg-background text-foreground shadow-sm[^"]*">Shared With Me/);
    assert.match(html, /border-primary\/50 bg-primary\/5[\s\S]*Brinewood/);
    assert.match(text(html), /Export this campaign/);
  });

  test("an explicit selected prop still wins", () => {
    const html = renderShell(h(CampaignSelector, { campaigns: [A, B], selected: null, onSelect: () => {} }), {
      stored: "b",
    });
    assert.doesNotMatch(text(html), /Export this campaign/);
  });
});
