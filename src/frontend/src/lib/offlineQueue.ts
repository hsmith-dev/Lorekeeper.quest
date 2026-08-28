// Local queue for shorthand notes captured with no signal at the table.
// IndexedDB, not localStorage — a queue of full draft notes across a session
// is a better fit for IndexedDB's larger capacity and structured storage than
// the small hash lists localStorage already holds for dedup (see hashNotes.ts).
//
// Scope is deliberately narrow: this queues raw notes, not generated
// narratives — narrative generation always needs a live LLM connection, so
// there is no "offline generation" to support here.

const DB_NAME = "lorekeeper-offline";
const DB_VERSION = 1;
const STORE_NAME = "queued_notes";

export interface QueuedNote {
  id: string; // client-generated, used as the IndexedDB key
  campaign_id: string;
  notes: string;
  session_date: string | null;
  queued_at: string;
}

function openDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, DB_VERSION);
    request.onupgradeneeded = () => {
      const db = request.result;
      if (!db.objectStoreNames.contains(STORE_NAME)) {
        db.createObjectStore(STORE_NAME, { keyPath: "id" });
      }
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

async function withStore<T>(mode: IDBTransactionMode, fn: (store: IDBObjectStore) => IDBRequest<T>): Promise<T> {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(STORE_NAME, mode);
    const store = tx.objectStore(STORE_NAME);
    const request = fn(store);
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
    tx.oncomplete = () => db.close();
  });
}

export async function enqueueNote(note: Omit<QueuedNote, "id" | "queued_at">): Promise<QueuedNote> {
  const full: QueuedNote = {
    ...note,
    id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    queued_at: new Date().toISOString(),
  };
  await withStore("readwrite", (store) => store.add(full));
  return full;
}

export async function listQueuedNotes(): Promise<QueuedNote[]> {
  if (!("indexedDB" in window)) return [];
  return withStore("readonly", (store) => store.getAll());
}

export async function removeQueuedNote(id: string): Promise<void> {
  await withStore("readwrite", (store) => store.delete(id));
}

export function isOfflineQueueSupported(): boolean {
  return typeof window !== "undefined" && "indexedDB" in window;
}
