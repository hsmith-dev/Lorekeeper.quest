import { useState, useCallback, useEffect, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";
import type { AxiosError } from "axios";
import { openSse, type Connect } from "../lib/sse";
import { campaignRoleKey } from "./useCampaignRole";
import type { ChatMessage, JournalSource, ResolvedSource, RetrievalDebug } from "../types";
import { sendChatMessage, getChatSession } from "../services/api";

/** A chat message as the UI renders it — assistant messages carry their RAG
 *  metadata (sources, grounded flag, retrieval trace) directly, so streaming
 *  updates never have to keep parallel index maps in sync. */
export interface UiChatMessage extends ChatMessage {
  sources?: JournalSource[];
  grounded?: boolean;
  retrieval?: RetrievalDebug | null;
  citations?: ResolvedSource[];
}

function extractError(err: unknown): string {
  const axiosErr = err as AxiosError<{ detail?: string }>;
  if (axiosErr?.response?.data?.detail) return axiosErr.response.data.detail;
  if (axiosErr?.response?.status === 503) return "503: AI model unavailable.";
  if (err instanceof Error) return err.message;
  return "Something went wrong.";
}

/** The chat stream's URL (same base as services/api.ts). */
export const CHAT_STREAM_PATH = `${import.meta.env.VITE_API_URL ?? ""}/api/chat/stream`;

/** The server's uniform "no access" detail (a revoked grant mid-stream). */
const NOT_FOUND_DETAIL = "Not found";

// A promotion ends the stream too, so this must not claim access was lost.
export const REVOKED_MESSAGE = "Your access to this campaign changed, so this reply was stopped. Send your message again.";

/** The grant changed mid-turn: the server dropped the turn. Never retried. */
class ChatRevoked extends Error {}
/** The hook unmounted (or the turn was cancelled): nothing to fall back to. */
class ChatAborted extends Error {}

/** The `meta` event: known before the first token. */
export interface ChatStreamMeta {
  session_id: string;
  sources: JournalSource[];
  grounded: boolean;
  retrieval: RetrievalDebug | null;
  citations?: ResolvedSource[];
}

/** How one streaming chat turn ended. Only "fallback" retries via the blocking POST. */
export type ChatTurnResult =
  | { kind: "ok"; sessionId: string }
  | { kind: "revoked" }
  | { kind: "aborted" }
  | { kind: "fallback"; reason: string };

export interface StreamChatTurnOptions {
  signal: AbortSignal;
  onMeta: (meta: ChatStreamMeta) => void;
  /** The reply so far (all deltas joined). */
  onDelta: (text: string) => void;
  /** The full reply from `done`, when the server sent one. */
  onDone: (reply: string) => void;
  connect?: Connect;
  headers?: () => Record<string, string> | null;
}

/**
 * Stream one chat turn (lib/sse.ts, one-shot: a POST is never replayed) and
 * classify how it ended: ok, revoked (`error {"detail":"Not found"}`: the
 * grant changed), aborted (unmount), or fallback (anything else: a status, a
 * network error, a model error, no token, no metadata or no reply).
 */
export async function streamChatTurn(
  url: string,
  body: unknown,
  { signal, onMeta, onDelta, onDone, connect, headers }: StreamChatTurnOptions,
): Promise<ChatTurnResult> {
  let sessionId = "";
  let acc = "";
  let reason: string;
  try {
    reason = await openSse(url, {
      method: "POST",
      body,
      signal,
      reconnect: false,
      // No pings on the chat stream, and the first token can take over
      // 45 s on CPU: no idle watchdog.
      idleMs: null,
      connect,
      headers,
      onEvent: (parsed) => {
        if (parsed.event === "meta") {
          const meta = parsed.data as ChatStreamMeta;
          sessionId = meta.session_id;
          onMeta(meta);
        } else if (parsed.event === "delta") {
          acc += (parsed.data as { text: string }).text;
          onDelta(acc);
        } else if (parsed.event === "error") {
          const detail = (parsed.data as { detail?: string } | null)?.detail;
          // Thrown out of openSse: the reader is cancelled, the turn ends.
          if (detail === NOT_FOUND_DETAIL) throw new ChatRevoked(detail);
          throw new Error(detail || "AI model unavailable.");
        } else if (parsed.event === "done") {
          const full = (parsed.data as { reply?: string }).reply;
          if (full) onDone(full);
        }
      },
    });
  } catch (err) {
    if (signal.aborted) return { kind: "aborted" };
    if (err instanceof ChatRevoked) return { kind: "revoked" };
    return { kind: "fallback", reason: err instanceof Error ? err.message : "stream failed" };
  }
  if (reason === "aborted") return { kind: "aborted" };
  if (reason !== "ended") return { kind: "fallback", reason: `stream unavailable (${reason})` };
  if (!sessionId) return { kind: "fallback", reason: "stream ended before metadata arrived" };
  if (!acc.trim()) return { kind: "fallback", reason: "stream ended with no reply" };
  return { kind: "ok", sessionId };
}

/** Replace the last assistant message via an updater. */
function patchLastAssistant(
  setMessages: React.Dispatch<React.SetStateAction<UiChatMessage[]>>,
  patch: Partial<UiChatMessage>
) {
  setMessages((prev) => {
    if (!prev.length || prev[prev.length - 1].role !== "assistant") return prev;
    const next = [...prev];
    next[next.length - 1] = { ...next[next.length - 1], ...patch };
    return next;
  });
}

export function useChat() {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<UiChatMessage[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  // True while tokens are streaming into the final assistant message.
  const [isStreaming, setIsStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const queryClient = useQueryClient();
  // The in-flight streaming turn; aborted on unmount so the server sees the
  // disconnect and frees the LLM slot.
  const streamRef = useRef<AbortController | null>(null);
  useEffect(() => () => streamRef.current?.abort(), []);

  /** Streaming send over SSE (lib/sse.ts, one-shot: a POST is never replayed).
   *  Returns the new session id, or throws to let the caller fall back to the
   *  blocking endpoint (ChatRevoked and ChatAborted never fall back). */
  const sendStreaming = useCallback(
    async (text: string, campaignId?: string, currentSessionId?: string | null): Promise<string> => {
      streamRef.current?.abort();
      const controller = new AbortController();
      streamRef.current = controller;
      try {
        const result = await streamChatTurn(
          CHAT_STREAM_PATH,
          {
            message: text,
            campaign_id: campaignId,
            session_id: currentSessionId ?? undefined,
          },
          {
            signal: controller.signal,
            onMeta: (meta) => {
              // Sources and the retrieval trace are known before the first
              // token — attach them to an initially-empty assistant message.
              setMessages((prev) => [
                ...prev,
                {
                  role: "assistant",
                  content: "",
                  sources: meta.sources ?? [],
                  grounded: meta.grounded,
                  retrieval: meta.retrieval,
                  citations: meta.citations ?? [],
                },
              ]);
              setIsStreaming(true);
            },
            onDelta: (content) => patchLastAssistant(setMessages, { content }),
            onDone: (content) => patchLastAssistant(setMessages, { content }),
          },
        );
        if (result.kind === "ok") return result.sessionId;
        if (result.kind === "aborted") throw new ChatAborted("aborted");
        if (result.kind === "revoked") throw new ChatRevoked(NOT_FOUND_DETAIL);
        throw new Error(result.reason);
      } finally {
        if (streamRef.current === controller) streamRef.current = null;
      }
    },
    []
  );

  const send = useCallback(
    async (text: string, campaignId?: string) => {
      if (!text.trim() || isLoading) return;

      setMessages((prev) => [...prev, { role: "user", content: text }]);
      setIsLoading(true);
      setError(null);

      // Prefer the streaming endpoint; fall back to the blocking one on any
      // failure (proxy without SSE support, provider error mid-setup, …).
      try {
        const sid = await sendStreaming(text, campaignId, sessionId);
        setSessionId(sid);
        return sid;
      } catch (err) {
        // The hook unmounted mid-stream: the fetch is aborted, nothing to show.
        if (err instanceof ChatAborted) return;
        const revoked = err instanceof ChatRevoked;
        // Drop any partial assistant message the stream created (and, when the
        // grant was revoked, the user turn the server did not keep), then retry
        // via the blocking endpoint unless revoked.
        setMessages((prev) => {
          const next = [...prev];
          if (next.length && next[next.length - 1].role === "assistant") next.pop();
          if (revoked && next.length && next[next.length - 1].role === "user") next.pop();
          return next;
        });
        if (revoked) {
          setError(REVOKED_MESSAGE);
          if (campaignId) void queryClient.invalidateQueries({ queryKey: campaignRoleKey(campaignId) });
          return;
        }
      } finally {
        setIsStreaming(false);
        setIsLoading(false);
      }

      setIsLoading(true);
      try {
        const { data } = await sendChatMessage({
          message: text,
          campaign_id: campaignId,
          session_id: sessionId ?? undefined,
        });
        setMessages((prev) => [
          ...prev,
          {
            role: "assistant",
            content: data.reply,
            sources: data.sources ?? [],
            grounded: data.grounded,
            retrieval: data.retrieval ?? null,
            citations: data.citations ?? [],
          },
        ]);
        setSessionId(data.session_id);
        return data.session_id;
      } catch (err) {
        setError(extractError(err));
        setMessages((prev) => prev.slice(0, -1));
      } finally {
        setIsLoading(false);
      }
    },
    [sessionId, isLoading, sendStreaming, queryClient]
  );

  const loadSession = useCallback(async (id: string) => {
    setIsLoading(true);
    setError(null);
    try {
      const { data } = await getChatSession(id);
      setSessionId(data.id);
      // A stored message carries its grounded flag; a redacted one is a notice.
      setMessages(data.messages.map((m) => ({ ...m, grounded: m.grounded ?? undefined })));
    } catch (err) {
      setError(extractError(err));
    } finally {
      setIsLoading(false);
    }
  }, []);

  const newSession = useCallback(() => {
    setSessionId(null);
    setMessages([]);
    setError(null);
  }, []);

  return { sessionId, messages, isLoading, isStreaming, error, send, loadSession, newSession };
}
