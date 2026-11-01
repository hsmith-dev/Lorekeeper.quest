#!/usr/bin/env node
// Checks the E0-UX.6 spoiler-safety primitives and the preview shell against
// the story's I/O matrix: VisibilityBadge, SecretField, FieldVisibilityHint,
// RoleBadge, the tab-scoped preview store (lib/preview.ts), useWriteGuard /
// <Button write>, PreviewBanner and the X-Lorekeeper-Preview request header.
// Static markup via renderToStaticMarkup plus direct store calls; keyboard and
// focus behaviour is covered by the manual Playwright harness.
// No test runner and no new dependency: node:test + node:assert, the .tsx
// files bundled by the esbuild that Vite already installs, and lib/preview.ts
// imported directly (Node >= 22.18 type stripping) to simulate reloads.
//
//   node scripts/check-spoiler-safety.mjs

import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, rmSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { afterEach, beforeEach, describe, test } from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";

import { build } from "esbuild";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createElement as h } from "react";
import { renderToStaticMarkup } from "react-dom/server";

const frontendDir = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const srcDir = join(frontendDir, "src");

// Minimal Web Storage fakes. sessionStorage holds the preview state;
// localStorage is read by the axios auth interceptor.
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
let session = new FakeStorage();
Object.defineProperty(globalThis, "sessionStorage", { configurable: true, get: () => session });
globalThis.localStorage = new FakeStorage();

// The bundle lives under node_modules/.cache so its external imports resolve
// to the same copies this script uses. `splitting` keeps one shared copy of
// lib/preview.ts across all entry points.
const cacheDir = join(frontendDir, "node_modules", ".cache");
mkdirSync(cacheDir, { recursive: true });
const outDir = mkdtempSync(join(cacheDir, "check-spoiler-safety-"));
process.on("exit", () => rmSync(outDir, { recursive: true, force: true }));

await build({
  entryPoints: {
    "visibility-badge": join(srcDir, "components/ui/visibility-badge.tsx"),
    "secret-field": join(srcDir, "components/ui/secret-field.tsx"),
    "field-visibility-hint": join(srcDir, "components/ui/field-visibility-hint.tsx"),
    "role-badge": join(srcDir, "components/ui/role-badge.tsx"),
    button: join(srcDir, "components/ui/button.tsx"),
    "preview-context": join(srcDir, "contexts/PreviewContext.tsx"),
    "preview-banner": join(srcDir, "components/shell/PreviewBanner.tsx"),
    preview: join(srcDir, "lib/preview.ts"),
    layers: join(srcDir, "lib/layers.ts"),
    api: join(srcDir, "services/api.ts"),
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
const { VisibilityBadge, visibilityChoice, visibilityOptions } = await load("visibility-badge");
const { SecretField } = await load("secret-field");
const { FieldVisibilityHint } = await load("field-visibility-hint");
const { RoleBadge } = await load("role-badge");
const { Button } = await load("button");
const { usePreview, useWriteGuard, PREVIEW_READ_ONLY_TITLE } = await load("preview-context");
const { PreviewBanner } = await load("preview-banner");
const store = await load("preview");
const { layerCount } = await load("layers");
const { default: api } = await load("api");

const render = (el) => renderToStaticMarkup(el);
const decode = (s) =>
  s
    .replace(/&#x27;|&#39;/g, "'")
    .replace(/&quot;/g, '"')
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&amp;/g, "&");
const text = (html) => decode(html.replace(/<[^>]+>/g, "")).replace(/\s+/g, " ").trim();
const svgClass = (html) => [...html.matchAll(/<svg[^>]*class="([^"]*)"/g)].map((m) => m[1]).join(" ");

function withPreview(fn) {
  store.setPreviewCampaignId("c1");
  try {
    return fn();
  } finally {
    store.setPreviewCampaignId(null);
  }
}

beforeEach(() => {
  store.setPreviewCampaignId(null);
  session.clear();
});

describe("VisibilityBadge", () => {
  test("GM read-only: Lock + 'GM only' in the gm wash", () => {
    const html = render(h(VisibilityBadge, { value: "gm" }));
    assert.equal(text(html), "GM only");
    assert.match(svgClass(html), /lucide-lock/);
    assert.match(html, /<svg[^>]*aria-hidden="true"/);
    assert.match(html, /bg-gm\/14/);
    assert.match(html, /text-gm/);
    assert.doesNotMatch(html, /<button/, "read-only is not a button");
  });

  test("Party and Private looks", () => {
    const party = render(h(VisibilityBadge, { value: "party" }));
    assert.equal(text(party), "Party");
    assert.match(svgClass(party), /lucide-eye/);
    assert.match(party, /border-border/);
    const priv = render(h(VisibilityBadge, { value: "private" }));
    assert.equal(text(priv), "Private");
    assert.match(svgClass(priv), /lucide-user-round/);
    assert.match(priv, /bg-info\/14/);
  });

  test("editable: a menu button with a chevron, menu closed", () => {
    const html = render(h(VisibilityBadge, { value: "gm", editable: true, onChange: () => {} }));
    assert.match(html, /<button[^>]*aria-haspopup="menu"/);
    assert.match(html, /aria-expanded="false"/);
    assert.match(html, /aria-label="Visibility: GM only"/);
    assert.match(svgClass(html), /lucide-chevron-down/);
    assert.doesNotMatch(html, /role="menu"/);
    assert.doesNotMatch(html, /Make visible/);
  });

  test("visibilityChoice: only widening to Party asks first", () => {
    assert.equal(visibilityChoice("gm", "party"), "confirm");
    assert.equal(visibilityChoice("private", "party"), "confirm");
    assert.equal(visibilityChoice("party", "gm"), "apply");
    assert.equal(visibilityChoice("gm", "private"), "apply");
    for (const v of ["party", "gm", "private"]) assert.equal(visibilityChoice(v, v), "noop");
  });

  test("editable without onChange renders the plain pill", () => {
    const html = render(h(VisibilityBadge, { value: "gm", editable: true }));
    assert.doesNotMatch(html, /aria-haspopup/);
    assert.doesNotMatch(html, /<button/);
    assert.equal(text(html), "GM only");
  });

  test("menu options: Private only when allowed or current", () => {
    assert.deepEqual(visibilityOptions("gm", false), ["party", "gm"]);
    assert.deepEqual(visibilityOptions("party", false), ["party", "gm"]);
    assert.deepEqual(visibilityOptions("gm", true), ["party", "gm", "private"]);
    assert.deepEqual(visibilityOptions("private", false), ["party", "gm", "private"]);
  });

  test("Player audience renders nothing", () => {
    assert.equal(render(h(VisibilityBadge, { value: "gm", audience: "player" })), "");
    assert.equal(render(h(VisibilityBadge, { value: "party", audience: "player", editable: true })), "");
  });

  test("Player's own journal: Shared or Private", () => {
    const own = (props) => render(h(VisibilityBadge, { audience: "player", ownJournal: true, ...props }));
    const shared = own({ value: "private", shared: true });
    assert.equal(text(shared), "Shared");
    assert.match(svgClass(shared), /lucide-eye/);
    assert.equal(text(own({ value: "party" })), "Shared");
    const priv = own({ value: "private" });
    assert.equal(text(priv), "Private");
    assert.match(svgClass(priv), /lucide-user-round/);
    assert.match(priv, /bg-info\/14/);
    assert.doesNotMatch(priv, /<button/);
  });

  test("GM view ignores `shared`", () => {
    assert.equal(text(render(h(VisibilityBadge, { value: "private", shared: true }))), "Private");
  });

  test("preview forces the Player rendering", () => {
    withPreview(() => {
      assert.equal(render(h(VisibilityBadge, { value: "gm", editable: true })), "");
      assert.equal(text(render(h(VisibilityBadge, { value: "private", ownJournal: true }))), "Private");
    });
  });
});

describe("SecretField", () => {
  const field = (props = {}) =>
    render(h(SecretField, { label: "GM notes", htmlFor: "notes", ...props }, h("textarea", { id: "notes" })));

  test("GM: dashed gm border, 6% wash, lock label, name starts 'GM only'", () => {
    const html = field();
    assert.match(html, /border-dashed/);
    assert.match(html, /border-gm\/50/);
    assert.match(html, /bg-gm\/6/);
    assert.match(svgClass(html), /lucide-lock/);
    assert.match(html, /<svg[^>]*aria-hidden="true"/);
    // Visible label row: "GM notes · GM only" (sr-only prefix stripped).
    const visible = text(html.replace(/<span class="sr-only">[^<]*<\/span>/g, ""));
    assert.equal(visible, "GM notes · GM only");
    // Accessible name: the label's text without aria-hidden parts.
    const labelId = /role="group" aria-labelledby="([^"]+)"/.exec(html)[1];
    const label = new RegExp(`<label id="${labelId}" for="notes">(.*?)</label>`).exec(html)[1];
    const name = text(label.replace(/<span aria-hidden="true"[^>]*>.*?<\/span>/g, ""));
    assert.match(name, /^GM only/);
    assert.match(name, /GM notes/);
  });

  test("hidden for Players and in preview", () => {
    assert.equal(field({ audience: "player" }), "");
    withPreview(() => assert.equal(field(), ""));
  });
});

describe("FieldVisibilityHint", () => {
  const hint = (props = {}) =>
    render(h(FieldVisibilityHint, props, h("input", { id: "name", "aria-describedby": "extra" })));

  test("GM: hint wired by aria-describedby, hidden until focus", () => {
    const html = hint();
    const hintId = /<p id="([^"]+)" hidden=""/.exec(html)?.[1];
    assert.ok(hintId, "hint rendered with the hidden attribute");
    assert.match(html, new RegExp(`aria-describedby="extra ${hintId}"`), "keeps the field's own description");
    assert.match(text(html), /^Visible to players$/);
    assert.match(svgClass(html), /lucide-eye/);
  });

  test("Player and preview: children only", () => {
    const only = '<input id="name" aria-describedby="extra"/>';
    assert.equal(hint({ audience: "player" }), only);
    withPreview(() => assert.equal(hint(), only));
  });
});

describe("RoleBadge", () => {
  test("muted pills", () => {
    for (const [role, label] of [
      ["gm", "GM"],
      ["co_gm", "Co-GM"],
      ["player", "Player"],
    ]) {
      const html = render(h(RoleBadge, { role }));
      assert.equal(text(html), label);
      assert.match(html, /bg-muted/);
      assert.match(html, /rounded-full/);
    }
  });
});

describe("preview store", () => {
  // Each import with a fresh query string is a new module instance, which is
  // how a page reload looks to the store.
  let n = 0;
  const reload = () => import(`../src/lib/preview.ts?reload=${++n}`);

  afterEach(() => {
    session = new FakeStorage();
  });

  test("enter, then reload keeps the campaign; exit clears", async () => {
    const tab = await reload();
    let calls = 0;
    const off = tab.subscribePreview(() => calls++);
    tab.setPreviewCampaignId("c1");
    assert.equal(tab.isPreviewActive(), true);
    assert.equal(tab.getPreviewCampaignId(), "c1");
    assert.equal(calls, 1);
    tab.setPreviewCampaignId("c1");
    assert.equal(calls, 1, "no notification without a change");

    const reloaded = await reload();
    assert.equal(reloaded.getPreviewCampaignId(), "c1", "survives a reload of the tab");

    reloaded.setPreviewCampaignId(null);
    assert.equal(reloaded.isPreviewActive(), false);
    assert.equal(session.getItem(tab.PREVIEW_STORAGE_KEY), null);
    assert.equal((await reload()).getPreviewCampaignId(), null);
    off();
  });

  test("a new tab (empty sessionStorage) starts without preview", async () => {
    (await reload()).setPreviewCampaignId("c1");
    session = new FakeStorage();
    assert.equal((await reload()).getPreviewCampaignId(), null);
  });

  test("junk in storage is ignored", async () => {
    session.setItem("lk-preview", "{not json");
    assert.equal((await reload()).getPreviewCampaignId(), null);
    session.setItem("lk-preview", JSON.stringify({ campaignId: 7 }));
    assert.equal((await reload()).getPreviewCampaignId(), null);
  });

  test("storage that throws: in memory only, no crash", async () => {
    const boom = () => {
      throw new Error("denied");
    };
    session = { getItem: boom, setItem: boom, removeItem: boom };
    const tab = await reload();
    assert.equal(tab.getPreviewCampaignId(), null);
    tab.setPreviewCampaignId("c1");
    assert.equal(tab.getPreviewCampaignId(), "c1");
    assert.deepEqual(tab.previewHeaders(), { "X-Lorekeeper-Preview": "member" });
    tab.setPreviewCampaignId(null);
    assert.equal(tab.isPreviewActive(), false);

    // The sessionStorage getter itself throwing (blocked site data).
    Object.defineProperty(globalThis, "sessionStorage", { configurable: true, get: boom });
    try {
      const blocked = await reload();
      blocked.setPreviewCampaignId("c2");
      assert.equal(blocked.getPreviewCampaignId(), "c2");
    } finally {
      Object.defineProperty(globalThis, "sessionStorage", { configurable: true, get: () => session });
    }
  });

  test("usePreview reflects the store; enter/exit reset the query cache", () => {
    let api;
    const Probe = () => {
      api = usePreview();
      return h("span", null, api.active ? `on:${api.campaignId}` : "off");
    };
    const client = new QueryClient();
    client.setQueryData(["secret"], "GM-only data");
    const wrap = () => render(h(QueryClientProvider, { client }, h(Probe)));
    assert.equal(text(wrap()), "off");
    api.enter("c1");
    assert.equal(store.getPreviewCampaignId(), "c1");
    assert.equal(client.getQueryData(["secret"]), undefined, "cached GM data dropped on enter");
    assert.equal(text(wrap()), "on:c1");
    client.setQueryData(["secret"], "member data");
    api.exit();
    assert.equal(store.getPreviewCampaignId(), null);
    assert.equal(client.getQueryData(["secret"]), undefined, "cache dropped on exit");
    // Without a QueryClientProvider the hook still works.
    render(h(Probe));
    api.enter("c2");
    assert.equal(store.getPreviewCampaignId(), "c2");
    api.exit();
    client.clear();
  });
});

describe("write guard", () => {
  test("useWriteGuard and <Button write>", () => {
    let guard;
    const Probe = () => {
      guard = useWriteGuard();
      return null;
    };
    render(h(Probe));
    assert.deepEqual(guard, { disabled: false });
    const idle = render(h(Button, { write: true, title: "Save entry" }, "Save"));
    assert.doesNotMatch(idle, / disabled=""/);
    assert.match(idle, /title="Save entry"/);

    withPreview(() => {
      render(h(Probe));
      assert.deepEqual(guard, { disabled: true, title: "Preview is read-only" });
      assert.equal(PREVIEW_READ_ONLY_TITLE, "Preview is read-only");
      const html = render(h(Button, { write: true, title: "Save entry" }, "Save"));
      assert.match(html, /<button[^>]*disabled=""/);
      assert.match(html, /title="Preview is read-only"/);
      // A Button without `write` is unchanged.
      const plain = render(h(Button, null, "Close"));
      assert.doesNotMatch(plain, / disabled=""| title=/);
    });
  });
});

describe("PreviewBanner", () => {
  test("hidden when inactive", () => {
    assert.equal(render(h(PreviewBanner)), "");
  });

  test("active: topmost info band with the AC copy and Exit preview", () => {
    withPreview(() => {
      const before = layerCount();
      const html = render(h(PreviewBanner));
      assert.match(html, /sticky top-0 z-\[60\]/);
      assert.match(html, /h-10/);
      assert.match(html, /bg-info/);
      assert.match(html, /text-background/);
      assert.doesNotMatch(html, /text-card|border-card/);
      assert.equal(
        text(html.replace(/<button[\s\S]*<\/button>/, "")),
        "Viewing as Player · You're seeing exactly what players see.",
      );
      assert.match(html, /<button[^>]*>Exit preview<\/button>/);
      assert.match(html, /<svg[^>]*aria-hidden="true"/);
      assert.equal(layerCount(), before, "the banner registers no Esc layer");
    });
  });
});

describe("X-Lorekeeper-Preview header", () => {
  async function sentHeaders() {
    let seen;
    await api.get("/api/ping", {
      adapter: async (config) => {
        seen = config.headers;
        return { data: null, status: 200, statusText: "OK", headers: {}, config };
      },
    });
    return seen;
  }

  test("sent only while preview is active", async () => {
    assert.equal((await sentHeaders()).get("X-Lorekeeper-Preview"), undefined);
    store.setPreviewCampaignId("c1");
    try {
      assert.equal((await sentHeaders()).get("X-Lorekeeper-Preview"), "member");
    } finally {
      store.setPreviewCampaignId(null);
    }
    assert.equal((await sentHeaders()).get("X-Lorekeeper-Preview"), undefined);
  });
});
