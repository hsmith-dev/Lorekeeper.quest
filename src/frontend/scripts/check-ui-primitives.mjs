#!/usr/bin/env node
// Checks the E0-UX.5 shared state primitives against the story's I/O matrix:
// the toast store (timers, pause/resume, eviction, announcements, title
// badge), ModelMissingNotice copy and admin link, and lib/format.ts.
// No test runner and no new dependency: node:test + node:assert, with the new
// .tsx files bundled by the esbuild that Vite already installs.
//
//   node scripts/check-ui-primitives.mjs

import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, rmSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { after, describe, mock, test } from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";

import { build } from "esbuild";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";

const frontendDir = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const srcDir = join(frontendDir, "src");

// The bundle lives under node_modules/.cache so its external imports (react,
// react-query, ...) resolve to the same copies this script uses.
const cacheDir = join(frontendDir, "node_modules", ".cache");
mkdirSync(cacheDir, { recursive: true });
const outDir = mkdtempSync(join(cacheDir, "check-ui-primitives-"));
process.on("exit", () => rmSync(outDir, { recursive: true, force: true }));

await build({
  entryPoints: {
    toast: join(srcDir, "components/ui/toast.tsx"),
    "model-missing-notice": join(srcDir, "components/ui/model-missing-notice.tsx"),
    format: join(srcDir, "lib/format.ts"),
    "inline-error": join(srcDir, "components/ui/inline-error.tsx"),
    "empty-state": join(srcDir, "components/ui/empty-state.tsx"),
  },
  outdir: outDir,
  outExtension: { ".js": ".mjs" },
  bundle: true,
  format: "esm",
  platform: "node",
  jsx: "automatic",
  alias: { "@": srcDir },
  // axios too: its Node build (via services/api) cannot be bundled to ESM.
  external: ["react", "react-dom", "@tanstack/react-query", "react-router-dom", "lucide-react", "axios"],
  define: { "import.meta.env.VITE_API_URL": "undefined" },
  logLevel: "error",
});

const load = (name) => import(pathToFileURL(join(outDir, `${name}.mjs`)).href);
const toastModule = await load("toast");
const { ModelMissingNotice } = await load("model-missing-notice");
const { formatEta, entryTitle } = await load("format");
const { InlineError } = await load("inline-error");
const { EmptyState } = await load("empty-state");
const { Inbox } = await import("lucide-react");

const {
  toast,
  dismissToast,
  pauseToast,
  resumeToast,
  getToastState,
  setTitleBadge,
  useToast,
  runToastAction,
  Toaster,
} = toastModule;

function clearToasts() {
  for (const t of getToastState().toasts) dismissToast(t.id);
}
const ids = () => getToastState().toasts.map((t) => t.id);
const has = (id) => ids().includes(id);

describe("toast store", () => {
  test.beforeEach(() => {
    mock.timers.enable({ apis: ["setTimeout", "Date"], now: 1_000_000 });
    clearToasts();
  });
  test.afterEach(() => {
    clearToasts();
    mock.timers.reset();
  });

  test("info toast shows and is gone after 6 s", () => {
    const id = toast({ text: "Saved", kind: "info" });
    assert.ok(has(id));
    mock.timers.tick(5_999);
    assert.ok(has(id), "still visible just before 6 s");
    mock.timers.tick(1);
    assert.ok(!has(id), "gone at 6 s");
  });

  test("kind defaults to info", () => {
    const id = toast({ text: "Hello" });
    assert.equal(getToastState().toasts.find((t) => t.id === id).kind, "info");
  });

  test("undo toast lasts 10 s; its action runs and can dismiss it", () => {
    let undone = 0;
    const id = toast({ text: "Entry deleted", kind: "undo", action: { label: "Undo", onClick: () => undone++ } });
    mock.timers.tick(9_999);
    assert.ok(has(id), "still visible just before 10 s");
    mock.timers.tick(1);
    assert.ok(!has(id), "gone at 10 s");

    // The Toaster's action button calls runToastAction(item).
    const id2 = toast({ text: "Entry deleted", kind: "undo", action: { label: "Undo", onClick: () => undone++ } });
    const item = getToastState().toasts.find((t) => t.id === id2);
    assert.equal(item.action.label, "Undo");
    runToastAction(item);
    assert.equal(undone, 1);
    assert.ok(!has(id2));
  });

  test("runToastAction dismisses even when onClick throws", () => {
    const id = toast({
      text: "Entry deleted",
      kind: "undo",
      action: {
        label: "Undo",
        onClick: () => {
          throw new Error("boom");
        },
      },
    });
    const item = getToastState().toasts.find((t) => t.id === id);
    assert.throws(() => runToastAction(item), /boom/);
    assert.ok(!has(id), "toast removed despite the throw");
  });

  test("Toaster markup: live region, toast text, action and dismiss", () => {
    const empty = renderToStaticMarkup(createElement(Toaster));
    assert.doesNotMatch(empty, /Notifications/, "no section with zero toasts");
    assert.equal((empty.match(/role="status"/g) ?? []).length, 1, "status region always mounted");

    toast({ text: "Saved" });
    toast({ text: "Entry deleted", kind: "undo", action: { label: "Undo", onClick: () => {} } });
    const html = renderToStaticMarkup(createElement(Toaster));
    assert.equal((html.match(/role="status"/g) ?? []).length, 1, "exactly one status region");
    assert.match(html, /role="status"[^>]*aria-live="polite"|aria-live="polite"[^>]*role="status"/);
    assert.match(html, /aria-label="Notifications"/);
    assert.match(html, />Saved</);
    assert.match(html, />Entry deleted</);
    assert.match(html, />Undo</);
    assert.equal((html.match(/aria-label="Dismiss notification"/g) ?? []).length, 2);
  });

  test("failure toast persists until dismissed", () => {
    const id = toast({ text: "Upload failed", kind: "failure" });
    mock.timers.tick(60 * 60 * 1000);
    assert.ok(has(id), "still visible after an hour");
    assert.equal(getToastState().toasts.find((t) => t.id === id).remaining, null);
    dismissToast(id);
    assert.ok(!has(id));
  });

  test("hover/focus pauses; resume continues with the remaining time", () => {
    const id = toast({ text: "Saved", kind: "info" });
    mock.timers.tick(4_000);
    pauseToast(id);
    pauseToast(id); // idempotent
    const paused = getToastState().toasts.find((t) => t.id === id);
    assert.equal(paused.paused, true);
    assert.equal(paused.remaining, 2_000);
    mock.timers.tick(30_000);
    assert.ok(has(id), "paused toast does not time out");
    resumeToast(id);
    resumeToast(id); // idempotent
    mock.timers.tick(1_999);
    assert.ok(has(id), "still visible before the remaining 2 s elapse");
    mock.timers.tick(1);
    assert.ok(!has(id), "gone once the remaining time elapses");
  });

  test("a 4th toast evicts the oldest non-failure", () => {
    const failure = toast({ text: "Failed", kind: "failure" });
    const info1 = toast({ text: "One" });
    const info2 = toast({ text: "Two" });
    const fourth = toast({ text: "Three" });
    assert.deepEqual(ids(), [failure, info2, fourth]);
    // The evicted toast's timer must not fire later against a reused slot.
    mock.timers.tick(6_000);
    assert.deepEqual(ids(), [failure]);
    assert.ok(!has(info1));
  });

  test("with 3 failures shown, the oldest failure is evicted", () => {
    const f1 = toast({ text: "F1", kind: "failure" });
    const f2 = toast({ text: "F2", kind: "failure" });
    const f3 = toast({ text: "F3", kind: "failure" });
    const next = toast({ text: "Next" });
    assert.deepEqual(ids(), [f2, f3, next]);
    assert.ok(!has(f1));
    assert.equal(getToastState().toasts.length, 3);
  });

  test("each toast's text is announced, and repeat text gets a new key", () => {
    toast({ text: "Saved" });
    const first = getToastState().announcement;
    assert.equal(first.text, "Saved");
    toast({ text: "Saved" });
    const second = getToastState().announcement;
    assert.equal(second.text, "Saved");
    assert.notEqual(second.key, first.key, "identical text re-announces");
    toast({ text: "Upload failed", kind: "failure" });
    assert.equal(getToastState().announcement.text, "Upload failed");
  });

  test("useToast() exposes toast, dismiss and setTitleBadge", () => {
    const api = useToast();
    assert.equal(api.toast, toast);
    assert.equal(api.dismiss, dismissToast);
    assert.equal(api.setTitleBadge, setTitleBadge);
  });
});

describe("setTitleBadge", () => {
  const realDocument = globalThis.document;
  test.beforeEach(() => {
    globalThis.document = { title: "World · Lorekeeper" };
  });
  after(() => {
    if (realDocument === undefined) delete globalThis.document;
    else globalThis.document = realDocument;
  });

  test("adds then removes the count prefix", () => {
    setTitleBadge(2);
    assert.equal(document.title, "(2) World · Lorekeeper");
    setTitleBadge(5);
    assert.equal(document.title, "(5) World · Lorekeeper", "replaces, never stacks");
    setTitleBadge(0);
    assert.equal(document.title, "World · Lorekeeper");
  });

  test("negative and NaN are treated as 0", () => {
    setTitleBadge(3);
    setTitleBadge(-1);
    assert.equal(document.title, "World · Lorekeeper");
    setTitleBadge(3);
    setTitleBadge(Number.NaN);
    assert.equal(document.title, "World · Lorekeeper");
  });

  test("re-applies after a later title change", () => {
    setTitleBadge(2);
    document.title = "Portal · Lorekeeper";
    setTitleBadge(2);
    assert.equal(document.title, "(2) Portal · Lorekeeper");
  });
});

describe("ModelMissingNotice", () => {
  const props = { model: "speech model", feature: "Live captions", sizeLabel: "~1.5 GB" };

  function render(extraProps, me) {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    if (me !== undefined) client.setQueryData(["me"], me);
    // React Router's useLayoutEffect warns under the server renderer; that
    // noise is expected here, everything else still reaches the console.
    const consoleError = console.error;
    console.error = (...args) => {
      if (typeof args[0] === "string" && args[0].includes("useLayoutEffect does nothing on the server")) return;
      consoleError(...args);
    };
    let html;
    try {
      html = renderToStaticMarkup(
        createElement(
          QueryClientProvider,
          { client },
          createElement(MemoryRouter, null, createElement(ModelMissingNotice, { ...props, ...extraProps })),
        ),
      );
    } finally {
      console.error = consoleError;
      client.clear();
    }
    return html;
  }

  const decode = (s) =>
    s
      .replace(/&#x27;|&#39;/g, "'")
      .replace(/&quot;/g, '"')
      .replace(/&lt;/g, "<")
      .replace(/&gt;/g, ">")
      .replace(/&amp;/g, "&");
  const text = (html) => decode(html.replace(/<[^>]+>/g, "")).replace(/\s+/g, " ").trim();
  const adminHref = /<a [^>]*href="\/admin\?tab=system"/;

  test("admin, not installed: install sentence with size and link", () => {
    const html = render({}, { is_admin: true });
    assert.match(
      text(html),
      /The speech model isn't installed\. An admin can add it in Admin › Models \(~1\.5 GB\)\./,
    );
    assert.match(html, adminHref);
    assert.match(text(html), /^Live captions is unavailable/, "names the feature");
  });

  test("non-admin, not installed: ask your admin, no link", () => {
    const html = render({}, { is_admin: false });
    assert.match(text(html), /The speech model isn't installed\. Ask your admin\./);
    assert.doesNotMatch(html, /<a /);
  });

  test("profile not loaded: treated as non-admin", () => {
    const html = render({}, undefined);
    assert.match(text(html), /The speech model isn't installed\. Ask your admin\./);
    assert.doesNotMatch(html, /<a /);
  });

  test("unreachable: admin gets link, non-admin is told to ask", () => {
    const admin = render({ reachable: false }, { is_admin: true });
    assert.match(text(admin), /The speech model isn't reachable\./);
    assert.match(admin, adminHref);
    const member = render({ reachable: false }, { is_admin: false });
    assert.match(text(member), /The speech model isn't reachable\. Ask your admin\./);
    assert.doesNotMatch(member, /<a /);
  });

  test("icon is an aria-hidden svg and there is no emoji", () => {
    const html = render({}, { is_admin: true });
    assert.match(html, /<svg[^>]*aria-hidden="true"/);
    assert.doesNotMatch(html, /\p{Extended_Pictographic}/u);
  });
});

describe("InlineError", () => {
  const render = (props) => renderToStaticMarkup(createElement(InlineError, props));

  test("array detail (FastAPI 422) falls back to text", () => {
    const err = { response: { data: { detail: [{ loc: ["body", "x"], msg: "bad", type: "value_error" }] } } };
    const html = render({ error: err, fallback: "Couldn't save." });
    assert.match(html, /role="alert"/);
    assert.match(html, /Couldn(&#x27;|')t save\./);
    const noFallback = render({ error: err });
    assert.match(noFallback, /Something went wrong\. Try again\./);
  });

  test("string error shown as-is; string detail used", () => {
    assert.match(render({ error: "Name is taken" }), /Name is taken/);
    assert.match(render({ error: { response: { data: { detail: "Too long" } } } }), /Too long/);
  });

  test("Retry button only with onRetry", () => {
    assert.doesNotMatch(render({ error: "Nope" }), /<button/);
    const html = render({ error: "Nope", onRetry: () => {} });
    assert.match(html, /<button[^>]*>Retry<\/button>/);
  });
});

describe("EmptyState", () => {
  test("aria-hidden icon, sentence, no emoji", () => {
    const html = renderToStaticMarkup(createElement(EmptyState, { icon: Inbox }, "No entries yet."));
    assert.match(html, /<svg[^>]*aria-hidden="true"/);
    assert.match(html, /No entries yet\./);
    assert.doesNotMatch(html, /\p{Extended_Pictographic}/u);
  });
});

describe("lib/format", () => {
  test("formatEta", () => {
    assert.equal(formatEta(90), "about 1–2 min left");
    assert.equal(formatEta(45), "about 1 min left");
    assert.equal(formatEta(600), "about 10 min left");
    assert.equal(formatEta(5400), "about 1–2 hours left");
    assert.equal(formatEta(0), "almost done");
    assert.equal(formatEta(Number.NaN), "estimating time left");
    for (const s of [1, 30, 61, 119, 120, 1800, 3570, 3600, 7200, 86_400, -5, Infinity]) {
      assert.doesNotMatch(formatEta(s), /^\d+$/, `${s}: never a bare number`);
      assert.match(formatEta(s), /^(about |almost done|estimating)/, `${s}: about/range copy`);
    }
  });

  test("entryTitle", () => {
    assert.equal(renderToStaticMarkup(entryTitle("The Ambush")), "<em>The Ambush</em>");
    assert.equal(renderToStaticMarkup(entryTitle("")), "<em>Untitled entry</em>");
    assert.equal(renderToStaticMarkup(entryTitle(null)), "<em>Untitled entry</em>");
  });
});
