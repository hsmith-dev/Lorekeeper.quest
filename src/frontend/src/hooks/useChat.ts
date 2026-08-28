import { useState, useCallback } from "react";
import type { AxiosError } from "axios";
import type { ChatMessage, JournalSource, RetrievalDebug } from "../types";
import { sendChatMessage, getChatSession } from "../services/api";

/** A chat message as the UI renders it — assistant messages carry their RAG
 *  metadata (sources, grounded flag, retrieval trace) directly, so streaming
 *  updates never have to keep parallel index maps in sync. */
export interface UiChatMessage extends ChatMessage {
  sources?: JournalSource[];
  grounded?: boolean;
  retrieval?: RetrievalDebug | null;
}

function extractError(err: unknown): string {
  const axiosErr = err as AxiosError<{ detail?: string }>;
  if (axiosErr?.response?.data?.detail) return axiosErr.response.data.detail;
  if (axiosErr?.response?.status === 503) return "503: AI model unavailable.";
  if (err instanceof Error) return err.message;
  return "Something went wrong.";
}

/** Parse one SSE frame ("event: x\ndata: {...}") into {event, data}. */
function parseSseFrame(frame: string): { event: string; data: unknown } | null {
  let event = "message";
  let dataLine: string | null = null;
  for (const line of frame.split("\n")) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) dataLine = line.slice(5).trim();
  }
  if (dataLine === null) return null;
  try {
    return { event, data: JSON.parse(dataLine) };
  } catch {
    return null;
  }
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

  /** Streaming send over SSE. Returns the new session id, or throws to let
   *  the caller fall back to the blocking endpoint. */
  const sendStreaming = useCallback(
    async (text: string, campaignId?: string, currentSessionId?: string | null): Promise<string> => {
      const token = localStorage.getItem("lk_token");
      const resp = await fetch("/api/chat/stream", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({
          message: text,
          campaign_id: campaignId,
          session_id: currentSessionId ?? undefined,
        }),
      });
      if (!resp.ok || !resp.body) throw new Error(`stream unavailable (${resp.status})`);

      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let newSessionId = "";
      let acc = "";

      // eslint-disable-next-line no-constant-condition
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        let sep: number;
        while ((sep = buffer.indexOf("\n\n")) !== -1) {
          const frame = buffer.slice(0, sep);
          buffer = buffer.slice(sep + 2);
          const parsed = parseSseFrame(frame);
          if (!parsed) continue;

          if (parsed.event === "meta") {
            const meta = parsed.data as {
              session_id: string;
              sources: JournalSource[];
              grounded: boolean;
              retrieval: RetrievalDebug | null;
            };
            newSessionId = meta.session_id;
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
              },
            ]);
            setIsStreaming(true);
          } else if (parsed.event === "delta") {
            acc += (parsed.data as { text: string }).text;
            patchLastAssistant(setMessages, { content: acc });
          } else if (parsed.event === "error") {
            throw new Error((parsed.data as { detail?: string }).detail || "AI model unavailable.");
          } else if (parsed.event === "done") {
            const full = (parsed.data as { reply?: string }).reply;
            if (full) patchLastAssistant(setMessages, { content: full });
          }
        }
      }
      if (!newSessionId) throw new Error("stream ended before metadata arrived");
      if (!acc.trim()) throw new Error("stream ended with no reply");
      return newSessionId;
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
      } catch {
        // Drop any partial assistant message the stream created, then retry
        // via the blocking endpoint.
        setMessages((prev) => {
          const next = [...prev];
          if (next.length && next[next.length - 1].role === "assistant") next.pop();
          return next;
        });
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
    [sessionId, isLoading, sendStreaming]
  );

  const loadSession = useCallback(async (id: string) => {
    setIsLoading(true);
    setError(null);
    try {
      const { data } = await getChatSession(id);
      setSessionId(data.id);
      setMessages(data.messages);
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
