#!/usr/bin/env node
// Checks E0-Access.11's useCampaignEvents (hooks/useCampaignEvents.ts): the SSE
// frame parser and splitter, which query keys each event refetches (the
// resync on `subscribed`, broadcast `visibility`/`role`, domain aliases), the
// reconnect policy (backoff, one immediate reconnect after access_changed,
// stop on 401/404) and the whole loop over a fake transport with a real
// QueryClient. Plus source guards: fetch with a bearer header, never
// EventSource or `?token=`.
// No test runner and no new dependency: node:test + node:assert and the
// esbuild that Vite already installs (same harness as check-campaign-switcher).
//
//   node scripts/check-campaign-events.mjs

import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, readFileSync, rmSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { beforeEach, describe, test } from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";

import { build } from "esbuild";
import { QueryClient } from "@tanstack/react-query";

const frontendDir = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const srcDir = join(frontendDir, "src");
const hookPath = join(srcDir, "hooks/useCampaignEvents.ts");

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
globalThis.localStorage = new FakeStorage();
globalThis.sessionStorage = new FakeStorage();

const cacheDir = join(frontendDir, "node_modules", ".cache");
mkdirSync(cacheDir, { recursive: true });
const outDir = mkdtempSync(join(cacheDir, "check-campaign-events-"));
process.on("exit", () => rmSync(outDir, { recursive: true, force: true }));

await build({
  entryPoints: { events: hookPath, preview: join(srcDir, "lib/preview.ts") },
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
const ev = await load("events");
const preview = await load("preview");

const CID = "11111111-1111-4111-8111-111111111111";
const OTHER = "22222222-2222-4222-8222-222222222222";
const ENTITY = "33333333-3333-4333-8333-333333333333";

const frame = (event, data) => `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;

function seeded() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  for (const key of [
    ["entities", CID],
    ["entities", OTHER],
    ["npcs", CID],
    ["campaignRole", CID],
    ["campaignRole", OTHER],
    ["journals", { campaign_id: CID }],
    ["journal", ENTITY],
    ["characterSheets", CID],
    ["admin-users"],
    ["me"],
  ]) {
    qc.setQueryData(key, { seeded: true });
  }
  return qc;
}
const invalidated = (qc, key) => qc.getQueryState(key)?.isInvalidated === true;
const tick = () => new Promise((r) => setTimeout(r, 0));

beforeEach(() => {
  localStorage.clear();
  preview.setPreviewCampaignId(null);
});

describe("frames", () => {
  test("parses event and JSON data; ignores comments; joins multi-line data", () => {
    assert.deepEqual(ev.parseSseFrame('event: invalidate\ndata: {"domain":"entities","id":null}'), {
      event: "invalidate",
      data: { domain: "entities", id: null },
    });
    assert.deepEqual(ev.parseSseFrame(": comment\nevent: x\ndata: [1,\ndata: 2]"), { event: "x", data: [1, 2] });
    assert.equal(ev.parseSseFrame("event: x"), null);
    assert.equal(ev.parseSseFrame("event: x\ndata: not json"), null);
  });

  test("the splitter keeps partial frames across chunks and accepts CRLF", () => {
    const split = ev.createFrameSplitter();
    const text = frame("subscribed", {}) + frame("ping", {});
    assert.deepEqual(split(text.slice(0, 7)), []);
    const got = [...split(text.slice(7, 30)), ...split(text.slice(30))];
    assert.deepEqual(got.map((f) => f.event), ["subscribed", "ping"]);
    assert.deepEqual(split('event: a\r\ndata: {}\r\n\r\n').map((f) => f.event), ["a"]);
  });
});

describe("what each event refetches", () => {
  test("invalidate {domain,id} refetches [domain, campaignId] only", () => {
    const qc = seeded();
    assert.equal(ev.applyFrame(qc, CID, { event: "invalidate", data: { domain: "entities", id: ENTITY } }), "invalidate");
    assert.ok(invalidated(qc, ["entities", CID]));
    assert.ok(!invalidated(qc, ["entities", OTHER]));
    assert.ok(!invalidated(qc, ["npcs", CID]));
    assert.ok(!invalidated(qc, ["campaignRole", CID]));
  });

  test("role also invalidates campaignRole, and refetches the whole Campaign", () => {
    const keys = ev.invalidationKeys({ domain: "role", id: null }, CID);
    assert.equal(keys.all, true);
    assert.deepEqual(keys.keys, [["role", CID], ["campaignRole", CID]]);
    const qc = seeded();
    ev.applyFrame(qc, CID, { event: "invalidate", data: { domain: "role", id: null } });
    for (const key of [["campaignRole", CID], ["entities", CID], ["npcs", CID], ["journals", { campaign_id: CID }]]) {
      assert.ok(invalidated(qc, key), JSON.stringify(key));
    }
    for (const key of [["campaignRole", OTHER], ["entities", OTHER], ["admin-users"], ["me"]]) {
      assert.ok(!invalidated(qc, key), JSON.stringify(key));
    }
  });

  test("visibility refetches the whole Campaign", () => {
    const qc = seeded();
    ev.applyFrame(qc, CID, { event: "invalidate", data: { domain: "visibility", id: null } });
    assert.ok(invalidated(qc, ["npcs", CID]) && invalidated(qc, ["journal", ENTITY]));
    assert.ok(!invalidated(qc, ["entities", OTHER]));
  });

  test("subscribed (the resync point) refetches every query of the Campaign", () => {
    const qc = seeded();
    assert.equal(ev.applyFrame(qc, CID, { event: "subscribed", data: {} }), "subscribed");
    for (const key of [["entities", CID], ["npcs", CID], ["campaignRole", CID], ["characterSheets", CID]]) {
      assert.ok(invalidated(qc, key), JSON.stringify(key));
    }
    assert.ok(!invalidated(qc, ["entities", OTHER]) && !invalidated(qc, ["admin-users"]));
  });

  test("domain aliases reach the existing keys", () => {
    assert.deepEqual(ev.invalidationKeys({ domain: "journal", id: ENTITY }, CID).keys, [
      ["journal", CID],
      ["journals"],
      ["journal", ENTITY],
    ]);
    assert.deepEqual(ev.invalidationKeys({ domain: "character_sheets", id: null }, CID).keys, [
      ["character_sheets", CID],
      ["characterSheets", CID],
    ]);
  });

  test("malformed invalidations and unknown events change nothing", () => {
    const qc = seeded();
    for (const data of [null, "x", { domain: "" }, { domain: 3 }, { domain: "entities", id: 7 }]) {
      assert.equal(ev.applyFrame(qc, CID, { event: "invalidate", data }), "other");
    }
    assert.equal(ev.applyFrame(qc, CID, { event: "ping", data: {} }), "other");
    assert.ok(!invalidated(qc, ["entities", CID]));
  });

  test("access_changed invalidates campaignRole", () => {
    const qc = seeded();
    assert.equal(ev.applyFrame(qc, CID, { event: "access_changed", data: { detail: "Not found" } }), "access_changed");
    assert.ok(invalidated(qc, ["campaignRole", CID]));
  });
});

describe("reconnect policy", () => {
  const half = () => 1; // the top of the jitter range: deterministic

  test("401 and 404 stop", () => {
    for (const status of [401, 404]) {
      const state = { attempt: 0, accessRetryUsed: false };
      assert.deepEqual(ev.nextStep({ kind: "status", status }, state, half), { action: "stop", reason: String(status) });
    }
  });

  test("other statuses, errors and plain ends back off, doubling to 30 s", () => {
    const state = { attempt: 0, accessRetryUsed: false };
    const delays = [];
    for (let i = 0; i < 7; i++) delays.push(ev.nextStep(i % 2 ? { kind: "error" } : { kind: "status", status: 503 }, state, half).delayMs);
    assert.deepEqual(delays, [1000, 2000, 4000, 8000, 16000, 30000, 30000]);
    assert.ok(ev.backoffMs(0, () => 0) >= 500 && ev.backoffMs(0, () => 0) <= 1000);
  });

  test("access_changed reconnects once at once; a stream that subscribed resets everything", () => {
    const state = { attempt: 3, accessRetryUsed: false };
    const changed = { kind: "ended", accessChanged: true, subscribed: false };
    assert.deepEqual(ev.nextStep(changed, state, half), { action: "reconnect", delayMs: 0 });
    assert.equal(ev.nextStep(changed, state, half).delayMs > 0, true); // only once
    const ranThenChanged = { kind: "ended", accessChanged: true, subscribed: true };
    assert.deepEqual(ev.nextStep(ranThenChanged, state, half), { action: "reconnect", delayMs: 0 });
    assert.equal(state.attempt, 0);
    const plainEnd = { kind: "ended", accessChanged: false, subscribed: true };
    assert.deepEqual(ev.nextStep(plainEnd, { attempt: 5, accessRetryUsed: true }, half), { action: "reconnect", delayMs: 1000 });
  });

  test("abort stops", () => {
    assert.equal(ev.nextStep({ kind: "aborted" }, { attempt: 0, accessRetryUsed: false }).action, "stop");
  });
});

describe("the loop over a fake transport", () => {
  test("bearer + preview headers, events applied, access_changed reconnect, stop on 404", async () => {
    localStorage.setItem("lk_token", "tok-123");
    preview.setPreviewCampaignId(CID);
    const qc = seeded();
    const calls = [];
    const sleeps = [];
    const script = [
      async (emit) => {
        emit({ event: "subscribed", data: {} });
        emit({ event: "invalidate", data: { domain: "entities", id: ENTITY } });
        emit({ event: "access_changed", data: { detail: "Not found" } });
        return { kind: "ended" };
      },
      async () => ({ kind: "status", status: 404 }),
    ];
    const open = async (url, headers, signal, onFrame) => {
      calls.push({ url, headers });
      return script[calls.length - 1](onFrame);
    };
    const stops = [];
    const controller = new AbortController();
    const reason = await ev.runCampaignEvents({
      campaignId: CID,
      queryClient: qc,
      signal: controller.signal,
      open,
      sleep: async (ms) => void sleeps.push(ms),
      onStop: (r) => stops.push(r),
    });
    assert.equal(reason, "404");
    assert.deepEqual(stops, ["404"]);
    assert.equal(calls.length, 2);
    assert.deepEqual(sleeps, []); // the access_changed reconnect waits for nothing
    for (const { url, headers } of calls) {
      assert.equal(url, `/api/campaigns/${CID}/events`);
      assert.ok(!url.includes("token"));
      assert.equal(headers.Authorization, "Bearer tok-123");
      assert.equal(headers["X-Lorekeeper-Preview"], "member");
    }
    assert.ok(invalidated(qc, ["entities", CID]) && invalidated(qc, ["campaignRole", CID]));
  });

  test("no preview header outside preview; backoff between failed connections; abort ends it", async () => {
    localStorage.setItem("lk_token", "tok-9");
    const qc = seeded();
    const controller = new AbortController();
    const calls = [];
    const sleeps = [];
    const open = async (_url, headers) => {
      calls.push(headers);
      if (calls.length === 3) controller.abort();
      return calls.length === 3 ? { kind: "aborted" } : { kind: "error" };
    };
    const reason = await ev.runCampaignEvents({
      campaignId: CID,
      queryClient: qc,
      signal: controller.signal,
      open,
      random: () => 1,
      sleep: async (ms) => void sleeps.push(ms),
    });
    assert.equal(reason, "aborted");
    assert.deepEqual(sleeps, [1000, 2000]);
    assert.ok(calls.every((h) => !("X-Lorekeeper-Preview" in h)));
  });

  test("no token: never connects", async () => {
    let opened = false;
    const reason = await ev.runCampaignEvents({
      campaignId: CID,
      queryClient: seeded(),
      signal: new AbortController().signal,
      open: async () => {
        opened = true;
        return { kind: "ended" };
      },
    });
    assert.equal(reason, "no_token");
    assert.equal(opened, false);
  });

  test("openFetchStream reads a real ReadableStream body chunk by chunk", async () => {
    const chunks = [frame("subscribed", {}).slice(0, 5), frame("subscribed", {}).slice(5) + frame("ping", {})];
    const realFetch = globalThis.fetch;
    let seen;
    globalThis.fetch = async (url, init) => {
      seen = { url, init };
      const body = new ReadableStream({
        start(c) {
          for (const ch of chunks) c.enqueue(new TextEncoder().encode(ch));
          c.close();
        },
      });
      return new Response(body, { status: 200, headers: { "Content-Type": "text/event-stream" } });
    };
    try {
      const got = [];
      const result = await ev.openFetchStream("/x", { Authorization: "Bearer t" }, new AbortController().signal, (f) =>
        got.push(f.event),
      );
      assert.deepEqual(result, { kind: "ended" });
      assert.deepEqual(got, ["subscribed", "ping"]);
      assert.equal(seen.init.headers.Authorization, "Bearer t");
      globalThis.fetch = async () => new Response("nope", { status: 404 });
      assert.deepEqual(await ev.openFetchStream("/x", {}, new AbortController().signal, () => {}), {
        kind: "status",
        status: 404,
      });
    } finally {
      globalThis.fetch = realFetch;
    }
    await tick();
  });
});

describe("source guards", () => {
  const source = readFileSync(hookPath, "utf8");
  test("no EventSource and no token in the URL", () => {
    assert.ok(!/new\s+EventSource|EventSource\(/.test(source));
    assert.ok(!/[?&]token=/.test(source));
  });
  test("the shell mounts the subscriber once", () => {
    const app = readFileSync(join(srcDir, "App.tsx"), "utf8");
    assert.equal(app.match(/<CampaignEventsSubscriber \/>/g)?.length, 1);
  });
});
