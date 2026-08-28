import { useCallback, useEffect, useState } from "react";
import * as api from "../services/api";
import { hashNotes, storeHash } from "../utils/hashNotes";
import {
  enqueueNote, listQueuedNotes, removeQueuedNote,
  isOfflineQueueSupported, type QueuedNote,
} from "../lib/offlineQueue";

export function useOfflineQueue() {
  const [queue, setQueue] = useState<QueuedNote[]>([]);
  const [syncing, setSyncing] = useState(false);

  const refresh = useCallback(async () => {
    if (!isOfflineQueueSupported()) return;
    setQueue(await listQueuedNotes());
  }, []);

  const queueNote = useCallback(async (campaign_id: string, notes: string, session_date: string | null) => {
    await enqueueNote({ campaign_id, notes, session_date });
    await refresh();
  }, [refresh]);

  const sync = useCallback(async () => {
    if (!navigator.onLine || syncing) return;
    const pending = await listQueuedNotes();
    if (pending.length === 0) return;
    setSyncing(true);
    try {
      for (const note of pending) {
        try {
          const hash = await hashNotes(note.notes);
          await api.generateJournal({
            notes: note.notes,
            campaign_id: note.campaign_id,
            session_date: note.session_date ?? undefined,
            entry_hash: hash,
          });
          storeHash(hash);
          await removeQueuedNote(note.id);
        } catch {
          // Leave it queued — could be a duplicate, an auth issue, or still
          // offline despite the event firing; next sync attempt retries it.
        }
      }
    } finally {
      setSyncing(false);
      await refresh();
    }
  }, [syncing, refresh]);

  useEffect(() => {
    refresh();
    const handleOnline = () => sync();
    window.addEventListener("online", handleOnline);
    window.addEventListener("focus", handleOnline);
    if (navigator.onLine) sync();
    return () => {
      window.removeEventListener("online", handleOnline);
      window.removeEventListener("focus", handleOnline);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return { queue, queueNote, sync, syncing, supported: isOfflineQueueSupported() };
}
