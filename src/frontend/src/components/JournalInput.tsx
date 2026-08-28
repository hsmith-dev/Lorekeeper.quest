import { useState, useRef, useEffect } from "react";
import { useGenerateJournal, useGenerateJournalDraft, useAutocomplete } from "../hooks/useJournals";
import { useDedup } from "../hooks/useDedup";
import { useDebounce } from "../hooks/useDebounce";
import { useOfflineQueue } from "../hooks/useOfflineQueue";
import { storeHash } from "../utils/hashNotes";
import { extractNotesFromImage, transcribeVoice, ingestDiscord } from "../services/api";
import { NarrativeReviewPanel } from "./NarrativeReviewPanel";
import { apiErrorMessage } from "../utils/apiError";
import type { Campaign } from "../types";

type InputMode = "quick" | "form" | "manual";

interface JournalInputProps {
  campaign: Campaign;
}

// ─── Structured Form ────────────────────────────────────────────────────────

function StructuredForm({ campaign }: { campaign: Campaign }) {
  const [summary, setSummary] = useState("");
  const [npcs, setNpcs] = useState("");
  const [loot, setLoot] = useState("");
  const [questUpdate, setQuestUpdate] = useState("");
  const [sessionDate, setSessionDate] = useState("");
  const [draft, setDraft] = useState<string | null>(null);
  const [pending, setPending] = useState<{ notes: string; hash: string } | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const generate = useGenerateJournal();
  const generateDraft = useGenerateJournalDraft();
  const { checkAndHash } = useDedup();

  const buildNotes = () => {
    const parts: string[] = [];
    if (summary.trim()) parts.push(summary.trim());
    if (npcs.trim()) parts.push(`NPCs: ${npcs.trim()}`);
    if (loot.trim()) parts.push(`Loot: ${loot.trim()}`);
    if (questUpdate.trim()) parts.push(`Quest: ${questUpdate.trim()}`);
    return parts.join(". ");
  };

  const handleGenerate = async () => {
    const notes = buildNotes();
    if (!notes) return;
    setSaveError(null);
    const { hash } = await checkAndHash(notes);
    setPending({ notes, hash });
    generateDraft.mutate(
      { notes, campaign_id: campaign.id },
      { onSuccess: ({ data }) => setDraft(data.narrative) }
    );
  };

  const handleSave = () => {
    if (!pending || draft === null) return;
    setSaveError(null);
    generate.mutate(
      {
        notes: pending.notes,
        campaign_id: campaign.id,
        entry_hash: pending.hash,
        session_date: sessionDate || undefined,
        narrative: draft,
      },
      {
        onSuccess: () => {
          storeHash(pending.hash);
          setSummary(""); setNpcs(""); setLoot(""); setQuestUpdate(""); setSessionDate("");
          setDraft(null); setPending(null);
        },
        onError: (err) => setSaveError(apiErrorMessage(err, "Could not save this entry. Try again.")),
      }
    );
  };

  const handleRegenerate = () => {
    if (!pending) return;
    setSaveError(null);
    generateDraft.mutate(
      { notes: pending.notes, campaign_id: campaign.id },
      { onSuccess: ({ data }) => setDraft(data.narrative) }
    );
  };

  if (draft !== null) {
    return (
      <NarrativeReviewPanel
        narrative={draft}
        onChange={setDraft}
        onSave={handleSave}
        onDiscard={() => { setDraft(null); setPending(null); setSaveError(null); }}
        onRegenerate={handleRegenerate}
        saving={generate.isPending}
        regenerating={generateDraft.isPending}
        error={saveError}
      />
    );
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <div className="sm:col-span-2">
          <label className="text-xs font-medium text-muted-foreground mb-1 block">What happened *</label>
          <textarea
            placeholder="Describe the session events…"
            value={summary}
            onChange={(e) => setSummary(e.target.value)}
            rows={3}
            className="resize-none w-full rounded-lg border border-input bg-background px-3 py-2.5 text-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
          />
        </div>
        <div>
          <label className="text-xs font-medium text-muted-foreground mb-1 block">NPCs encountered</label>
          <input
            type="text"
            placeholder="Elara, King Aldric, the lich…"
            value={npcs}
            onChange={(e) => setNpcs(e.target.value)}
            className="w-full rounded-lg border border-input bg-background px-3 py-2 text-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
          />
        </div>
        <div>
          <label className="text-xs font-medium text-muted-foreground mb-1 block">Loot / items found</label>
          <input
            type="text"
            placeholder="+2 sword, phylactery, gold…"
            value={loot}
            onChange={(e) => setLoot(e.target.value)}
            className="w-full rounded-lg border border-input bg-background px-3 py-2 text-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
          />
        </div>
        <div>
          <label className="text-xs font-medium text-muted-foreground mb-1 block">Quest update</label>
          <input
            type="text"
            placeholder="Find the phylactery — completed"
            value={questUpdate}
            onChange={(e) => setQuestUpdate(e.target.value)}
            className="w-full rounded-lg border border-input bg-background px-3 py-2 text-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
          />
        </div>
        <div>
          <label className="text-xs font-medium text-muted-foreground mb-1 block">Session date</label>
          <input
            type="date"
            value={sessionDate}
            onChange={(e) => setSessionDate(e.target.value)}
            className="w-full rounded-lg border border-input bg-background px-3 py-2 text-sm text-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
          />
        </div>
      </div>
      <div className="flex items-center justify-end">
        <button
          onClick={handleGenerate}
          disabled={generateDraft.isPending || !summary.trim()}
          className="shrink-0 rounded-md bg-primary px-5 py-2 text-sm font-semibold text-primary-foreground hover:opacity-90 disabled:opacity-50 transition-opacity"
          style={{ fontFamily: "var(--font-heading)" }}
        >
          {generateDraft.isPending ? "Generating…" : "Generate Entry"}
        </button>
      </div>
      {(generateDraft.isError || generate.isError) && (
        <p className="text-sm text-destructive bg-destructive/10 rounded-md px-3 py-2">Something went wrong. Try again.</p>
      )}
    </div>
  );
}

// ─── Manual Entry (no AI at all) ────────────────────────────────────────────

function ManualEntryForm({ campaign }: { campaign: Campaign }) {
  const [narrative, setNarrative] = useState("");
  const [sessionDate, setSessionDate] = useState("");
  const [saveError, setSaveError] = useState<string | null>(null);
  const [dupWarning, setDupWarning] = useState(false);
  const [forceSubmit, setForceSubmit] = useState(false);
  const generate = useGenerateJournal();
  const { checkAndHash } = useDedup();

  const handleSave = async () => {
    const text = narrative.trim();
    if (!text) return;
    setSaveError(null);
    const { hash, duplicate } = await checkAndHash(text);
    if (duplicate && !forceSubmit) { setDupWarning(true); return; }
    generate.mutate(
      {
        // No separate "shorthand notes" concept here — the user wrote the
        // real thing directly. Reuse a truncated slice of it as `notes`
        // purely so the required field + the "Notes:" preview elsewhere
        // (JournalCard, Timeline) have something short to show.
        notes: text.slice(0, 200),
        campaign_id: campaign.id,
        entry_hash: hash,
        session_date: sessionDate || undefined,
        // Setting narrative directly skips server-side generation entirely
        // (see GenerateRequest's docstring in app/schemas/journal.py) — this
        // is the one save path in the app that never calls the LLM at all.
        narrative: text,
      },
      {
        onSuccess: () => {
          storeHash(hash);
          setNarrative(""); setSessionDate(""); setDupWarning(false); setForceSubmit(false);
        },
        onError: (err) => setSaveError(apiErrorMessage(err, "Could not save this entry. Try again.")),
      }
    );
  };

  return (
    <div className="flex flex-col gap-3">
      <div>
        <label className="text-xs font-medium text-muted-foreground mb-1 block">
          Write your entry — saved exactly as typed, no AI involved
        </label>
        <textarea
          placeholder="The party crept into the ruined temple at dusk…"
          value={narrative}
          onChange={(e) => { setNarrative(e.target.value); setDupWarning(false); setForceSubmit(false); }}
          rows={10}
          className="resize-y w-full rounded-lg border border-input bg-background px-3 py-2.5 text-sm leading-relaxed placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
        />
      </div>
      <div>
        <label className="text-xs font-medium text-muted-foreground mb-1 block">Session date</label>
        <input
          type="date"
          value={sessionDate}
          onChange={(e) => setSessionDate(e.target.value)}
          className="w-full sm:w-56 rounded-lg border border-input bg-background px-3 py-2 text-sm text-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
        />
      </div>
      <div className="flex items-center justify-end gap-3">
        {dupWarning && (
          <p className="text-xs text-amber-500">
            Duplicate?{" "}
            <button className="underline underline-offset-2" onClick={() => { setForceSubmit(true); setDupWarning(false); }}>
              Save anyway
            </button>
          </p>
        )}
        <button
          onClick={handleSave}
          disabled={generate.isPending || !narrative.trim()}
          className="shrink-0 rounded-md bg-primary px-5 py-2 text-sm font-semibold text-primary-foreground hover:opacity-90 disabled:opacity-50 transition-opacity"
          style={{ fontFamily: "var(--font-heading)" }}
        >
          {generate.isPending ? "Saving…" : "Save Entry"}
        </button>
      </div>
      {(saveError || generate.isError) && (
        <p className="text-sm text-destructive bg-destructive/10 rounded-md px-3 py-2">
          {saveError ?? "Something went wrong. Try again."}
        </p>
      )}
    </div>
  );
}

// ─── Discord Paste Modal ─────────────────────────────────────────────────────

function DiscordModal({ onExtract, onClose }: { onExtract: (text: string) => void; onClose: () => void }) {
  const [raw, setRaw] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleClean = async () => {
    if (!raw.trim()) return;
    setLoading(true); setError(null);
    try {
      const { data } = await ingestDiscord(raw);
      onExtract(data.cleaned_text);
      onClose();
    } catch (e: unknown) {
      setError((e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? "Could not clean text.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-background/80 backdrop-blur-sm">
      <div className="w-full max-w-lg rounded-xl border border-border bg-background shadow-xl flex flex-col gap-4 p-5">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold text-foreground" style={{ fontFamily: "var(--font-heading)" }}>
            Paste from Discord
          </h2>
          <button onClick={onClose} className="text-muted-foreground hover:text-foreground transition-colors">
            <svg width="16" height="16" viewBox="0 0 20 20" fill="currentColor">
              <path fillRule="evenodd" clipRule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" />
            </svg>
          </button>
        </div>
        <p className="text-xs text-muted-foreground">Paste raw Discord chat — timestamps and usernames will be stripped automatically.</p>
        <textarea
          placeholder="Paste Discord chat here…"
          value={raw}
          onChange={(e) => setRaw(e.target.value)}
          rows={8}
          className="resize-none w-full rounded-lg border border-input bg-background px-3 py-2.5 text-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring font-mono text-xs"
        />
        {error && <p className="text-xs text-destructive">{error}</p>}
        <div className="flex gap-2 justify-end">
          <button onClick={onClose} className="px-4 py-2 text-sm text-muted-foreground hover:text-foreground transition-colors">Cancel</button>
          <button
            onClick={handleClean}
            disabled={loading || !raw.trim()}
            className="rounded-md bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground hover:opacity-90 disabled:opacity-50 transition-opacity"
          >
            {loading ? "Cleaning…" : "Import Notes"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ─── Main JournalInput ───────────────────────────────────────────────────────

export function JournalInput({ campaign }: JournalInputProps) {
  const [mode, setMode] = useState<InputMode>("quick");
  const [notes, setNotes] = useState("");
  const [dupWarning, setDupWarning] = useState(false);
  const [forceSubmit, setForceSubmit] = useState(false);
  const [imagePreview, setImagePreview] = useState<string | null>(null);
  const [extracting, setExtracting] = useState(false);
  const [extractError, setExtractError] = useState<string | null>(null);
  const [suggestion, setSuggestion] = useState("");
  const [recording, setRecording] = useState(false);
  const [transcribing, setTranscribing] = useState(false);
  const [showDiscord, setShowDiscord] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const mediaRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const { checkAndHash } = useDedup();
  const generate = useGenerateJournal();
  const generateDraft = useGenerateJournalDraft();
  const autocomplete = useAutocomplete();
  const debouncedNotes = useDebounce(notes, 900);
  const offlineQueue = useOfflineQueue();
  const [queuedMessage, setQueuedMessage] = useState(false);
  const [draft, setDraft] = useState<string | null>(null);
  const [pending, setPending] = useState<{ notes: string; hash: string } | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);

  useEffect(() => {
    if (debouncedNotes.trim().length < 15) { setSuggestion(""); return; }
    autocomplete.mutate(
      { text: debouncedNotes, campaign_id: campaign.id },
      {
        onSuccess: ({ data }) => { if (data.suggestion) setSuggestion(data.suggestion); },
        onError: () => setSuggestion(""),
      }
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [debouncedNotes, campaign.id]);

  const handleNotesChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setNotes(e.target.value);
    setDupWarning(false);
    setForceSubmit(false);
    setSuggestion("");
  };

  const acceptSuggestion = () => {
    if (!suggestion) return;
    setNotes((n) => n.trimEnd() + (n.endsWith(" ") ? "" : " ") + suggestion);
    setSuggestion("");
    textareaRef.current?.focus();
  };

  const handleKey = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { handleSubmit(); return; }
    if (e.key === "Tab" && suggestion) { e.preventDefault(); acceptSuggestion(); }
    if (e.key === "Escape") setSuggestion("");
  };

  const handleSubmit = async () => {
    if (!notes.trim()) return;

    if (!navigator.onLine && offlineQueue.supported) {
      await offlineQueue.queueNote(campaign.id, notes.trim(), null);
      setNotes(""); setDupWarning(false); setForceSubmit(false);
      setImagePreview(null); setSuggestion("");
      setQueuedMessage(true);
      setTimeout(() => setQueuedMessage(false), 4000);
      return;
    }

    const { hash, duplicate } = await checkAndHash(notes);
    if (duplicate && !forceSubmit) { setDupWarning(true); return; }
    setPending({ notes: notes.trim(), hash });
    generateDraft.mutate(
      { notes: notes.trim(), campaign_id: campaign.id },
      {
        onSuccess: ({ data }) => {
          setDupWarning(false); setForceSubmit(false);
          setDraft(data.narrative);
        },
        onError: async () => {
          setPending(null);
          // Network almost certainly dropped between typing and submitting —
          // queue it rather than silently losing the notes.
          if (!navigator.onLine && offlineQueue.supported) {
            await offlineQueue.queueNote(campaign.id, notes.trim(), null);
            setNotes(""); setDupWarning(false); setForceSubmit(false);
            setImagePreview(null); setSuggestion("");
            setQueuedMessage(true);
            setTimeout(() => setQueuedMessage(false), 4000);
          }
        },
      }
    );
  };

  const handleSaveDraft = () => {
    if (!pending || draft === null) return;
    setSaveError(null);
    generate.mutate(
      { notes: pending.notes, campaign_id: campaign.id, entry_hash: pending.hash, narrative: draft },
      {
        onSuccess: () => {
          storeHash(pending.hash);
          setNotes(""); setImagePreview(null); setSuggestion("");
          setDraft(null); setPending(null);
        },
        onError: (err) => setSaveError(apiErrorMessage(err, "Could not save this entry. Try again.")),
      }
    );
  };

  const handleRegenerateDraft = () => {
    if (!pending) return;
    setSaveError(null);
    generateDraft.mutate(
      { notes: pending.notes, campaign_id: campaign.id },
      { onSuccess: ({ data }) => setDraft(data.narrative) }
    );
  };

  const handleImageSelect = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    e.target.value = "";
    setExtractError(null);
    setImagePreview(URL.createObjectURL(file));
    setExtracting(true);
    try {
      const { data } = await extractNotesFromImage(file);
      setNotes(data.extracted_text);
      setDupWarning(false); setForceSubmit(false); setSuggestion("");
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? "Could not read image.";
      setExtractError(msg); setImagePreview(null);
    } finally { setExtracting(false); }
  };

  const startRecording = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const recorder = new MediaRecorder(stream);
      chunksRef.current = [];
      recorder.ondataavailable = (e) => { if (e.data.size > 0) chunksRef.current.push(e.data); };
      recorder.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        const blob = new Blob(chunksRef.current, { type: "audio/webm" });
        setTranscribing(true);
        try {
          const { data } = await transcribeVoice(blob);
          setNotes((n) => n ? n + " " + data.transcribed_text : data.transcribed_text);
          setSuggestion("");
        } catch {
          setExtractError("Could not transcribe audio. Try again.");
        } finally { setTranscribing(false); }
      };
      recorder.start();
      mediaRef.current = recorder;
      setRecording(true);
    } catch {
      setExtractError("Microphone access denied.");
    }
  };

  const stopRecording = () => {
    mediaRef.current?.stop();
    mediaRef.current = null;
    setRecording(false);
  };

  return (
    <div className="flex flex-col gap-3">
      {/* Mode toggle — always visible, regardless of which mode's internal
          state (e.g. an AI draft mid-review) is showing, so switching modes
          is never a dead end (see StructuredForm/NarrativeReviewPanel below,
          neither of which have their own way back). */}
      <div className="flex flex-wrap gap-1 text-xs border-b border-border pb-2" data-tour="journal-input">
        <button
          onClick={() => setMode("quick")}
          className={`px-2.5 py-1 rounded-md font-medium transition-colors ${mode === "quick" ? "bg-muted text-foreground" : "text-muted-foreground hover:text-foreground hover:bg-muted/60"}`}
        >
          Quick Entry
        </button>
        <button
          onClick={() => setMode("form")}
          className={`px-2.5 py-1 rounded-md font-medium transition-colors ${mode === "form" ? "bg-muted text-foreground" : "text-muted-foreground hover:text-foreground hover:bg-muted/60"}`}
        >
          Session Form
        </button>
        <button
          onClick={() => setMode("manual")}
          className={`px-2.5 py-1 rounded-md font-medium transition-colors ${mode === "manual" ? "bg-muted text-foreground" : "text-muted-foreground hover:text-foreground hover:bg-muted/60"}`}
        >
          Write It Yourself
        </button>
      </div>

      {mode === "form" && <StructuredForm campaign={campaign} />}
      {mode === "manual" && <ManualEntryForm campaign={campaign} />}

      {mode === "quick" && (draft !== null ? (
        <NarrativeReviewPanel
          narrative={draft}
          onChange={setDraft}
          onSave={handleSaveDraft}
          onDiscard={() => { setDraft(null); setPending(null); setSaveError(null); }}
          onRegenerate={handleRegenerateDraft}
          saving={generate.isPending}
          regenerating={generateDraft.isPending}
          error={saveError}
        />
      ) : (
      <>
      {offlineQueue.queue.length > 0 && (
        <div className="flex items-center justify-between gap-3 rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-700 dark:text-amber-400">
          <span>
            {offlineQueue.queue.length} note{offlineQueue.queue.length === 1 ? "" : "s"} queued locally —
            {navigator.onLine ? " syncing…" : " will send once you're back online."}
          </span>
          {navigator.onLine && !offlineQueue.syncing && (
            <button onClick={() => offlineQueue.sync()} className="underline underline-offset-2 shrink-0">
              Sync now
            </button>
          )}
        </div>
      )}

      {queuedMessage && (
        <div className="rounded-lg border border-green-500/30 bg-green-500/10 px-3 py-2 text-xs text-green-700 dark:text-green-400">
          ✓ Saved locally — no connection right now, will send once you're back online.
        </div>
      )}

      {imagePreview && (
        <div className="flex items-center gap-3 rounded-lg border border-border bg-muted/30 px-3 py-2">
          <img src={imagePreview} alt="Uploaded" className="h-14 w-14 rounded-md object-cover border border-border shrink-0" />
          <div className="flex flex-col gap-0.5 min-w-0">
            {extracting ? (
              <p className="text-sm text-muted-foreground animate-pulse">Reading notes from image…</p>
            ) : (
              <p className="text-sm text-foreground font-medium">Notes extracted from image</p>
            )}
            <p className="text-xs text-muted-foreground">Review and edit below before generating</p>
          </div>
          <button onClick={() => { setImagePreview(null); setExtractError(null); }} className="ml-auto shrink-0 p-1 rounded text-muted-foreground hover:text-foreground transition-colors">
            <svg width="14" height="14" viewBox="0 0 20 20" fill="currentColor"><path fillRule="evenodd" clipRule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" /></svg>
          </button>
        </div>
      )}

      {extractError && <p className="text-sm text-destructive bg-destructive/10 rounded-md px-3 py-2">{extractError}</p>}

      <div className="relative">
        <textarea
          ref={textareaRef}
          placeholder="Enter session notes… (e.g. defeated the lich, found phylactery, Aldric leveled up)"
          value={notes}
          onChange={handleNotesChange}
          onKeyDown={handleKey}
          rows={4}
          disabled={extracting || transcribing}
          className="resize-none w-full rounded-lg border border-input bg-background px-3 py-2.5 pr-10 text-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring transition-shadow leading-relaxed disabled:opacity-60"
        />
        {/* Image upload icon */}
        <button type="button" onClick={() => fileRef.current?.click()} disabled={extracting || transcribing} title="Import from photo"
          className="absolute bottom-2.5 right-2.5 p-1 rounded text-muted-foreground hover:text-foreground transition-colors disabled:opacity-40">
          {extracting ? (
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="animate-spin"><path d="M21 12a9 9 0 11-6.219-8.56" /></svg>
          ) : (
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <rect x="3" y="3" width="18" height="18" rx="2" ry="2" /><circle cx="8.5" cy="8.5" r="1.5" /><polyline points="21 15 16 10 5 21" />
            </svg>
          )}
        </button>
      </div>

      {/* Autocomplete suggestion */}
      {suggestion && !extracting && !transcribing && (
        <div className="flex items-center gap-2 text-xs">
          <span className="text-muted-foreground shrink-0">Suggestion:</span>
          <button type="button" onClick={acceptSuggestion}
            className="flex items-center gap-1.5 rounded-md border border-border bg-muted/40 px-2.5 py-1 text-foreground hover:bg-muted transition-colors max-w-full truncate" title="Click or Tab to insert">
            <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" className="shrink-0 text-primary">
              <path d="M12 2a10 10 0 1 0 10 10" /><path d="M22 2 12 12" />
            </svg>
            <span className="truncate">{suggestion}</span>
            <kbd className="shrink-0 rounded border border-border bg-background px-1 py-0.5 text-[10px] text-muted-foreground font-mono">Tab</kbd>
          </button>
          <button type="button" onClick={() => setSuggestion("")} className="text-muted-foreground hover:text-foreground transition-colors shrink-0">
            <svg width="12" height="12" viewBox="0 0 20 20" fill="currentColor"><path fillRule="evenodd" clipRule="evenodd" d="M4.293 4.293a1 1 0 011.414 0L10 8.586l4.293-4.293a1 1 0 111.414 1.414L11.414 10l4.293 4.293a1 1 0 01-1.414 1.414L10 11.414l-4.293 4.293a1 1 0 01-1.414-1.414L8.586 10 4.293 5.707a1 1 0 010-1.414z" /></svg>
          </button>
        </div>
      )}

      {transcribing && (
        <p className="text-xs text-muted-foreground animate-pulse flex items-center gap-1.5">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="animate-spin"><path d="M21 12a9 9 0 11-6.219-8.56" /></svg>
          Transcribing audio…
        </p>
      )}

      <input ref={fileRef} type="file" accept="image/jpeg,image/png,image/webp,image/gif" className="hidden" onChange={handleImageSelect} />

      <div className="flex items-center justify-between gap-2 flex-wrap">
        {/* Left: extra input buttons */}
        <div className="flex items-center gap-1.5">
          {/* Voice */}
          <button type="button" onClick={recording ? stopRecording : startRecording}
            disabled={transcribing || extracting}
            title={recording ? "Stop recording" : "Record voice note"}
            className={`flex items-center gap-1 px-2.5 py-1.5 rounded-md border text-xs transition-colors disabled:opacity-40 ${recording ? "border-red-500 text-red-500 bg-red-500/10 animate-pulse" : "border-border text-muted-foreground hover:text-foreground hover:bg-muted/60"}`}>
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z" /><path d="M19 10v2a7 7 0 0 1-14 0v-2" /><line x1="12" y1="19" x2="12" y2="23" /><line x1="8" y1="23" x2="16" y2="23" />
            </svg>
            {recording ? "Stop" : "Voice"}
          </button>
          {/* Discord paste */}
          <button type="button" onClick={() => setShowDiscord(true)}
            title="Paste from Discord"
            className="flex items-center gap-1 px-2.5 py-1.5 rounded-md border border-border text-xs text-muted-foreground hover:text-foreground hover:bg-muted/60 transition-colors">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor">
              <path d="M20.317 4.37a19.791 19.791 0 0 0-4.885-1.515.074.074 0 0 0-.079.037c-.21.375-.444.864-.608 1.25a18.27 18.27 0 0 0-5.487 0 12.64 12.64 0 0 0-.617-1.25.077.077 0 0 0-.079-.037A19.736 19.736 0 0 0 3.677 4.37a.07.07 0 0 0-.032.027C.533 9.046-.32 13.58.099 18.057c.002.022.015.043.03.055a19.9 19.9 0 0 0 5.993 3.03.078.078 0 0 0 .084-.028c.462-.63.874-1.295 1.226-1.994a.076.076 0 0 0-.041-.106 13.107 13.107 0 0 1-1.872-.892.077.077 0 0 1-.008-.128 10.2 10.2 0 0 0 .372-.292.074.074 0 0 1 .077-.01c3.928 1.793 8.18 1.793 12.062 0a.074.074 0 0 1 .078.01c.12.098.246.198.373.292a.077.077 0 0 1-.006.127 12.299 12.299 0 0 1-1.873.892.077.077 0 0 0-.041.107c.36.698.772 1.362 1.225 1.993a.076.076 0 0 0 .084.028 19.839 19.839 0 0 0 6.002-3.03.077.077 0 0 0 .032-.054c.5-5.177-.838-9.674-3.549-13.66a.061.061 0 0 0-.031-.03zM8.02 15.33c-1.183 0-2.157-1.085-2.157-2.419 0-1.333.956-2.419 2.157-2.419 1.21 0 2.176 1.096 2.157 2.42 0 1.333-.956 2.418-2.157 2.418zm7.975 0c-1.183 0-2.157-1.085-2.157-2.419 0-1.333.955-2.419 2.157-2.419 1.21 0 2.176 1.096 2.157 2.42 0 1.333-.946 2.418-2.157 2.418z"/>
            </svg>
            Discord
          </button>
          {/* Upload photo */}
          <button type="button" onClick={() => fileRef.current?.click()} disabled={extracting}
            className="flex items-center gap-1 px-2.5 py-1.5 rounded-md border border-border text-xs text-muted-foreground hover:text-foreground hover:bg-muted/60 transition-colors disabled:opacity-40">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <rect x="3" y="3" width="18" height="18" rx="2" ry="2" /><circle cx="8.5" cy="8.5" r="1.5" /><polyline points="21 15 16 10 5 21" />
            </svg>
            Photo
          </button>
        </div>

        {/* Right: dup warning + submit */}
        <div className="flex items-center gap-3">
          {dupWarning && (
            <p className="text-xs text-amber-500">
              Duplicate?{" "}
              <button className="underline underline-offset-2" onClick={() => { setForceSubmit(true); setDupWarning(false); }}>
                Submit anyway
              </button>
            </p>
          )}
          <button onClick={handleSubmit} disabled={generateDraft.isPending || !notes.trim() || extracting || transcribing}
            className="shrink-0 rounded-md bg-primary px-5 py-2 text-sm font-semibold text-primary-foreground hover:opacity-90 disabled:opacity-50 transition-opacity"
            style={{ fontFamily: "var(--font-heading)" }}>
            {generateDraft.isPending ? "Generating…" : "Generate Entry"}
          </button>
        </div>
      </div>

      {(generateDraft.isError || generate.isError) && (
        <p className="text-sm text-destructive bg-destructive/10 rounded-md px-3 py-2">Something went wrong. Try again.</p>
      )}

      {showDiscord && <DiscordModal onExtract={(text) => { setNotes(text); setSuggestion(""); }} onClose={() => setShowDiscord(false)} />}
      </>
      ))}
    </div>
  );
}
