import { useState, useRef, useEffect } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { getCampaigns, getChatHealth, getChatSessions, deleteChatSession } from "../services/api";
import { useDebounce } from "../hooks/useDebounce";
import { useChat } from "../hooks/useChat";
import type { Campaign, ChatSessionSummary, JournalSource, RetrievalDebug } from "../types";

const METHOD_LABEL: Record<string, string> = {
  semantic: "semantic match",
  keyword: "keyword match",
  both: "semantic + keyword",
};

/** "How this answer was built" — the retrieval trace behind an assistant
 *  reply: rewritten query, every candidate either retriever surfaced with
 *  its scores and gate verdict, and the exact system prompt the model saw.
 *  Groundedness as something you can inspect, not something we assert. */
function RetrievalPanel({ retrieval }: { retrieval: RetrievalDebug }) {
  const [open, setOpen] = useState(false);
  const [showPrompt, setShowPrompt] = useState(false);
  return (
    <div className="max-w-[82%] mt-1">
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors"
      >
        <svg width="12" height="12" viewBox="0 0 20 20" fill="currentColor" className={`transition-transform ${open ? "rotate-90" : ""}`}>
          <path fillRule="evenodd" clipRule="evenodd" d="M7.293 14.707a1 1 0 010-1.414L10.586 10 7.293 6.707a1 1 0 011.414-1.414l4 4a1 1 0 010 1.414l-4 4a1 1 0 01-1.414 0z" />
        </svg>
        How this answer was built
      </button>
      {open && (
        <div className="mt-1.5 rounded-md border border-border bg-muted/30 px-3 py-2.5 text-xs flex flex-col gap-2.5">
          <div>
            <p className="font-semibold text-foreground mb-0.5">Retrieval query</p>
            <p className="text-muted-foreground font-mono">{retrieval.query}</p>
            {retrieval.rewritten_from && (
              <p className="text-muted-foreground mt-0.5">
                rewritten from: <span className="italic">“{retrieval.rewritten_from}”</span>
              </p>
            )}
          </div>
          <div>
            <p className="font-semibold text-foreground mb-1">
              Candidates considered <span className="font-normal text-muted-foreground">(vector-relevance gate ≤ {retrieval.threshold})</span>
            </p>
            {retrieval.candidates.length === 0 ? (
              <p className="text-muted-foreground italic">Neither retriever surfaced any journal entries.</p>
            ) : (
              <div className="flex flex-col gap-1">
                {retrieval.candidates.map((c) => (
                  <div key={c.id} className={`flex items-baseline gap-2 ${c.used ? "" : "opacity-55"}`}>
                    <span className={`shrink-0 font-mono ${c.used ? "text-green-600 dark:text-green-400" : c.passed_gate ? "text-muted-foreground" : "text-amber-600 dark:text-amber-400"}`}>
                      {c.used ? "✓ used" : c.passed_gate ? "· passed" : "✗ gated"}
                    </span>
                    <span className="truncate text-muted-foreground">{c.shorthand}</span>
                    <span className="shrink-0 font-mono text-muted-foreground">
                      {c.vector_distance != null ? `d=${c.vector_distance.toFixed(3)}` : "d=—"}
                      {c.lexical_rank != null ? ` · fts#${c.lexical_rank}` : ""}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
          {retrieval.system_prompt && (
            <div>
              <button onClick={() => setShowPrompt((p) => !p)} className="font-semibold text-foreground hover:text-primary transition-colors">
                {showPrompt ? "▾ Hide" : "▸ Show"} the exact prompt the model saw
              </button>
              {showPrompt && (
                <pre className="mt-1 max-h-56 overflow-auto whitespace-pre-wrap rounded bg-background/60 border border-border p-2 font-mono text-[11px] leading-relaxed text-muted-foreground">{retrieval.system_prompt}</pre>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function SourcesPanel({ sources }: { sources: JournalSource[] }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="max-w-[82%] mt-1">
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors"
      >
        <svg width="12" height="12" viewBox="0 0 20 20" fill="currentColor" className={`transition-transform ${open ? "rotate-90" : ""}`}>
          <path fillRule="evenodd" clipRule="evenodd" d="M7.293 14.707a1 1 0 010-1.414L10.586 10 7.293 6.707a1 1 0 011.414-1.414l4 4a1 1 0 010 1.414l-4 4a1 1 0 01-1.414 0z" />
        </svg>
        {sources.length} journal {sources.length === 1 ? "source" : "sources"} used
      </button>
      {open && (
        <div className="mt-1.5 flex flex-col gap-2">
          {sources.map((s) => (
            <div key={s.id} className="rounded-md border border-border bg-muted/30 px-3 py-2 text-xs">
              {s.session_date && (
                <p className="text-muted-foreground mb-1 font-medium">{s.session_date}</p>
              )}
              <p className="text-muted-foreground italic mb-1 truncate">Notes: {s.shorthand}</p>
              <p className="text-foreground leading-relaxed">{s.snippet}…</p>
              {s.method && (
                <p className="mt-1 font-mono text-[11px] text-muted-foreground">
                  {METHOD_LABEL[s.method] ?? s.method}
                  {s.distance != null ? ` · distance ${s.distance.toFixed(3)}` : ""}
                </p>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function AIStatus() {
  const { data, isLoading } = useQuery({
    queryKey: ["chat-health"],
    queryFn: () => getChatHealth().then((r) => r.data),
    refetchInterval: 30_000,
    retry: false,
  });
  if (isLoading) return null;
  return (
    <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
      <span className={`w-2 h-2 rounded-full ${data?.ai_online ? "bg-green-500" : "bg-red-500"}`} />
      {data?.ai_online ? "AI online" : "AI offline"}
    </div>
  );
}

function SessionItem({
  session,
  active,
  onSelect,
  onDelete,
}: {
  session: ChatSessionSummary;
  active: boolean;
  onSelect: () => void;
  onDelete: () => void;
}) {
  const date = new Date(session.updated_at).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
  });

  return (
    <div
      className={`group flex items-start justify-between gap-2 rounded-lg px-3 py-2.5 cursor-pointer transition-colors ${
        active ? "bg-muted text-foreground" : "hover:bg-muted/50 text-muted-foreground hover:text-foreground"
      }`}
      onClick={onSelect}
    >
      <div className="flex flex-col gap-0.5 min-w-0">
        <p className="text-sm font-medium truncate leading-tight">{session.title}</p>
        <p className="text-xs opacity-60 truncate">
          {session.campaign_name ? `${session.campaign_name} · ` : ""}
          {session.message_count / 2 | 0} exchanges · {date}
        </p>
      </div>
      <button
        onClick={(e) => { e.stopPropagation(); onDelete(); }}
        className="shrink-0 opacity-0 group-hover:opacity-100 p-1 rounded text-muted-foreground hover:text-destructive transition-all"
        title="Delete conversation"
      >
        <svg width="14" height="14" viewBox="0 0 20 20" fill="currentColor">
          <path fillRule="evenodd" clipRule="evenodd" d="M9 2a1 1 0 00-.894.553L7.382 4H4a1 1 0 000 2v10a2 2 0 002 2h8a2 2 0 002-2V6a1 1 0 100-2h-3.382l-.724-1.447A1 1 0 0011 2H9zM7 8a1 1 0 012 0v6a1 1 0 11-2 0V8zm5-1a1 1 0 00-1 1v6a1 1 0 102 0V8a1 1 0 00-1-1z" />
        </svg>
      </button>
    </div>
  );
}

export function ChatPage() {
  const [campaignId, setCampaignId] = useState<string>("");
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [sessionSearch, setSessionSearch] = useState("");
  const { sessionId, messages, isLoading, isStreaming, error, send, loadSession, newSession } = useChat();
  const [input, setInput] = useState("");
  const bottomRef = useRef<HTMLDivElement>(null);
  const qc = useQueryClient();
  const debouncedSearch = useDebounce(sessionSearch, 300);

  const { data: campaignData } = useQuery({
    queryKey: ["campaigns"],
    queryFn: () => getCampaigns().then((r) => r.data as Campaign[]),
  });

  const { data: sessions, isLoading: sessionsLoading } = useQuery({
    queryKey: ["chat-sessions", debouncedSearch],
    queryFn: () => getChatSessions(debouncedSearch || undefined).then((r) => r.data),
  });

  // Auto-select only campaign
  useEffect(() => {
    if (campaignData?.length === 1 && !campaignId) setCampaignId(campaignData[0].id);
  }, [campaignData, campaignId]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isLoading]);

  const handleSend = async () => {
    const text = input.trim();
    if (!text) return;
    setInput("");
    const newId = await send(text, campaignId || undefined);
    if (newId) qc.invalidateQueries({ queryKey: ["chat-sessions"] });  // invalidates all search variants
  };

  const handleKey = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); handleSend(); }
  };

  const handleDelete = async (id: string) => {
    await deleteChatSession(id);
    qc.invalidateQueries({ queryKey: ["chat-sessions"] });
    if (sessionId === id) newSession();
  };

  const handleSelectSession = async (session: ChatSessionSummary) => {
    await loadSession(session.id);
    if (session.campaign_id) setCampaignId(session.campaign_id);
    setSidebarOpen(false);
  };

  const handleRetry = () => {
    const userMessages = messages.filter((m) => m.role === "user");
    const last = userMessages[userMessages.length - 1];
    if (last) send(last.content, campaignId || undefined);
  };

  const activeCampaign = campaignData?.find((c) => c.id === campaignId);

  const Sidebar = (
    <div className="flex flex-col h-full">
      <div className="p-3 border-b border-border flex flex-col gap-2">
        <button
          onClick={() => { newSession(); setSidebarOpen(false); }}
          className="w-full text-sm font-semibold py-2 px-3 rounded-lg bg-primary text-primary-foreground hover:opacity-90 transition-opacity text-left"
          style={{ fontFamily: "var(--font-heading)" }}
        >
          + New Conversation
        </button>
        <input
          type="text"
          placeholder="Search conversations…"
          value={sessionSearch}
          onChange={(e) => setSessionSearch(e.target.value)}
          className="w-full rounded-md border border-input bg-background px-2.5 py-1.5 text-xs placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
        />
      </div>
      <div className="flex-1 overflow-y-auto p-2 flex flex-col gap-1">
        {sessionsLoading && (
          <div className="flex flex-col gap-2 p-2">
            {[...Array(4)].map((_, i) => (
              <div key={i} className="h-10 rounded-lg bg-muted/50 animate-pulse" />
            ))}
          </div>
        )}
        {!sessionsLoading && !sessions?.length && (
          <p className="text-xs text-muted-foreground text-center py-6">No conversations yet.</p>
        )}
        {sessions?.map((s) => (
          <SessionItem
            key={s.id}
            session={s}
            active={s.id === sessionId}
            onSelect={() => handleSelectSession(s)}
            onDelete={() => handleDelete(s.id)}
          />
        ))}
      </div>
    </div>
  );

  return (
    <div className="max-w-5xl mx-auto px-4 py-6 flex flex-col" style={{ height: "calc(100dvh - 3.5rem)" }}>
      {/* Mobile sidebar overlay */}
      {sidebarOpen && (
        <div className="fixed inset-0 z-40 md:hidden" onClick={() => setSidebarOpen(false)}>
          <div className="absolute inset-0 bg-background/80 backdrop-blur-sm" />
          <div
            className="absolute left-0 top-14 bottom-0 w-72 bg-background border-r border-border"
            onClick={(e) => e.stopPropagation()}
          >
            {Sidebar}
          </div>
        </div>
      )}

      <div className="flex gap-4 flex-1 min-h-0">
        {/* Desktop sidebar */}
        <aside className="hidden md:flex flex-col w-64 shrink-0 border border-border rounded-lg overflow-hidden">
          {Sidebar}
        </aside>

        {/* Chat panel */}
        <div className="flex-1 flex flex-col min-w-0">
          {/* Header */}
          <div className="mb-3 flex items-start justify-between gap-3 flex-wrap">
            <div className="flex items-center gap-2">
              {/* Mobile sidebar toggle */}
              <button
                className="md:hidden p-1.5 rounded-md border border-border text-muted-foreground hover:text-foreground transition-colors"
                onClick={() => setSidebarOpen(true)}
                title="View conversations"
              >
                <svg width="16" height="16" viewBox="0 0 20 20" fill="currentColor">
                  <path fillRule="evenodd" clipRule="evenodd" d="M3 5a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1zm0 5a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1zm0 5a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1z" />
                </svg>
              </button>
              <div>
                <h1 className="text-xl font-bold text-foreground" style={{ fontFamily: "var(--font-heading)" }}>
                  {sessionId
                    ? (sessions?.find((s) => s.id === sessionId)?.title ?? "Conversation")
                    : "New Conversation"}
                </h1>
                <p className="text-xs text-muted-foreground mt-0.5">
                  {activeCampaign
                    ? <><span className="text-foreground">{activeCampaign.name}</span><span className="opacity-50"> · {activeCampaign.genre}</span></>
                    : "No campaign context"}
                </p>
              </div>
            </div>
            <div className="flex items-center gap-2 shrink-0 flex-wrap justify-end">
              <AIStatus />
              <select
                value={campaignId}
                onChange={(e) => setCampaignId(e.target.value)}
                className="text-xs rounded-md border border-input bg-background text-foreground px-2 py-1.5 focus:outline-none focus:ring-1 focus:ring-ring"
              >
                <option value="">No campaign</option>
                {campaignData?.map((c) => (
                  <option key={c.id} value={c.id}>{c.name}</option>
                ))}
              </select>
            </div>
          </div>

          <div className="border-t border-border mb-3" />

          {/* Messages */}
          <div className="flex-1 overflow-y-auto flex flex-col gap-4 pr-1 pb-2">
            {messages.length === 0 && !isLoading && (
              <div className="flex flex-col items-center justify-center flex-1 text-center gap-3 py-16">
                <span className="text-5xl">📜</span>
                <p className="text-lg text-foreground" style={{ fontFamily: "var(--font-heading)" }}>
                  The chronicles await your words.
                </p>
                <p className="text-sm text-muted-foreground max-w-xs">
                  {activeCampaign
                    ? `I have the chronicles of ${activeCampaign.name} at hand.`
                    : "Select a campaign for contextual answers, or ask anything."}
                </p>
              </div>
            )}

            {messages.map((msg, i) => (
              <div key={i} className={`flex flex-col ${msg.role === "user" ? "items-end" : "items-start"}`}>
                <div className={`max-w-[82%] rounded-lg px-4 py-3 text-sm leading-relaxed ${
                  msg.role === "user"
                    ? "bg-primary text-primary-foreground"
                    : "bg-card text-card-foreground border border-border"
                }`}>
                  {msg.role === "assistant" && (
                    <p className="text-xs font-semibold mb-1.5 opacity-50 tracking-widest" style={{ fontFamily: "var(--font-heading)" }}>
                      LOREKEEPER
                    </p>
                  )}
                  <p className="whitespace-pre-wrap">{msg.content}{isStreaming && i === messages.length - 1 && msg.role === "assistant" ? "▍" : ""}</p>
                </div>
                {msg.role === "assistant" && (msg.sources?.length ?? 0) > 0 && (
                  <SourcesPanel sources={msg.sources!} />
                )}
                {msg.role === "assistant" && msg.grounded === false && (
                  <p className="mt-1 text-xs text-amber-600 dark:text-amber-400 flex items-center gap-1">
                    <span aria-hidden="true">⚠</span>
                    Not from your journal — no campaign records matched this question, so this is improvised.
                  </p>
                )}
                {msg.role === "assistant" && msg.retrieval && (
                  <RetrievalPanel retrieval={msg.retrieval} />
                )}
              </div>
            ))}

            {isLoading && !isStreaming && (
              <div className="flex justify-start">
                <div className="bg-card border border-border rounded-lg px-4 py-3 text-sm text-muted-foreground italic">
                  <span className="animate-pulse">Consulting the ancient tomes…</span>
                </div>
              </div>
            )}

            {error && (
              <div className="flex flex-col gap-2">
                <div className="bg-destructive/10 border border-destructive/30 rounded-lg px-4 py-3 text-sm text-destructive">
                  {error.includes("503") || error.includes("unavailable")
                    ? "Lorekeeper.Quest AI is temporarily unavailable. Please try again in a moment."
                    : error}
                </div>
                {messages.some((m) => m.role === "user") && (
                  <button
                    onClick={handleRetry}
                    disabled={isLoading}
                    className="self-start text-xs px-3 py-1.5 rounded-md border border-border text-muted-foreground hover:text-foreground transition-colors"
                  >
                    Retry last message
                  </button>
                )}
              </div>
            )}
            <div ref={bottomRef} />
          </div>

          {/* Input */}
          <div className="mt-3 flex gap-2 items-end border border-border rounded-lg bg-card p-2.5">
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKey}
              placeholder="Ask your question… (Enter to send, Shift+Enter for newline)"
              rows={2}
              disabled={isLoading}
              className="flex-1 resize-none bg-transparent text-foreground text-sm focus:outline-none placeholder:text-muted-foreground leading-relaxed"
            />
            <button
              onClick={handleSend}
              disabled={isLoading || !input.trim()}
              className="shrink-0 px-4 py-2 rounded-md bg-primary text-primary-foreground text-sm font-semibold disabled:opacity-40 hover:opacity-90 transition-opacity"
              style={{ fontFamily: "var(--font-heading)" }}
            >
              Send
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
