export async function hashNotes(notes: string): Promise<string> {
  const normalized = notes.trim().toLowerCase();
  const encoded = new TextEncoder().encode(normalized);
  const hashBuffer = await crypto.subtle.digest("SHA-256", encoded);
  const hashArray = Array.from(new Uint8Array(hashBuffer));
  return hashArray.map((b) => b.toString(16).padStart(2, "0")).join("");
}

const DEDUP_KEY = "lk_dedup_hashes";
const MAX_STORED = 100;

export function isDuplicate(hash: string): boolean {
  const stored: string[] = JSON.parse(localStorage.getItem(DEDUP_KEY) ?? "[]");
  return stored.includes(hash);
}

export function storeHash(hash: string): void {
  const stored: string[] = JSON.parse(localStorage.getItem(DEDUP_KEY) ?? "[]");
  const updated = [hash, ...stored].slice(0, MAX_STORED);
  localStorage.setItem(DEDUP_KEY, JSON.stringify(updated));
}
