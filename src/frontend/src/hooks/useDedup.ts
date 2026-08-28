import { hashNotes, isDuplicate, storeHash } from "../utils/hashNotes";

export function useDedup() {
  const checkAndHash = async (notes: string): Promise<{ hash: string; duplicate: boolean }> => {
    const hash = await hashNotes(notes);
    return { hash, duplicate: isDuplicate(hash) };
  };

  return { checkAndHash, storeHash };
}
