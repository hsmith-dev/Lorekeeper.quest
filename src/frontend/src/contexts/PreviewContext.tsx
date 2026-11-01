import { useCallback, useContext, useMemo, useSyncExternalStore } from "react";
import { QueryClientContext } from "@tanstack/react-query";

import { getPreviewCampaignId, setPreviewCampaignId, subscribePreview } from "@/lib/preview";

// Hooks over the tab-scoped preview store in lib/preview.ts. No provider is
// needed: the store is module-level so the axios interceptor can read it too.
//
// Preview only changes what the GM's screen renders and adds a request header.
// It is not access control: what a Player may see is decided server-side
// (AD-13). Nothing in E0-UX.6 calls enter(); the entry points arrive in
// E0-UX.7 and E7.7.

export const PREVIEW_READ_ONLY_TITLE = "Preview is read-only";

export interface PreviewState {
  active: boolean;
  campaignId: string | null;
  enter: (campaignId: string) => void;
  exit: () => void;
}

export function usePreview(): PreviewState {
  // The same snapshot on the server keeps static renders (the check script)
  // in step with the store.
  const campaignId = useSyncExternalStore(subscribePreview, getPreviewCampaignId, getPreviewCampaignId);
  // Optional: the hook also works outside a QueryClientProvider.
  const queryClient = useContext(QueryClientContext);

  // Cached responses were fetched as the GM; drop them so nothing GM-only is
  // shown from cache, and refetch active queries with (or without) the header.
  const resetCache = useCallback(() => {
    if (queryClient) void queryClient.resetQueries();
  }, [queryClient]);

  const enter = useCallback(
    (id: string) => {
      setPreviewCampaignId(id);
      resetCache();
    },
    [resetCache],
  );

  const exit = useCallback(() => {
    setPreviewCampaignId(null);
    resetCache();
  }, [resetCache]);

  return useMemo(
    () => ({ active: campaignId !== null, campaignId, enter, exit }),
    [campaignId, enter, exit],
  );
}

export interface WriteGuard {
  disabled: boolean;
  title?: string;
}

const GUARD_OFF: WriteGuard = { disabled: false };
const GUARD_ON: WriteGuard = { disabled: true, title: PREVIEW_READ_ONLY_TITLE };

/** Props for any control that writes data: disabled while preview is on. */
export function useWriteGuard(): WriteGuard {
  const { active } = usePreview();
  return active ? GUARD_ON : GUARD_OFF;
}
