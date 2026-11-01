#!/usr/bin/env node
// Checks the E0-UX.9 keyboard shortcut registry (lib/shortcuts.ts) and the help
// list (components/shell/ShortcutHelp.tsx) against the story's I/O matrix:
// every matrix row through dispatchShortcut with fake events and elements,
// the real layer stack (pushLayer), the real preview store and toast state;
// parseShortcut refusals and labels; grouping and order; the register/remove
// lifecycle; the single-key switch in localStorage; suspension while the help
// is open; an SSR check that useShortcut throws on a reserved key during
// render; and an SSR of ShortcutList.
// Node has no DOM, so useShortcut's effect, focus return and the pushed-level
// behaviour are covered by the manual Playwright harness.
// No test runner and no new dependency: node:test + node:assert and the
// esbuild that Vite already installs (same harness as check-routes).
//
//   node scripts/check-shortcuts.mjs

import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, rmSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { afterEach, beforeEach, describe, test } from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";

import { build } from "esbuild";
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
const outDir = mkdtempSync(join(cacheDir, "check-shortcuts-"));
process.on("exit", () => rmSync(outDir, { recursive: true, force: true }));

await build({
  entryPoints: {
    shortcuts: join(srcDir, "lib/shortcuts.ts"),
    help: join(srcDir, "components/shell/ShortcutHelp.tsx"),
    layers: join(srcDir, "lib/layers.ts"),
    registry: join(srcDir, "lib/slideOverRegistry.ts"),
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
  define: { "import.meta.env.VITE_API_URL": "undefined", "import.meta.env.DEV": "false" },
  logLevel: "error",
});

const load = (name) => import(pathToFileURL(join(outDir, `${name}.mjs`)).href);
const S = await load("shortcuts");
const { ShortcutList, ShortcutHelp, SHORTCUT_HELP_TITLE, pushHelpIntoActiveSlideOver } = await load("help");
const { activateSlideOver, deactivateSlideOver } = await load("registry");
const { pushLayer, layerCount } = await load("layers");
const store = await load("preview");
const T = await load("toast");

const decode = (s) =>
  s
    .replace(/&#x27;|&#39;/g, "'")
    .replace(/&quot;/g, '"')
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&amp;/g, "&");
const text = (html) => decode(html.replace(/<[^>]+>/g, " ")).replace(/\s+/g, " ").trim();

// ---------------------------------------------------------------------------
// Fakes

/** A minimal element: tag, attributes, parent, contenteditable. */
function el(tagName, attrs = {}, parent = null) {
  return {
    tagName: tagName.toUpperCase(),
    parentElement: parent,
    isContentEditable: false,
    getAttribute: (n) => (n in attrs ? String(attrs[n]) : null),
    hasAttribute: (n) => n in attrs,
  };
}
const body = el("body");
const main = el("main", { tabindex: "-1" }, body);
const div = el("div", {}, main);

function key(k, init = {}) {
  return {
    key: k,
    shiftKey: false,
    ctrlKey: false,
    metaKey: false,
    altKey: false,
    repeat: false,
    isComposing: false,
    keyCode: 0,
    defaultPrevented: false,
    preventDefault() {
      this.defaultPrevented = true;
    },
    ...init,
  };
}

const MOD_IS_META = S.parseShortcut("Mod+Enter").label[0] === "⌘";
const modEnter = (init = {}) => key("Enter", MOD_IS_META ? { metaKey: true, ...init } : { ctrlKey: true, ...init });

const removers = [];
/** Register through the registry; counts handler calls. Removed after each test. */
function reg(k, opts = {}) {
  const calls = [];
  const remove = S.registerShortcut({
    key: k,
    scope: opts.scope ?? "page",
    description: opts.description ?? `do ${k}`,
    ...opts,
    handler: (e) => calls.push(e),
  });
  removers.push(remove);
  return { calls, remove };
}

const fire = (event, active = div) => S.dispatchShortcut(event, active);

beforeEach(() => {
  local.clear();
  S.resetShortcutSettingsCache();
  store.setPreviewCampaignId(null);
});
afterEach(() => {
  while (removers.length) removers.pop()();
  for (const t of T.getToastState().toasts) T.dismissToast(t.id);
  assert.equal(layerCount(), 0, "a test leaked a layer");
});

// ---------------------------------------------------------------------------

describe("parseShortcut", () => {
  test("allowed keys and their labels", () => {
    assert.deepEqual(S.parseShortcut("?"), { key: "?", shift: false, mod: false, single: true, label: ["?"] });
    assert.deepEqual(S.parseShortcut("j"), { key: "j", shift: false, mod: false, single: true, label: ["J"] });
    assert.deepEqual(S.parseShortcut("Shift+A"), { key: "a", shift: true, mod: false, single: true, label: ["Shift", "A"] });
    assert.equal(S.parseShortcut("/").key, "/");
    assert.equal(S.parseShortcut("+").key, "+");
    assert.deepEqual(S.parseShortcut("Space"), { key: " ", shift: false, mod: false, single: true, label: ["Space"] });
    assert.deepEqual(S.parseShortcut(" "), { key: " ", shift: false, mod: false, single: true, label: ["Space"] });
    const me = S.parseShortcut("Mod+Enter");
    assert.equal(me.key, "Enter");
    assert.equal(me.mod, true);
    assert.equal(me.single, false);
    assert.ok(me.label[0] === "⌘" || me.label[0] === "Ctrl");
    assert.equal(me.label[1], "Enter");
  });

  test("reserved keys throw, naming the key", () => {
    const reserved = [
      "Escape",
      "Esc",
      "Tab",
      "ArrowUp",
      "ArrowDown",
      "ArrowLeft",
      "ArrowRight",
      "Home",
      "End",
      "PageUp",
      "PageDown",
      "F1",
      "F5",
      "F12",
      "Backspace",
      "Delete",
      "Enter",
      "Shift+Enter",
      "Alt+x",
      "Alt+j",
      "Mod+L",
      "Mod+k",
      "Mod+Shift+Enter",
      "Ctrl+Enter",
      "Meta+j",
      "Ctrl+s",
      "",
      "Hyper+j",
      "Foo",
      "J",
    ];
    for (const k of reserved) {
      assert.throws(() => S.parseShortcut(k), (err) => err instanceof Error && err.message.includes(`"${k}"`), k);
    }
    assert.throws(() => S.parseShortcut("Escape"), /layer stack/);
  });
});

describe("dispatchShortcut: the I/O matrix", () => {
  test("open help: ? on the page body fires", () => {
    const { calls } = reg("?", { scope: "global", overLayers: true });
    const e = key("?", { shiftKey: true });
    assert.equal(fire(e, body), true);
    assert.equal(calls.length, 1);
    assert.equal(e.defaultPrevented, true, "preventDefault when it fires");
  });

  test("typing: input, textarea, select, contenteditable and textbox roles never fire", () => {
    const { calls } = reg("?", { scope: "global" });
    const editor = el("div", { contenteditable: "true" }, main);
    const targets = [
      el("input", { type: "text" }, main),
      el("textarea", {}, main),
      el("select", {}, main),
      editor,
      el("p", {}, editor),
      { ...el("div", {}, main), isContentEditable: true },
      el("div", { role: "textbox" }, main),
    ];
    for (const t of targets) {
      const e = key("?", { shiftKey: true });
      assert.equal(fire(e, t), false);
      assert.equal(e.defaultPrevented, false, "the character is typed");
    }
    assert.equal(calls.length, 0);
    // contenteditable="false" is not editable.
    assert.equal(fire(key("?"), el("div", { contenteditable: "false" }, main)), true);
  });

  test("IME composition never fires", () => {
    const { calls } = reg("j");
    assert.equal(fire(key("j", { isComposing: true })), false);
    assert.equal(fire(key("j", { keyCode: 229 })), false);
    assert.equal(calls.length, 0);
  });

  test("modifier held: Ctrl+?, Meta+j, Alt+j do not fire a plain shortcut", () => {
    const q = reg("?");
    const j = reg("j");
    assert.equal(fire(key("?", { ctrlKey: true, shiftKey: true })), false);
    assert.equal(fire(key("j", { metaKey: true })), false);
    assert.equal(fire(key("j", { altKey: true })), false);
    assert.equal(fire(key("j", { ctrlKey: true })), false);
    assert.equal(q.calls.length + j.calls.length, 0);
  });

  test("Caps Lock: J without Shift fires j; Shift+A needs Shift", () => {
    const j = reg("j");
    const a = reg("Shift+A");
    assert.equal(fire(key("J")), true);
    assert.equal(j.calls.length, 1);
    assert.equal(fire(key("a")), false, "plain a is not Shift+A");
    assert.equal(fire(key("A", { shiftKey: true })), true);
    assert.equal(a.calls.length, 1);
    assert.equal(fire(key("J", { shiftKey: true })), false, "Shift+J is not j");
  });

  test("Esc is never handled", () => {
    const { calls } = reg("?", { overLayers: true });
    assert.equal(fire(key("Escape")), false);
    assert.equal(fire(key("Esc")), false);
    assert.equal(calls.length, 0);
  });

  test("Space: fires on the page, not with a button (or other control) focused", () => {
    const { calls } = reg("Space");
    assert.equal(fire(key(" "), body), true);
    assert.equal(fire(key(" "), main), true, "main[tabindex=-1] is not a control");
    for (const t of [
      el("button", {}, main),
      el("a", { href: "/x" }, main),
      el("summary", {}, main),
      el("div", { role: "checkbox" }, main),
      el("div", { tabindex: "0" }, main),
    ]) {
      const e = key(" ");
      assert.equal(fire(e, t), false);
      assert.equal(e.defaultPrevented, false, "the control activates");
    }
    assert.equal(calls.length, 2);
  });

  test("other keys still fire with a button focused", () => {
    const { calls } = reg("j");
    assert.equal(fire(key("j"), el("button", {}, main)), true);
    assert.equal(calls.length, 1);
  });

  test("typeahead widgets (menu, menubar, listbox, tree, treegrid, grid) block every shortcut", () => {
    const { calls } = reg("j", { overLayers: true });
    const me = reg("Mod+Enter", { overLayers: true });
    for (const role of ["menu", "menubar", "listbox", "tree", "treegrid", "grid"]) {
      const widget = el("div", { role }, main);
      const item = el("button", { role: "menuitem" }, widget);
      assert.equal(fire(key("j"), item), false, role);
      assert.equal(fire(modEnter(), item), false, role);
      assert.equal(fire(key("j"), widget), false, role);
    }
    assert.equal(calls.length + me.calls.length, 0);
  });

  test("unmounted (removed) shortcuts do not fire and are not listed", () => {
    const { calls, remove } = reg("j");
    assert.equal(S.listShortcuts().length, 1);
    remove();
    remove(); // idempotent
    assert.equal(fire(key("j")), false);
    assert.equal(calls.length, 0);
    assert.equal(S.listShortcuts().length, 0);
  });

  test("duplicate key: the most recently registered fires", () => {
    const first = reg("j");
    const second = reg("j");
    assert.equal(fire(key("j")), true);
    assert.equal(first.calls.length, 0);
    assert.equal(second.calls.length, 1);
    second.remove();
    assert.equal(fire(key("j")), true);
    assert.equal(first.calls.length, 1);
  });

  test("layer above: page j goes quiet under a SlideOver; ? (overLayers) still fires", () => {
    const help = reg("?", { scope: "global", overLayers: true });
    const j = reg("j");
    const removeLayer = pushLayer(() => {});
    try {
      assert.equal(fire(key("j")), false);
      assert.equal(j.calls.length, 0);
      assert.equal(fire(key("?")), true);
      assert.equal(help.calls.length, 1);
      // Registered inside the open layer: sees its own layer and fires.
      const inner = reg("k");
      assert.equal(fire(key("k")), true);
      assert.equal(inner.calls.length, 1);
    } finally {
      removeLayer();
    }
    assert.equal(fire(key("j")), true, "fires again once the layer closes");
    assert.equal(j.calls.length, 1);
  });

  test("preview write: handler not run; toast 'Preview is read-only'", () => {
    const w = reg("e", { write: true });
    const r = reg("r");
    store.setPreviewCampaignId("c1");
    const e = key("e");
    assert.equal(fire(e), true);
    assert.equal(e.defaultPrevented, true);
    assert.equal(w.calls.length, 0);
    const toasts = T.getToastState().toasts;
    assert.equal(toasts.length, 1);
    assert.equal(toasts[0].text, "Preview is read-only");
    assert.equal(fire(key("r")), true, "read-only shortcuts still run in preview");
    assert.equal(r.calls.length, 1);
    store.setPreviewCampaignId(null);
    assert.equal(fire(key("e")), true);
    assert.equal(w.calls.length, 1);
  });

  test("off switch: lk_shortcuts=off stops single keys (? included); Mod+Enter still fires", () => {
    const q = reg("?", { scope: "global", overLayers: true });
    const me = reg("Mod+Enter");
    local.setItem("lk_shortcuts", "off");
    S.resetShortcutSettingsCache();
    assert.equal(S.singleKeyShortcutsEnabled(), false);
    assert.equal(fire(key("?")), false);
    assert.equal(q.calls.length, 0);
    assert.equal(fire(modEnter()), true);
    assert.equal(me.calls.length, 1);
    // Mod+Enter needs exactly Mod.
    assert.equal(fire(modEnter({ shiftKey: true })), false);
    assert.equal(fire(modEnter({ altKey: true })), false);
    assert.equal(fire(key("Enter")), false);
    assert.equal(fire(key("Enter", { ctrlKey: true, metaKey: true })), false);

    S.setSingleKeyShortcutsEnabled(true);
    assert.equal(local.getItem("lk_shortcuts"), null);
    assert.equal(fire(key("?")), true);
    S.setSingleKeyShortcutsEnabled(false);
    assert.equal(local.getItem("lk_shortcuts"), "off");
    S.resetShortcutSettingsCache();
    assert.equal(S.singleKeyShortcutsEnabled(), false, "read back from storage");
  });

  test("Mod+Enter fires from a textarea? no: typing targets block every shortcut", () => {
    const me = reg("Mod+Enter");
    assert.equal(fire(modEnter(), el("textarea", {}, main)), false);
    assert.equal(me.calls.length, 0);
  });

  test("help open: nothing registered before it fires", () => {
    const q = reg("?", { scope: "global", overLayers: true });
    const j = reg("j");
    const resume = S.suspendShortcuts();
    try {
      assert.equal(fire(key("?")), false);
      assert.equal(fire(key("j")), false);
      const inside = reg("x");
      assert.equal(fire(key("x")), true, "registered while open still fires");
      assert.equal(inside.calls.length, 1);
    } finally {
      resume();
      resume(); // idempotent
    }
    assert.equal(fire(key("j")), true);
    assert.equal(q.calls.length, 0);
    assert.equal(j.calls.length, 1);
  });

  test("close help: Esc goes to the layer stack, not to a shortcut", () => {
    reg("?", { overLayers: true });
    let closed = 0;
    const removeLayer = pushLayer(() => closed++);
    try {
      assert.equal(fire(key("Escape")), false);
    } finally {
      removeLayer();
    }
    assert.equal(closed, 0, "dispatchShortcut never runs layer handlers itself");
  });

  test("repeat: held ? is ignored unless allowRepeat", () => {
    const q = reg("?");
    const n = reg("n", { allowRepeat: true });
    assert.equal(fire(key("?", { repeat: true })), false);
    assert.equal(q.calls.length, 0);
    assert.equal(fire(key("n", { repeat: true })), true);
    assert.equal(n.calls.length, 1);
  });

  test("an event already handled (defaultPrevented) is left alone", () => {
    const { calls } = reg("j");
    const e = key("j");
    e.preventDefault();
    assert.equal(fire(e), false);
    assert.equal(calls.length, 0);
  });

  test("matchesShortcut handles '+' and '/'", () => {
    assert.equal(S.matchesShortcut(S.parseShortcut("+"), key("+", { shiftKey: true })), true);
    assert.equal(S.matchesShortcut(S.parseShortcut("/"), key("/")), true);
    assert.equal(S.matchesShortcut(S.parseShortcut("/"), key("?")), false);
  });
});

describe("focus helpers", () => {
  test("isTypingTarget / isInteractiveTarget", () => {
    assert.equal(S.isTypingTarget(null), false);
    assert.equal(S.isTypingTarget(el("input", {}, main)), true);
    assert.equal(S.isTypingTarget(el("button", {}, main)), false);
    assert.equal(S.isInteractiveTarget(el("button", {}, main)), true);
    assert.equal(S.isInteractiveTarget(el("a", {}, main)), false, "a without href");
    assert.equal(S.isInteractiveTarget(el("a", { href: "#" }, main)), true);
    assert.equal(S.isInteractiveTarget(div), false);
    assert.equal(S.isInteractiveTarget(main), false);
  });
});

describe("registry: listing, grouping, lifecycle", () => {
  test("registerShortcut throws on a reserved key and registers nothing", () => {
    assert.throws(() => S.registerShortcut({ key: "Mod+L", scope: "page", description: "x", handler() {} }), /Mod\+L/);
    assert.equal(S.listShortcuts().length, 0);
  });

  test("register/remove bumps the version and notifies subscribers", () => {
    let notified = 0;
    const unsubscribe = S.subscribeShortcuts(() => notified++);
    const v0 = S.getShortcutsVersion();
    const { remove } = reg("j");
    assert.ok(S.getShortcutsVersion() > v0);
    remove();
    assert.equal(notified, 2);
    unsubscribe();
    reg("k");
    assert.equal(notified, 2, "unsubscribed");
  });

  test("groups: Global first, then page (route title), then other scopes in first-registered order", () => {
    reg("n", { scope: "Journal", description: "Next entry" });
    reg("j", { scope: "page", description: "Down" });
    reg("w", { scope: "World", description: "World" });
    reg("?", { scope: "global", description: "Show keyboard shortcuts", overLayers: true });
    reg("p", { scope: "Journal", description: "Previous entry" });
    reg("k", { scope: "page", description: "Up" });
    const groups = S.groupShortcuts(S.listShortcuts(), "History");
    assert.deepEqual(
      groups.map((g) => [g.label, g.items.map((i) => i.description)]),
      [
        ["Global", ["Show keyboard shortcuts"]],
        ["History", ["Down", "Up"]],
        ["Journal", ["Next entry", "Previous entry"]],
        ["World", ["World"]],
      ],
    );
    assert.equal(S.groupShortcuts(S.listShortcuts(), undefined)[1].label, "This page");
    assert.deepEqual(S.groupShortcuts([], "x"), []);
  });

  test("listShortcuts exposes metadata, not handlers", () => {
    reg("e", { write: true, description: "Edit" });
    const [entry] = S.listShortcuts();
    assert.equal(entry.description, "Edit");
    assert.equal(entry.write, true);
    assert.equal("handler" in entry, false);
  });
});

describe("document listener", () => {
  test("one keydown listener on the first register, removed after the last remover", () => {
    const saved = Object.getOwnPropertyDescriptor(globalThis, "document");
    const added = [];
    const removed = [];
    globalThis.document = {
      activeElement: null,
      addEventListener: (type, fn) => added.push([type, fn]),
      removeEventListener: (type, fn) => removed.push([type, fn]),
    };
    try {
      const a = S.registerShortcut({ key: "j", scope: "page", description: "j", handler() {} });
      const b = S.registerShortcut({ key: "k", scope: "page", description: "k", handler() {} });
      assert.equal(added.length, 1);
      assert.equal(added[0][0], "keydown");
      a();
      assert.equal(removed.length, 0, "still registered: k");
      b();
      assert.equal(removed.length, 1);
      assert.equal(removed[0][0], "keydown");
      assert.equal(removed[0][1], added[0][1], "the same listener is removed");
    } finally {
      if (saved) Object.defineProperty(globalThis, "document", saved);
      else delete globalThis.document;
    }
  });
});

describe("help push into the active SlideOver", () => {
  test("pushes a 'Keyboard shortcuts' level when a SlideOver is active, else false", () => {
    assert.equal(pushHelpIntoActiveSlideOver(), false, "no active SlideOver");
    const pushed = [];
    const reg = { name: "Entity", returnTarget: null, supersede() {}, push: (o) => pushed.push(o) };
    activateSlideOver(reg, null);
    try {
      assert.equal(pushHelpIntoActiveSlideOver(), true);
      assert.equal(pushed.length, 1);
      assert.equal(pushed[0].title, "Keyboard shortcuts");
      assert.equal(typeof pushed[0].render, "function");
    } finally {
      deactivateSlideOver(reg);
    }
    assert.equal(pushHelpIntoActiveSlideOver(), false, "deactivated");
  });
});

describe("server renders", () => {
  test("useShortcut throws on a reserved key during render", () => {
    const Probe = ({ k }) => {
      S.useShortcut(k, { scope: "page", description: "x" }, () => {});
      return null;
    };
    for (const k of ["Escape", "Mod+L", "Alt+x", "ArrowDown", "Enter"]) {
      assert.throws(() => renderToStaticMarkup(h(Probe, { k })), (err) => err.message.includes(`"${k}"`), k);
    }
    assert.equal(renderToStaticMarkup(h(Probe, { k: "j" })), "");
    assert.equal(S.listShortcuts().length, 0, "effects do not run on the server");
  });

  test("ShortcutList: switch, sections, dl of kbd keys, preview note", () => {
    const groups = [
      {
        scope: "global",
        label: "Global",
        items: [{ id: 1, key: "?", parsed: S.parseShortcut("?"), scope: "global", description: "Show keyboard shortcuts" }],
      },
      {
        scope: "page",
        label: "History",
        items: [
          { id: 2, key: "Shift+A", parsed: S.parseShortcut("Shift+A"), scope: "page", description: "Archive", write: true },
          { id: 3, key: "j", parsed: S.parseShortcut("j"), scope: "page", description: "Next" },
        ],
      },
    ];
    const html = renderToStaticMarkup(h(ShortcutList, { groups, previewing: true, enabled: true, onToggle() {} }));
    assert.match(html, /<button[^>]*role="switch"[^>]*aria-checked="true"/);
    assert.match(html, /role="switch"[^>]*class="[^"]*min-h-11 min-w-11/);
    assert.match(text(html), /Single-key shortcuts/);
    const sections = [...html.matchAll(/<section aria-labelledby="([^"]+)">\s*<h3 id="([^"]+)"[^>]*>([^<]+)<\/h3>/g)];
    assert.deepEqual(
      sections.map((m) => m[3]),
      ["Global", "History"],
    );
    for (const m of sections) assert.equal(m[1], m[2], "section is labelled by its h3");
    assert.equal((html.match(/<dl/g) ?? []).length, 2);
    assert.match(html, /<dt[^>]*><kbd[^>]*>\?<\/kbd><\/dt><dd[^>]*>Show keyboard shortcuts<\/dd>/);
    assert.match(html, /<kbd[^>]*>Shift<\/kbd><kbd[^>]*>A<\/kbd>/);
    assert.equal((text(html).match(/Not available in preview/g) ?? []).length, 1, "only on the write item");

    const off = renderToStaticMarkup(h(ShortcutList, { groups, previewing: false, enabled: false, onToggle() {} }));
    assert.match(off, /aria-checked="false"/);
    assert.doesNotMatch(off, /Not available in preview/);

    const empty = renderToStaticMarkup(h(ShortcutList, { groups: [], previewing: false, enabled: true, onToggle() {} }));
    assert.match(text(empty), /No keyboard shortcuts/);
  });

  test("ShortcutHelp renders nothing while closed (mounted only when open) and registers nothing on the server", () => {
    const html = renderToStaticMarkup(h(MemoryRouter, null, h(ShortcutHelp)));
    assert.equal(SHORTCUT_HELP_TITLE, "Keyboard shortcuts");
    assert.equal(html, "", "a closed help mounts no SlideOver, so its open frame is never visibility:hidden");
    assert.equal(S.listShortcuts().length, 0);
  });
});
