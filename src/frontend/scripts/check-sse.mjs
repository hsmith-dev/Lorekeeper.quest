#!/usr/bin/env node
// Checks E0-Jobs.9's lib/sse.ts (the only SSE client) and hooks/useJobStream.ts:
// the frame parser and splitter, the headers (bearer + preview, no token: no
// connection), the reconnect policy (backoff and jitter bounds, one immediate
// reconnect after access_changed, stop on 401/404), the whole `openSse` loop
// over a fake fetch (reconnect, abort, idle watchdog, ping filtering, one-shot
// POST, onEvent exceptions), the Job cache merging, and source guards across
// src/: no EventSource, no `?token=`, and fetch stream readers only in
// lib/sse.ts (AdminPage's model-install progress is the one deferred exception).
// No test runner and no new dependency: node:test + node:assert and the
// esbuild that Vite already installs (same harness as check-campaign-events).
//
//   node scripts/check-sse.mjs

import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, readdirSync, readFileSync, rmSync, statSync } from "node:fs";
import { dirname, join, relative, resolve } from "node:path";
import { afterEach, beforeEach, describe, test } from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";

import { build } from "esbuild";
import { QueryClient } from "@tanstack/react-query";

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
globalThis.localStorage = new FakeStorage();
globalThis.sessionStorage = new FakeStorage();

const cacheDir = join(frontendDir, "node_modules", ".cache");
mkdirSync(cacheDir, { recursive: true });
const outDir = mkdtempSync(join(cacheDir, "check-sse-"));
process.on("exit", () => rmSync(outDir, { recursive: true, force: true }));

await build({
  entryPoints: {
    sse: join(srcDir, "lib/sse.ts"),
    jobs: join(srcDir, "hooks/useJobStream.ts"),
    jobsApi: join(srcDir, "services/api/jobs.ts"),
    preview: join(srcDir, "lib/preview.ts"),
    chat: join(srcDir, "hooks/useChat.ts"),
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
const sse = await load("sse");
const jobs = await load("jobs");
const jobsApi = await load("jobsApi");
const preview = await load("preview");
const chat = await load("chat");

const CID = "11111111-1111-4111-8111-111111111111";
const OTHER = "22222222-2222-4222-8222-222222222222";
const JOB = "33333333-3333-4333-8333-333333333333";
const JOB2 = "44444444-4444-4444-8444-444444444444";

const enc = new TextEncoder();
const frame = (event, data) => `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const top = () => 1; // the top of the jitter range: deterministic

/**
 * A fake fetch answering from `script` (one entry per call). An entry is a
 * function (url, init, i) → Response | Promise<Response> (or throws).
 */
function installFetch(script) {
  const calls = [];
  globalThis.fetch = async (url, init) => {
    const i = calls.length;
    calls.push({ url, init });
    const entry = script[Math.min(i, script.length - 1)];
    return entry(url, init, i);
  };
  return calls;
}

/** A streaming 200 whose body sends `chunks` (strings, or ms delays) then closes unless `open`. */
function streamOf(chunks, { open = false, onCancel } = {}) {
  return (_url, init) => {
    const body = new ReadableStream({
      async start(c) {
        // A real fetch errors its body when its signal aborts.
        init.signal.addEventListener("abort", () => {
          try {
            c.error(new DOMException("aborted", "AbortError"));
          } catch {
            // already closed
          }
        });
        for (const ch of chunks) {
          if (typeof ch === "number") await wait(ch);
          else if (!init.signal.aborted) c.enqueue(enc.encode(ch));
        }
        if (!open && !init.signal.aborted) c.close();
      },
      cancel() {
        onCancel?.();
      },
    });
    return new Response(body, { status: 200, headers: { "Content-Type": "text/event-stream" } });
  };
}

const status = (code, onCancel) => () =>
  new Response(new ReadableStream({ cancel: () => onCancel?.() }), { status: code });
const networkError = () => () => {
  throw new TypeError("Failed to fetch");
};

const realFetch = globalThis.fetch;
beforeEach(() => {
  localStorage.clear();
  preview.setPreviewCampaignId(null);
});
afterEach(() => {
  globalThis.fetch = realFetch;
});

describe("frames", () => {
  test("parses event and JSON data; ignores comments; joins multi-line data", () => {
    assert.deepEqual(sse.parseSseFrame('event: job\ndata: {"job_id":"x"}'), { event: "job", data: { job_id: "x" } });
    assert.deepEqual(sse.parseSseFrame(": c\nevent: x\ndata: [1,\ndata: 2]"), { event: "x", data: [1, 2] });
    assert.deepEqual(sse.parseSseFrame("data: {}"), { event: "message", data: {} });
    assert.equal(sse.parseSseFrame("event: x"), null);
    assert.equal(sse.parseSseFrame("event: x\ndata: nope"), null);
  });

  test("the splitter keeps partial frames across chunks; CRLF and CR separators", () => {
    const split = sse.createFrameSplitter();
    const text = frame("subscribed", {}) + frame("job", { a: 1 });
    assert.deepEqual(split(text.slice(0, 9)), []);
    const got = [...split(text.slice(9, 31)), ...split(text.slice(31))];
    assert.deepEqual(got.map((f) => f.event), ["subscribed", "job"]);
    assert.deepEqual(split("event: a\r\ndata: {}\r\n\r\n").map((f) => f.event), ["a"]);
    assert.deepEqual(split("event: b\rdata: {}\r\r").map((f) => f.event), ["b"]);
  });
});

describe("headers", () => {
  test("no token: null; bearer always; preview header only while previewing", () => {
    assert.equal(sse.sseHeaders(), null);
    localStorage.setItem("lk_token", "t1");
    assert.deepEqual(sse.sseHeaders(), { Authorization: "Bearer t1" });
    preview.setPreviewCampaignId(CID);
    assert.deepEqual(sse.sseHeaders(), { Authorization: "Bearer t1", "X-Lorekeeper-Preview": "member" });
  });
});

describe("reconnect policy", () => {
  test("backoff doubles from 1 s to 30 s, jittered within x0.5-1", () => {
    for (let attempt = 0; attempt < 10; attempt++) {
      const ceiling = Math.min(30_000, 1_000 * 2 ** attempt);
      assert.equal(sse.backoffMs(attempt, () => 0), ceiling / 2);
      assert.equal(sse.backoffMs(attempt, top), ceiling);
      for (let k = 0; k < 20; k++) {
        const d = sse.backoffMs(attempt);
        assert.ok(d >= ceiling / 2 && d <= ceiling, `${attempt}: ${d}`);
      }
    }
  });

  test("401/404/abort stop; access_changed reconnects once at once", () => {
    for (const code of [401, 404]) {
      assert.deepEqual(sse.nextStep({ kind: "status", status: code }, { attempt: 0, accessRetryUsed: false }), {
        action: "stop",
        reason: String(code),
      });
    }
    assert.equal(sse.nextStep({ kind: "aborted" }, { attempt: 0, accessRetryUsed: false }).action, "stop");
    const state = { attempt: 2, accessRetryUsed: false };
    const changed = { kind: "ended", accessChanged: true, subscribed: false };
    assert.deepEqual(sse.nextStep(changed, state, top), { action: "reconnect", delayMs: 0 });
    assert.deepEqual(sse.nextStep(changed, state, top), { action: "reconnect", delayMs: 4000 });
    assert.equal(sse.nextStep({ kind: "status", status: 503 }, state, top).delayMs, 8000);
  });
});

describe("openSse over a fake fetch", () => {
  test("drops, statuses and access_changed: backoff, one immediate reconnect, stop on 404; pings filtered", async () => {
    localStorage.setItem("lk_token", "tok-1");
    let cancelled503 = false;
    const calls = installFetch([
      streamOf([frame("subscribed", {}), frame("ping", {}), frame("job", { n: 1 })]), // plain end
      networkError(),
      status(503, () => (cancelled503 = true)),
      streamOf([frame("ping", {}), frame("access_changed", { detail: "Not found" })]),
      streamOf([frame("access_changed", { detail: "Not found" })]), // again, no subscribed in between
      streamOf([frame("subscribed", {}), frame("access_changed", { detail: "Not found" })]),
      status(404),
    ]);
    const events = [];
    const sleeps = [];
    const stops = [];
    const reason = await sse.openSse("/api/x/stream", {
      signal: new AbortController().signal,
      onEvent: (f) => events.push(f.event),
      onStop: (r) => stops.push(r),
      sleep: async (ms) => void sleeps.push(ms),
      random: top,
    });
    assert.equal(reason, "404");
    assert.deepEqual(stops, ["404"]);
    assert.equal(calls.length, 7);
    // end → 1 s; error → 2 s; 503 → 4 s; access_changed → 0 (no sleep); access_changed
    // again without subscribed → 8 s; subscribed + access_changed → 0 (no sleep).
    assert.deepEqual(sleeps, [1000, 2000, 4000, 8000]);
    assert.deepEqual(events, ["subscribed", "job", "access_changed", "access_changed", "subscribed", "access_changed"]);
    assert.ok(cancelled503, "a non-ok answer's body is cancelled");
    for (const { url, init } of calls) {
      assert.equal(url, "/api/x/stream");
      assert.ok(!/token/.test(url));
      assert.equal(init.method, "GET");
      assert.equal(init.headers.Authorization, "Bearer tok-1");
      assert.equal(init.headers.Accept, "text/event-stream");
      assert.ok(!("X-Lorekeeper-Preview" in init.headers));
    }
  });

  test("subscribed resets the backoff", async () => {
    localStorage.setItem("lk_token", "tok-r");
    installFetch([
      networkError(),
      networkError(),
      streamOf([frame("subscribed", {})]),
      networkError(),
      status(401),
    ]);
    const sleeps = [];
    const reason = await sse.openSse("/s", {
      signal: new AbortController().signal,
      onEvent: () => {},
      sleep: async (ms) => void sleeps.push(ms),
      random: top,
    });
    assert.equal(reason, "401");
    assert.deepEqual(sleeps, [1000, 2000, 1000, 2000]);
  });

  test("the preview header rides along while previewing", async () => {
    localStorage.setItem("lk_token", "tok-p");
    preview.setPreviewCampaignId(CID);
    const calls = installFetch([status(404)]);
    await sse.openSse("/s", { signal: new AbortController().signal, onEvent: () => {} });
    assert.equal(calls[0].init.headers["X-Lorekeeper-Preview"], "member");
  });

  test("no token: never connects", async () => {
    const calls = installFetch([status(200)]);
    const stops = [];
    const reason = await sse.openSse("/s", {
      signal: new AbortController().signal,
      onEvent: () => {},
      onStop: (r) => stops.push(r),
    });
    assert.equal(reason, "no_token");
    assert.deepEqual(stops, ["no_token"]);
    assert.equal(calls.length, 0);
  });

  test("abort mid-stream cancels the fetch and the reader; no onStop", async () => {
    localStorage.setItem("lk_token", "tok-a");
    const calls = installFetch([streamOf([frame("subscribed", {})], { open: true })]);
    const controller = new AbortController();
    const stops = [];
    const done = sse.openSse("/s", {
      signal: controller.signal,
      onEvent: (f) => {
        if (f.event === "subscribed") setTimeout(() => controller.abort(), 5);
      },
      onStop: (r) => stops.push(r),
    });
    assert.equal(await done, "aborted");
    assert.equal(calls.length, 1);
    assert.ok(calls[0].init.signal.aborted, "the fetch's own signal is aborted");
    assert.deepEqual(stops, []);
  });

  test("abort during the backoff sleep ends at once", async () => {
    localStorage.setItem("lk_token", "tok-s");
    installFetch([networkError()]);
    const controller = new AbortController();
    setTimeout(() => controller.abort(), 20);
    const started = Date.now();
    const reason = await sse.openSse("/s", { signal: controller.signal, onEvent: () => {}, random: top });
    assert.equal(reason, "aborted");
    assert.ok(Date.now() - started < 900, "did not wait out the 1 s backoff");
  });

  test("the idle watchdog ends a silent stream as an error, then reconnects", async () => {
    localStorage.setItem("lk_token", "tok-w");
    const calls = installFetch([streamOf([frame("subscribed", {})], { open: true }), status(404)]);
    const sleeps = [];
    const events = [];
    const reason = await sse.openSse("/s", {
      signal: new AbortController().signal,
      idleMs: 40,
      onEvent: (f) => events.push(f.event),
      sleep: async (ms) => void sleeps.push(ms),
      random: top,
    });
    assert.equal(reason, "404");
    assert.equal(calls.length, 2);
    assert.deepEqual(events, ["subscribed"]);
    assert.deepEqual(sleeps, [1000]);
    const one = installFetch([streamOf([], { open: true })]);
    assert.deepEqual(await sse.connectSse("/s", {}, new AbortController().signal, () => {}, { idleMs: 30 }), {
      kind: "error",
    });
    assert.ok(one[0].init.signal.aborted);
  });

  test("pings re-arm the watchdog but never reach onEvent", async () => {
    localStorage.setItem("lk_token", "tok-k");
    installFetch([
      streamOf([frame("subscribed", {}), 25, frame("ping", {}), 25, frame("ping", {}), 25, frame("ping", {}), 25, frame("job", {})]),
      status(404),
    ]);
    const events = [];
    const sleeps = [];
    await sse.openSse("/s", {
      signal: new AbortController().signal,
      idleMs: 50,
      onEvent: (f) => events.push(f.event),
      sleep: async (ms) => void sleeps.push(ms),
      random: top,
    });
    assert.deepEqual(events, ["subscribed", "job"]);
    assert.deepEqual(sleeps, [1000]); // a plain end, not a watchdog error before `job`
  });

  test("idleMs: null turns the watchdog off", async () => {
    installFetch([streamOf([60, frame("done", {})])]);
    const got = [];
    const result = await sse.connectSse("/s", {}, new AbortController().signal, (f) => got.push(f.event), {
      idleMs: null,
    });
    assert.deepEqual(result, { kind: "ended" });
    assert.deepEqual(got, ["done"]);
  });
});

describe("one-shot (the chat POST)", () => {
  test("POSTs JSON once with the bearer header and returns how it ended", async () => {
    localStorage.setItem("lk_token", "tok-c");
    preview.setPreviewCampaignId(CID);
    const calls = installFetch([streamOf([frame("meta", { session_id: "s" }), frame("delta", { text: "hi" }), frame("done", {})])]);
    const events = [];
    const reason = await sse.openSse("/api/chat/stream", {
      method: "POST",
      body: { message: "hello", campaign_id: CID },
      reconnect: false,
      idleMs: null,
      signal: new AbortController().signal,
      onEvent: (f) => events.push(f.event),
    });
    assert.equal(reason, "ended");
    assert.deepEqual(events, ["meta", "delta", "done"]);
    assert.equal(calls.length, 1);
    const { init } = calls[0];
    assert.equal(init.method, "POST");
    assert.deepEqual(JSON.parse(init.body), { message: "hello", campaign_id: CID });
    assert.equal(init.headers["Content-Type"], "application/json");
    assert.equal(init.headers.Authorization, "Bearer tok-c");
    assert.equal(init.headers["X-Lorekeeper-Preview"], "member");
  });

  test("never replayed: a status, a network error or a drop returns at once", async () => {
    localStorage.setItem("lk_token", "tok-c");
    for (const [entry, want] of [
      [status(503), "503"],
      [status(429), "429"],
      [status(404), "404"],
      [networkError(), "error"],
      [streamOf([frame("meta", {})]), "ended"],
    ]) {
      const calls = installFetch([entry, status(200)]);
      const sleeps = [];
      const reason = await sse.openSse("/c", {
        method: "POST",
        body: {},
        reconnect: false,
        signal: new AbortController().signal,
        onEvent: () => {},
        sleep: async (ms) => void sleeps.push(ms),
      });
      assert.equal(reason, want);
      assert.equal(calls.length, 1, want);
      assert.deepEqual(sleeps, []);
    }
  });

  test("an exception from onEvent cancels the reader and propagates", async () => {
    localStorage.setItem("lk_token", "tok-e");
    let cancelled = false;
    installFetch([
      streamOf([frame("meta", {}), frame("error", { detail: "Not found" }), frame("delta", { text: "late" })], {
        open: true,
        onCancel: () => (cancelled = true),
      }),
    ]);
    const events = [];
    await assert.rejects(
      sse.openSse("/c", {
        method: "POST",
        body: {},
        reconnect: false,
        idleMs: null,
        signal: new AbortController().signal,
        onEvent: (f) => {
          events.push(f.event);
          if (f.event === "error") throw new Error(f.data.detail);
        },
      }),
      /Not found/,
    );
    assert.deepEqual(events, ["meta", "error"]);
    await wait(0);
    assert.ok(cancelled, "the reader was cancelled");
  });
});

describe("reconnecting: a throwing onEvent", () => {
  test("ends that connection as an error, backs off and reconnects; openSse does not reject", async () => {
    localStorage.setItem("lk_token", "tok-t");
    let cancelled = false;
    const calls = installFetch([
      streamOf([frame("subscribed", {}), frame("job", { bad: true }), frame("job", { late: true })], {
        open: true,
        onCancel: () => (cancelled = true),
      }),
      status(404),
    ]);
    const events = [];
    const sleeps = [];
    const realError = console.error;
    const logged = [];
    console.error = (...args) => void logged.push(args);
    try {
      const reason = await sse.openSse("/s", {
        signal: new AbortController().signal,
        onEvent: (f) => {
          events.push(f.event);
          if (f.event === "job") throw new Error("handler bug");
        },
        sleep: async (ms) => void sleeps.push(ms),
        random: top,
      });
      assert.equal(reason, "404");
    } finally {
      console.error = realError;
    }
    assert.equal(calls.length, 2);
    assert.deepEqual(events, ["subscribed", "job"]);
    assert.deepEqual(sleeps, [1000]);
    assert.equal(logged.length, 1);
    await wait(0);
    assert.ok(cancelled, "the reader was cancelled");
  });
});

describe("streamChatTurn (useChat's stream classification)", () => {
  const turn = (opts = {}) => {
    const seen = { meta: [], deltas: [], done: [] };
    const run = chat.streamChatTurn("/api/chat/stream", { message: "hi" }, {
      signal: opts.signal ?? new AbortController().signal,
      onMeta: (m) => seen.meta.push(m.session_id),
      onDelta: (t) => seen.deltas.push(t),
      onDone: (r) => seen.done.push(r),
    });
    return { run, seen };
  };
  const meta = frame("meta", { session_id: "sess-1", sources: [], grounded: true, retrieval: null });

  test("meta + delta + done: ok with the session id", async () => {
    localStorage.setItem("lk_token", "tok-c");
    const calls = installFetch([
      streamOf([meta, frame("delta", { text: "Hel" }), frame("delta", { text: "lo" }), frame("done", { reply: "Hello" })]),
    ]);
    const { run, seen } = turn();
    assert.deepEqual(await run, { kind: "ok", sessionId: "sess-1" });
    assert.deepEqual(seen, { meta: ["sess-1"], deltas: ["Hel", "Hello"], done: ["Hello"] });
    assert.equal(calls.length, 1);
    assert.equal(calls[0].init.method, "POST");
    assert.equal(calls[0].init.headers.Authorization, "Bearer tok-c");
  });

  test('error {"detail":"Not found"} mid-stream: revoked', async () => {
    localStorage.setItem("lk_token", "tok-c");
    installFetch([streamOf([meta, frame("delta", { text: "par" }), frame("error", { detail: "Not found" })], { open: true })]);
    assert.deepEqual(await turn().run, { kind: "revoked" });
  });

  test("a model error, a 503, a dropped connection: fallback", async () => {
    localStorage.setItem("lk_token", "tok-c");
    for (const entry of [
      streamOf([meta, frame("error", { detail: "AI model unavailable" })], { open: true }),
      status(503),
      networkError(),
    ]) {
      const calls = installFetch([entry, status(200)]);
      assert.equal((await turn().run).kind, "fallback");
      assert.equal(calls.length, 1);
    }
  });

  test("no token: fallback, never fetched", async () => {
    const calls = installFetch([status(200)]);
    assert.equal((await turn().run).kind, "fallback");
    assert.equal(calls.length, 0);
  });

  test("a stream ending with no meta, or with no text: fallback", async () => {
    localStorage.setItem("lk_token", "tok-c");
    installFetch([streamOf([frame("delta", { text: "x" }), frame("done", {})])]);
    assert.equal((await turn().run).kind, "fallback");
    installFetch([streamOf([meta, frame("delta", { text: "  " }), frame("done", { reply: "" })])]);
    assert.equal((await turn().run).kind, "fallback");
  });

  test("abort mid-stream: aborted (no fallback), the fetch is aborted", async () => {
    localStorage.setItem("lk_token", "tok-c");
    const calls = installFetch([streamOf([meta], { open: true })]);
    const controller = new AbortController();
    const { run, seen } = turn({ signal: controller.signal });
    setTimeout(() => controller.abort(), 20);
    assert.deepEqual(await run, { kind: "aborted" });
    assert.deepEqual(seen.meta, ["sess-1"]);
    assert.ok(calls[0].init.signal.aborted);
  });
});

// ─── Jobs ────────────────────────────────────────────────────────────────────

const job = (id, over = {}) => ({
  id,
  kind: "extract",
  status: "running",
  progress: 0.2,
  stage: "Reading",
  eta_seconds: 60,
  error_code: null,
  error_message: null,
  result_ref: null,
  attempts: 1,
  created_at: "2026-11-20T10:00:00Z",
  started_at: "2026-11-20T10:00:01Z",
  finished_at: null,
  queue_position: null,
  ...over,
});
const event = (id, over = {}) => ({
  job_id: id,
  kind: "extract",
  status: "running",
  progress: 0.5,
  stage: "Thinking",
  eta_seconds: 30,
  error_code: null,
  error_message: null,
  result_ref: null,
  ...over,
});
const listKey = ["jobs", CID];
const detailKey = (id) => ["jobs", CID, id];
const invalidated = (qc, key) => qc.getQueryState(key)?.isInvalidated === true;

function seededJobs() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  qc.setQueryData(listKey, { jobs: [job(JOB), job(JOB2, { status: "queued", queue_position: 1, progress: null })] });
  qc.setQueryData(detailKey(JOB), job(JOB));
  qc.setQueryData(["jobs", OTHER], { jobs: [] });
  qc.setQueryData(["entities", CID], { seeded: true });
  return qc;
}

describe("Job cache merging", () => {
  test("the API paths and keys", () => {
    assert.equal(jobsApi.JOB_STREAM_PATH(CID), `/api/jobs/stream?campaign_id=${CID}`);
    assert.deepEqual(jobs.jobsListKey(CID), ["jobs", CID]);
    assert.deepEqual(jobs.jobKey(CID, JOB), ["jobs", CID, JOB]);
  });

  test("a progress event patches the list row and the detail, no refetch", () => {
    const qc = seededJobs();
    assert.equal(jobs.applyJobFrame(qc, CID, { event: "job", data: event(JOB) }), "job");
    const row = qc.getQueryData(listKey).jobs[0];
    assert.equal(row.progress, 0.5);
    assert.equal(row.stage, "Thinking");
    assert.equal(row.eta_seconds, 30);
    assert.equal(row.attempts, 1); // fields the event does not carry are kept
    assert.equal(qc.getQueryData(detailKey(JOB)).stage, "Thinking");
    assert.ok(!invalidated(qc, listKey) && !invalidated(qc, detailKey(JOB)));
    assert.equal(qc.getQueryData(listKey).jobs[1].progress, null); // other rows untouched
  });

  test("a status change patches, then refetches the list and the detail", () => {
    const qc = seededJobs();
    jobs.applyJobFrame(qc, CID, { event: "job", data: event(JOB, { status: "failed", error_code: "timeout", error_message: "Timed out" }) });
    assert.equal(qc.getQueryData(listKey).jobs[0].status, "failed");
    assert.equal(qc.getQueryData(detailKey(JOB)).error_code, "timeout");
    assert.ok(invalidated(qc, listKey) && invalidated(qc, detailKey(JOB)));
    assert.ok(!invalidated(qc, ["jobs", OTHER]) && !invalidated(qc, ["entities", CID]));
  });

  test("a queued Job that starts loses its queue position", () => {
    const qc = seededJobs();
    jobs.applyJobFrame(qc, CID, { event: "job", data: event(JOB2) });
    assert.equal(qc.getQueryData(listKey).jobs[1].queue_position, null);
    assert.ok(invalidated(qc, listKey));
  });

  test("an unknown Job refetches the list", () => {
    const qc = seededJobs();
    jobs.applyJobFrame(qc, CID, { event: "job", data: event("55555555-5555-4555-8555-555555555555") });
    assert.ok(invalidated(qc, listKey));
    assert.equal(qc.getQueryData(listKey).jobs.length, 2);
  });

  test("malformed job data and unknown events change nothing", () => {
    const qc = seededJobs();
    for (const data of [null, "x", {}, { job_id: JOB }, { job_id: JOB, kind: "k", status: "exploded" }, { job_id: 3, kind: "k", status: "done" }]) {
      assert.equal(jobs.applyJobFrame(qc, CID, { event: "job", data }), "other");
    }
    assert.equal(jobs.applyJobFrame(qc, CID, { event: "invalidate", data: {} }), "other");
    assert.equal(qc.getQueryData(listKey).jobs[0].progress, 0.2);
    assert.ok(!invalidated(qc, listKey));
  });

  test("subscribed refetches the Campaign's Job list and items only", () => {
    const qc = seededJobs();
    assert.equal(jobs.applyJobFrame(qc, CID, { event: "subscribed", data: {} }), "subscribed");
    assert.ok(invalidated(qc, listKey) && invalidated(qc, detailKey(JOB)));
    assert.ok(!invalidated(qc, ["jobs", OTHER]) && !invalidated(qc, ["entities", CID]));
  });

  test("runJobStream: the stream URL, every subscribed refetches, 404 stops and refetches", async () => {
    localStorage.setItem("lk_token", "tok-j");
    const qc = seededJobs();
    const calls = installFetch([
      streamOf([frame("subscribed", {}), frame("job", event(JOB, { progress: 0.9 }))]),
      streamOf([frame("subscribed", {})]),
      status(404),
    ]);
    const subscribedSeen = [];
    const realInvalidate = qc.invalidateQueries.bind(qc);
    qc.invalidateQueries = (filters) => {
      if (JSON.stringify(filters?.queryKey) === JSON.stringify(listKey) && !filters.exact) subscribedSeen.push(1);
      return realInvalidate(filters);
    };
    const stops = [];
    const reason = await jobs.runJobStream({
      campaignId: CID,
      queryClient: qc,
      signal: new AbortController().signal,
      sleep: async () => {},
      onStop: (r) => stops.push(r),
    });
    assert.equal(reason, "404");
    assert.deepEqual(stops, ["404"]);
    assert.equal(calls.length, 3);
    for (const { url, init } of calls) {
      assert.equal(url, `/api/jobs/stream?campaign_id=${CID}`);
      assert.equal(init.headers.Authorization, "Bearer tok-j");
    }
    // Two subscribed (one per stream) plus the 404 stop: three full Job refetches.
    assert.equal(subscribedSeen.length, 3);
    assert.equal(qc.getQueryData(listKey).jobs[0].progress, 0.9);
  });
});

// ─── Source guards ───────────────────────────────────────────────────────────

function walk(dir) {
  const out = [];
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) out.push(...walk(p));
    else if (/\.(ts|tsx|js|jsx|mjs)$/.test(name)) out.push(p);
  }
  return out;
}

describe("source guards", () => {
  const files = walk(srcDir).map((p) => ({ rel: relative(srcDir, p).split("\\").join("/"), text: readFileSync(p, "utf8") }));

  test("no EventSource and no token in a URL anywhere in src/", () => {
    for (const { rel, text } of files) {
      // Any use (comments may name it to say it is not used).
      assert.ok(!/new\s+EventSource|EventSource\s*\(|\.EventSource\b|\bEventSource\s*[<.]/.test(text), `${rel}: EventSource`);
      assert.ok(!/[?&]token=/.test(text), `${rel}: ?token=`);
    }
  });

  test("fetch stream readers only in lib/sse.ts (AdminPage model install deferred)", () => {
    const allowed = new Set(["lib/sse.ts", "pages/AdminPage.tsx"]);
    for (const { rel, text } of files) {
      if (allowed.has(rel)) continue;
      assert.ok(!/\.getReader\(|\.body\s*\.\s*pipeThrough|text\/event-stream/.test(text), `${rel}: reads a stream itself`);
    }
  });

  test("chat, Campaign events and Jobs all stream through openSse; chat never reconnects", () => {
    const read = (rel) => files.find((f) => f.rel === rel).text;
    for (const rel of ["hooks/useChat.ts", "hooks/useCampaignEvents.ts", "hooks/useJobStream.ts"]) {
      assert.ok(/\bopenSse\(/.test(read(rel)), `${rel}: openSse`);
      assert.ok(!/\bfetch\(/.test(read(rel)), `${rel}: no direct fetch`);
    }
    const chat = read("hooks/useChat.ts");
    assert.ok(/reconnect:\s*false/.test(chat));
    assert.ok(/idleMs:\s*null/.test(chat));
    assert.ok(/\.abort\(\)/.test(chat), "the chat stream is aborted on unmount");
  });

  test("the shell does not mount the Job stream (the tray, E0-Jobs.10, does)", () => {
    const app = readFileSync(join(srcDir, "App.tsx"), "utf8");
    assert.ok(!/<JobStreamSubscriber\b/.test(app));
  });
});
