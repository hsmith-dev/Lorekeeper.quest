import { useState, useCallback } from "react";
import type { AxiosError } from "axios";
import type { ChatMessage, JournalSource } from "../types";
import { sendChatMessage, getChatSession } from "../services/api";

function extractError(err: unknown): string {
  const axiosErr = err as AxiosError<{ detail?: string }>;
  if (axiosErr?.response?.data?.detail) return axiosErr.response.data.detail;
  if (axiosErr?.response?.status === 503) return "503: AI model unavailable.";
  if (err instanceof Error) return err.message;
  return "Something went wrong.";
}

export function useChat() {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  // sources[i] holds RAG sources for messages[i] (assistant messages only)
  const [sources, setSources] = useState<Record<number, JournalSource[]>>({});
  // ungrounded[i] marks assistant messages[i] that answered a campaign
  // question with no retrieved context backing them (ChatResponse.grounded
  // === false) — rendered with a "not from your journal" notice.
  const [ungrounded, setUngrounded] = useState<Record<number, boolean>>({});
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const send = useCallback(
    async (text: string, campaignId?: string) => {
      if (!text.trim() || isLoading) return;

      setMessages((prev) => [...prev, { role: "user", content: text }]);
      setIsLoading(true);
      setError(null);

      try {
        const { data } = await sendChatMessage({
          message: text,
          campaign_id: campaignId,
          session_id: sessionId ?? undefined,
        });
        setMessages((prev) => {
          const next = [...prev, { role: "assistant" as const, content: data.reply }];
          if (data.sources?.length) {
            setSources((s) => ({ ...s, [next.length - 1]: data.sources }));
          }
          if (data.grounded === false) {
            setUngrounded((u) => ({ ...u, [next.length - 1]: true }));
          }
          return next;
        });
        setSessionId(data.session_id);
        return data.session_id;
      } catch (err) {
        setError(extractError(err));
        setMessages((prev) => prev.slice(0, -1));
      } finally {
        setIsLoading(false);
      }
    },
    [sessionId, isLoading]
  );

  const loadSession = useCallback(async (id: string) => {
    setIsLoading(true);
    setError(null);
    try {
      const { data } = await getChatSession(id);
      setSessionId(data.id);
      setMessages(data.messages);
      setSources({});
      setUngrounded({});
    } catch (err) {
      setError(extractError(err));
    } finally {
      setIsLoading(false);
    }
  }, []);

  const newSession = useCallback(() => {
    setSessionId(null);
    setMessages([]);
    setSources({});
    setUngrounded({});
    setError(null);
  }, []);

  return { sessionId, messages, sources, ungrounded, isLoading, error, send, loadSession, newSession };
}
