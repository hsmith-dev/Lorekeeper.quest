import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useCampaigns } from "../hooks/useCampaigns";
import { useGenerateJournal, useGenerateJournalDraft } from "../hooks/useJournals";
import { useDedup } from "../hooks/useDedup";
import { transcribeVoice, summarizeSession } from "../services/api";
import { NarrativeReviewPanel } from "../components/NarrativeReviewPanel";
import { PageHeader } from "../components/PageHeader";
import { apiErrorMessage } from "../utils/apiError";
import type { Campaign } from "../types";

const SEGMENT_MS = 30_000;

type SegmentStatus = "recording" | "transcribing" | "done" | "error";
interface Segment {
  index: number;
  status: SegmentStatus;
  text: string;
}

function formatElapsed(ms: number) {
  const totalSec = Math.floor(ms / 1000);
  const m = Math.floor(totalSec / 60).toString().padStart(2, "0");
  const s = (totalSec % 60).toString().padStart(2, "0");
  return `${m}:${s}`;
}

function RecordingPanel({ campaign }: { campaign: Campaign }) {
  const navigate = useNavigate();
  const generate = useGenerateJournal();
  const generateDraft = useGenerateJournalDraft();
  const { checkAndHash, storeHash } = useDedup();

  const [isRecording, setIsRecording] = useState(false);
  const [segments, setSegments] = useState<Segment[]>([]);
  const [elapsedMs, setElapsedMs] = useState(0);
  const [finalTranscript, setFinalTranscript] = useState<string | null>(null);
  const [summarizing, setSummarizing] = useState(false);
  const [suggestedNotes, setSuggestedNotes] = useState<string | null>(null);
  const [summaryError, setSummaryError] = useState<string | null>(null);
  const [dupWarning, setDupWarning] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [draft, setDraft] = useState<string | null>(null);
  const [pending, setPending] = useState<{ notes: string; hash: string } | null>(null);
  const [saved, setSaved] = useState(false);

  const streamRef = useRef<MediaStream | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const segmentTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const elapsedTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const startTimeRef = useRef<number>(0);
  const segmentIndexRef = useRef(0);
  const stoppingRef = useRef(false);

  const transcribeSegment = async (blob: Blob, index: number) => {
    setSegments((prev) => [...prev, { index, status: "transcribing", text: "" }]);
    try {
      const { data } = await transcribeVoice(blob);
      setSegments((prev) => prev.map((s) => (s.index === index ? { ...s, status: "done", text: data.transcribed_text } : s)));
    } catch {
      setSegments((prev) => prev.map((s) => (s.index === index ? { ...s, status: "error", text: "" } : s)));
    }
  };

  const startNewSegmentRecorder = () => {
    if (!streamRef.current) return;
    const recorder = new MediaRecorder(streamRef.current);
    const chunks: Blob[] = [];
    recorder.ondataavailable = (e) => { if (e.data.size > 0) chunks.push(e.data); };
    recorder.onstop = () => {
      const blob = new Blob(chunks, { type: "audio/webm" });
      if (blob.size > 0) transcribeSegment(blob, segmentIndexRef.current);
      segmentIndexRef.current += 1;
      if (!stoppingRef.current) startNewSegmentRecorder();
    };
    recorder.start();
    recorderRef.current = recorder;
  };

  const handleStart = async () => {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    streamRef.current = stream;
    stoppingRef.current = false;
    segmentIndexRef.current = 0;
    setSegments([]);
    setFinalTranscript(null);
    startTimeRef.current = Date.now();
    setElapsedMs(0);
    elapsedTimerRef.current = setInterval(() => setElapsedMs(Date.now() - startTimeRef.current), 1000);
    startNewSegmentRecorder();
    segmentTimerRef.current = setInterval(() => {
      recorderRef.current?.stop();
    }, SEGMENT_MS);
    setIsRecording(true);
  };

  const handleStop = () => {
    stoppingRef.current = true;
    setIsRecording(false);
    if (segmentTimerRef.current) clearInterval(segmentTimerRef.current);
    if (elapsedTimerRef.current) clearInterval(elapsedTimerRef.current);
    recorderRef.current?.stop();
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
  };

  useEffect(() => {
    const allDone = segments.length > 0 && segments.every((s) => s.status === "done" || s.status === "error");
    if (!isRecording && allDone && finalTranscript === null) {
      const transcript = segments
        .slice()
        .sort((a, b) => a.index - b.index)
        .map((s) => s.text)
        .filter(Boolean)
        .join(" ");
      setFinalTranscript(transcript);
    }
  }, [segments, isRecording, finalTranscript]);

  useEffect(() => () => {
    stoppingRef.current = true;
    if (segmentTimerRef.current) clearInterval(segmentTimerRef.current);
    if (elapsedTimerRef.current) clearInterval(elapsedTimerRef.current);
    streamRef.current?.getTracks().forEach((t) => t.stop());
  }, []);

  const pendingCount = segments.filter((s) => s.status === "transcribing").length;

  const handleSummarize = async () => {
    if (!finalTranscript) return;
    setSummarizing(true);
    setSummaryError(null);
    try {
      const { data } = await summarizeSession(campaign.id, finalTranscript);
      setSuggestedNotes(data.suggested_notes);
    } catch {
      setSummaryError("Could not summarize the transcript. Try again.");
    } finally {
      setSummarizing(false);
    }
  };

  const handleGenerateDraft = async (force = false) => {
    if (!suggestedNotes?.trim()) return;
    setSaveError(null);
    const { hash, duplicate } = await checkAndHash(suggestedNotes);
    if (duplicate && !force) { setDupWarning(true); return; }
    setPending({ notes: suggestedNotes.trim(), hash });
    generateDraft.mutate(
      { notes: suggestedNotes.trim(), campaign_id: campaign.id },
      {
        onSuccess: ({ data }) => { setDupWarning(false); setDraft(data.narrative); },
        onError: (err) => { setPending(null); setSaveError(apiErrorMessage(err, "Could not generate the journal entry. Try again.")); },
      }
    );
  };

  const handleSaveDraft = () => {
    if (!pending || draft === null) return;
    setSaveError(null);
    generate.mutate(
      { notes: pending.notes, campaign_id: campaign.id, entry_hash: pending.hash, narrative: draft },
      {
        onSuccess: () => { storeHash(pending.hash); setSaved(true); },
        onError: (err) => setSaveError(apiErrorMessage(err, "Could not save journal entry. Try again.")),
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

  return (
    <div className="flex flex-col gap-6">
      <div className="rounded-lg border border-border bg-muted/20 p-6 flex flex-col items-center gap-4">
        <p className="text-3xl font-mono text-foreground">{formatElapsed(elapsedMs)}</p>
        <button
          onClick={isRecording ? handleStop : handleStart}
          className={`px-6 py-3 rounded-full font-semibold text-sm transition-colors ${
            isRecording ? "bg-destructive text-destructive-foreground hover:bg-destructive/90" : "bg-primary text-primary-foreground hover:bg-primary/90"
          }`}
        >
          {isRecording ? "Stop Session Recording" : "Start Session Recording"}
        </button>
        {isRecording && (
          <p className="text-xs text-muted-foreground">
            Recording for {campaign.name} — transcribing in the background every {SEGMENT_MS / 1000}s.
          </p>
        )}
        {!isRecording && pendingCount > 0 && (
          <p className="text-xs text-muted-foreground">Finishing transcription of {pendingCount} segment(s)…</p>
        )}
      </div>

      {segments.length > 0 && (
        <div className="flex flex-col gap-2">
          <h3 className="text-xs font-semibold uppercase tracking-widest text-muted-foreground" style={{ fontFamily: "var(--font-heading)" }}>
            Segments ({segments.length})
          </h3>
          <div className="flex flex-wrap gap-1.5">
            {segments.slice().sort((a, b) => a.index - b.index).map((s) => (
              <span
                key={s.index}
                title={s.text}
                className={`text-[10px] px-2 py-0.5 rounded-full border font-medium ${
                  s.status === "done" ? "bg-green-500/10 text-green-600 border-green-500/20"
                  : s.status === "error" ? "bg-destructive/10 text-destructive border-destructive/20"
                  : "bg-muted text-muted-foreground border-border animate-pulse"
                }`}
              >
                #{s.index + 1} {s.status}
              </span>
            ))}
          </div>
        </div>
      )}

      {finalTranscript !== null && (
        <div className="flex flex-col gap-2">
          <h3 className="text-xs font-semibold uppercase tracking-widest text-muted-foreground" style={{ fontFamily: "var(--font-heading)" }}>
            Full Transcript
          </h3>
          <textarea
            readOnly
            value={finalTranscript || "(No speech was transcribed.)"}
            className="w-full min-h-[150px] rounded-md border border-border bg-background px-3 py-2 text-sm"
          />
          {suggestedNotes === null && (
            <button
              onClick={handleSummarize}
              disabled={summarizing || !finalTranscript.trim()}
              className="self-start px-4 py-2 rounded-md bg-primary text-primary-foreground text-sm font-medium hover:bg-primary/90 disabled:opacity-50"
            >
              {summarizing ? "Summarizing…" : "Summarize into Session Notes"}
            </button>
          )}
          {summaryError && <p className="text-xs text-destructive">{summaryError}</p>}
        </div>
      )}

      {suggestedNotes !== null && draft === null && !saved && (
        <div className="flex flex-col gap-2">
          <h3 className="text-xs font-semibold uppercase tracking-widest text-muted-foreground" style={{ fontFamily: "var(--font-heading)" }}>
            Suggested Session Notes (edit before generating)
          </h3>
          <textarea
            value={suggestedNotes}
            onChange={(e) => { setSuggestedNotes(e.target.value); setDupWarning(false); }}
            className="w-full min-h-[150px] rounded-md border border-border bg-background px-3 py-2 text-sm"
          />
          <div className="flex items-center gap-3">
            <button
              onClick={() => handleGenerateDraft(false)}
              disabled={generateDraft.isPending || !suggestedNotes.trim()}
              className="px-4 py-2 rounded-md bg-primary text-primary-foreground text-sm font-medium hover:bg-primary/90 disabled:opacity-50"
            >
              {generateDraft.isPending ? "Generating…" : "Generate Journal Entry"}
            </button>
            {dupWarning && (
              <div className="text-xs text-muted-foreground">
                Looks like a duplicate.{" "}
                <button className="underline underline-offset-2" onClick={() => handleGenerateDraft(true)}>Generate anyway</button>
              </div>
            )}
          </div>
          {saveError && <p className="text-xs text-destructive">{saveError}</p>}
        </div>
      )}

      {draft !== null && !saved && (
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
      )}

      {saved && (
        <div className="rounded-lg border border-green-500/20 bg-green-500/10 p-4 flex items-center justify-between">
          <p className="text-sm text-green-600">Journal entry saved.</p>
          <button onClick={() => navigate("/history")} className="text-xs underline underline-offset-2 text-green-600">
            View History
          </button>
        </div>
      )}
    </div>
  );
}

export function RecordSessionPage() {
  const { data: campaigns } = useCampaigns();
  const [selected, setSelected] = useState<Campaign | null>(null);
  const navigate = useNavigate();

  return (
    <div className="max-w-3xl mx-auto px-4 py-6 md:py-10 flex flex-col gap-6">
      <PageHeader
        title="Record Session"
        description="Record your whole gaming session. Audio is transcribed in short segments as you go, so nothing is lost even for a multi-hour session."
      />

      {campaigns && campaigns.length > 0 && (
        <div className="flex gap-1.5 flex-wrap border-b border-border pb-3">
          {campaigns.map((c) => (
            <button key={c.id} onClick={() => setSelected(c)}
              className={`px-3 py-1.5 rounded-md text-sm transition-colors ${
                selected?.id === c.id ? "bg-muted text-foreground font-medium" : "text-muted-foreground hover:text-foreground hover:bg-muted/60"
              }`}>
              {c.name}
            </button>
          ))}
        </div>
      )}

      {!selected && (
        <div className="text-center py-16 text-muted-foreground border border-dashed border-border rounded-xl">
          <p className="text-4xl mb-3">🎙️</p>
          <p className="text-sm font-medium text-foreground mb-1">Select a campaign</p>
          <p className="text-xs">Choose a campaign above to record a session for it.</p>
        </div>
      )}

      {selected && <RecordingPanel campaign={selected} />}

      {!selected && (
        <button onClick={() => navigate(-1)} className="text-xs text-muted-foreground hover:text-foreground self-start">
          ← Back
        </button>
      )}
    </div>
  );
}
