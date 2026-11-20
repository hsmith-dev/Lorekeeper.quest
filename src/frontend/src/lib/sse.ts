// The one SSE client of the frontend (E0-Jobs.9, AR-24). Every server stream
// goes through `openSse`: the Campaign events stream (hooks/useCampaignEvents),
// the Job stream (hooks/useJobStream) and the chat POST (hooks/useChat).
//
// Transport: fetch + ReadableStream. Auth goes only in the
// `Authorization: Bearer` header (never EventSource, never a token in the URL),
// plus `X-Lorekeeper-Preview` while preview is active (lib/preview.ts). With no
// `lk_token` it never connects and ends with "no_token".
//
// Every server stream emits the same control frames (app/core/sse.py):
//
//   event: subscribed      {}                     the subscription is live (resync point)
//   event: ping            {}                     keep-alive every 15 s; never reaches onEvent
//   event: access_changed  {"detail":"Not found"} the grant changed; the stream ends
//
// Resync contract: there are no event ids and no replay. Every `subscribed`
// (the first and each one after a reconnect) is passed to the caller, who
// refetches; anything read before it may be stale.
//
// Reconnects (`reconnect: true`, the default): backoff 1 s doubling to 30 s
// with jitter (x0.5-1), reset by `subscribed`. After `access_changed` it
// reconnects once at once (a promotion fires it too); a second one without a
// `subscribed` in between backs off. It stops on abort, 401 and 404. A stream
// silent for `idleMs` (45 s; pings arrive every 15 s) is dead: ended as an
// error, then reconnected.
//
// One-shot (`reconnect: false`): one connection, never replayed (a chat POST).
// The end reason says how it went: "ended", "error", "aborted", "no_token" or
// the HTTP status of a non-stream answer ("503").
//
// An exception thrown by `onEvent` cancels the reader. One-shot, it propagates
// out of `openSse` (useChat ends a turn on `error` this way). Reconnecting, it
// is logged and ends that connection as an error: back off, then reconnect.

import { previewHeaders } from "./preview";

export const BACKOFF_BASE_MS = 1_000;
export const BACKOFF_MAX_MS = 30_000;
/** No chunk (pings included, every 15 s) for this long: the connection is dead. */
export const IDLE_TIMEOUT_MS = 45_000;

// ─── Frames ──────────────────────────────────────────────────────────────────

export interface SseFrame {
  event: string;
  data: unknown;
}

/** Parse one SSE frame ("event: x\ndata: {...}"); multi-line data is joined with "\n". */
export function parseSseFrame(frame: string): SseFrame | null {
  let event = "message";
  const data: string[] = [];
  for (const raw of frame.split(/\r\n|\r|\n/)) {
    if (raw === "" || raw.startsWith(":")) continue;
    const colon = raw.indexOf(":");
    const field = colon === -1 ? raw : raw.slice(0, colon);
    let value = colon === -1 ? "" : raw.slice(colon + 1);
    if (value.startsWith(" ")) value = value.slice(1);
    if (field === "event") event = value;
    else if (field === "data") data.push(value);
  }
  if (data.length === 0) return null;
  try {
    return { event, data: JSON.parse(data.join("\n")) };
  } catch {
    return null;
  }
}

/** A stateful splitter: feed decoded text chunks, get whole frames back. */
export function createFrameSplitter(): (chunk: string) => SseFrame[] {
  let buffer = "";
  return (chunk: string) => {
    buffer += chunk;
    const frames: SseFrame[] = [];
    for (;;) {
      const match = /\r\n\r\n|\n\n|\r\r/.exec(buffer);
      if (!match) break;
      const frame = parseSseFrame(buffer.slice(0, match.index));
      buffer = buffer.slice(match.index + match[0].length);
      if (frame) frames.push(frame);
    }
    return frames;
  };
}

// ─── Headers ─────────────────────────────────────────────────────────────────

/** Bearer + preview headers for a stream request, or null without a token. */
export function sseHeaders(): Record<string, string> | null {
  let token: string | null = null;
  try {
    token = localStorage.getItem("lk_token");
  } catch {
    token = null;
  }
  if (!token) return null;
  return { Authorization: `Bearer ${token}`, ...previewHeaders() };
}

// ─── Reconnect policy ────────────────────────────────────────────────────────

/** How one connection ended. */
export type StreamOutcome =
  | { kind: "status"; status: number } // the server answered without a stream
  | { kind: "ended"; accessChanged: boolean; subscribed: boolean } // a stream that ran, then ended
  | { kind: "error" } // network failure or idle watchdog
  | { kind: "aborted" };

export interface ReconnectState {
  /** Failed attempts since the last `subscribed`. */
  attempt: number;
  /** An `access_changed` reconnect was just used and no stream has subscribed since. */
  accessRetryUsed: boolean;
}

export type ReconnectDecision = { action: "stop"; reason: string } | { action: "reconnect"; delayMs: number };

export function backoffMs(attempt: number, random: () => number = Math.random): number {
  const ceiling = Math.min(BACKOFF_MAX_MS, BACKOFF_BASE_MS * 2 ** Math.max(0, attempt));
  return Math.round(ceiling * (0.5 + random() / 2));
}

/** Decide what follows `outcome`, updating `state` in place. */
export function nextStep(
  outcome: StreamOutcome,
  state: ReconnectState,
  random: () => number = Math.random,
): ReconnectDecision {
  if (outcome.kind === "aborted") return { action: "stop", reason: "aborted" };
  if (outcome.kind === "status" && (outcome.status === 401 || outcome.status === 404)) {
    return { action: "stop", reason: String(outcome.status) };
  }
  if (outcome.kind === "ended" && outcome.subscribed) {
    state.attempt = 0;
    state.accessRetryUsed = false;
  }
  if (outcome.kind === "ended" && outcome.accessChanged && !state.accessRetryUsed) {
    state.accessRetryUsed = true;
    return { action: "reconnect", delayMs: 0 };
  }
  const delayMs = backoffMs(state.attempt, random);
  state.attempt += 1;
  return { action: "reconnect", delayMs };
}

// ─── One connection ──────────────────────────────────────────────────────────

export type ConnectResult =
  | { kind: "status"; status: number }
  | { kind: "ended" }
  | { kind: "error" }
  | { kind: "aborted" };

export interface ConnectOptions {
  method?: "GET" | "POST";
  /** Sent as JSON (with `Content-Type: application/json`). */
  body?: unknown;
  /** Idle watchdog; null turns it off. Default 45 s. */
  idleMs?: number | null;
}

/** One connection: (url, headers, signal, onFrame, options) → how it ended. */
export type Connect = (
  url: string,
  headers: Record<string, string>,
  signal: AbortSignal,
  onFrame: (frame: SseFrame) => void,
  options?: ConnectOptions,
) => Promise<ConnectResult>;

/**
 * Open one fetch stream and feed its frames (pings included) to `onFrame`.
 * Abort (the caller's signal) cancels the fetch and the reader, so the server
 * sees the disconnect. An exception from `onFrame` cancels the reader and is
 * rethrown.
 */
export const connectSse: Connect = async (url, headers, signal, onFrame, options = {}) => {
  const { method = "GET", body, idleMs = IDLE_TIMEOUT_MS } = options;
  if (signal.aborted) return { kind: "aborted" };
  // Our own controller: aborted by the caller's signal or by the idle watchdog
  // (a half-open connection never errors on its own).
  const local = new AbortController();
  const forward = () => local.abort();
  signal.addEventListener("abort", forward);
  let idle: ReturnType<typeof setTimeout> | undefined;
  const arm = () => {
    if (idleMs === null) return;
    if (idle !== undefined) clearTimeout(idle);
    idle = setTimeout(() => local.abort(), idleMs);
  };
  const outcome = (fallback: "ended" | "error"): ConnectResult => {
    if (signal.aborted) return { kind: "aborted" };
    if (local.signal.aborted) return { kind: "error" };
    return { kind: fallback };
  };
  try {
    let resp: Response;
    arm();
    try {
      resp = await fetch(url, {
        method,
        headers: {
          Accept: "text/event-stream",
          ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
          ...headers,
        },
        body: body !== undefined ? JSON.stringify(body) : undefined,
        signal: local.signal,
        cache: "no-store",
      });
    } catch {
      return outcome("error");
    }
    if (!resp.ok || !resp.body) {
      void resp.body?.cancel().catch(() => undefined);
      return { kind: "status", status: resp.status };
    }
    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    const split = createFrameSplitter();
    let thrown: { error: unknown } | null = null;
    try {
      read: for (;;) {
        arm();
        const { done, value } = await reader.read();
        if (done) break;
        for (const frame of split(decoder.decode(value, { stream: true }))) {
          try {
            onFrame(frame);
          } catch (error) {
            thrown = { error };
            break read;
          }
        }
      }
    } catch {
      return outcome("error");
    } finally {
      void reader.cancel().catch(() => undefined);
    }
    if (thrown) throw thrown.error;
    return outcome("ended");
  } finally {
    if (idle !== undefined) clearTimeout(idle);
    signal.removeEventListener("abort", forward);
  }
};

// ─── The loop ────────────────────────────────────────────────────────────────

/**
 * How `openSse` ended: "aborted", "no_token", "401", "404"; one-shot also
 * "ended", "error" or another status ("503").
 */
export type SseEndReason = string;

export interface OpenSseOptions extends ConnectOptions {
  /** Every frame but `ping` (`subscribed` and `access_changed` included). */
  onEvent: (frame: SseFrame) => void;
  signal: AbortSignal;
  /** Reconnect per the policy above (default), or one connection only. */
  reconnect?: boolean;
  /** Called once when it ends for good (not on abort). */
  onStop?: (reason: SseEndReason) => void;
  /** Request headers; null means no token (default `sseHeaders`). */
  headers?: () => Record<string, string> | null;
  connect?: Connect;
  sleep?: (ms: number, signal: AbortSignal) => Promise<void>;
  random?: () => number;
}

export const abortableSleep = (ms: number, signal: AbortSignal) =>
  new Promise<void>((resolve) => {
    if (signal.aborted) return resolve();
    const timer = setTimeout(done, ms);
    function done() {
      clearTimeout(timer);
      signal.removeEventListener("abort", done);
      resolve();
    }
    signal.addEventListener("abort", done);
  });

/** Connect, deliver frames, reconnect per `nextStep`, until stopped or aborted. */
export async function openSse(
  url: string,
  {
    method,
    body,
    idleMs,
    onEvent,
    signal,
    reconnect = true,
    onStop,
    headers = sseHeaders,
    connect = connectSse,
    sleep = abortableSleep,
    random = Math.random,
  }: OpenSseOptions,
): Promise<SseEndReason> {
  const state: ReconnectState = { attempt: 0, accessRetryUsed: false };
  const stop = (reason: SseEndReason): SseEndReason => {
    if (reason !== "aborted") onStop?.(reason);
    return reason;
  };
  for (;;) {
    if (signal.aborted) return "aborted";
    const hdrs = headers();
    if (!hdrs) return stop("no_token");
    let subscribed = false;
    let accessChanged = false;
    let result: ConnectResult;
    try {
      result = await connect(
        url,
        hdrs,
        signal,
        (frame) => {
          if (frame.event === "ping") return;
          if (frame.event === "subscribed") {
            subscribed = true;
            state.attempt = 0;
            state.accessRetryUsed = false;
          } else if (frame.event === "access_changed") {
            accessChanged = true;
          }
          onEvent(frame);
        },
        { method, body, idleMs },
      );
    } catch (error) {
      if (!reconnect) throw error;
      // A handler bug must not end a long-lived stream for good.
      console.error("openSse: onEvent threw; reconnecting", error);
      result = signal.aborted ? { kind: "aborted" } : { kind: "error" };
    }
    if (!reconnect) {
      return stop(result.kind === "status" ? String(result.status) : result.kind);
    }
    const outcome: StreamOutcome = result.kind === "ended" ? { kind: "ended", accessChanged, subscribed } : result;
    const step = nextStep(outcome, state, random);
    if (step.action === "stop") return stop(step.reason);
    if (step.delayMs > 0) await sleep(step.delayMs, signal);
  }
}
