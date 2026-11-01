import { navAudience, type NavAudience } from "@/lib/routes";
import { useCampaigns } from "./useCampaigns";
import { useCurrentCampaign } from "./useCurrentCampaign";
import { useEffectiveRole } from "./useEffectiveRole";

// Who the shell (nav set and route gating, E0-UX.8) renders for. Cosmetic
// only: the server decides what a user may read or change (AD-13).

/** "player" only with a current campaign and a non-GM effective role. */
export function useNavAudience(): NavAudience {
  const { current } = useCurrentCampaign();
  const { isGm } = useEffectiveRole();
  return navAudience({ hasCampaign: current !== null, isGm });
}

/**
 * Logged in and the campaign list (so the role) is not settled yet. Gated
 * routes and the `*` not-found route both wait on this, so a Player can't tell
 * a hidden page from a missing one by timing. A failed list stops the wait
 * (no campaign: no gating, see navAudience).
 */
export function useRoleSettling(): boolean {
  const loggedIn = isLoggedIn();
  const { ready } = useCurrentCampaign();
  const { isError } = useCampaigns({ enabled: loggedIn });
  return loggedIn && !ready && !isError;
}

/** Whether a login token is stored. Never throws. */
export function isLoggedIn(): boolean {
  try {
    return typeof localStorage !== "undefined" && !!localStorage.getItem("lk_token");
  } catch {
    return false;
  }
}
