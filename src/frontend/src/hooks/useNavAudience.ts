import { navAudience, type NavAudience } from "@/lib/routes";
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

/** Whether a login token is stored. Never throws. */
export function isLoggedIn(): boolean {
  try {
    return typeof localStorage !== "undefined" && !!localStorage.getItem("lk_token");
  } catch {
    return false;
  }
}
